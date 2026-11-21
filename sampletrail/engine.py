"""CSV reconciliation and deterministic assay screening."""

import csv
import io
import re
from collections import Counter, defaultdict
from decimal import Decimal


LABEL = "SYNTHETIC DEMONSTRATION DATA — NOT REAL MINE OR LABORATORY DATA."
MANIFEST = ("slot", "sample_id", "kind", "parent_slot", "crm", "drillhole", "from_m", "to_m",
            "collected", "dispatch", "sender", "dispatched_at", "receiver", "received_at",
            "seal", "observed_seal", "data_label")
ASSAYS = ("slot", "sample_id", "drillhole", "from_m", "to_m",
          "analyte", "unit", "method", "value", "data_label")
CONTROL_TYPES = ("CRM", "BLANK", "CORE_DUP", "PREP_DUP")
WARNING = "WARNING"
FAIL = "FAIL"
PASS = "PASS"


def number(value):
    if not re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,9})?", str(value)):
        raise ValueError("Expected a nonnegative decimal with up to nine digits on either side of the point.")
    return Decimal(str(value))


def read_csv(raw, fields):
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if tuple(next(reader, [])) != fields:
            raise ValueError("CSV header must match the documented template.")
        parsed = []
        for values in reader:
            if not values:
                continue
            if len(values) != len(fields) or any(len(value) > 240 for value in values):
                raise ValueError(f"CSV line {reader.line_num} has invalid column lengths or count.")
            record = dict(zip(fields, (value.strip() for value in values)))
            if record["data_label"] != LABEL:
                raise ValueError(f"CSV line {reader.line_num} needs the synthetic data label.")
            parsed.append(dict(record, line=reader.line_num))
            if len(parsed) > 2000:
                raise ValueError("CSV limit is 2,000 records.")
    except (UnicodeError, csv.Error) as error:
        raise ValueError("Expected a well-formed UTF-8 CSV.") from error
    if not parsed:
        raise ValueError("CSV needs at least one data record.")
    return parsed


def validate_manifest(rows):
    for field in ("slot", "sample_id"):
        values = [row[field] for row in rows]
        if "" in values or len(set(values)) != len(values):
            raise ValueError(f"Manifest {field} must be present and unique.")
    if any(row["kind"] not in ("ROUTINE", *CONTROL_TYPES) for row in rows):
        raise ValueError("Manifest contains an unknown sample kind.")


def validate_rules(rules):
    try:
        if not isinstance(rules["id"], str) or not rules["id"].strip():
            raise ValueError("Add a project rule-set ID.")
        if not isinstance(rules["source"], str) or not rules["source"].strip():
            raise ValueError("Add a project rule source.")
        if not isinstance(rules["crm"], dict) or not rules["crm"]:
            raise ValueError("Configure at least one CRM.")
        limits(rules["blank"])
        for crm in rules["crm"].values():
            number(crm["reference"])
            limits(crm)
            if not isinstance(crm["certificate"], str) or not crm["certificate"].strip():
                raise ValueError("Each CRM needs a certificate reference.")
        for kind in ("CORE_DUP", "PREP_DUP"):
            settings = rules["duplicate"][kind]
            if number(settings["floor"]) <= 0:
                raise ValueError("The duplicate mean floor must be above zero.")
            limits(settings["absolute"])
            limits(settings["rpd"])
    except (KeyError, TypeError) as error:
        raise ValueError("Rule JSON must match the supplied project template.") from error
    return rules


def limits(values):
    pass_max, warn_max = number(values["pass"]), number(values["warn"])
    if pass_max > warn_max:
        raise ValueError("PASS maximum must be at or below the WARNING maximum.")
    return pass_max, warn_max


def show(value):
    return format(value.normalize(), "f")


def issue(code, reason, source, status=FAIL):
    return dict(code=code, reason=reason, source=source, status=status)


def interval(row):
    if not row["drillhole"]:
        raise ValueError("Missing drillhole.")
    start, end = number(row["from_m"]), number(row["to_m"])
    if start >= end:
        raise ValueError("Interval start must be less than end.")
    return row["drillhole"], start, end


