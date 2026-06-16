"""
Turns a client requirement (+ reference past projects) into a structured
proposal by calling the chosen LLM, then hands the structure to the docx builder.

The whole "don't run wild / keep it feasible" requirement is enforced here in
the SYSTEM_PROMPT and by parsing the model's output into a fixed structure.
"""
import json
import os

import llm
from .docx_builder import build_docx

# Bound the prompt so a large client requirement + WorkDrive references stay under
# the model's tokens-per-minute limit (override in .env).
REQUIREMENT_LIMIT = int(os.getenv("PROPOSAL_REQUIREMENT_CHAR_LIMIT", "24000"))
REFERENCES_LIMIT = int(os.getenv("PROPOSAL_REFERENCES_CHAR_LIMIT", "16000"))

# The proposal structure the model MUST return. This MATCHES the company Word
# template (template_docx/template.docx): Objective -> numbered Milestones, each
# with a list of scope tasks -> Effort & Cost. Keeping a fixed schema is what
# stops the AI from inventing extra grandiose sections of its own.
PROPOSAL_SCHEMA = {
    "project_title": "string - short plain name, e.g. 'Proposal: <System> Implementation'",
    "objective": "string - 2-4 sentences stating what the solution will do, plain language",
    "milestones": [
        {
            "title": "string - e.g. 'Milestone 1: System Setup & Configuration'",
            "scope": ["list of concrete, granular configuration/build tasks for this milestone"],
        }
    ],
    "total_effort": "string - conservative estimate like '6-8 weeks' or 'XX person-days'",
    "total_cost": "string - leave as 'To be confirmed' unless a figure was provided",
}

SYSTEM_PROMPT = """You are a senior proposal writer for a software/IT services company.
You write project proposals that are GROUNDED, REALISTIC and ACHIEVABLE.

CRITICAL RULES — follow every one:
1. SCOPE COMES ONLY FROM THE CLIENT REQUIREMENT. Every milestone, every task,
   every deliverable in your output must trace back to something the client
   actually asked for in the CLIENT REQUIREMENT section. If it isn't in the
   requirement, it does NOT go in the proposal.
2. PAST PROPOSALS ARE STYLE REFERENCES ONLY. Use them ONLY for:
     - tone of writing
     - the way milestones are named and structured
     - the level of detail in each milestone's tasks
     - typical technology choices we use
   DO NOT COPY their scope, modules or features. If the past proposal built a
   CRM but the current client only asked for an inventory system, the proposal
   must be about inventory — NOT CRM.
3. No grandiose claims. No "world-class", "cutting-edge", "revolutionary",
   "state-of-the-art", "seamless", "10x", or guaranteed business outcomes.
4. Only mainstream, proven technologies. Do not invent experimental tooling.
5. Be honest about scope and effort. Keep estimates conservative; list
   uncertainties under assumptions rather than expanding scope.
6. Do NOT invent prices, hours, team member names, or client facts that were
   not provided. Use qualitative wording for pricing.
7. If the requirement is vague, NARROW the scope and add an assumption — do
   not pad the proposal with extra modules from the past proposals.
8. Milestones mirror the STYLE (naming pattern, task granularity, voice) of the
   past proposals — but the content of each milestone must come from the
   client requirement.
9. For total_cost, do NOT invent a number. Use "To be confirmed" unless a
   figure was actually provided. total_effort may be a conservative estimate.

Before writing, silently ask yourself for every task you're about to include:
  "Did the CLIENT REQUIREMENT actually mention this?"
If the answer is no, delete the task.

Return ONLY a single valid JSON object matching this schema (no markdown, no commentary):
""" + json.dumps(PROPOSAL_SCHEMA, indent=2)


def _build_user_prompt(requirement: str, references: str, company: dict) -> str:
    parts = [
        f"COMPANY WRITING THE PROPOSAL: {company.get('name', '')}",
        "",
        "=== CLIENT REQUIREMENT (THE ONLY SOURCE OF SCOPE) ===",
        requirement.strip()[:REQUIREMENT_LIMIT] or "(none provided — keep scope minimal and conservative)",
        "",
        "=== OUR PAST PROPOSALS — STYLE REFERENCE ONLY, DO NOT COPY SCOPE ===",
        "These show how WE write proposals: tone, milestone naming, task",
        "granularity, technology choices. Use them ONLY for style. Their",
        "modules/features are NOT part of the current proposal unless the",
        "client requirement above also asked for them.",
        "",
        references.strip()[:REFERENCES_LIMIT] or "(none provided)",
        "",
        "Now write the proposal as JSON. Every milestone and task must trace",
        "back to the CLIENT REQUIREMENT above. If a feature appears in the",
        "past proposals but the client did not ask for it, EXCLUDE it.",
    ]
    return "\n".join(parts)


def _coerce(data: dict) -> dict:
    """Make sure every expected key exists so the docx/template never crashes."""
    safe = {
        "project_title": str(data.get("project_title") or "Project Proposal"),
        "objective": str(data.get("objective") or ""),
        "total_effort": str(data.get("total_effort") or "To be confirmed"),
        "total_cost": str(data.get("total_cost") or "To be confirmed"),
        "milestones": [],
    }
    for ms in data.get("milestones") or []:
        if isinstance(ms, dict):
            scope = ms.get("scope") or []
            if not isinstance(scope, list):
                scope = [scope]
            safe["milestones"].append({
                "title": str(ms.get("title") or "Milestone"),
                "scope": [str(t) for t in scope],
            })
    return safe


def build_proposal(provider: str, requirement: str, references: str, company: dict,
                   output_dir: str, template_path: str | None = None) -> dict:
    """
    Full pipeline: prompt -> LLM -> JSON -> .docx file.
    Returns a dict with the parsed content and the saved file path.
    """
    system_prompt = SYSTEM_PROMPT
    user_prompt = _build_user_prompt(requirement, references, company)

    raw = llm.generate(provider, system_prompt, user_prompt)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Some models wrap JSON in ```json fences; strip and retry once.
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(cleaned)

    content = _coerce(data)
    file_path = build_docx(content, company, output_dir, template_path, provider=provider)
    return {"content": content, "file_path": file_path}
