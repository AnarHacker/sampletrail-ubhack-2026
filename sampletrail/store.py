"""SQLite persistence for the local demonstration batch."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256

from .engine import ASSAYS, MANIFEST, compare, read_csv, screen, validate_manifest, validate_rules


class Store:
    def __init__(self, path):
        self.path = path
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS manifest (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    source BLOB NOT NULL,
                    uploaded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rule_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    settings TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS report (
                    id INTEGER PRIMARY KEY,
                    report_code TEXT NOT NULL UNIQUE,
                    previous_id INTEGER UNIQUE REFERENCES report(id),
                    issuer TEXT NOT NULL,
                    signatory TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    assay BLOB NOT NULL,
                    pdf BLOB NOT NULL,
                    assay_hash TEXT NOT NULL,
                    pdf_hash TEXT NOT NULL,
                    rules TEXT NOT NULL,
                    evaluation TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review (
                    report_id INTEGER PRIMARY KEY REFERENCES report(id),
                    reviewer TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def transaction(self, write=True):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def configure(self, settings):
        validate_rules(settings)
        with self.transaction() as conn:
            if current_report(conn):
                raise ValueError("Rule settings are frozen for this batch after its first report.")
            conn.execute("INSERT OR REPLACE INTO rule_config VALUES (1, ?)", (dump(settings),))

    def import_manifest(self, raw):
        records = read_csv(raw, MANIFEST)
        validate_manifest(records)
        with self.transaction() as conn:
            if conn.execute("SELECT id FROM manifest").fetchone():
                raise ValueError("This batch already has a manifest. Use a fresh database for another batch.")
            conn.execute("INSERT INTO manifest VALUES (1, ?, ?)", (raw, now()))

    def import_report(self, inputs, raw, pdf):
        rows = read_csv(raw, ASSAYS)
        if not pdf.startswith(b"%PDF-") or not pdf.rstrip().endswith(b"%%EOF"):
            raise ValueError("Attach a PDF file with the assay export.")
        report_code = required(inputs, "report_code")
        issuer = required(inputs, "issuer")
        signatory = required(inputs, "signatory")
        issued_at = required(inputs, "issued_at")
        original = optional(inputs, "replaces")
        reason = optional(inputs, "reason")
        try:
            date = datetime.fromisoformat(issued_at)
            if date.utcoffset() is None:
                raise ValueError()
        except ValueError as error:
            raise ValueError("Issue time must be ISO 8601 with a time zone offset.") from error
        with self.transaction() as conn:
            manifest = conn.execute("SELECT source FROM manifest").fetchone()
            if not manifest:
                raise ValueError("Import a submission manifest first.")
            config = conn.execute("SELECT settings FROM rule_config").fetchone()
            if not config:
                raise ValueError("Save the project rule settings first.")
            previous = current_report(conn)
            if previous:
                if original != previous["report_code"] or not reason:
                    raise ValueError("Replacement must reference the current report and give the lab's reason.")
                if issuer != previous["issuer"] or date <= datetime.fromisoformat(previous["issued_at"]):
                    raise ValueError("Replacement must record the same issuer and a later issue time.")
            elif original or reason:
                raise ValueError("The initial report has no replacement reference or correction reason.")
            if conn.execute("SELECT id FROM report WHERE report_code = ?", (report_code,)).fetchone():
                raise ValueError("Report ID has already been registered.")
            if previous and (previous["assay_hash"], previous["pdf_hash"]) == (digest(raw), digest(pdf)):
                raise ValueError("The files are identical to the current report.")
            settings = previous["rules"] if previous else config["settings"]
            evaluation = screen(read_csv(manifest["source"], MANIFEST), rows, json.loads(settings))
            cursor = conn.execute("""
                INSERT INTO report (report_code, previous_id, issuer, signatory, issued_at, imported_at, reason,
                                    assay, pdf, assay_hash, pdf_hash, rules, evaluation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (report_code, previous["id"] if previous else None, issuer, signatory, issued_at, now(),
                  reason, raw, pdf, digest(raw), digest(pdf), settings, dump(evaluation)))
            return cursor.lastrowid

    def record_review(self, report_id, form):
        reviewer = required(form, "reviewer")
        decision = required(form, "decision")
        notes = required(form, "notes", 1000)
        with self.transaction() as conn:
            report = current_report(conn)
            if not report or report["id"] != report_id:
                raise ValueError("This report is no longer current. Refresh the review.")
            if conn.execute("SELECT report_id FROM review WHERE report_id = ?", (report_id,)).fetchone():
                raise ValueError("A decision is already recorded for this report.")
            status = batch_status(json.loads(report["evaluation"]), None, False)
            choices = ("HOLD FOR INVESTIGATION", "REQUEST FOLLOW-UP", "SCREENING REVIEW COMPLETE")
            if decision not in choices:
                raise ValueError("Select a screening disposition.")
            if status == "HOLD — QC ISSUE" and decision != choices[0]:
                raise ValueError("A failed check requires an investigation hold.")
            if status == "REVIEW REQUIRED" and decision == choices[2]:
                raise ValueError("A warning requires an investigation or follow-up disposition.")
            conn.execute("INSERT INTO review VALUES (?, ?, ?, ?, ?)", (report_id, reviewer, decision, notes, now()))

    def dashboard(self):
        with self.transaction(write=False) as conn:
            source = conn.execute("SELECT * FROM manifest").fetchone()
            config = conn.execute("SELECT settings FROM rule_config").fetchone()
            manifest = read_csv(source["source"], MANIFEST) if source else []
            reports = [
                dict(row) for row in conn.execute("""
                    SELECT id, report_code, previous_id, issuer, signatory, issued_at, imported_at,
                           reason, assay_hash, pdf_hash FROM report ORDER BY id DESC
                """)
            ]
            reviews = {row["report_id"]: dict(row) for row in conn.execute("SELECT * FROM review")}
            current = current_report(conn)
            dashboard = dict(manifest_count=len(manifest), manifest_time=source["uploaded_at"] if source else None,
                             manifest_hash=digest(source["source"]) if source else None, reports=reports,
                             rules=json.loads(config["settings"]) if config else None,
                             state="PENDING DATA", evaluation=None, impact=None)
            for record in reports:
                record["review"] = reviews.get(record["id"])
                record["superseded"] = record["id"] != current["id"]
            if current:
                previous = conn.execute("SELECT * FROM report WHERE id = ?", (current["previous_id"],)).fetchone()
                current_review = reviews.get(current["id"])
                evaluation = json.loads(current["evaluation"])
                dashboard.update(evaluation=evaluation, state=batch_status(evaluation, current_review, bool(previous)))
                if previous:
                    dashboard["impact"] = compare(read_csv(previous["assay"], ASSAYS), read_csv(current["assay"], ASSAYS),
                                                  json.loads(previous["evaluation"]), evaluation)
            return dashboard

    def attachment(self, kind, report_id):
        with self.transaction(write=False) as conn:
            if kind == "manifest":
                row = conn.execute("SELECT source FROM manifest").fetchone()
                return row["source"] if row else None
            row = conn.execute("SELECT pdf, assay FROM report WHERE id = ?", (report_id,)).fetchone()
            return row[kind] if row and kind in ("pdf", "assay") else None


def current_report(conn):
    return conn.execute("SELECT * FROM report ORDER BY id DESC LIMIT 1").fetchone()


def batch_status(evaluation, review, replacement):
    if any(item["status"] == "FAIL" for item in evaluation["findings"]):
        return "HOLD — QC ISSUE"
    if review and review["decision"] == "HOLD FOR INVESTIGATION":
        return "HOLD — QC ISSUE"
    if review:
        return "REVIEWED"
    if evaluation["findings"] or replacement:
        return "REVIEW REQUIRED"
    return "READY FOR REVIEW"


def optional(inputs, key, maximum=240):
    value = inputs.get(key, "")
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"Invalid {key.replace('_', ' ')}.")
    return value.strip()


def required(inputs, key, maximum=240):
    value = optional(inputs, key, maximum)
    if not value:
        raise ValueError(f"Add {key.replace('_', ' ')}.")
    return value


def digest(raw):
    return sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dump(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False)