def reconcile(manifest, assays):
    expected = {row["slot"]: row for row in manifest}
    known_ids = {row["sample_id"] for row in manifest}
    ids = Counter(row["sample_id"] for row in assays)
    by_slot = defaultdict(list)
    issues = []
    for row in assays:
        slot, sample_id = row["slot"], row["sample_id"]
        source = f"Assay CSV line {row['line']}"
        by_slot[slot].append(row)
        if slot not in expected:
            issues.append(issue(f"EXTRA_SLOT:{slot}:{row['line']}", f"Unexpected submission slot {slot or '(empty)'}.", source))
        if not sample_id:
            issues.append(issue(f"EMPTY_ID:{slot}:{row['line']}", "Laboratory sample identifier is missing.", source))
        elif sample_id not in known_ids:
            issues.append(issue(f"EXTRA_ID:{sample_id}", f"Unexpected laboratory sample ID {sample_id}.", source))
        if sample_id and ids[sample_id] > 1:
            issues.append(issue(f"DUP_ID:{sample_id}:{row['line']}", f"Duplicate laboratory ID {sample_id}.", source))

    matches, table = {}, []
    for slot, row in expected.items():
        returned = by_slot[slot]
        source = f"Manifest line {row['line']}" + "".join(f" · Assay CSV line {item['line']}" for item in returned)
        notes = []

        def flag(code, reason):
            notes.append(reason)
            issues.append(issue(f"{code}:{slot}", reason, source))

        if row["sample_id"] not in ids:
            flag("MISSING_ID", f"Expected ID {row['sample_id']} is absent.")
        custody = ("dispatch", "sender", "dispatched_at", "receiver", "received_at", "seal", "observed_seal")
        if not all(row[key] for key in custody) or row["seal"] != row["observed_seal"]:
            flag("CUSTODY", "Custody fields are incomplete or the receipt seal differs.")
        expected_interval = None
        if row["kind"] == "ROUTINE" or any(row[key] for key in ("drillhole", "from_m", "to_m")):
            try:
                expected_interval = interval(row)
                if not row["collected"]:
                    raise ValueError("Collection date is missing.")
            except ValueError as error:
                flag("FIELD_INTERVAL", f"Manifest origin is invalid. {error}")

        if len(returned) != 1:
            flag("SLOT_COUNT", f"Expected one result for {slot}, found {len(returned)}.")
        else:
            lab = returned[0]
            if lab["sample_id"] != row["sample_id"]:
                flag("MAPPING", f"{slot} expects {row['sample_id']}, lab reported {lab['sample_id'] or '(empty)'}.")
            elif ids[lab["sample_id"]] != 1:
                notes.append("Laboratory sample ID is ambiguous.")
            if expected_interval and any(lab[key] for key in ("drillhole", "from_m", "to_m")):
                try:
                    if interval(lab) != expected_interval:
                        flag("LAB_INTERVAL", f"Assay drillhole or interval differs from the manifest for {slot}.")
                except ValueError:
                    flag("LAB_INTERVAL", f"Assay drillhole or interval is incomplete or invalid for {slot}.")
            if (lab["analyte"], lab["unit"], lab["method"]) != ("Cu", "%", "SIM-CU"):
                flag("METHOD", f"{slot} requires Cu in % using SIM-CU.")
            try:
                value = number(lab["value"])
            except ValueError:
                flag("RESULT", f"{slot} has a missing, censored or invalid result.")
            else:
                if not notes:
                    matches[slot] = (value, lab["line"])

        table.append(dict(slot=slot, expected=row["sample_id"], kind=row["kind"],
                          reported=", ".join(item["sample_id"] or "(empty)" for item in returned),
                          result=", ".join(item["value"] for item in returned),
                          issues=notes, source=source, manifest=row))
    return matches, table, issues


def screen(manifest, assays, rules):
    matches, table, issues = reconcile(manifest, assays)
    expected = {row["slot"]: row for row in manifest}
    checks = []
    for kind in CONTROL_TYPES:
        if not any(row["kind"] == kind for row in manifest):
            issues.append(issue("REQUIRED:" + kind, f"No {kind} present in the manifest.", "Manifest"))
    for row in manifest:
        if row["kind"] in CONTROL_TYPES:
            check = evaluate_control(row, expected, matches, rules)
            checks.append(check)
            if check["status"] != PASS:
                issues.append(issue(f"QC:{row['slot']}", check["reason"], check["source"], check["status"]))
    return dict(checks=checks, reconciliation=table, findings=issues,
                matched=len(matches), expected=len(manifest))


