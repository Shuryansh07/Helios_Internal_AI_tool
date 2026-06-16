"""
Transcript intelligence: classify the client and extract structured meeting
details in a single OpenAI call.

Returns one rich dict that every downstream generator consumes, so analysis runs
once per meeting regardless of which documents the user later generates.
"""
import json
import os

import llm

# We force OpenAI per the project decision; the openai provider already requests
# a JSON object response, so the model reliably returns parseable JSON.
_PROVIDER = "openai"

# Meeting transcripts are large (and non-Latin scripts tokenize densely), so the
# dashboard runs on a cheaper, higher rate-limit model by default. Override with
# OPENAI_DASHBOARD_MODEL. TRANSCRIPT_CHAR_LIMIT bounds tokens-per-request.
MODEL = os.getenv("OPENAI_DASHBOARD_MODEL", "gpt-4o-mini")
CHAR_LIMIT = int(os.getenv("TRANSCRIPT_CHAR_LIMIT", "40000"))

ANALYSIS_SYSTEM_PROMPT = """You are a meeting intelligence analyst for a software/IT services company.
You read a meeting transcript and return ONE JSON object (no markdown, no commentary).

First decide whether the meeting is with an EXISTING CLIENT or a NEW LEAD.

Signals for EXISTING CLIENT:
- References to past projects, invoices, ongoing work, or previous conversations
- Discussion of bugs, updates, enhancements, or support for a system already built
- The client implies their company has worked with us before

Signals for NEW LEAD:
- First-time introduction of their business
- Requirements discussed from scratch, discovery-phase language
  ("we are looking for", "we need someone to", "can you build")
- No reference to past work together

Be honest with the confidence score. If signals are weak or mixed, lower it.

Then extract everything useful. Use empty strings/lists when something was not
discussed — never invent facts, names, budgets, or dates that are not in the
transcript.

Also read the CLIENT'S MOOD from tone, word choice, enthusiasm, concerns,
hesitation, and how they respond. Judge sentiment toward the project/engagement —
not the meeting's general politeness. Base it only on the transcript.

Return EXACTLY this JSON schema:
{
  "classification": "new_lead" | "existing_client",
  "confidence": 0-100 integer,
  "client_name": "company or client name, or '' if unclear",
  "sentiment": {
    "overall": "positive" | "neutral" | "negative",
    "score": 0-100 integer (0 = very negative, 50 = neutral, 100 = very positive),
    "mood": ONE word/label describing the client's emotion — choose the closest of:
            "Happy", "Excited", "Satisfied", "Neutral", "Concerned",
            "Slightly Angry", "Angry", "Frustrated",
    "signals": ["short phrases/cues from the transcript that reveal the mood"]
  },
  "summary": "2-3 sentence neutral summary of the meeting",
  "requirements": ["concrete requirements/asks discussed"],
  "budget": "any budget hint stated, else ''",
  "timeline": "any timeline/deadline stated, else ''",
  "tech_stack": ["technologies explicitly mentioned"],
  "decision_makers": ["named people who appear to decide, with role if stated"],
  "attendees": ["all named participants"],
  "agenda_items": ["topics covered, in order"],
  "decisions": ["decisions explicitly made"],
  "issues": ["problems / blockers / concerns raised"],
  "next_steps": ["agreed follow-ups"],
  "action_items": [
    {"description": "...", "assigned_to": "name or ''",
     "priority": "High" | "Medium" | "Low", "due_date": "as stated or ''"}
  ]
}
Infer action-item priority from urgency/tone in the transcript. Default to "Medium" when unclear."""


def _loose_json(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start:end + 1])
        raise


