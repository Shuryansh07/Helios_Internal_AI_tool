/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });

const state = {
  analysis: null,
  transcript: "",
  lastMermaid: "",
  docs: 0, newLeads: 0, existing: 0,
};

/* ---------- elements ---------- */
const transcriptEl = $("transcript");
const analyzeBtn = $("analyzeBtn");
const uploadBtn = $("uploadBtn");
const fileInput = $("fileInput");
const saveWd = $("saveWd");

/* ---------- init ---------- */
(async function init() {
  // proposals indexed (reuses existing endpoint)
  try {
    const s = await (await fetch("/api/workdrive/status")).json();
    $("statIndexed").textContent = s.count ?? "—";
  } catch {}
  // meetings (gated)
  loadMeetings();
})();

async function loadMeetings() {
  if (!window.MEETINGS_CONFIGURED) return;
  const m = await (await fetch("/api/meetings")).json();
  renderMeetings(m.meetings || []);
  $("statMeetings").textContent = "Zoho Meetings";
}

function renderMeetings(meetings) {
  const panel = $("meetingsPanel");
  const empty = $("meetingsEmpty");
  if (!meetings.length) { if (empty) empty.textContent = "No Zoho meetings found"; return; }
  if (empty) empty.hidden = true;
  panel.hidden = false;
  panel.innerHTML =
    `<div class="meetings-head mono">Recent Zoho Meetings · ${meetings.length}</div>` +
    meetings.map(m => `
      <div class="meeting" data-key="${esc(m.key)}" data-title="${esc(m.title)}" data-t="${m.has_transcript ? 1 : 0}">
        <div class="m-row">
          <b>${esc(m.title)}</b>
          ${m.has_transcript ? '<span class="chip live" style="padding:2px 9px"><span class="dot"></span>transcript</span>'
                             : (m.has_recording ? '<span class="chip" style="padding:2px 9px">recording</span>' : '')}
        </div>
        <div class="muted small">${esc(m.date)}${m.host ? " · " + esc(m.host) : ""}${m.duration ? " · " + esc(m.duration) : ""}</div>
      </div>`).join("");
  panel.querySelectorAll(".meeting").forEach(el =>
    el.addEventListener("click", async () => {
      const info = $("uploadInfo");
      info.textContent = "Fetching transcript from Zoho…";
      try {
        const r = await fetch(`/api/meetings/${el.dataset.key}/transcript`);
        const d = await r.json();
        if (!r.ok || !d.transcript) {
          info.innerHTML = `<span class="err">${esc(d.error || "Transcript not available via API — open it in Zoho Meeting, copy the transcript, and paste it below.")}</span>`;
          return;
        }
        transcriptEl.value = d.transcript;
        setSourceTag(el.dataset.title || "Meeting transcript");
        info.textContent = "Transcript loaded. Click Analyze.";
      } catch (e) {
        info.innerHTML = `<span class="err">Failed to fetch transcript: ${esc(e.message)}</span>`;
      }
    })
  );
}

/* ---------- source tag beside "Transcript Processing" ---------- */
function setSourceTag(name) {
  const tag = $("srcTag");
  if (!tag) return;
  if (name) { $("srcTagText").textContent = name; tag.hidden = false; }
  else { tag.hidden = true; $("srcTagText").textContent = ""; }
}
$("srcTagClear")?.addEventListener("click", () => { setSourceTag(""); transcriptEl.value = ""; $("uploadInfo").textContent = ""; });

/* ---------- sidebar: sync Zoho meetings ---------- */
const syncMeet = $("syncMeet");
if (syncMeet) syncMeet.addEventListener("click", async () => {
  if (!window.MEETINGS_CONFIGURED) { alert("Zoho Meetings isn't connected (manual mode)."); return; }
  syncMeet.disabled = true;
  const label = syncMeet.textContent;
  syncMeet.textContent = "Syncing…";
  try { await loadMeetings(); }
  catch (e) { alert("Sync failed: " + e.message); }
  finally { syncMeet.disabled = false; syncMeet.textContent = label; }
});

const dropzone = $("dropzone");
if (dropzone) {
  dropzone.addEventListener("click", (e) => { if (e.target.tagName !== "BUTTON") fileInput.click(); });
  ["dragover", "dragenter"].forEach(ev =>
    dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev =>
    dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.remove("over"); }));
  dropzone.addEventListener("drop", e => {
    if (e.dataTransfer?.files?.length) { fileInput.files = e.dataTransfer.files; fileInput.dispatchEvent(new Event("change")); }
  });
}

