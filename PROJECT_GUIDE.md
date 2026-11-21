# SampleTrail — Assay Integrity Engine

A single-batch QA/QC prototype for UB Hack Workflow 01. It uses Python 3.12 and SQLite with the standard library. Run the interactive demo on loopback or share the completed synthetic walkthrough on Render Free.

## Run the five-minute demo

From the project folder:

```powershell
python -m sampletrail --db demo-run.sqlite3
```

Open **http://127.0.0.1:8000**. If the port is in use, add `--port 8080` and open the printed URL. Choose a fresh database filename for a clean rehearsal. The supplied fixtures are already in [demo/fixtures](demo/fixtures). Recreate them with `python -m sampletrail.fixtures`.

1. Under **Import evidence**, choose **Use demo rules**, paste the rule editor code printed in the terminal and save. You can edit the demo settings before V1. Keep the supplied settings on stage to match the expected findings.
2. Select **Import demo manifest**, **Prepare demo V1**, then **Import and screen report**. The dashboard shows **HOLD — QC ISSUE**. Open the checks and S07 evidence. The failed blank and mismatched sample ID block the batch. CRM B remains in the warning band.
3. Record **HOLD FOR INVESTIGATION**. Example scope is “Confirm the sample ID and blank result with the issuing lab.”
4. Prepare and import V2. The comparison shows the corrected ID and blank, resolved findings, and the remaining CRM B warning. V1’s decision applies only to V1.
5. Record **REQUEST FOLLOW-UP** against V2. Example scope is “Check CRM B with the project QA/QC lead before dataset use.” The V2 state becomes **REVIEWED**, and CRM B remains visible.

Download either report’s PDF and CSV from the timeline. **Verify a source-file copy** checks the supplied file against the stored bytes with SHA-256. Source hashes and scope are shown alongside decisions.

The form also accepts local CSVs and PDFs that follow the [synthetic fixture specification](demo/DEMO_DATA_SPECIFICATION.md). The demo handles one copper method and one batch per database. Reviewer names and issuing roles are simulated local metadata. The reviewer’s action records an investigation or screening disposition. Project acceptance and laboratory authority require separate professional verification.

## Test

```powershell
python -m unittest discover -s tests -v
```

## Render Free deployment

The hosted showcase rebuilds a temporary SQLite database from the bundled synthetic manifest, rules, reports and sample decisions at each startup. Visitors can inspect the completed V1/V2 comparison and download the source files. Use the local demo for uploads, rule edits, new decisions and uploaded-copy verification. The local `--db` file still persists across normal local restarts.

1. Put this project on the approved Git branch that Render will read, with [render.yaml](render.yaml) and [the Python version file](.python-version) at the repository root.
2. Open the [Render Dashboard](https://dashboard.render.com/), choose **New → Blueprint**, connect the approved repository, and select that branch. Leave **Blueprint Path** at `render.yaml`.
3. Give the Blueprint a name, review the proposed resources, and confirm it contains one Python web service on **Free** with a **$0** estimate. Click **Deploy Blueprint**. [Render Blueprint setup](https://render.com/docs/infrastructure-as-code#setup)
4. When the service is live, open its `onrender.com` URL. Confirm **Hosted showcase**, **REVIEWED**, **20 / 20** matched records, **one CRM warning**, and the V1-to-V2 replacement comparison. Open `/healthz` on the same URL and check for `{"ok": true}`.

To create the service manually, choose **New → Web Service**, select the approved repository and branch, and enter these settings.

| Render field | Value |
| --- | --- |
| Name | `sampletrail` or another available name |
| Language | Python |
| Root Directory | Leave blank |
| Instance Type | **Free** |
| Build Command | `python -m sampletrail.fixtures` |
| Start Command | `python -m sampletrail --hosted` |
| Health Check Path | `/healthz` |
| Auto-Deploy | Off |

Render provides `PORT` and the service URL. The app binds to `0.0.0.0` in hosted mode. The configuration requires zero add-ons and no payment method. Use a workspace without a payment method to avoid usage overage charges. Render Free loses runtime files when it restarts, redeploys or spins down. It spins down after 15 minutes without inbound traffic, so allow about a minute for the first visit afterward. [Render web services](https://render.com/docs/web-services#port-binding) · [Render Free limits](https://render.com/docs/free)

To preview the Render start command locally in PowerShell, run:

```powershell
$env:PORT = '10000'
python -m sampletrail --hosted
```

Open `http://127.0.0.1:10000`. After stopping the preview, clear that shell setting with `Remove-Item Env:PORT` to return to the usual local port.
