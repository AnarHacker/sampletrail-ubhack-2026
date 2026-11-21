"""Generate the fictional batch, rules and report attachments used on stage."""

import csv
import json
from pathlib import Path

from .engine import ASSAYS, LABEL, MANIFEST


DIRECTORY = Path(__file__).resolve().parents[1] / "demo" / "fixtures"

REPORTS = {
    "v1": dict(report_code="SIM-RPT-001", issuer="Demo Lab", signatory="Lab Officer A",
               issued_at="2026-11-24T12:00:00+08:00", replaces="", reason=""),
    "v2": dict(report_code="SIM-RPT-002", issuer="Demo Lab", signatory="Lab QA Lead A",
               issued_at="2026-11-24T13:00:00+08:00", replaces="SIM-RPT-001",
               reason="Lab transcription corrections: S07 sample ID and S17 blank value."),
}

RULES = {
    "id": "SIM-CU-RULES-01",
    "source": "Demo Ridge project rules",
    "data_label": LABEL,
    "crm": {
        "A": {"certificate": "SIM-CERT-A", "reference": "0.250", "pass": "0.020", "warn": "0.040"},
        "B": {"certificate": "SIM-CERT-B", "reference": "0.500", "pass": "0.020", "warn": "0.040"},
    },
    "blank": {"pass": "0.005", "warn": "0.010"},
    "duplicate": {
        kind: {"floor": "0.050", "absolute": {"pass": "0.003", "warn": "0.006"},
               "rpd": {"pass": "10", "warn": "20"}}
        for kind in ("CORE_DUP", "PREP_DUP")
    },
}


def make_rows():
    base = dict(collected="2026-11-24", dispatch="SIM-DSP-01", sender="Field Geologist A",
                dispatched_at="2026-11-24T09:00:00+08:00", receiver="Receiving Clerk A / Demo Lab",
                received_at="2026-11-24T10:30:00+08:00", seal="SIM-SEAL-01", observed_seal="SIM-SEAL-01",
                data_label=LABEL)
    manifest = [
        dict(base, slot=f"S{i:02}", sample_id=f"SIM-ST-{i:03}", kind="ROUTINE", parent_slot="", crm="",
             drillhole="SIM-DH-01", from_m=str(31 + i), to_m=str(32 + i))
        for i in range(1, 16)
    ]
    for slot, sample_id, kind, parent, crm in (
        ("S16", "SIM-CD-01", "CORE_DUP", "S01", ""),
        ("S17", "SIM-BLK-01", "BLANK", "", ""),
        ("S18", "SIM-PD-01", "PREP_DUP", "S02", ""),
        ("S19", "SIM-CRM-A", "CRM", "", "A"),
        ("S20", "SIM-CRM-B", "CRM", "", "B"),
    ):
        origin = dict(drillhole="SIM-DH-01", from_m="32", to_m="33") if kind == "CORE_DUP" else dict(drillhole="", from_m="", to_m="")
        manifest.append(dict(base, slot=slot, sample_id=sample_id, kind=kind, parent_slot=parent, crm=crm, **origin))
    values = ("0.300", "0.010", "0.247", "0.188", "0.332", "0.105", "0.224", "0.173", "0.196", "0.255",
              "0.138", "0.280", "0.215", "0.145", "0.251", "0.312", "0.004", "0.012", "0.254", "0.524")
    corrected = [
        dict({key: row[key] for key in ("slot", "sample_id", "drillhole", "from_m", "to_m")},
             analyte="Cu", unit="%", method="SIM-CU", value=value, data_label=LABEL)
        for row, value in zip(manifest, values, strict=True)
    ]
    initial = [dict(row) for row in corrected]
    initial[6]["sample_id"] = "SIM-ST-070"
    initial[16]["value"] = "0.015"
    return manifest, initial, corrected


def write_csv(path, fields, records):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def pdf_page(lines):
    commands = []
    y = 790
    for size, line in lines:
        value = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"BT /F1 {size} Tf 54 {y} Td ({value}) Tj ET")
        y -= size + 6
    content = "\n".join(commands).encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii") + item + b"\nendobj\n")
    start = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        result.extend(f"{offset:010} 00000 n \n".encode("ascii"))
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode("ascii"))
    return bytes(result)


def make_report(path, version, rows):
    meta = REPORTS[version]
    lines = [(15, "Demo Ridge | Assay report"),
             (10, LABEL),
             (11, f"{meta['report_code']}   |   SIM-BATCH-01   |   Cu % / SIM-CU"),
             (10, f"{meta['issuer']} · Release: {meta['signatory']}"),
             (10, f"Issued: {meta['issued_at']}")]
    if meta["replaces"]:
        lines += [(10, f"Complete replacement of {meta['replaces']}"),
                  (10, "S07: SIM-ST-070 to SIM-ST-007. S17: 0.015% to 0.004%."),
                  (10, "Reason: transcription errors in the original report.")]
    lines += [(10, "Slot   Reported sample           Cu (%)")]
    lines += [(10, f"{row['slot']:<7}{row['sample_id']:<26}{row['value']}") for row in rows]
    path.write_bytes(pdf_page(lines))


def generate(directory=DIRECTORY):
    directory.mkdir(parents=True, exist_ok=True)
    manifest, initial, corrected = make_rows()
    write_csv(directory / "manifest.csv", MANIFEST, manifest)
    for version, rows in (("v1", initial), ("v2", corrected)):
        write_csv(directory / f"{version}.csv", ASSAYS, rows)
        make_report(directory / f"{version}.pdf", version, rows)
    (directory / "rules.json").write_text(
        json.dumps(RULES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key, rule in RULES["crm"].items():
        (directory / f"SIM-CERT-{key}.pdf").write_bytes(pdf_page([
            (15, f"Demo reference certificate | SIM-CERT-{key}"),
            (10, LABEL),
            (11, f"Material: SIM-CRM-{key} · Demo Ridge · SIM-CU"),
            (11, f"Fictional reference value: {rule['reference']}% Cu"),
            (11, "Acceptance bands are set in the demo project rules."),
        ]))


def seed_demo(store):
    """Recreate the completed synthetic walkthrough in a fresh SQLite database."""
    store.configure(json.loads((DIRECTORY / "rules.json").read_text(encoding="utf-8")))
    store.import_manifest((DIRECTORY / "manifest.csv").read_bytes())
    for version, decision, notes in (
        ("v1", "HOLD FOR INVESTIGATION", "Confirm the sample ID and blank value with the issuing lab."),
        ("v2", "REQUEST FOLLOW-UP", "Check CRM B with the project QA/QC lead before dataset use."),
    ):
        report = store.import_report(REPORTS[version], (DIRECTORY / f"{version}.csv").read_bytes(),
                                     (DIRECTORY / f"{version}.pdf").read_bytes())
        store.record_review(report, dict(reviewer="Reviewing Geologist A", decision=decision, notes=notes))


if __name__ == "__main__":
    generate()
