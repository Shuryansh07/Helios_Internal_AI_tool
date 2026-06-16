/* Live Capture — record/upload external call audio → transcribe → analyze.
   Reuses the existing /api/analyze and /api/generate/* endpoints. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });

const state = { analysis: null, transcript: "", docs: 0 };
const transcriptEl = $("transcript");
$("sideToggle")?.addEventListener("click", () => $("sidebar").classList.toggle("collapsed"));

/* ============ RECORDING ============ */
const SEGMENT_MS = 90000;   // transcribe every ~90s so each HF request stays small
let recording = false, mediaRec, audioCtx, displayStream, micStream, segTimer, secTimer, secs = 0;
const status = (m, err) => { const s = $("recStatus"); s.textContent = m; s.style.color = err ? "var(--error)" : ""; };
const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
function pickMime() {
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"]) if (MediaRecorder.isTypeSupported(m)) return m;
  return "";
}

$("recordBtn").addEventListener("click", startRecording);
$("stopBtn").addEventListener("click", stopRecording);

async function startRecording() {
  try {
    displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
  } catch { status("Screen/tab share cancelled."); return; }
  if (!displayStream.getAudioTracks().length) {
    status("No tab audio captured — re-share the meeting tab and tick 'Share tab audio'.", true);
    displayStream.getTracks().forEach(t => t.stop()); return;
  }
  try { micStream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { micStream = null; }

  audioCtx = new AudioContext();
  const dest = audioCtx.createMediaStreamDestination();
  audioCtx.createMediaStreamSource(displayStream).connect(dest);          // call audio (remote participants)
  if (micStream) audioCtx.createMediaStreamSource(micStream).connect(dest); // your voice

  recording = true; secs = 0;
  uiRecording(true);
  status("Recording… transcript updates every ~90s.");
  secTimer = setInterval(() => { secs++; $("recTimer").textContent = fmt(secs); }, 1000);
  recordSegment(dest.stream);
  displayStream.getVideoTracks()[0]?.addEventListener("ended", stopRecording); // user clicked browser "Stop sharing"
}

function recordSegment(stream) {
  const chunks = [];
  mediaRec = new MediaRecorder(stream, pickMime() ? { mimeType: pickMime() } : undefined);
  mediaRec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
  mediaRec.onstop = async () => {
    const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
    if (blob.size > 2000) await transcribeBlob(blob);
    if (recording) recordSegment(stream);
  };
  mediaRec.start();
  segTimer = setTimeout(() => { try { mediaRec.stop(); } catch {} }, SEGMENT_MS);
}

function stopRecording() {
  if (!recording) return;
  recording = false; clearTimeout(segTimer); clearInterval(secTimer);
  try { mediaRec.stop(); } catch {}
  [displayStream, micStream].forEach(s => s && s.getTracks().forEach(t => t.stop()));
  if (audioCtx) audioCtx.close().catch(() => {});
  uiRecording(false);
  status("Recording stopped — finishing last segment…");
}

function uiRecording(on) {
  $("recordBtn").classList.toggle("recording", on);
  $("recordBtn").disabled = on; $("stopBtn").disabled = !on;
  $("recTimer").hidden = !on;
}

/* ============ UPLOAD AUDIO ============ */
$("audioFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  status(`Transcribing ${f.name}…`);
  await transcribeBlob(f, f.name);
  e.target.value = "";
});

async function transcribeBlob(blob, name = "segment.webm") {
  if (!recording) status("Transcribing…");
  const fd = new FormData(); fd.append("audio", blob, name);
  try {
    const r = await fetch("/api/transcribe", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) { status(d.error || "Transcription failed", true); return; }
    if (d.text) { transcriptEl.value = (transcriptEl.value ? transcriptEl.value + " " : "") + d.text.trim(); transcriptEl.scrollTop = transcriptEl.scrollHeight; }
    status(recording ? "Recording… live transcript updating." : "Transcript ready — click Analyze.");
  } catch (e) { status("Transcription error: " + e.message, true); }
}