def evaluate_control(row, expected, matches, rules):
    slot, kind = row["slot"], row["kind"]
    label = row["sample_id"]
    source = f"{rules['id']} · {rules['source']} · Manifest line {row['line']}"
    settings = rule_description(row, rules)
    if slot not in matches:
        return failed_control(slot, kind, label, source, settings, "Control result is missing or ambiguous.")
    measured, line = matches[slot]
    source += f" · Assay CSV line {line}"
    if kind == "CRM":
        config = rules["crm"].get(row["crm"])
        if config is None:
            return failed_control(slot, kind, label, source, settings, f"Missing CRM configuration for {row['crm']}.")
        reference = number(config["reference"])
        metric = abs(measured - reference)
        unit, formula = "pp Cu", f"|{show(measured)} − {show(reference)}|"
        source += f" · Certificate {config['certificate']}"
    elif kind == "BLANK":
        config, metric, unit, formula = rules["blank"], measured, "% Cu", show(measured)
    else:
        parent_slot = row["parent_slot"]
        if parent_slot not in matches or expected[parent_slot]["kind"] != "ROUTINE":
            return failed_control(slot, kind, label, source, settings, "Explicit routine parent result is missing or ambiguous.")
        parent, parent_line = matches[parent_slot]
        source += f" · Parent {expected[parent_slot]['sample_id']}, assay CSV line {parent_line}"
        duplicate = rules["duplicate"][kind]
        mean = (measured + parent) / 2
        delta = abs(measured - parent)
        floor = number(duplicate["floor"])
        formula = f"|{show(measured)} − {show(parent)}|"
        if mean <= floor:
            config, metric, unit = duplicate["absolute"], delta, "pp Cu"
            formula += f" · mean {show(mean)} ≤ floor {show(floor)}% Cu"
        else:
            config, metric, unit = duplicate["rpd"], 100 * delta / mean, "% RPD"
            formula = f"100 × {formula} ÷ {show(mean)} · mean > floor {show(floor)}% Cu"
    pass_max, warn_max = limits(config)
    status = PASS if metric <= pass_max else WARNING if metric <= warn_max else FAIL
    detail = {
        PASS: "within the pass limit",
        WARNING: "above the pass limit and within the warning band",
        FAIL: "above the warning maximum",
    }[status]
    value = show(metric)
    if len(value) > 18:
        value = f"≈{metric:.6f}"
    return dict(slot=slot, kind=kind, label=label, status=status, source=source, formula=formula,
                unit=unit, value=value, measured=show(measured), metric=float(metric),
                pass_max=show(pass_max), warn_max=show(warn_max), settings=settings,
                reason=f"{label}: {value} {unit} is {detail}.")


def rule_description(row, rules):
    def band(config, unit):
        lower, upper = limits(config)
        return f"pass ≤ {show(lower)}, warning ≤ {show(upper)} {unit}"

    kind = row["kind"]
    if kind == "CRM":
        config = rules["crm"].get(row["crm"])
        if config is None:
            return "No configured limits for this CRM."
        return (f"Certificate {config['certificate']} at {config['reference']}% Cu. "
                f"Absolute deviation: {band(config, 'pp Cu')}.")
    if kind == "BLANK":
        return f"Measured blank: {band(rules['blank'], '% Cu')}."
    config = rules["duplicate"][kind]
    return (f"Mean ≤ {config['floor']}% Cu uses absolute difference: {band(config['absolute'], 'pp Cu')}. "
            f"Above the floor use {band(config['rpd'], '% RPD')}.")


def failed_control(slot, kind, label, source, settings, why):
    return dict(slot=slot, kind=kind, label=label, status=FAIL, source=source,
                reason=f"{label}: {why}", formula="Calculation unavailable.", settings=settings)


def compare(previous, current, before, after):
    def group(rows):
        slots = defaultdict(list)
        fields = ("sample_id", "value", "drillhole", "from_m", "to_m", "analyte", "unit", "method")
        for row in rows:
            slots[row["slot"]].append({key: row[key] for key in fields})
        return {slot: sorted(items, key=lambda item: tuple(item.values())) for slot, items in slots.items()}

    first, second = group(previous), group(current)
    changes = [
        dict(slot=slot, before=first.get(slot, []), after=second.get(slot, []))
        for slot in sorted(first.keys() | second.keys()) if first.get(slot) != second.get(slot)
    ]
    old = {item["code"]: item for item in before["findings"]}
    new = {item["code"]: item for item in after["findings"]}
    return dict(changes=changes, resolved=[item for code, item in old.items() if code not in new],
                ongoing=[dict(item, previous_status=old[code]["status"]) for code, item in new.items() if code in old],
                introduced=[item for code, item in new.items() if code not in old])
