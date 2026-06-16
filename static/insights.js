/* Portfolio Insights — Zoho Projects + AI */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

$("sideToggle")?.addEventListener("click", () => $("sidebar").classList.toggle("collapsed"));

/* standard semantic colors by status meaning */
function statusColor(name) {
  const n = (name || "").toLowerCase();
  if (/cancel|reject|drop/.test(n)) return "#ff7b72";                 // red
  if (/hold|block|pause|stall/.test(n)) return "#ffb020";             // amber
  if (/closed|finish|complete|done|live|deliver/.test(n)) return "#56d364"; // green
  if (/progress|develop|build|active|ongoing/.test(n)) return "#00e0ff";    // cyan
  if (/test|qa|uat/.test(n)) return "#7aa2ff";                        // blue
  if (/confirm|review|approval|sign/.test(n)) return "#dcb8ff";       // violet
  if (/invoice|paid|billed|payment/.test(n)) return "#2ec4b6";        // teal
  if (/plan|backlog|new|requirement|scope/.test(n)) return "#9aa4ad"; // grey
  return "#00e0ff";                                                   // default cyan
}

let PROJECTS = [];
let filter = "all";
let search = "";

async function loadPortfolio() {
  if (!window.PROJECTS_CONFIGURED) { showError("Zoho Projects isn't connected (add ZohoProjects scopes)."); return; }
  setKpis("…");
  try {
    const pf = await (await fetch("/api/insights/projects")).json();
    if (pf.error) { showError(pf.error); return; }
    PROJECTS = pf.projects || [];
    renderKpis(pf.stats || {});
    renderStatus(pf.stats?.by_status || []);
    renderProjects();
    $("insError").hidden = true;
  } catch (e) { showError("Failed to load projects: " + e.message); }
}
function showError(m) { const e = $("insError"); e.textContent = m; e.hidden = false; }
function setKpis(v) { ["kTotal","kActive","kOverdue","kTasks","kAvg"].forEach(id => $(id).textContent = v); }

function renderKpis(s) {
  $("kTotal").textContent = s.total ?? 0;
  $("kActive").textContent = s.active ?? 0;
  $("kOverdue").textContent = s.overdue ?? 0;
  $("kTasks").textContent = (s.open_tasks ?? 0).toLocaleString();
  $("kAvg").textContent = (s.avg_percent ?? 0) + "%";
}

function renderStatus(list) {
  const max = Math.max(1, ...list.map(s => s.count));
  $("statusBars").innerHTML = list.map((s, i) => {
    const c = statusColor(s.name);
    return `
    <div class="sbar">
      <span class="sb-name">${esc(s.name)}</span>
      <span class="sb-track"><span class="sb-fill" style="width:${Math.max(6, s.count / max * 100).toFixed(0)}%;background:${c};--glow:${c};animation-delay:${(i * 0.12).toFixed(2)}s"></span></span>
      <span class="sb-count">${s.count}</span>
    </div>`;
  }).join("");
}

function projMatches(p) {
  if (search) {
    const text = `${p.name} ${p.owner} ${p.status} ${p.group}`.toLowerCase();
    if (!text.includes(search)) return false;
  }
  if (filter === "overdue") return p.overdue;
  if (filter === "onhold") return /hold/i.test(p.status);
  if (filter === "active") return !p.is_completed;
  return true;
}
function renderProjects() {
  const list = PROJECTS.filter(projMatches);
  // sort: overdue first, then by open tasks desc
  list.sort((a, b) => (b.overdue - a.overdue) || (b.open_tasks - a.open_tasks));
  $("projFilterLabel").textContent = `${list.length} shown`;
  $("projList").innerHTML = list.map(p => `
    <div class="proj" data-id="${esc(p.id)}" data-name="${esc(p.name)}">
      <div class="proj-top">
        <span class="proj-name">${esc(p.name)}</span>
      </div>
      <span class="st-chip" style="background:${hexA(statusColor(p.status),0.16)};color:${statusColor(p.status)}">${esc(p.status)}</span>
      <div class="proj-pct">
        <span class="bar"><span style="width:${p.percent}%"></span></span>
        <span class="pct-val">${p.percent}%</span>
      </div>
      <div class="proj-meta">
        <span>${p.open_tasks} open tasks</span>
        <span>${p.open_milestones} milestones</span>
        ${p.end_date ? `<span class="${p.overdue ? "overdue" : ""}">${p.overdue ? "⚠ overdue " : "due "}${esc(p.end_date)}</span>` : ""}
        ${p.owner ? `<span>${esc(p.owner)}</span>` : ""}
      </div>
    </div>`).join("") || '<div class="muted" style="font-size:13px;padding:8px">No projects match this filter.</div>';
  $("projList").querySelectorAll(".proj").forEach(el =>
    el.addEventListener("click", () => openDrawer(el.dataset.id, el.dataset.name)));
}

