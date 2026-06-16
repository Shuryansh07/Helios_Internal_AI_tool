/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const escHtml = (s) => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/* ---------- state ---------- */
const state = {
  attachments: [],         // [{name, text}] — files uploaded in the current turn
  currentChatId: null,
  // multi-turn conversation memory:
  requirement: "",         // the initial client requirement for this chat
  currentProposal: null,   // last proposal JSON the model produced (for edits)
  messages: [],            // [{role: 'user'|'assistant', content: string}]
  format: "docx",          // output format: "docx" (Word) or "xlsx" (Excel)
};

/* ---------- elements ---------- */
const chatView = $("chat");
const centerLogo = $("centerLogo");
const msgInput = $("msg");
const sendBtn = $("go");
const attachBtn = $("attach");
const fileInput = $("fileInput");
const attachmentsBar = $("attachments");
const providerSelect = $("provider");
const sidebar = $("sidebar");

/* ---------- auto-grow textarea ---------- */
function autoGrow() {
  msgInput.style.height = "auto";
  msgInput.style.height = Math.min(msgInput.scrollHeight, 200) + "px";
}
msgInput.addEventListener("input", autoGrow);
msgInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendBtn.click(); }
});

/* ---------- attachments (file picker) ---------- */
attachBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", async () => {
  if (!fileInput.files.length) return;
  const form = new FormData();
  for (const f of fileInput.files) form.append("files", f);
  attachBtn.disabled = true;
  try {
    const res = await fetch("/api/extract", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) { addErrorBubble(data.error || "Upload failed."); return; }
    // Split the combined text back per file using the "--- name ---" header we add server-side
    const blocks = data.text.split(/^--- (.+?) ---\n/m).filter(Boolean);
    // blocks alternates [filename, text, filename, text...]
    for (let i = 0; i < blocks.length; i += 2) {
      const name = blocks[i], text = (blocks[i + 1] || "").trim();
      if (name && text) state.attachments.push({ name, text });
    }
    if (data.errors?.length) addErrorBubble(data.errors.join("; "));
    renderAttachments();
  } catch (e) {
    addErrorBubble("Upload error: " + e.message);
  } finally {
    attachBtn.disabled = false;
    fileInput.value = "";
  }
});

function renderAttachments() {
  attachmentsBar.innerHTML = "";
  attachmentsBar.hidden = state.attachments.length === 0;
  state.attachments.forEach((a, idx) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `📎 ${escHtml(a.name)}<span class="x" data-i="${idx}" title="Remove">×</span>`;
    attachmentsBar.appendChild(chip);
  });
  attachmentsBar.querySelectorAll(".x").forEach(el =>
    el.addEventListener("click", () => {
      state.attachments.splice(+el.dataset.i, 1);
      renderAttachments();
    })
  );
}