def _coerce(data: dict) -> dict:
    """Guarantee every expected key exists and has the right shape."""
    def slist(key):
        v = data.get(key) or []
        if not isinstance(v, list):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()]

    cls = str(data.get("classification") or "").lower()
    if cls not in ("new_lead", "existing_client"):
        cls = "new_lead"  # safe default: treat unknowns as discovery

    try:
        conf = int(round(float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0
    conf = max(0, min(100, conf))

    actions = []
    for a in (data.get("action_items") or []):
        if not isinstance(a, dict):
            a = {"description": str(a)}
        pr = str(a.get("priority") or "Medium").capitalize()
        if pr not in ("High", "Medium", "Low"):
            pr = "Medium"
        desc = str(a.get("description") or "").strip()
        if not desc:
            continue
        actions.append({
            "description": desc,
            "assigned_to": str(a.get("assigned_to") or "").strip(),
            "priority": pr,
            "due_date": str(a.get("due_date") or "").strip(),
        })

    sent = data.get("sentiment")
    if not isinstance(sent, dict):
        sent = {}
    overall = str(sent.get("overall") or "").lower()
    if overall not in ("positive", "neutral", "negative"):
        overall = "neutral"
    try:
        sscore = int(round(float(sent.get("score", 50))))
    except (TypeError, ValueError):
        sscore = 50
    sscore = max(0, min(100, sscore))
    sentiment = {
        "overall": overall,
        "score": sscore,
        "mood": str(sent.get("mood") or "").strip(),
        "signals": [str(x).strip() for x in (sent.get("signals") or []) if str(x).strip()],
    }

    return {
        "classification": cls,
        "confidence": conf,
        "client_name": str(data.get("client_name") or "").strip(),
        "sentiment": sentiment,
        "summary": str(data.get("summary") or "").strip(),
        "requirements": slist("requirements"),
        "budget": str(data.get("budget") or "").strip(),
        "timeline": str(data.get("timeline") or "").strip(),
        "tech_stack": slist("tech_stack"),
        "decision_makers": slist("decision_makers"),
        "attendees": slist("attendees"),
        "agenda_items": slist("agenda_items"),
        "decisions": slist("decisions"),
        "issues": slist("issues"),
        "next_steps": slist("next_steps"),
        "action_items": actions,
    }


def analyze_transcript(transcript: str, meeting_meta: dict | None = None) -> dict:
    """Classify + extract from a transcript. Returns the coerced analysis dict."""
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Transcript is empty.")

    meta_line = ""
    if meeting_meta:
        bits = [f"{k}: {v}" for k, v in meeting_meta.items() if v]
        if bits:
            meta_line = "MEETING METADATA: " + " | ".join(bits) + "\n\n"

    user_prompt = (
        meta_line
        + "=== MEETING TRANSCRIPT ===\n"
        + transcript[:CHAR_LIMIT]  # keep request under the model's TPM
        + "\n\nReturn the analysis JSON now."
    )
    raw = llm.generate(_PROVIDER, ANALYSIS_SYSTEM_PROMPT, user_prompt, model=MODEL)
    return _coerce(_loose_json(raw))


FLOWCHART_SYSTEM_PROMPT = """You are a systems analyst. Given extracted meeting requirements for a software
project, produce a Mermaid.js flowchart that shows the proposed system's user
journey and component/data flow.

Return ONE JSON object: {"mermaid": "<mermaid source>"}.

Rules for the mermaid source:
- It MUST start with "flowchart TD".
- Keep node labels short and quoted where they contain spaces/special chars.
- 8-16 nodes is ideal. Group with subgraphs if it helps clarity.
- Only model what the requirements support; do not invent unrelated components.
- Use \\n for line breaks inside the JSON string."""


def generate_flowchart_mermaid(analysis: dict) -> str:
    """Ask OpenAI for a Mermaid flowchart based on the analysis. Returns mermaid source."""
    reqs = "\n".join(f"- {r}" for r in analysis.get("requirements", [])) or "(none captured)"
    tech = ", ".join(analysis.get("tech_stack", [])) or "unspecified"
    user_prompt = (
        f"CLIENT: {analysis.get('client_name') or 'Prospect'}\n"
        f"TECH STACK: {tech}\n\n"
        f"REQUIREMENTS:\n{reqs}\n\n"
        "Return the JSON with the mermaid flowchart now."
    )
    raw = llm.generate(_PROVIDER, FLOWCHART_SYSTEM_PROMPT, user_prompt, model=MODEL)
    return _clean_mermaid(raw)


FLOWCHART_TEXT_SYSTEM = """You are a process architect for a Zoho implementation company. Convert the user's
described workflow (or a PRD / requirements document) into a Mermaid.js flowchart
that captures the steps, decisions, and branches.

When HOUSE-STYLE REFERENCE flowcharts are provided, MATCH their structure and
conventions: how work is grouped (e.g. swimlanes/branches per Zoho app), node
naming style, granularity, and how decisions/branches are shown. The references
are for STYLE — use the user's workflow for the actual content.

Return ONE JSON object: {"mermaid": "<mermaid source>"}.

Rules for the mermaid source:
- It MUST start with "flowchart TD".
- Use decision nodes for conditionals: cond{"Question?"} with labeled edges -->|Yes| / -->|No|.
- Keep node labels short; quote labels containing spaces/special characters.
- Model only what the description supports; do not invent unrelated steps.
- Use \\n for line breaks inside the JSON string."""


def flowchart_from_text(description: str, references: list | None = None) -> str:
    """Generate a Mermaid flowchart from a workflow description, optionally guided
    by house-style reference flowcharts (each a dict with name/mermaid/style_notes)."""
    description = (description or "").strip()
    if not description:
        raise ValueError("Describe a workflow or upload a document first.")

    ref_block = ""
    for r in (references or [])[:2]:
        ref_block += (
            f"\n--- HOUSE-STYLE REFERENCE: {r.get('name','')} ---\n"
            f"Style: {r.get('style_notes','')}\n"
            f"Mermaid:\n{(r.get('mermaid') or '')[:2500]}\n"
        )
    if ref_block:
        ref_block = ("\n\n=== HOUSE-STYLE REFERENCES (match this structure/conventions, NOT the content) ==="
                     + ref_block)

    user_prompt = ("WORKFLOW / REQUIREMENTS:\n" + description[:CHAR_LIMIT] + ref_block
                   + "\n\nReturn the JSON with the mermaid flowchart now.")
    raw = llm.generate(_PROVIDER, FLOWCHART_TEXT_SYSTEM, user_prompt, model=MODEL)
    return _clean_mermaid(raw)


def _clean_mermaid(raw: str) -> str:
    src = str(_loose_json(raw).get("mermaid") or "").strip()
    if src.startswith("```"):
        src = src.removeprefix("```mermaid").removeprefix("```").removesuffix("```").strip()
    if not src.lower().startswith(("flowchart", "graph")):
        src = "flowchart TD\n" + src
    return src


PORTFOLIO_SYSTEM = """You are a delivery operations analyst reviewing a software company's live project
portfolio (from Zoho Projects). Give a sharp, honest read of portfolio health.
Base everything ONLY on the data provided — do not invent projects or numbers.

Return ONE JSON object:
{
  "headline": "one punchy sentence on overall portfolio health",
  "summary": "2-4 sentences: what's going well, where the pressure is",
  "at_risk": [
    {"project": "name", "reason": "why it's at risk (overdue, stalled at low %, heavy open-task load, on hold, etc.)",
     "severity": "High" | "Medium" | "Low"}
  ],
  "recommendations": ["concrete, prioritised next actions for the delivery lead"]
}
Flag as at-risk: overdue projects, ones started but stuck near 0%, very high open-task counts, or On Hold items. List the most important 3-6."""


def analyze_portfolio(portfolio: dict) -> dict:
    """AI read of the project portfolio: headline, summary, at-risk list, recommendations."""
    stats = portfolio.get("stats", {})
    projects = portfolio.get("projects", [])
    lines = []
    for p in projects[:120]:
        lines.append(
            f"- {p['name']} | status={p['status']} | {p['percent']}% | "
            f"open_tasks={p['open_tasks']} | open_milestones={p['open_milestones']} | "
            f"due={p['end_date'] or 'n/a'}{' | OVERDUE' if p['overdue'] else ''}"
        )
    user = (
        f"PORTFOLIO STATS: total={stats.get('total')}, active={stats.get('active')}, "
        f"completed={stats.get('completed')}, overdue={stats.get('overdue')}, "
        f"open_tasks={stats.get('open_tasks')}, avg_completion={stats.get('avg_percent')}%\n\n"
        "PROJECTS:\n" + "\n".join(lines) + "\n\nReturn the portfolio analysis JSON now."
    )
    raw = llm.generate(_PROVIDER, PORTFOLIO_SYSTEM, user, model=MODEL)
    d = _loose_json(raw)
    at_risk = []
    for a in (d.get("at_risk") or []):
        if isinstance(a, dict) and (a.get("project") or a.get("reason")):
            sev = str(a.get("severity") or "Medium").capitalize()
            at_risk.append({
                "project": str(a.get("project") or "").strip(),
                "reason": str(a.get("reason") or "").strip(),
                "severity": sev if sev in ("High", "Medium", "Low") else "Medium",
            })
    return {
        "headline": str(d.get("headline") or "").strip(),
        "summary": str(d.get("summary") or "").strip(),
        "at_risk": at_risk,
        "recommendations": [str(x).strip() for x in (d.get("recommendations") or []) if str(x).strip()],
    }


FOCUS_SYSTEM = """You are a delivery lead planning the next moves on a single software project.
You are given the project's open tasks (from Zoho Projects) and any action items
captured from client meetings. Produce a focused, prioritised plan. Base it ONLY
on the items provided — do not invent tasks.

Return ONE JSON object:
{
  "focus": "1-2 sentences on what to concentrate on right now",
  "priorities": [
    {"item": "the task/action to do", "why": "why it's high priority", "rank": 1}
  ],
  "quick_wins": ["small items that can be closed fast"],
  "blockers": ["anything that looks like a blocker or needs a decision"]
}
Order priorities 1..N (most important first), 4-7 items. Pull from BOTH the Zoho
tasks and the meeting action items, and call out where a meeting action isn't yet
reflected in the project tasks."""


def analyze_project_tasks(project_name: str, tasks: list, meeting_actions: list | None = None) -> dict:
    """AI focus plan for one project, combining its Zoho tasks and saved meeting actions."""
    tlines = [f"- [{t.get('status')}/{t.get('priority')}] {t.get('name')}"
              + (f" (owner {t['owner']})" if t.get("owner") else "")
              for t in (tasks or []) if not t.get("is_completed")][:80]
    mlines = [f"- [{m.get('priority')}] {m.get('description')}"
              + (f" (owner {m['owner']})" if m.get("owner") else "")
              for m in (meeting_actions or []) if not m.get("done")][:40]
    user = (
        f"PROJECT: {project_name}\n\n"
        "OPEN ZOHO TASKS:\n" + ("\n".join(tlines) or "(none)") + "\n\n"
        "MEETING ACTION ITEMS (from client calls):\n" + ("\n".join(mlines) or "(none)") + "\n\n"
        "Return the focus plan JSON now."
    )
    raw = llm.generate(_PROVIDER, FOCUS_SYSTEM, user, model=MODEL)
    d = _loose_json(raw)
    pri = []
    for i, p in enumerate(d.get("priorities") or [], 1):
        if isinstance(p, dict) and p.get("item"):
            pri.append({"item": str(p.get("item")).strip(),
                        "why": str(p.get("why") or "").strip(),
                        "rank": int(p.get("rank") or i)})
    return {
        "focus": str(d.get("focus") or "").strip(),
        "priorities": pri,
        "quick_wins": [str(x).strip() for x in (d.get("quick_wins") or []) if str(x).strip()],
        "blockers": [str(x).strip() for x in (d.get("blockers") or []) if str(x).strip()],
    }
