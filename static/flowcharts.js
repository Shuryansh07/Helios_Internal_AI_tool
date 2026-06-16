/* Process Architect — generate + render + export Mermaid flowcharts */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const THEMES = {
  cyan: { primaryBorderColor: "#00e0ff", lineColor: "#00e0ff" },
  violet: { primaryBorderColor: "#dcb8ff", lineColor: "#7701d0" },
  grey: { primaryBorderColor: "#859397", lineColor: "#859397" },
};
let accent = "cyan";
function initMermaid() {
  const t = THEMES[accent];
  mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose",
    themeVariables: { primaryColor: "#1d2026", primaryBorderColor: t.primaryBorderColor, lineColor: t.lineColor, fontFamily: "Inter" } });
}
initMermaid();

let zoom = 1, panX = 0, panY = 0;
let mode = "diagram";

/* output mode toggle (Diagram / AI Image) */
document.querySelectorAll("#flowMode .fmt-btn").forEach(b =>
  b.addEventListener("click", () => {
    mode = b.dataset.mode;
    document.querySelectorAll("#flowMode .fmt-btn").forEach(x => x.classList.toggle("active", x === b));
  })
);

/* sidebar collapse */
$("sideToggle")?.addEventListener("click", () => $("sidebar").classList.toggle("collapsed"));

/* ---- house-style library (train on WorkDrive flowcharts) ---- */
const libDot = $("libDot"), libDetail = $("libDetail"), libSync = $("libSync");
function timeAgo(iso) {
  if (!iso) return "never";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (isNaN(m)) return "unknown";
  if (m < 1) return "just now"; if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60); return h < 24 ? h + "h ago" : Math.floor(h / 24) + "d ago";
}
async function refreshLib() {
  try {
    const s = await (await fetch("/api/flowchart/library/status")).json();
    if (!s.configured) { libDot.className = "wd-dot"; libDetail.textContent = "Not configured — set ZOHO_FLOWCHART_FOLDER_ID"; libSync.disabled = true; return; }
    libDot.className = "wd-dot " + (s.last_error ? "err" : "ok");
    libDetail.innerHTML = `${s.count} flowchart(s) trained · synced ${timeAgo(s.last_sync)}`
      + (s.last_error ? `<br><span style="color:#ff8a7a">${esc(s.last_error)}</span>` : "");
    libSync.disabled = false;
  } catch { libDetail.textContent = "Status unavailable."; }
}
libSync.addEventListener("click", async () => {
  libSync.disabled = true; libSync.classList.add("busy"); libSync.textContent = "Training… (reading images)";
  try {
    const r = await fetch("/api/flowchart/library/sync", { method: "POST" });
    const j = await r.json();
    if (!j.ok) { libDetail.textContent = "Error: " + (j.error || "sync failed"); libDot.className = "wd-dot err"; }
    else await refreshLib();
  } catch (e) { libDetail.textContent = "Network error during training."; }
  finally { libSync.classList.remove("busy"); libSync.textContent = "Train / Sync"; libSync.disabled = false; }
});
refreshLib();