/* ---------- upload ---------- */
uploadBtn.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
fileInput.addEventListener("change", async () => {
  if (!fileInput.files.length) return;
  const names = Array.from(fileInput.files).map(f => f.name);
  const form = new FormData();
  for (const f of fileInput.files) form.append("files", f);
  uploadBtn.disabled = true;
  $("uploadInfo").textContent = "Reading files…";
  try {
    const r = await fetch("/api/transcript/upload", { method: "POST", body: form });
    const d = await r.json();
    if (!r.ok) { $("uploadInfo").innerHTML = `<span class="err">${esc(d.error)}</span>`; return; }
    transcriptEl.value = (transcriptEl.value ? transcriptEl.value + "\n\n" : "") + (d.transcript || "");
    if (names.length) setSourceTag(names.length > 1 ? `${names[0]} +${names.length - 1}` : names[0]);
    $("uploadInfo").textContent = d.errors?.length ? d.errors.join("; ") : "Loaded.";
  } catch (e) {
    $("uploadInfo").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  } finally {
    uploadBtn.disabled = false; fileInput.value = "";
  }
});

/* ---------- analyze ---------- */
analyzeBtn.addEventListener("click", async () => {
  const transcript = transcriptEl.value.trim();
  if (!transcript) { alert("Paste or upload a transcript first."); return; }
  state.transcript = transcript;
  analyzeBtn.disabled = true; analyzeBtn.textContent = "Analyzing…";
  try {
    const r = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript }),
    });
    const d = await r.json();
    if (!r.ok) { alert(d.error || "Analysis failed."); return; }
    state.analysis = d;
    if (d.classification === "new_lead") state.newLeads++; else state.existing++;
    $("statRatio").textContent = `${state.newLeads} / ${state.existing}`;
    renderResult(d);
  } catch (e) {
    alert("Network error: " + e.message);
  } finally {
    analyzeBtn.disabled = false; analyzeBtn.textContent = "⚡ Analyze";
  }
});

/* ---------- render intelligence ---------- */
function listBlock(label, arr) {
  if (!arr?.length) return "";
  return `<div class="kv full"><div class="k">${esc(label)}</div>
    <div class="v"><ul>${arr.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div></div>`;
}
function kvBlock(label, val) {
  if (!val) return "";
  return `<div class="kv"><div class="k">${esc(label)}</div><div class="v">${esc(val)}</div></div>`;
}

const MOOD_EMOJI = {
  "happy": "😊", "excited": "🤩", "satisfied": "🙂", "neutral": "😐",
  "concerned": "😟", "slightly angry": "😠", "angry": "😡", "frustrated": "😤",
};
function renderSentiment(s) {
  const box = $("sentimentBox");
  if (!box) return;
  if (!s || !s.mood && !s.overall) { box.innerHTML = ""; return; }
  const overall = (s.overall || "neutral").toLowerCase();
  const mood = s.mood || (overall === "positive" ? "Happy" : overall === "negative" ? "Angry" : "Neutral");
  const emoji = MOOD_EMOJI[mood.toLowerCase()] || (overall === "positive" ? "😊" : overall === "negative" ? "😡" : "😐");
  const score = (typeof s.score === "number") ? s.score : 50;
  box.innerHTML = `
    <div class="sent-head">
      <span class="mono">Client Mood</span>
      <span class="sent-mood ${overall}">${emoji} ${esc(mood)}</span>
    </div>
    <div class="bar sent ${overall}"><span style="width:${score}%"></span></div>
    <div class="sent-scale mono"><span>Negative</span><span>${score}%</span><span>Positive</span></div>
    ${s.signals?.length ? `<div class="sent-signals">${s.signals.slice(0,4).map(x => `<span class="chip" style="padding:3px 10px">${esc(x)}</span>`).join("")}</div>` : ""}
  `;
}

function renderResult(d) {
  $("resultEmpty").hidden = true;
  $("resultBody").hidden = false;
  renderSentiment(d.sentiment);
  const isNew = d.classification === "new_lead";
  const badge = $("clsBadge");
  badge.className = "badge " + (isNew ? "new" : "existing");
  badge.textContent = isNew ? "● NEW LEAD" : "● EXISTING CLIENT";
  $("confFill").style.width = (d.confidence || 0) + "%";
  $("confText").textContent = `Confidence: ${d.confidence || 0}%`;

  $("kvGrid").innerHTML =
    kvBlock("Client", d.client_name || "—") +
    kvBlock("Matched record", d.matched_crm_record || "—") +
    kvBlock("Budget", d.budget) +
    kvBlock("Timeline", d.timeline) +
    (d.tech_stack?.length ? kvBlock("Tech stack", d.tech_stack.join(", ")) : "") +
    (d.summary ? `<div class="kv full"><div class="k">Summary</div><div class="v">${esc(d.summary)}</div></div>` : "") +
    listBlock("Requirements", d.requirements) +
    listBlock("Decision makers", d.decision_makers);

  // action buttons by branch
  const actions = $("actions");
  $("outputs").innerHTML = "";
  $("flowWrap").hidden = true;
  if (isNew) {
    actions.innerHTML = `
      <button class="btn" data-gen="srs">📄 Generate SRS</button>
      <button class="btn" data-gen="sow">📋 Generate SOW</button>
      <button class="btn" data-gen="flowchart">🔀 Generate Flowchart</button>
      <button class="btn cta" id="toProposal">🚀 Open in Proposal Generator →</button>`;
  } else {
    actions.innerHTML = `
      <button class="btn" data-gen="mom">📝 Generate MOM</button>
      <button class="btn" data-gen="action-items">✅ Generate Action Items</button>`;
  }
  actions.querySelectorAll("[data-gen]").forEach(b =>
    b.addEventListener("click", () => generate(b.dataset.gen, b)));
  const toProp = $("toProposal");
  if (toProp) toProp.addEventListener("click", openInProposal);

  // Save meeting action items into the in-app Action Log (surfaces in Insights → project).
  if (d.action_items?.length) {
    const save = document.createElement("button");
    save.className = "btn";
    save.innerHTML = "📌 Save to Action Log";
    save.addEventListener("click", () => saveActionLog(save));
    actions.appendChild(save);
  }
}

