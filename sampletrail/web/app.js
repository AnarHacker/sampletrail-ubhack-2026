"use strict";

const $ = (id) => document.getElementById(id);
let snapshot;
let fixtureVersion = "";
let runningOperation = false;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function tone(status) {
  if (status === "FAIL" || status.startsWith("HOLD")) return "fail";
  if (status === "WARNING" || status === "REVIEW REQUIRED") return "warn";
  if (status === "PASS" || status === "REVIEWED" || status === "READY FOR REVIEW") return "pass";
  return "neutral";
}

function badge(status) {
  return `<span class="badge ${tone(status)}">${escapeHtml(status)}</span>`;
}

function clock(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Ulaanbaatar", dateStyle: "medium", timeStyle: "medium",
  }).format(new Date(iso)) + " ULAT";
}

async function request(url, data) {
  const options = data === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  };
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The operation failed.");
  return result;
}

async function fixture(name) {
  const result = await fetch("/fixtures/" + name);
  if (!result.ok) throw new Error("Demo files are missing. Run python -m sampletrail.fixtures.");
  return result.blob();
}

function encodeFile(file) {
  if (!file) throw new Error("Select the required source files.");
  if (file.size > 3 * 1024 * 1024) throw new Error("Maximum size is 3 MB per file.");
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(new Error("Could not read the selected file."));
    reader.readAsDataURL(file);
  });
}

function message(text, error = false) {
  const element = $("message");
  element.hidden = false;
  element.textContent = text;
  element.classList.toggle("error", error);
}

async function perform(action, { checking = false, refresh = true, reveal = true } = {}) {
  if (runningOperation) return;
  runningOperation = true;
  if (checking) {
    $("batch-state").className = "state neutral";
    $("batch-state").textContent = "CHECKING";
  }
  try {
    const result = await action();
    if (refresh) await refreshDashboard();
    if (result) message(result);
    if (reveal) $("message").scrollIntoView({ block: "nearest" });
  } catch (error) {
    message(error.message, true);
    $("message").scrollIntoView({ block: "nearest" });
    if (checking && snapshot) setState(snapshot.state);
  } finally {
    runningOperation = false;
  }
}

function setState(state) {
  $("batch-state").className = "state " + tone(state);
  $("batch-state").textContent = state;
}

async function refreshDashboard() {
  snapshot = await request("/api/dashboard");
  $("workbench").hidden = snapshot.hosted;
  $("import-link").hidden = snapshot.hosted;
  $("showcase-note").hidden = !snapshot.hosted;
  const current = snapshot.reports[0];
  setState(snapshot.state);
  $("batch-context").textContent = current ? `Cu (%) · SIM-CU · Current report ${current.report_code}` : "Cu (%) · SIM-CU";
  if (snapshot.rules && !$("rule-text").value) $("rule-text").value = JSON.stringify(snapshot.rules, null, 2);
  if (current) for (const input of $("rules-form").elements) input.disabled = true;
  const evaluation = snapshot.evaluation;
  $("dashboard").innerHTML = evaluation
    ? overview(evaluation) + (snapshot.impact ? impact(snapshot.impact) : "")
      + charts(evaluation.checks) + reconciliation(evaluation.reconciliation)
      + history(snapshot) + (snapshot.hosted ? "" : reviewForm(current, snapshot.state, evaluation) + verifyForm(snapshot))
    : `<section class="card pending"><h2>Waiting for batch evidence</h2>
        <p>${snapshot.manifest_count ? `${snapshot.manifest_count} submitted samples registered.` : "Import the sample manifest."}
        ${snapshot.rules ? "Project rules are saved." : "Save the project rules."}
        Add the assay CSV and its report PDF to screen the batch.</p><a href="#workbench">Open evidence import</a></section>`;
}

