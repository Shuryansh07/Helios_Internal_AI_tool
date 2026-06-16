"""
Expand a meeting analysis into document-specific structured content for the SRS
and SOW. One OpenAI call each, grounded strictly in the extracted requirements —
no invented scope, budgets, or dates.

MOM and Action Items don't need expansion: the analysis already carries agenda /
decisions / issues / next_steps / action_items directly.
"""
import json
import os

import llm

_PROVIDER = "openai"
MODEL = os.getenv("OPENAI_DASHBOARD_MODEL", "gpt-4o-mini")
CHAR_LIMIT = int(os.getenv("TRANSCRIPT_CHAR_LIMIT", "40000"))


def _loose_json(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            return json.loads(s[a:b + 1])
        raise


def _slist(v):
    if not v:
        return []
    if not isinstance(v, list):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()]


def _analysis_brief(analysis: dict, transcript: str | None = None) -> str:
    brief = (
        f"CLIENT: {analysis.get('client_name') or 'Prospect'}\n"
        f"TIMELINE MENTIONED: {analysis.get('timeline') or '(none)'}\n"
        f"BUDGET MENTIONED: {analysis.get('budget') or '(none)'}\n"
        f"TECH STACK: {', '.join(analysis.get('tech_stack', [])) or '(unspecified)'}\n\n"
        "REQUIREMENTS DISCUSSED:\n"
        + ("\n".join(f"- {r}" for r in analysis.get("requirements", [])) or "(none captured)")
        + "\n\nMEETING SUMMARY:\n" + (analysis.get("summary") or "")
    )
    if transcript and transcript.strip():
        brief += ("\n\n=== FULL MEETING TRANSCRIPT (primary source — ground every detail here) ===\n"
                  + transcript.strip()[:CHAR_LIMIT])
    return brief


SRS_SYSTEM = """You are a senior business analyst writing a Software Requirements Specification.
Base EVERYTHING strictly on the meeting requirements provided — do not invent
features, integrations, or numbers that were not discussed. Keep it realistic and
implementable. No grandiose language.

Return ONE JSON object:
{
  "executive_summary": "2-4 sentence plain-language summary of the system",
  "functional_requirements": ["specific, testable 'The system shall ...' statements"],
  "non_functional_requirements": ["performance, security, usability, availability, etc. — only those reasonably implied"],
  "system_architecture": "short paragraph describing the high-level architecture/components",
  "assumptions": ["assumptions made due to gaps in the requirements"],
  "dependencies": ["external systems, data, or client inputs the project depends on"],
  "out_of_scope": ["things explicitly NOT included to prevent scope creep"]
}"""


def srs_content(analysis: dict, transcript: str | None = None) -> dict:
    raw = llm.generate(_PROVIDER, SRS_SYSTEM, _analysis_brief(analysis, transcript) + "\n\nReturn the SRS JSON now.", model=MODEL)
    d = _loose_json(raw)
    return {
        "executive_summary": str(d.get("executive_summary") or "").strip(),
        "functional_requirements": _slist(d.get("functional_requirements")),
        "non_functional_requirements": _slist(d.get("non_functional_requirements")),
        "system_architecture": str(d.get("system_architecture") or "").strip(),
        "assumptions": _slist(d.get("assumptions")),
        "dependencies": _slist(d.get("dependencies")),
        "out_of_scope": _slist(d.get("out_of_scope")),
    }


SOW_SYSTEM = """You are a delivery lead writing a Scope of Work. Base scope strictly on the
meeting requirements — do not invent features. Do NOT invent prices or hours: use
"To be confirmed" for any amount, and express payment milestones as percentages
tied to delivery events. Keep timelines conservative.

Return ONE JSON object:
{
  "project_overview": "2-4 sentence overview",
  "deliverables": ["itemized, concrete deliverables"],
  "timeline": [
    {"phase": "Phase name", "duration": "e.g. '2-3 weeks'", "activities": ["..."]}
  ],
  "payment_milestones": [
    {"milestone": "trigger event, e.g. 'On project kickoff'", "percentage": "e.g. '30%'"}
  ],
  "terms": ["standard, reasonable terms & conditions lines"]
}"""


def sow_content(analysis: dict, transcript: str | None = None) -> dict:
    raw = llm.generate(_PROVIDER, SOW_SYSTEM, _analysis_brief(analysis, transcript) + "\n\nReturn the SOW JSON now.", model=MODEL)
    d = _loose_json(raw)
    timeline = []
    for ph in (d.get("timeline") or []):
        if isinstance(ph, dict):
            timeline.append({
                "phase": str(ph.get("phase") or "Phase").strip(),
                "duration": str(ph.get("duration") or "").strip(),
                "activities": _slist(ph.get("activities")),
            })
    milestones = []
    for m in (d.get("payment_milestones") or []):
        if isinstance(m, dict):
            milestones.append({
                "milestone": str(m.get("milestone") or "").strip(),
                "percentage": str(m.get("percentage") or "").strip(),
            })
    return {
        "project_overview": str(d.get("project_overview") or "").strip(),
        "deliverables": _slist(d.get("deliverables")),
        "timeline": timeline,
        "payment_milestones": milestones,
        "terms": _slist(d.get("terms")),
    }