async function saveActionLog(btn) {
  const a = state.analysis;
  if (!a?.action_items?.length) return;
  btn.disabled = true; const lbl = btn.innerHTML; btn.innerHTML = "Saving…";
  try {
    const r = await fetch("/api/actions/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client: a.client_name, items: a.action_items }),
    });
    const d = await r.json();
    btn.innerHTML = d.ok ? `✓ Saved ${d.added} to Action Log` : "Save failed";
  } catch (e) { btn.innerHTML = "Error"; }
  finally { setTimeout(() => { btn.disabled = false; btn.innerHTML = lbl; }, 2500); }
}

/* ---------- generate documents ---------- */
const ENDPOINT = {
  srs: "/api/generate/srs", sow: "/api/generate/sow", mom: "/api/generate/mom",
  "action-items": "/api/generate/action-items", flowchart: "/api/generate/flowchart",
};

async function generate(kind, btn) {
  if (!state.analysis) return;
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "Generating…";
  try {
    const r = await fetch(ENDPOINT[kind], {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analysis: state.analysis, transcript: state.transcript, save_to_workdrive: saveWd.checked }),
    });
    const d = await r.json();
    if (!r.ok) { addOutput(`<span class="err">${esc(d.error || "Failed")}</span>`); return; }
    state.docs++; $("statDocs").textContent = state.docs;
    let wd = "";
    if (d.workdrive) wd = d.workdrive.saved ? `<span class="wd">✓ WorkDrive: ${esc(d.workdrive.folder || "saved")}</span>`
                                            : `<span class="wd">WorkDrive: ${esc(d.workdrive.reason || "skipped")}</span>`;
    addOutput(`<a class="dl" href="${d.download_url}" download>⬇ ${esc(d.filename)}${wd}</a>`);
    if (kind === "flowchart" && d.mermaid) renderFlowchart(d.mermaid);
  } catch (e) {
    addOutput(`<span class="err">${esc(e.message)}</span>`);
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}
function addOutput(html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  $("outputs").appendChild(div.firstChild || div);
}

/* ---------- flowchart render + export ---------- */
async function renderFlowchart(src) {
  state.lastMermaid = src;
  $("flowWrap").hidden = false;
  try {
    const { svg } = await mermaid.render("flowGraph_" + Date.now(), src);
    $("flowRender").innerHTML = svg;
  } catch (e) {
    $("flowRender").innerHTML = `<pre style="color:#b00">${esc(src)}</pre>`;
  }
}
$("svgBtn").addEventListener("click", () => {
  const svg = $("flowRender").querySelector("svg"); if (!svg) return;
  downloadBlob(new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml" }), "flowchart.svg");
});
$("pngBtn").addEventListener("click", () => {
  const svg = $("flowRender").querySelector("svg"); if (!svg) return;
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.onload = () => {
    const scale = 2, w = (svg.viewBox.baseVal.width || svg.clientWidth), h = (svg.viewBox.baseVal.height || svg.clientHeight);
    const canvas = document.createElement("canvas");
    canvas.width = w * scale; canvas.height = h * scale;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale); ctx.drawImage(img, 0, 0, w, h);
    canvas.toBlob(b => downloadBlob(b, "flowchart.png"), "image/png");
  };
  img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
});
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------- hand off to the proposal chat ---------- */
function openInProposal() {
  const a = state.analysis || {};
  const parts = [];
  if (a.client_name) parts.push(`Client: ${a.client_name}`);
  if (a.requirements?.length) parts.push("Requirements:\n" + a.requirements.map(r => `- ${r}`).join("\n"));
  if (a.timeline) parts.push(`Timeline: ${a.timeline}`);
  if (a.tech_stack?.length) parts.push(`Tech stack: ${a.tech_stack.join(", ")}`);
  localStorage.setItem("helios.prefill", parts.join("\n\n"));
  window.location.href = "/";
}