function overview(evaluation) {
  const pass = evaluation.checks.filter((item) => item.status === "PASS").length;
  const warning = evaluation.findings.filter((item) => item.status === "WARNING").length;
  const fail = evaluation.findings.filter((item) => item.status === "FAIL").length;
  return `<section class="card"><h2>Batch quality overview</h2><div class="statistics">
    <div><strong>${evaluation.matched} / ${evaluation.expected}</strong><span>Matched records</span></div>
    <div><strong>${pass} / ${evaluation.checks.length}</strong><span>QC controls passed</span></div>
    <div><strong>${fail}</strong><span>Blocking findings</span></div>
    <div><strong>${warning}</strong><span>Warnings</span></div>
  </div>
  <h3>Findings to investigate</h3>${findings(evaluation.findings, "No open screening findings.")}
  <nav class="section-links" aria-label="Batch evidence">
    ${snapshot.impact ? '<a href="#impact">Replacement impact</a>' : ""}
    <a href="#qc">QC checks</a><a href="#reconciliation">Sample reconciliation</a>
    <a href="#timeline">Timeline</a>${snapshot.reports[0].review ? "" : '<a href="#review">Record a review</a>'}
  </nav>
  </section>`;
}

function findings(items, empty) {
  if (!items.length) return `<p class="muted">${empty}</p>`;
  return `<ul class="findings">${items.map((item) => `<li>${badge(item.status)}
    <div>${escapeHtml(item.reason)}<small>${escapeHtml(item.source)}</small></div></li>`).join("")}</ul>`;
}