/* ============ ANALYZE (reuses /api/analyze) ============ */
$("analyzeBtn").addEventListener("click", async () => {
  const t = transcriptEl.value.trim();
  if (!t) { alert("Record, upload, or paste a transcript first."); return; }
  state.transcript = t;
  const btn = $("analyzeBtn"); btn.disabled = true; btn.textContent = "Analyzing…";
  try {
    const r = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ transcript: t }) });
    const d = await r.json();
    if (!r.ok) { alert(d.error || "Analysis failed."); return; }
    state.analysis = d; renderResult(d);
  } catch (e) { alert("Network error: " + e.message); }
  finally { btn.disabled = false; btn.textContent = "⚡ Analyze"; }
});

/* ============ INTELLIGENCE RENDER ============ */
const MOOD_EMOJI = { happy: "😊", excited: "🤩", satisfied: "🙂", neutral: "😐", concerned: "😟", "slightly angry": "😠", angry: "😡", frustrated: "😤" };
function renderSentiment(s) {
  const box = $("sentimentBox");
  if (!s || (!s.mood && !s.overall)) { box.innerHTML = ""; return; }
  const overall = (s.overall || "neutral").toLowerCase();
  const mood = s.mood || (overall === "positive" ? "Happy" : overall === "negative" ? "Angry" : "Neutral");
  const emoji = MOOD_EMOJI[mood.toLowerCase()] || (overall === "positive" ? "😊" : overall === "negative" ? "😡" : "😐");
  const score = typeof s.score === "number" ? s.score : 50;
  box.innerHTML = `
    <div class="sent-head"><span class="mono">Client Mood</span><span class="sent-mood ${overall}">${emoji} ${esc(mood)}</span></div>
    <div class="bar sent ${overall}"><span style="width:${score}%"></span></div>
    <div class="sent-scale mono"><span>Negative</span><span>${score}%</span><span>Positive</span></div>
    ${s.signals?.length ? `<div class="sent-signals">${s.signals.slice(0, 4).map(x => `<span class="chip" style="padding:3px 10px">${esc(x)}</span>`).join("")}</div>` : ""}`;
}
const kv = (l, v) => v ? `<div class="kv"><div class="k">${esc(l)}</div><div class="v">${esc(v)}</div></div>` : "";
const kvList = (l, a) => a?.length ? `<div class="kv full"><div class="k">${esc(l)}</div><div class="v"><ul>${a.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div></div>` : "";

function renderResult(d) {
  $("resultEmpty").hidden = true; $("resultBody").hidden = false;
  const isNew = d.classification === "new_lead";
  const badge = $("clsBadge"); badge.className = "badge " + (isNew ? "new" : "existing");
  badge.textContent = isNew ? "● NEW LEAD" : "● EXISTING CLIENT";
  $("confFill").style.width = (d.confidence || 0) + "%"; $("confText").textContent = `Confidence: ${d.confidence || 0}%`;
  renderSentiment(d.sentiment);
  $("kvGrid").innerHTML = kv("Client", d.client_name || "—") + kv("Matched record", d.matched_crm_record || "—")
    + kv("Budget", d.budget) + kv("Timeline", d.timeline)
    + (d.tech_stack?.length ? kv("Tech stack", d.tech_stack.join(", ")) : "")
    + (d.summary ? `<div class="kv full"><div class="k">Summary</div><div class="v">${esc(d.summary)}</div></div>` : "")
    + kvList("Requirements", d.requirements) + kvList("Decision makers", d.decision_makers);

  const actions = $("actions"); $("outputs").innerHTML = ""; $("flowWrap").hidden = true;
  actions.innerHTML = isNew
    ? `<button class="btn" data-gen="srs">📄 SRS</button><button class="btn" data-gen="sow">📋 SOW</button><button class="btn" data-gen="flowchart">🔀 Flowchart</button><button class="btn cta" id="toProposal">🚀 Open in Proposal →</button>`
    : `<button class="btn" data-gen="mom">📝 MOM</button><button class="btn" data-gen="action-items">✅ Action Items</button>`;
  actions.querySelectorAll("[data-gen]").forEach(b => b.addEventListener("click", () => generate(b.dataset.gen, b)));
  $("toProposal")?.addEventListener("click", openInProposal);
  if (d.action_items?.length) {
    const save = document.createElement("button"); save.className = "btn"; save.innerHTML = "📌 Save to Action Log";
    save.addEventListener("click", () => saveActionLog(save)); actions.appendChild(save);
  }
}

