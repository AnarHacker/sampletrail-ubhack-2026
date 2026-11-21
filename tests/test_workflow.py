import base64
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sampletrail.__main__ import create_server
from sampletrail.engine import ASSAYS, FAIL, MANIFEST, PASS, WARNING, read_csv, screen
from sampletrail.fixtures import REPORTS, RULES, generate
from sampletrail.store import Store, digest


class DemoTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.folder = Path(workspace.name)
        generate(self.folder)
        self.manifest = self.read("manifest.csv")
        self.first = self.read("v1.csv")
        self.second = self.read("v2.csv")
        self.v1 = self.read("v1.pdf")
        self.v2 = self.read("v2.pdf")

    def read(self, name):
        return (self.folder / name).read_bytes()

    def evaluation(self, name="v1"):
        return screen(read_csv(self.manifest, MANIFEST), read_csv(self.read(name + ".csv"), ASSAYS), RULES)

    def test_fixture_types_and_expected_findings(self):
        rows = read_csv(self.manifest, MANIFEST)
        self.assertEqual(20, len(rows))
        self.assertEqual(15, sum(row["kind"] == "ROUTINE" for row in rows))
        first = self.evaluation()
        second = self.evaluation("v2")
        self.assertEqual((19, 20), (first["matched"], second["matched"]))
        checks = {check["slot"]: check for check in first["checks"]}
        self.assertEqual(FAIL, checks["S17"]["status"])
        self.assertEqual(WARNING, checks["S20"]["status"])
        self.assertEqual((PASS, "% RPD"), (checks["S16"]["status"], checks["S16"]["unit"]))
        self.assertEqual((PASS, "pp Cu", "0.002"), tuple(checks["S18"][key] for key in ("status", "unit", "value")))
        self.assertEqual(["QC:S20"], [item["code"] for item in second["findings"]])

    def test_duplicate_threshold_boundary_and_zero(self):
        rows = read_csv(self.manifest, MANIFEST)
        assays = read_csv(self.second, ASSAYS)
        for parent, duplicate, expected, branch in (
            ("0", "0", PASS, "pp Cu"),
            ("0.047", "0.053", WARNING, "pp Cu"),
            ("0.19", "0.21", PASS, "% RPD"),
            ("0.18", "0.22", WARNING, "% RPD"),
            ("0.179", "0.221", FAIL, "% RPD"),
        ):
            with self.subTest(parent=parent, duplicate=duplicate):
                assays[0]["value"], assays[15]["value"] = parent, duplicate
                check = screen(rows, assays, RULES)["checks"][0]
                self.assertEqual((expected, branch), (check["status"], check["unit"]))

    def test_invalid_identity_interval_custody_and_result(self):
        manifest = read_csv(self.manifest, MANIFEST)
        assays = read_csv(self.second, ASSAYS)
        manifest[2]["observed_seal"] = "SIM-WRONG"
        assays[0]["sample_id"] = assays[1]["sample_id"]
        assays[3]["from_m"] = "900"
        assays[4]["value"] = "<0.005"
        assays[5]["sample_id"] = ""
        assays.append(dict(assays[6], slot="S99", line=24))
        evaluation = screen(manifest, assays, RULES)
        codes = {item["code"].split(":")[0] for item in evaluation["findings"]}
        self.assertTrue({"DUP_ID", "MISSING_ID", "MAPPING", "LAB_INTERVAL", "CUSTODY",
                         "RESULT", "EMPTY_ID", "EXTRA_SLOT"}.issubset(codes))
        self.assertEqual(FAIL, evaluation["checks"][0]["status"])
        self.assertIn("absolute difference", evaluation["checks"][0]["settings"])

    def test_database_transitions_and_failed_writes(self):
        path = self.folder / "demo.sqlite3"
        store = Store(path)
        self.assertEqual("PENDING DATA", store.dashboard()["state"])
        store.import_manifest(self.manifest)
        changed_rules = copy.deepcopy(RULES)
        changed_rules["blank"]["pass"] = "0.009"
        changed_rules["blank"]["warn"] = "0.005"
        with self.assertRaises(ValueError):
            store.configure(changed_rules)
        store.configure(RULES)
        first = store.import_report(REPORTS["v1"], self.first, self.v1)
        self.assertEqual("HOLD — QC ISSUE", store.dashboard()["state"])
        review = {"reviewer": "Reviewer A", "decision": "REQUEST FOLLOW-UP", "notes": "Investigate."}
        with self.assertRaisesRegex(ValueError, "hold"):
            store.record_review(first, review)
        store.record_review(first, dict(review, decision="HOLD FOR INVESTIGATION"))
        with self.assertRaisesRegex(ValueError, "frozen"):
            store.configure(RULES)
        with self.assertRaisesRegex(ValueError, "reference"):
            store.import_report(dict(REPORTS["v2"], replaces="incorrect"), self.second, self.v2)
        self.assertEqual(1, len(store.dashboard()["reports"]))
        second = store.import_report(REPORTS["v2"], self.second, self.v2)
        self.assertEqual(b"%PDF-", store.attachment("pdf", first)[:5])
        with self.assertRaisesRegex(ValueError, "no longer current"):
            store.record_review(first, review)
        view = Store(path).dashboard()
        self.assertEqual("REVIEW REQUIRED", view["state"])
        self.assertEqual(["S07", "S17"], [item["slot"] for item in view["impact"]["changes"]])
        self.assertEqual(["QC:S20"], [item["code"] for item in view["impact"]["ongoing"]])
        self.assertIn("QC:S17", {item["code"] for item in view["impact"]["resolved"]})
        self.assertIsNone(view["reports"][0]["review"])
        self.assertTrue(view["reports"][1]["superseded"])
        self.assertEqual("HOLD FOR INVESTIGATION", view["reports"][1]["review"]["decision"])
        self.assertEqual(digest(self.second), view["reports"][0]["assay_hash"])
        store.record_review(second, review)
        self.assertEqual("REVIEWED", Store(path).dashboard()["state"])
        self.assertEqual(1, len(store.dashboard()["evaluation"]["findings"]))
        with self.assertRaisesRegex(ValueError, "already"):
            store.record_review(second, review)

    def test_public_http_demo_flow(self):
        server = create_server(self.folder / "http.sqlite3", port=0, operator_code="test-code")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        root = f"http://127.0.0.1:{server.server_port}"

        def post(path, data):
            with urlopen(Request(root + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}), timeout=5) as response:
                return json.load(response)

        def encode(raw):
            return base64.b64encode(raw).decode("ascii")

        with urlopen(root, timeout=5) as document:
            self.assertIn(b"Assay batch review", document.read())
        with self.assertRaises(HTTPError) as denied:
            post("/api/rules", {"rules": RULES, "code": "wrong"})
        self.assertEqual(403, denied.exception.code)
        post("/api/rules", {"rules": RULES, "code": "test-code"})
        post("/api/manifest", {"file": encode(self.manifest)})
        for version, csv, pdf in (("v1", self.first, self.v1), ("v2", self.second, self.v2)):
            result = post("/api/report", dict(REPORTS[version], csv=encode(csv), pdf=encode(pdf)))
            with urlopen(f"{root}/api/source/{result['id']}/pdf", timeout=5) as document:
                self.assertEqual(pdf, document.read())
            self.assertTrue(post("/api/verify", {"kind": "pdf", "id": result["id"], "file": encode(pdf)})["match"])
            self.assertFalse(post("/api/verify", {"kind": "pdf", "id": result["id"], "file": encode(pdf + b"changed")})["match"])
            post("/api/review", {"id": result["id"], "reviewer": "Demo Reviewer",
                                 "decision": "HOLD FOR INVESTIGATION" if version == "v1" else "REQUEST FOLLOW-UP",
                                 "notes": "Review demo evidence."})
        with urlopen(root + "/api/dashboard", timeout=5) as response:
            self.assertEqual("REVIEWED", json.load(response)["state"])

    def test_render_start_rebuilds_read_only_showcase(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        address = f"http://127.0.0.1:{port}"
        env = dict(os.environ, PORT=str(port), TMP=str(self.folder), TEMP=str(self.folder),
                   TMPDIR=str(self.folder))
        hashes = []
        for _ in range(2):
            server = subprocess.Popen([sys.executable, "-m", "sampletrail", "--hosted"],
                                      env=env, stdout=subprocess.PIPE, text=True)
            try:
                ping = Request(address + "/healthz", headers={"Host": "sampletrail.onrender.com"})
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with urlopen(ping, timeout=1) as response:
                            self.assertEqual({"ok": True}, json.load(response))
                        break
                    except URLError:
                        if server.poll() is not None or time.monotonic() >= deadline:
                            raise
                        time.sleep(0.05)
                self.assertEqual(f"SampleTrail: http://0.0.0.0:{port}", server.stdout.readline().strip())
                with urlopen(address + "/api/dashboard", timeout=2) as response:
                    view = json.load(response)
                self.assertTrue(view["hosted"])
                self.assertEqual("REVIEWED", view["state"])
                self.assertEqual(20, view["evaluation"]["matched"])
                self.assertEqual(["QC:S20"], [finding["code"] for finding in view["impact"]["ongoing"]])
                self.assertEqual(["S07", "S17"], [change["slot"] for change in view["impact"]["changes"]])
                self.assertEqual(["REQUEST FOLLOW-UP", "HOLD FOR INVESTIGATION"],
                                 [report["review"]["decision"] for report in view["reports"]])
                with urlopen(address + "/api/source/2/pdf", timeout=2) as response:
                    self.assertEqual(self.v2, response.read())
                rejected = Request(address + "/api/review", data=b"{}", method="POST")
                with self.assertRaises(HTTPError) as denied:
                    urlopen(rejected, timeout=2)
                self.assertEqual(403, denied.exception.code)
                denied.exception.close()
                hashes.append([report["pdf_hash"] for report in view["reports"]])
            finally:
                server.terminate()
                server.wait(timeout=5)
                server.stdout.close()
        self.assertEqual(hashes[0], hashes[1])