function changes(changes) {
  const entries = changes.flatMap((change) => {
    const first = change.before[0];
    const last = change.after[0];
    if (change.before.length !== 1 || change.after.length !== 1) {
      return [[change.slot, "Returned records", JSON.stringify(change.before), JSON.stringify(change.after)]];
    }
    const fieldLabels = { sample_id: "Sample ID", value: "Assay value", drillhole: "Drillhole",
      from_m: "From (m)", to_m: "To (m)", analyte: "Analyte", unit: "Unit", method: "Method" };
    return Object.keys(first).filter((field) => first[field] !== last[field])
      .map((field) => [change.slot, fieldLabels[field], first[field], last[field]]);
  });
  if (!entries.length) return '<p class="muted">The rows match.</p>';
  return `<div class="scroller"><table><thead><tr><th>Slot</th><th>Field</th><th>Previous</th><th>Current</th></tr></thead>
    <tbody>${entries.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function impact(data) {
  const [current, previous] = snapshot.reports;
  return `<section class="card impact" id="impact"><h2>Replacement impact</h2>
    <p><strong>${escapeHtml(previous.report_code)} → ${escapeHtml(current.report_code)}</strong>
    · ${escapeHtml(current.reason)}</p>
    ${changes(data.changes)}
    <div class="impact-grid"><div><h3>Resolved (${data.resolved.length})</h3>
      ${data.resolved.length ? `<ul>${data.resolved.map((item) => `<li>${escapeHtml(item.reason)}</li>`).join("")}</ul>` : '<p class="muted">No findings cleared.</p>'}
    </div><div><h3>Still open (${data.ongoing.length + data.introduced.length})</h3>
      ${findings([...data.ongoing, ...data.introduced], "No remaining findings.")}
    </div></div>
    ${previous.review ? `<p class="callout">${current.review ? "New decision recorded on the replacement." : "Re-review required."}
      Previous decision <strong>${escapeHtml(previous.review.decision)}</strong> applies only to ${escapeHtml(previous.report_code)}.</p>` : ""}
  </section>`;
}

function charts(checks) {
  const groups = [
    ["CRM reference comparison", ["CRM"]],
    ["Blank threshold", ["BLANK"]],
    ["Duplicate precision", ["CORE_DUP", "PREP_DUP"]],
  ];
  return `<section class="card" id="qc"><h2>Quality control checks</h2><div class="chart-grid">
    ${groups.map(([title, kinds]) => `<div class="chart"><h3>${title}</h3>
      ${checks.filter((item) => kinds.includes(item.kind)).map(chartCheck).join("") || '<p class="muted">Control absent.</p>'}
    </div>`).join("")}</div></section>`;
}

function chartCheck(check) {
  const maximum = Math.max(check.metric || 0, Number(check.warn_max) * 1.2 || 0, 0.000001);
  const bar = check.metric === undefined ? "" : `<meter min="0" max="${maximum}" low="${Number(check.pass_max)}"
    high="${Number(check.warn_max)}" optimum="0" value="${check.metric}" aria-label="${escapeHtml(check.reason)}"></meter>
    <div class="threshold"><span>Pass ≤ ${escapeHtml(check.pass_max)}</span><span>Warn ≤ ${escapeHtml(check.warn_max)}</span></div>`;
  return `<div class="check"><div class="check-heading"><strong>${escapeHtml(check.label)}</strong>${badge(check.status)}</div>
    <p>${escapeHtml(check.metric === undefined ? check.reason : `${check.value} ${check.unit}`)}</p>${bar}
    <details><summary>Calculation and source</summary><p>${escapeHtml(check.formula)}</p><p>${escapeHtml(check.settings)}</p><p>${escapeHtml(check.reason)}</p>
    <p class="muted">${escapeHtml(check.source)}</p></details></div>`;
}

function reconciliation(rows) {
  const ordered = [...rows.filter((row) => row.issues.length), ...rows.filter((row) => !row.issues.length)];
  return `<section class="card" id="reconciliation"><h2>Sample identity reconciliation</h2>
    <div class="scroller"><table><thead><tr><th>Slot</th><th>Expected ID</th><th>Lab ID</th><th>Kind</th><th>Cu (%)</th><th>Evidence</th></tr></thead>
    <tbody>${ordered.map((row) => {
      const custody = row.manifest;
      return `<tr><td>${escapeHtml(row.slot)}</td><td>${escapeHtml(row.expected)}</td><td>${escapeHtml(row.reported || "—")}</td>
        <td>${escapeHtml(row.kind)}</td><td>${escapeHtml(row.result || "—")}</td><td>
        <details><summary>${row.issues.length ? badge("FAIL") : badge("MATCHED")}</summary>
        <p>${escapeHtml(row.issues.join(" "))}</p>
        <p><strong>Field</strong> ${escapeHtml(custody.drillhole || "Control material")}
          ${custody.from_m ? escapeHtml(custody.from_m + "–" + custody.to_m + " m") : ""} · ${escapeHtml(custody.collected)}</p>
        <p><strong>Dispatch</strong> ${escapeHtml(custody.dispatch)} · ${escapeHtml(custody.sender)} · ${escapeHtml(custody.dispatched_at)}</p>
        <p><strong>Receipt</strong> ${escapeHtml(custody.receiver)} · ${escapeHtml(custody.received_at)}
        · Seal ${escapeHtml(custody.seal)} → ${escapeHtml(custody.observed_seal)}</p>
        <small>${escapeHtml(row.source)}</small></details></td></tr>`;
    }).join("")}</tbody></table></div>
  </section>`;
}

function history(data) {
  return `<section class="card" id="timeline"><h2>Sample-to-review timeline</h2>
      <p>Submission imported ${clock(data.manifest_time)} · <a href="/api/source/manifest">Manifest CSV</a></p>
      <code>${data.manifest_hash}</code>
      <ol class="timeline">${[...data.reports].reverse().map((report) => `<li>
        <div class="check-heading"><h3>${escapeHtml(report.report_code)}</h3>
          ${badge(report.superseded ? "SUPERSEDED" : "CURRENT")}</div>
        <p>Issued ${clock(report.issued_at)} · ${escapeHtml(report.issuer)} · ${escapeHtml(report.signatory)}<br>Imported ${clock(report.imported_at)}</p>
        ${report.reason ? `<p>${escapeHtml(report.reason)}</p>` : ""}
        <details><summary>Source files and SHA-256</summary>
          <p><a href="/api/source/${report.id}/pdf">Lab PDF</a><br><code>${report.pdf_hash}</code></p>
          <p><a href="/api/source/${report.id}/assay">Assay CSV</a><br><code>${report.assay_hash}</code></p>
        </details>
        ${report.review ? `<p><strong>${escapeHtml(report.review.decision)}</strong> · ${escapeHtml(report.review.reviewer)}
          · ${clock(report.review.recorded_at)}<br>${escapeHtml(report.review.notes)}</p>
          ${report.superseded ? '<p class="muted">Historical decision. Applies to this report only.</p>' : ""}`
          : '<p class="muted">No decision recorded.</p>'}
      </li>`).join("")}</ol></section>`;
}

function reviewForm(current, state, evaluation) {
  if (current.review) return "";
  return `<section class="card" id="review"><h2>Record a review</h2>
    <p>Decision for <strong>${escapeHtml(current.report_code)}</strong>.</p>
    <form id="review-form" data-report="${current.id}">
      <label>Local demo reviewer<input name="reviewer" required maxlength="240" value="Reviewing Geologist A"></label>
      <label>Disposition<select name="decision" required>
        <option>HOLD FOR INVESTIGATION</option>
        ${state === "HOLD — QC ISSUE" ? "" : '<option selected>REQUEST FOLLOW-UP</option>'}
        ${evaluation.findings.length ? "" : "<option>SCREENING REVIEW COMPLETE</option>"}
      </select></label>
      <label>Scope, finding or follow-up<textarea name="notes" rows="2" maxlength="1000" required></textarea></label>
      <button type="submit">Save decision</button>
    </form></section>`;
}

function verifyForm(data) {
  return `<section class="card"><details><summary>Verify a source-file copy</summary>
    <form id="verify-form">
      <label>Registered source<select name="source">
        <option value="0:manifest">Submission manifest</option>
        ${data.reports.map((report) => `<option value="${report.id}:pdf">${escapeHtml(report.report_code)} PDF</option>
          <option value="${report.id}:assay">${escapeHtml(report.report_code)} CSV</option>`).join("")}
      </select></label>
      <label>Copy to verify<input name="file" type="file" required></label>
      <button type="submit">Compare SHA-256</button>
      <p id="verification-result" role="status"></p>
    </form></details></section>`;
}

$("load-rules").addEventListener("click", () => perform(async () => {
  $("rule-text").value = await (await fixture("rules.json")).text();
  $("rule-code").focus();
}, { refresh: false, reveal: false }));

$("demo-manifest").addEventListener("click", () => perform(async () => {
  await request("/api/manifest", { file: await encodeFile(await fixture("manifest.csv")) });
  return "Demo manifest imported.";
}));

for (const button of document.querySelectorAll("[data-prepare]")) {
  button.addEventListener("click", () => perform(async () => {
    const version = button.dataset.prepare;
    const metadata = (await request("/api/fixture-meta"))[version];
    for (const [name, value] of Object.entries(metadata)) $("report-form").elements.namedItem(name).value = value;
    for (const name of ["csv", "pdf"]) $("report-form").elements.namedItem(name).value = "";
    fixtureVersion = version;
    $("prepared").textContent = `${version.toUpperCase()} CSV and PDF ready to import.`;
  }, { refresh: false, reveal: false }));
}

document.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  const fields = new FormData(form);
  switch (form.id) {
    case "rules-form":
      perform(async () => {
        await request("/api/rules", { code: $("rule-code").value, rules: JSON.parse($("rule-text").value) });
        $("rule-code").value = "";
        return "Project rules saved.";
      });
      break;
    case "manifest-form":
      perform(async () => {
        await request("/api/manifest", { file: await encodeFile(form.elements.file.files[0]) });
        return "Manifest imported.";
      });
      break;
    case "report-form":
      perform(async () => {
        const names = ["csv", "pdf"];
        const uploaded = names.map((name) => form.elements.namedItem(name).files[0]);
        const files = uploaded.some(Boolean) || !fixtureVersion ? uploaded
          : await Promise.all(names.map((name) => fixture(`${fixtureVersion}.${name}`)));
        const [csv, pdf] = await Promise.all(files.map(encodeFile));
        await request("/api/report", { ...Object.fromEntries(fields), csv, pdf });
        form.reset();
        fixtureVersion = "";
        $("prepared").textContent = "";
        return "Report imported. Batch checks completed.";
      }, { checking: true });
      break;
    case "review-form":
      perform(async () => {
        await request("/api/review", { ...Object.fromEntries(fields), id: Number(form.dataset.report) });
        return "Decision recorded against this report version.";
      });
      break;
    case "verify-form":
      perform(async () => {
        const [id, kind] = fields.get("source").split(":");
        const check = await request("/api/verify", { id, kind, file: await encodeFile(form.elements.file.files[0]) });
        $("verification-result").textContent = check.match ? "MATCH · copy equals the registered bytes."
          : `MISMATCH · expected ${check.expected}, calculated ${check.supplied}.`;
      }, { refresh: false, reveal: false });
      break;
  }
});

perform(refreshDashboard, { refresh: false, reveal: false });