/* ============ GENERATE (reuses existing endpoints) ============ */
const ENDPOINT = { srs: "/api/generate/srs", sow: "/api/generate/sow", mom: "/api/generate/mom", "action-items": "/api/generate/action-items", flowchart: "/api/generate/flowchart" };
async function generate(kind, btn) {
  if (!state.analysis) return;
  const lbl = btn.textContent; btn.disabled = true; btn.textContent = "Generating…";
  try {
    const r = await fetch(ENDPOINT[kind], { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analysis: state.analysis, transcript: state.transcript, save_to_workdrive: $("saveWd").checked }) });
    const d = await r.json();
    if (!r.ok) { addOutput(`<span class="err">${esc(d.error || "Failed")}</span>`); return; }
    let wd = d.workdrive ? (d.workdrive.saved ? `<span class="wd">✓ WorkDrive</span>` : `<span class="wd">${esc(d.workdrive.reason || "")}</span>`) : "";
    addOutput(`<a class="dl" href="${d.download_url}" download>⬇ ${esc(d.filename)}${wd}</a>`);
    if (kind === "flowchart" && d.mermaid) renderFlow(d.mermaid);
  } catch (e) { addOutput(`<span class="err">${esc(e.message)}</span>`); }
  finally { btn.disabled = false; btn.textContent = lbl; }
}
function addOutput(html) { const div = document.createElement("div"); div.innerHTML = html; $("outputs").appendChild(div.firstChild || div); }
async function saveActionLog(btn) {
  const a = state.analysis; if (!a?.action_items?.length) return;
  btn.disabled = true; const l = btn.innerHTML; btn.innerHTML = "Saving…";
  try { const r = await fetch("/api/actions/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client: a.client_name, items: a.action_items }) }); const d = await r.json(); btn.innerHTML = d.ok ? `✓ Saved ${d.added}` : "Failed"; }
  catch { btn.innerHTML = "Error"; } finally { setTimeout(() => { btn.disabled = false; btn.innerHTML = l; }, 2500); }
}
function openInProposal() {
  const a = state.analysis || {}; const parts = [];
  if (a.client_name) parts.push(`Client: ${a.client_name}`);
  if (a.requirements?.length) parts.push("Requirements:\n" + a.requirements.map(r => `- ${r}`).join("\n"));
  if (a.timeline) parts.push(`Timeline: ${a.timeline}`);
  localStorage.setItem("helios.prefill", parts.join("\n\n")); window.location.href = "/";
}

/* flowchart render + export */
async function renderFlow(src) {
  $("flowWrap").hidden = false;
  try { const { svg } = await mermaid.render("flow_" + Date.now(), src); $("flowRender").innerHTML = svg; }
  catch { $("flowRender").innerHTML = `<pre>${esc(src)}</pre>`; }
}
function dl(blob, name) { const u = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000); }
$("svgBtn").addEventListener("click", () => { const s = $("flowRender").querySelector("svg"); if (s) dl(new Blob([new XMLSerializer().serializeToString(s)], { type: "image/svg+xml" }), "flowchart.svg"); });
$("pngBtn").addEventListener("click", () => {
  const s = $("flowRender").querySelector("svg"); if (!s) return;
  const xml = new XMLSerializer().serializeToString(s), img = new Image();
  img.onload = () => { const w = s.viewBox.baseVal.width || s.clientWidth, h = s.viewBox.baseVal.height || s.clientHeight, c = document.createElement("canvas"); c.width = w * 2; c.height = h * 2; const x = c.getContext("2d"); x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); x.scale(2, 2); x.drawImage(img, 0, 0, w, h); c.toBlob(b => dl(b, "flowchart.png"), "image/png"); };
  img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
});