/* ---- project drawer (read-only) ---- */
let drawerProject = null;
async function openDrawer(id, name) {
  drawerProject = { id, name };
  $("pdName").textContent = name;
  $("pdMeta").textContent = "Loading actionables…";
  $("pdFocusBox").hidden = true; $("pdMeetWrap").hidden = true;
  $("pdTasks").innerHTML = ""; $("pdMeetings").innerHTML = "";
  $("projDrawer").hidden = false; $("drawerOverlay").hidden = false;
  try {
    const d = await (await fetch(`/api/insights/projects/${id}/tasks?name=${encodeURIComponent(name)}`)).json();
    if (d.error) { $("pdMeta").textContent = d.error; return; }
    const open = (d.tasks || []).filter(t => !t.is_completed);
    $("pdMeta").textContent = `${open.length} open tasks${d.meeting_actions?.length ? ` · ${d.meeting_actions.length} meeting actions` : ""}`;
    renderTasks(open);
    renderMeetingActions(d.meeting_actions || []);
  } catch (e) { $("pdMeta").textContent = "Failed to load: " + e.message; }
}
function renderTasks(tasks) {
  $("pdTaskCount").textContent = tasks.length;
  $("pdTasks").innerHTML = tasks.map(t => `
    <div class="task-row">
      <span class="tdot" style="background:${esc(t.status_color)}"></span>
      <div class="task-name">${esc(t.name)}
        <div class="task-meta">
          <span class="tchip">${esc(t.status)}</span>
          ${t.priority && t.priority !== "None" ? `<span class="tchip ${t.priority.toLowerCase()}">${esc(t.priority)}</span>` : ""}
          ${t.owner ? `<span class="tchip">${esc(t.owner)}</span>` : ""}
          ${t.percent ? `<span class="tchip">${t.percent}%</span>` : ""}
        </div>
      </div>
    </div>`).join("") || '<div class="empty-note">No open tasks 🎉</div>';
}
function renderMeetingActions(items) {
  $("pdMeetWrap").hidden = items.length === 0;
  $("pdMeetCount").textContent = items.length ? `· ${items.length}` : "";
  $("pdMeetings").innerHTML = items.map(m => `
    <div class="ma-row ${m.done ? "done" : ""}" data-id="${esc(m.id)}">
      <span class="ma-check ${m.done ? "done" : ""}"><span class="material-symbols-outlined">check</span></span>
      <div class="ma-body"><div class="ma-desc">${esc(m.description)}</div>
        <div class="task-meta">${m.priority ? `<span class="tchip ${(m.priority||"").toLowerCase()}">${esc(m.priority)}</span>` : ""}${m.owner ? `<span class="tchip">${esc(m.owner)}</span>` : ""}${m.due_date ? `<span class="tchip">due ${esc(m.due_date)}</span>` : ""}</div>
      </div>
    </div>`).join("");
  $("pdMeetings").querySelectorAll(".ma-row").forEach(row =>
    row.querySelector(".ma-check").addEventListener("click", async () => {
      await fetch("/api/actions/toggle", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: row.dataset.id }) });
      row.classList.toggle("done"); row.querySelector(".ma-check").classList.toggle("done");
    }));
}
$("pdFocus").addEventListener("click", async () => {
  if (!drawerProject) return;
  const btn = $("pdFocus"); btn.disabled = true; const lbl = btn.innerHTML; btn.innerHTML = "Thinking…";
  try {
    const d = await (await fetch(`/api/insights/projects/${drawerProject.id}/focus`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: drawerProject.name }),
    })).json();
    if (d.error) { $("pdFocusBox").hidden = false; $("pdFocusBox").innerHTML = `<span class="err">${esc(d.error)}</span>`; return; }
    $("pdFocusBox").hidden = false;
    $("pdFocusBox").innerHTML = `
      <div class="fb-focus">${esc(d.focus)}</div>
      ${d.priorities?.length ? `<h4>Priorities</h4>${d.priorities.map(p => `<div class="fb-pri"><span class="fb-rank">${p.rank}</span><div>${esc(p.item)}${p.why ? `<div class="why">${esc(p.why)}</div>` : ""}</div></div>`).join("")}` : ""}
      ${d.quick_wins?.length ? `<h4>Quick Wins</h4><ul class="fb-list">${d.quick_wins.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${d.blockers?.length ? `<h4>Blockers</h4><ul class="fb-list">${d.blockers.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
  } catch (e) { $("pdFocusBox").hidden = false; $("pdFocusBox").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  finally { btn.disabled = false; btn.innerHTML = lbl; }
});
function closeDrawer() { $("projDrawer").hidden = true; $("drawerOverlay").hidden = true; drawerProject = null; }
$("pdClose").addEventListener("click", closeDrawer);
$("drawerOverlay").addEventListener("click", closeDrawer);
function hexA(hex, a) {
  const h = (hex || "#859397").replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

document.querySelectorAll(".chip-btn").forEach(b => b.addEventListener("click", () => {
  filter = b.dataset.filter;
  document.querySelectorAll(".chip-btn").forEach(x => x.classList.toggle("active", x === b));
  renderProjects();
}));
$("refreshBtn").addEventListener("click", loadPortfolio);

/* project search */
const projSearch = $("projSearch"), projSearchClear = $("projSearchClear");
projSearch.addEventListener("input", () => {
  search = projSearch.value.trim().toLowerCase();
  projSearchClear.hidden = !search;
  renderProjects();
});
projSearchClear.addEventListener("click", () => { projSearch.value = ""; search = ""; projSearchClear.hidden = true; renderProjects(); projSearch.focus(); });

/* ---- AI analysis ---- */
$("analyzeBtn").addEventListener("click", async () => {
  const btn = $("analyzeBtn"); btn.disabled = true;
  const label = btn.innerHTML; btn.innerHTML = "Analyzing portfolio…";
  try {
    const r = await fetch("/api/insights/analyze", { method: "POST" });
    const d = await r.json();
    if (!r.ok) { showError(d.error || "Analysis failed"); return; }
    renderAI(d);
  } catch (e) { showError("Analysis error: " + e.message); }
  finally { btn.disabled = false; btn.innerHTML = label; }
});
function renderAI(d) {
  $("aiEmpty").hidden = true; $("aiBody").hidden = false;
  $("aiHeadline").textContent = d.headline || "";
  $("aiSummary").textContent = d.summary || "";
  $("aiRisks").innerHTML = (d.at_risk || []).map(r => `
    <div class="risk">
      <div class="risk-top"><span class="sev ${(r.severity || "Medium").toLowerCase()}">${esc(r.severity || "Medium")}</span>
        <span class="risk-name">${esc(r.project)}</span></div>
      <div class="risk-reason">${esc(r.reason)}</div>
    </div>`).join("") || '<div class="muted" style="font-size:12.5px">No major risks flagged.</div>';
  $("aiRecs").innerHTML = (d.recommendations || []).map(x => `<li>${esc(x)}</li>`).join("");
}

loadPortfolio();