/* ---------- chat rendering ---------- */
function addUserBubble(text) {
  chatView.classList.add("has-messages");
  const wrap = document.createElement("div");
  wrap.className = "message-wrap user";
  wrap.innerHTML = `<div class="bubble user">${escHtml(text)}</div>`;
  chatView.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

function addThinking() {
  chatView.classList.add("has-messages");
  const wrap = document.createElement("div");
  wrap.className = "message-wrap";
  wrap.innerHTML = `<div class="bubble assistant"><i style="color:var(--muted)">Drafting a realistic proposal…</i></div>`;
  chatView.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
  return wrap;
}

function addAssistantText(text) {
  chatView.classList.add("has-messages");
  const wrap = document.createElement("div");
  wrap.className = "message-wrap";
  wrap.innerHTML = `<div class="bubble assistant">${escHtml(text).replace(/\n/g, "<br>")}</div>`;
  chatView.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

function addErrorBubble(msg) {
  chatView.classList.add("has-messages");
  const wrap = document.createElement("div");
  wrap.className = "message-wrap";
  wrap.innerHTML = `<div class="bubble error">${escHtml(msg)}</div>`;
  chatView.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

function renderProposalBubble(c, downloadUrl, filename, usedTemplate, autoMatched, type, changesSummary, format) {
  const wrap = document.createElement("div");
  wrap.className = "message-wrap";
  const list = (arr) => !arr?.length ? "" :
    "<ul>" + arr.map(i => "<li>" + escHtml(typeof i === "object" ? Object.values(i).filter(Boolean).join(" — ") : i) + "</li>").join("") + "</ul>";

  let inner = "";
  if (type === "edit") inner += `<div class="edit-tag">✏️ Updated proposal${changesSummary ? " — " + escHtml(changesSummary) : ""}</div>`;
  inner += `<h3>${escHtml(c.project_title || "Proposal")}</h3>`;
  if (c.objective) inner += `<p><b>Objective:</b> ${escHtml(c.objective)}</p>`;
  (c.milestones || []).forEach(m => {
    inner += `<p><b>${escHtml(m.title || "Milestone")}</b></p>${list(m.scope)}`;
  });
  if (c.total_effort || c.total_cost) {
    inner += `<p><b>Effort:</b> ${escHtml(c.total_effort || "—")}<br><b>Cost:</b> ${escHtml(c.total_cost || "—")}</p>`;
  }
  inner += `<a class="download" href="${downloadUrl}" download>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download ${escHtml(filename)}
            </a>`;
  if (autoMatched?.length) {
    const list = autoMatched.map(m => `${escHtml(m.name)}${m.score ? ` <span style="color:var(--muted)">(${(m.score*100|0)}% match)</span>` : ""}`).join("<br>");
    inner += `<div class="auto-matches"><b>✨ Auto-matched from WorkDrive:</b><br>${list}</div>`;
  }
  const metaText = format === "xlsx"
    ? "Excel (.xlsx) in the WorkDrive proposal format."
    : (usedTemplate ? "Filled into your Word template." : "Default layout used (no template found).");
  inner += `<div class="meta">${metaText}</div>`;
  wrap.innerHTML = `<div class="bubble assistant">${inner}</div>`;
  chatView.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

/* ---------- send / generate ---------- */
sendBtn.addEventListener("click", async () => {
  const typed = msgInput.value.trim();
  if (!typed && !state.attachments.length) return;

  const provider = providerSelect.value;

  // Build the current turn's user content (typed text + any attachments).
  const turnBlocks = [];
  if (typed) turnBlocks.push(typed);
  state.attachments.forEach(a => turnBlocks.push(`--- ${a.name} ---\n${a.text}`));
  const turnContent = turnBlocks.join("\n\n");

  // If this turn has fresh file attachments OR there's no requirement yet,
  // treat it as setting/refreshing the client requirement.
  if (state.attachments.length || !state.requirement) {
    state.requirement = turnContent;
  }

  const attachmentNames = state.attachments.map(a => a.name);
  const displayMsg = (typed || "(no text — using uploaded files)")
                    + (attachmentNames.length ? `\n\n📎 ${attachmentNames.join(", ")}` : "");
  addUserBubble(displayMsg);

  // Append to conversation memory.
  state.messages.push({ role: "user", content: turnContent });

  // Clear the input + uploaded files for next turn
  msgInput.value = ""; autoGrow();
  state.attachments = []; renderAttachments();

  const thinking = addThinking();
  sendBtn.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider,
        format: state.format,
        requirement: state.requirement,
        current_proposal: state.currentProposal,
        messages: state.messages,
      }),
    });
    const data = await res.json();
    thinking.remove();
    if (!res.ok) { addErrorBubble(data.error || "Failed."); return; }

    if (data.type === "chat") {
      addAssistantText(data.message);
      state.messages.push({ role: "assistant", content: data.message });
    } else {
      // proposal | edit
      renderProposalBubble(
        data.content, data.download_url, data.filename, data.used_template,
        data.auto_matched, data.type, data.changes_summary, data.format
      );
      state.currentProposal = data.content;
      state.messages.push({
        role: "assistant",
        content: data.type === "edit"
          ? `Updated the proposal: ${data.changes_summary || "(no summary)"}`
          : `Generated proposal: ${data.content.project_title || ""}`,
      });
      saveHistory({
        id: state.currentChatId || (state.currentChatId = Date.now().toString()),
        title: data.content.project_title || state.requirement.slice(0, 60),
        ts: Date.now(),
        provider,
        requirement: state.requirement,
        proposal: data.content,
        download_url: data.download_url,
        filename: data.filename,
        used_template: data.used_template,
        format: data.format,
        auto_matched: data.auto_matched,
        messages: state.messages,
      });
    }
  } catch (e) {
    thinking.remove();
    addErrorBubble("Network error: " + e.message);
  } finally {
    sendBtn.disabled = false;
  }
});

