# Five-minute Assay Integrity Engine demo

| Time | Action | Expected evidence |
| --- | --- | --- |
| 0:00–0:55 | Import the synthetic submission and V1 assay batch with its report. | 20 expected rows, dispatch and matched receipt, current V1, one wrong ID. |
| 0:55–2:15 | Inspect reconciliation, CRM ranges, blank threshold and both duplicate calculations. | V1 hold with an ID mismatch and blank FAIL. The second CRM shows WARNING. The low duplicate uses absolute difference. |
| 2:15–2:40 | Record the V1 investigation hold. | A named local demo reviewer records a decision against exact V1. |
| 2:40–4:05 | Import V2 with its PDF, replacement link and reason. | Compare stable slots. ID and blank findings clear, CRM warning remains, V1 review needs re-review. |
| 4:05–5:00 | Record V2’s separate follow-up decision. Open evidence history. | V2 is reviewed with unresolved CRM follow-up. V1 records and hashes remain inspectable. |

The corrected report is the single exception scenario. Its two data errors are in the same report. Five minutes live and three minutes technical questions follow the dedicated mining page. [Official mining challenge](https://www.ubblockchainweek.net/hackathon/) (accessed 21 November 2026).

## Technical architecture and minimum build

One browser page served on loopback by Python 3.12, one SQLite database and local fixture files. This workspace has Python and the Java runtime, with no Java compiler, Maven or cached SQLite JDBC verified. Python’s standard library supplies CSV parsing, exact decimal arithmetic, SQLite transactions, SHA-256, HTTP and tests. [Python SQLite](https://docs.python.org/3.12/library/sqlite3.html) · [Python HTTP server](https://docs.python.org/3.12/library/http.server.html) (accessed 21 November 2026).

1. Import one manifest and one versioned rule set. Reconcile stable slots, IDs, drillhole intervals and custody evidence. Save source bytes.
2. A pure evaluator screens CRM, blank and duplicate records. Show PASS, WARNING and FAIL with input references, limits, formula and reason. Edit the rule set using the local operator code before the first report. Freeze the rule snapshot for V1 and V2 so version impact is comparable.
3. Store each report and its evidence in a transaction. A replacement must reference the current report and include issuer metadata and reason. Diff rows by stable slot, re-evaluate and compare findings.
4. Derive PENDING DATA until submission and report exist, CHECKING while an analysis is running, HOLD — QC ISSUE for failures, REVIEW REQUIRED for warnings or when a prior review needs renewal, READY FOR REVIEW for a clean unreviewed initial version, and REVIEWED after a reviewer records a decision on a non-held version. A recorded hold never clears a failed check. REVIEWED means a decision is logged and can retain unresolved warnings.
5. Use compact threshold charts and a reconciliation table. Expose source files, hashes and the field-to-review timeline. Repeat using a fresh database path. Test parser, controls, low-mean branch, access to rule editing, failed imports, version comparison and review invariants.

The local demo covers one batch, one method, one analyte and two versions. Application run steps are in the project README.