/* ---- upload (reuses the proposal /api/extract endpoint) ---- */
const upload = $("flowUpload"), fileInput = $("flowFile");
$("flowBrowse").addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
upload.addEventListener("click", () => fileInput.click());
["dragover", "dragenter"].forEach(ev => upload.addEventListener(ev, e => { e.preventDefault(); upload.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => upload.addEventListener(ev, e => { e.preventDefault(); upload.classList.remove("over"); }));
upload.addEventListener("drop", e => { if (e.dataTransfer?.files?.length) { fileInput.files = e.dataTransfer.files; handleFiles(); } });
fileInput.addEventListener("change", handleFiles);

async function handleFiles() {
  if (!fileInput.files.length) return;
  const form = new FormData();
  for (const f of fileInput.files) form.append("files", f);
  setStatus("Reading document…");
  try {
    const r = await fetch("/api/extract", { method: "POST", body: form });
    const d = await r.json();
    if (!r.ok) { setStatus(d.error || "Upload failed", true); return; }
    const box = $("flowPrompt");
    box.value = (box.value ? box.value + "\n\n" : "") + (d.text || "");
    setStatus(d.errors?.length ? d.errors.join("; ") : "Document loaded. Edit or Generate.");
  } catch (e) { setStatus("Upload error: " + e.message, true); }
  finally { fileInput.value = ""; }
}

/* ---- generate ---- */
$("flowGen").addEventListener("click", async () => {
  const prompt = $("flowPrompt").value.trim();
  if (!prompt) { setStatus("Describe a workflow or upload a document first.", true); return; }
  const btn = $("flowGen"); btn.disabled = true;
  const endpoint = mode === "image" ? "/api/flowchart/image" : "/api/flowchart";
  showLoading(mode === "image" ? "Rendering image with gpt-image-2…" : "Drafting your flowchart…");
  setStatus(mode === "image" ? "Rendering image (gpt-image-2)… ~20s" : "Generating flowchart…");
  try {
    const r = await fetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const d = await r.json();
    if (!r.ok) { setStatus(d.error || "Generation failed", true); return; }
    if (mode === "image") renderImage(d.image, d.download_url);
    else await render(d.mermaid);
    showDetails(d, mode, prompt);
    setStatus(d.references?.length
      ? `Styled to match: ${d.references.map(x => x.name).join(", ")}`
      : "AI Status: Ready");
    saveFH({
      id: String(Date.now()), ts: Date.now(), prompt,
      title: (prompt.split("\n").find(l => l.trim()) || prompt).trim().slice(0, 52),
      mode, mermaid: mode === "diagram" ? d.mermaid : null,
      download_url: mode === "image" ? d.download_url : null,
    });
  } catch (e) { setStatus("Network error: " + e.message, true); }
  finally { hideLoading(); btn.disabled = false; }
});

/* ---- recent flowcharts history (localStorage) ---- */
const FHKEY = "helios.flowcharts.v1";
const loadFH = () => { try { return JSON.parse(localStorage.getItem(FHKEY) || "[]"); } catch { return []; } };
function saveFH(entry) {
  const list = loadFH().filter(x => x.id !== entry.id);
  list.unshift(entry);
  localStorage.setItem(FHKEY, JSON.stringify(list.slice(0, 30)));
  renderFH();
}
function renderFH() {
  const list = loadFH(), el = $("flowHist");
  if (!list.length) { el.innerHTML = '<div class="fh-empty">No flowcharts yet</div>'; return; }
  el.innerHTML = list.map(it =>
    `<button class="fh-item" data-id="${it.id}"><span class="fh-title">${esc(it.title || "Flowchart")}</span><span class="fh-mode ${it.mode === "image" ? "img" : ""}">${it.mode === "image" ? "IMG" : "DGM"}</span></button>`
  ).join("");
  el.querySelectorAll(".fh-item").forEach(b => b.addEventListener("click", () => openFH(b.dataset.id)));
}
function openFH(id) {
  const it = loadFH().find(x => x.id === id); if (!it) return;
  if (it.prompt) $("flowPrompt").value = it.prompt;
  if (it.mode === "image" && it.download_url) { renderImage(it.download_url); setStatus("Loaded saved image"); }
  else if (it.mermaid) { render(it.mermaid); setStatus("Loaded saved diagram"); }
}
$("fhClear")?.addEventListener("click", () => { localStorage.removeItem(FHKEY); renderFH(); });
renderFH();

function showLoading(text) {
  $("loadingText").textContent = text || "Generating…";
  $("flowEmpty").style.display = "none";
  $("flowRender").innerHTML = "";
  $("flowLoading").classList.add("show");
}
function hideLoading() { $("flowLoading").classList.remove("show"); }

let imageUrl = null;
function renderImage(dataUri, downloadUrl) {
  imageUrl = dataUri;
  window._mermaidSrc = null;
  $("flowEmpty").style.display = "none";
  $("flowRender").innerHTML = `<img src="${dataUri}" alt="Generated flowchart" style="max-width:100%;border-radius:12px;display:block">`;
  zoom = 1; panX = panY = 0; applyZoom();
}

async function render(src) {
  window._mermaidSrc = src; imageUrl = null; zoom = 1; panX = panY = 0;
  $("flowEmpty").style.display = "none";
  try {
    const { svg } = await mermaid.render("flowGraph_" + Date.now(), src);
    $("flowRender").innerHTML = svg;
    zoom = 1; applyZoom();
  } catch (e) {
    $("flowRender").innerHTML = `<pre style="color:#ff7b72;white-space:pre-wrap">${esc(src)}</pre>`;
  }
}

function setStatus(msg, err) {
  const s = $("flowStatus");
  s.textContent = msg; s.style.color = err ? "var(--error)" : "";
}

/* ---- zoom + pan ---- */
function applyZoom() {
  $("flowRender").style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  $("zoomVal").textContent = Math.round(zoom * 100) + "%";
}
$("zoomIn").addEventListener("click", () => { zoom = Math.min(3, zoom + 0.15); applyZoom(); });
$("zoomOut").addEventListener("click", () => { zoom = Math.max(0.3, zoom - 0.15); applyZoom(); });
$("zoomReset").addEventListener("click", () => { zoom = 1; panX = panY = 0; applyZoom(); });

const scroll = $("canvasScroll");
let dragging = false, sx = 0, sy = 0;
scroll.addEventListener("mousedown", e => {
  if (e.target.closest(".detail-panel") || e.target.closest(".canvas-toolbar")) return;
  dragging = true; sx = e.clientX - panX; sy = e.clientY - panY; scroll.classList.add("panning");
});
window.addEventListener("mousemove", e => { if (!dragging) return; panX = e.clientX - sx; panY = e.clientY - sy; applyZoom(); });
window.addEventListener("mouseup", () => { dragging = false; scroll.classList.remove("panning"); });
scroll.addEventListener("wheel", e => {
  if (!e.ctrlKey) return; e.preventDefault();
  zoom = Math.min(3, Math.max(0.3, zoom + (e.deltaY < 0 ? 0.1 : -0.1))); applyZoom();
}, { passive: false });

/* ---- color theme dots ---- */
document.querySelectorAll("#colorDots .cdot").forEach(dot =>
  dot.addEventListener("click", async () => {
    accent = dot.dataset.color;
    document.querySelectorAll("#colorDots .cdot").forEach(x => x.classList.toggle("active", x === dot));
    initMermaid();
    if (window._mermaidSrc) await render(window._mermaidSrc);
  })
);

/* ---- generation details panel ---- */
function showDetails(d, gmode, prompt) {
  $("dpType").textContent = gmode === "image" ? "AI Image · gpt-image-2" : "Mermaid Diagram";
  const refs = d.references || [];
  if (refs.length) {
    const top = refs[0], pct = Math.round((top.score || 0) * 100);
    $("dpMatchWrap").hidden = false;
    $("dpMatchFill").style.width = pct + "%";
    $("dpMatchVal").textContent = pct + "%";
    $("dpRef").textContent = "Matched: " + top.name;
  } else $("dpMatchWrap").hidden = true;
  const p = (prompt || "").trim();
  $("dpTrace").textContent = '"' + p.slice(0, 240) + (p.length > 240 ? "…" : "") + '"';
  $("detailPanel").hidden = false;
}
$("dpClose").addEventListener("click", () => $("detailPanel").hidden = true);

/* ---- export ---- */
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("dlSvg").addEventListener("click", () => {
  const svg = $("flowRender").querySelector("svg"); if (!svg) return;
  downloadBlob(new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml" }), "flowchart.svg");
});
$("dlPng").addEventListener("click", () => {
  if (imageUrl) {  // AI Image mode — download the generated PNG directly
    const a = document.createElement("a"); a.href = imageUrl; a.download = "flowchart.png"; a.click();
    return;
  }
  const svg = $("flowRender").querySelector("svg"); if (!svg) return;
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.onload = () => {
    const scale = 2, w = svg.viewBox.baseVal.width || svg.clientWidth, h = svg.viewBox.baseVal.height || svg.clientHeight;
    const canvas = document.createElement("canvas");
    canvas.width = w * scale; canvas.height = h * scale;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#10131a"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale); ctx.drawImage(img, 0, 0, w, h);
    canvas.toBlob(b => downloadBlob(b, "flowchart.png"), "image/png");
  };
  img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
});