# ---------------------------------------------------------------------------
# Detailed Minutes of Meeting — point-wise, grounded in the transcript
# ---------------------------------------------------------------------------
MOM_SYSTEM = """You are an executive assistant writing DETAILED, formal Minutes of Meeting from a
transcript. The minutes must be thorough and point-wise — far more detailed than a
summary. Capture what was actually discussed, by whom where clear, with specifics
(numbers, systems, dates, commitments). Ground EVERYTHING in the transcript; never
invent facts, names, figures, or dates. If the transcript is in another language,
write the minutes in clear English.

Return ONE JSON object:
{
  "overview": "3-5 sentence overview of the meeting purpose and outcome",
  "attendees": ["names / roles actually mentioned"],
  "agenda": [
    {
      "topic": "Concise topic title",
      "points": ["detailed discussion point", "another specific point", "..."]
    }
  ],
  "decisions": ["each decision made, with the reasoning/context behind it"],
  "open_issues": [
    {"issue": "the problem/blocker raised", "impact": "why it matters", "owner": "who will handle it or ''"}
  ],
  "next_steps": ["concrete next step with owner and timing where stated"],
  "action_items": [
    {"description": "specific action", "owner": "name or ''",
     "priority": "High" | "Medium" | "Low", "due_date": "as stated or ''",
     "details": ["clarifying sub-point", "..."]}
  ]
}
Be comprehensive: prefer 4-10 agenda topics each with several points when the
transcript supports it. Keep each point a complete, specific statement."""


def mom_content(analysis: dict, transcript: str | None = None) -> dict:
    raw = llm.generate(_PROVIDER, MOM_SYSTEM,
                       _analysis_brief(analysis, transcript) + "\n\nReturn the detailed Minutes JSON now.", model=MODEL)
    d = _loose_json(raw)
    agenda = []
    for a in (d.get("agenda") or []):
        if isinstance(a, dict):
            agenda.append({"topic": str(a.get("topic") or "Discussion").strip(),
                           "points": _slist(a.get("points"))})
        elif str(a).strip():
            agenda.append({"topic": str(a).strip(), "points": []})
    issues = []
    for i in (d.get("open_issues") or []):
        if isinstance(i, dict):
            issues.append({"issue": str(i.get("issue") or "").strip(),
                           "impact": str(i.get("impact") or "").strip(),
                           "owner": str(i.get("owner") or "").strip()})
        elif str(i).strip():
            issues.append({"issue": str(i).strip(), "impact": "", "owner": ""})
    return {
        "overview": str(d.get("overview") or analysis.get("summary") or "").strip(),
        "attendees": _slist(d.get("attendees")) or analysis.get("attendees", []),
        "agenda": agenda,
        "decisions": _slist(d.get("decisions")),
        "open_issues": issues,
        "next_steps": _slist(d.get("next_steps")),
        "action_items": _action_items(d.get("action_items")),
    }


# ---------------------------------------------------------------------------
# Detailed Action Items
# ---------------------------------------------------------------------------
ACTIONS_SYSTEM = """You extract a DETAILED action-item tracker from a meeting transcript. Be
exhaustive: capture every commitment, follow-up, task, or "I will / you should /
we need to" item — explicit or clearly implied. Ground everything in the
transcript; do not invent owners, dates, or tasks. If the transcript is in another
language, write the items in English.

Return ONE JSON object:
{
  "action_items": [
    {
      "description": "specific, actionable task (start with a verb)",
      "owner": "person responsible, or '' ",
      "priority": "High" | "Medium" | "Low",
      "due_date": "as stated, or ''",
      "details": ["clarifying sub-point or acceptance note", "..."]
    }
  ]
}
Infer priority from urgency/tone; default Medium. Aim to capture ALL items, not just the top few."""


def _action_items(raw_list) -> list:
    out = []
    for a in (raw_list or []):
        if not isinstance(a, dict):
            a = {"description": str(a)}
        desc = str(a.get("description") or "").strip()
        if not desc:
            continue
        pr = str(a.get("priority") or "Medium").capitalize()
        if pr not in ("High", "Medium", "Low"):
            pr = "Medium"
        out.append({
            "description": desc,
            "owner": str(a.get("owner") or a.get("assigned_to") or "").strip(),
            "priority": pr,
            "due_date": str(a.get("due_date") or "").strip(),
            "details": _slist(a.get("details")),
        })
    return out


def action_items_content(analysis: dict, transcript: str | None = None) -> list:
    if not (transcript and transcript.strip()):
        # No transcript — fall back to whatever the analysis captured.
        return _action_items(analysis.get("action_items"))
    raw = llm.generate(_PROVIDER, ACTIONS_SYSTEM,
                       _analysis_brief(analysis, transcript) + "\n\nReturn the action-items JSON now.", model=MODEL)
    items = _action_items(_loose_json(raw).get("action_items"))
    return items or _action_items(analysis.get("action_items"))