/* ---------- history (localStorage) ---------- */
const HKEY = "helios.history.v1";
function loadHistory() { try { return JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch { return []; } }
function writeHistory(list) { localStorage.setItem(HKEY, JSON.stringify(list)); }

function saveHistory(entry) {
  const list = loadHistory();
  const existing = list.findIndex(x => x.id === entry.id);
  if (existing >= 0) list[existing] = entry; else list.unshift(entry);
  writeHistory(list.slice(0, 50));  // keep last 50
  state.currentChatId = entry.id;
  renderHistory();
}

function renderHistory() {
  const list = loadHistory();
  const today = $("todayList"), older = $("olderList");
  today.innerHTML = ""; older.innerHTML = "";
  const startOfToday = new Date(); startOfToday.setHours(0,0,0,0);
  const t = startOfToday.getTime();
  let hasToday = false, hasOlder = false;
  list.forEach(item => {
    const btn = document.createElement("button");
    btn.className = "history-item" + (item.id === state.currentChatId ? " active" : "");
    btn.textContent = item.title || "Untitled";
    btn.title = item.title;
    btn.addEventListener("click", () => openChat(item.id));
    if (item.ts >= t) { today.appendChild(btn); hasToday = true; }
    else { older.appendChild(btn); hasOlder = true; }
  });
  $("todayHeader").hidden = !hasToday;
  $("olderHeader").hidden = !hasOlder;
}

function openChat(id) {
  const list = loadHistory();
  const item = list.find(x => x.id === id);
  if (!item) return;
  state.currentChatId = id;
  state.requirement = item.requirement || "";
  state.currentProposal = item.proposal || null;
  state.messages = Array.isArray(item.messages) ? item.messages.slice() : [];
  chatView.innerHTML = "";
  chatView.appendChild(centerLogo);
  chatView.classList.add("has-messages");

  // Replay the conversation. The first user message includes the requirement.
  if (state.messages.length) {
    state.messages.forEach((m, idx) => {
      if (m.role === "user") {
        addUserBubble(m.content);
      } else if (idx === state.messages.length - 1 && state.currentProposal) {
        // Last assistant turn = the latest proposal — show full proposal bubble
        renderProposalBubble(state.currentProposal, item.download_url, item.filename, item.used_template, item.auto_matched, undefined, undefined, item.format);
      } else {
        addAssistantText(m.content);
      }
    });
  } else {
    // legacy entries: just show what we have
    addUserBubble(item.userDisplay || item.requirement || "");
    if (item.proposal) {
      renderProposalBubble(item.proposal, item.download_url, item.filename, item.used_template, item.auto_matched, undefined, undefined, item.format);
    }
  }
  renderHistory();
}

function newChat() {
  state.currentChatId = null;
  state.attachments = [];
  state.requirement = "";
  state.currentProposal = null;
  state.messages = [];
  renderAttachments();
  chatView.innerHTML = "";
  chatView.appendChild(centerLogo);
  chatView.classList.remove("has-messages");
  msgInput.value = ""; autoGrow();
  renderHistory();
}

/* ---------- output format toggle (.docx / .xlsx) ---------- */
document.querySelectorAll("#formatToggle .fmt-btn").forEach(btn =>
  btn.addEventListener("click", () => {
    state.format = btn.dataset.fmt;
    document.querySelectorAll("#formatToggle .fmt-btn")
      .forEach(b => b.classList.toggle("active", b === btn));
  })
);

/* ---------- sidebar buttons ---------- */
$("newChat").addEventListener("click", newChat);
$("sideToggle").addEventListener("click", () => sidebar.classList.toggle("collapsed"));

/* ---------- WorkDrive sidebar ---------- */
const wdDot = $("wdDot"), wdDetail = $("wdDetail"), wdSync = $("wdSync");

function timeAgo(iso) {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (isNaN(ms)) return "unknown";
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

async function refreshWorkDriveStatus() {
  try {
    const s = await (await fetch("/api/workdrive/status")).json();
    if (!s.configured) {
      wdDot.className = "wd-dot";
      wdDetail.textContent = "Not configured — add Zoho keys to .env";
      wdSync.disabled = true;
      return;
    }
    wdDot.className = "wd-dot " + (s.last_error ? "err" : "ok");
    wdDetail.innerHTML = `${s.count} proposal(s) indexed<br>Synced ${timeAgo(s.last_sync)}`
      + (s.last_error ? `<br><span style="color:#ff8a7a">${escHtml(s.last_error)}</span>` : "");
    wdSync.disabled = false;
  } catch (e) {
    wdDetail.textContent = "Status unavailable.";
  }
}

wdSync.addEventListener("click", async () => {
  wdSync.disabled = true; wdSync.classList.add("busy"); wdSync.textContent = "Syncing…";
  try {
    const r = await fetch("/api/workdrive/sync", { method: "POST" });
    const j = await r.json();
    if (!j.ok) { wdDetail.textContent = "Error: " + (j.error || "sync failed"); wdDot.className = "wd-dot err"; }
    else { await refreshWorkDriveStatus(); }
  } catch (e) {
    wdDetail.textContent = "Network error during sync.";
  } finally {
    wdSync.classList.remove("busy"); wdSync.textContent = "Sync"; wdSync.disabled = false;
  }
});

/* ---------- init ---------- */
if (providerSelect.options[providerSelect.selectedIndex]?.disabled) {
  const firstEnabled = Array.from(providerSelect.options).find(o => !o.disabled);
  if (firstEnabled) providerSelect.value = firstEnabled.value;
}
renderHistory();
autoGrow();
refreshWorkDriveStatus();

/* ---------- prefill handed off from the Meeting Intelligence dashboard ---------- */
(function applyPrefill() {
  const pre = localStorage.getItem("helios.prefill");
  if (pre) {
    localStorage.removeItem("helios.prefill");
    msgInput.value = pre;
    autoGrow();
    msgInput.focus();
  }
})();
