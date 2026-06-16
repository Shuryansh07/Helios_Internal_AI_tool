"""
Multi-turn chat for the proposal assistant.

Each turn, the LLM picks ONE of three modes and responds as a single JSON object:
  - "proposal" : generate a new proposal from a fresh requirement
  - "edit"     : modify the existing proposal (returns the FULL updated proposal)
  - "chat"     : plain conversational answer; does not change the proposal
"""
import json

import llm

from .generator import PROPOSAL_SCHEMA, _coerce, REQUIREMENT_LIMIT, REFERENCES_LIMIT


CHAT_SYSTEM_PROMPT = """You are a senior proposal assistant.

You are in a multi-turn conversation. For each user message you must choose ONE
of the three response modes and reply with a single valid JSON object — no
markdown, no commentary.

=== MODE 1: NEW PROPOSAL ===
Use when the user has provided a NEW client requirement and wants a proposal,
or when no proposal yet exists in the conversation.
{
  "type": "proposal",
  "proposal": <full proposal object matching the schema below>
}

=== MODE 2: EDIT EXISTING PROPOSAL ===
Use when the user asks to change, add, remove, or reword anything in the
CURRENT PROPOSAL shown below. ALWAYS return the FULL updated proposal,
including unchanged parts — not just the diff.
{
  "type": "edit",
  "proposal": <full updated proposal object>,
  "changes_summary": "one short sentence describing what changed"
}

=== MODE 3: CHAT / ANSWER ===
Use when the user is asking a question, requesting an explanation, or just
chatting. Do NOT touch the proposal in this mode.
{
  "type": "chat",
  "message": "your reply in plain prose, concise and direct"
}

=== PROPOSAL SCHEMA (modes 1 and 2) ===
""" + json.dumps(PROPOSAL_SCHEMA, indent=2) + """

=== HARD RULES FOR MODES 1 AND 2 ===
- SCOPE comes ONLY from the CLIENT REQUIREMENT. Every milestone and task must
  trace back to it. If something isn't in the requirement, it is NOT in the
  proposal.
- WORKDRIVE REFERENCES are STYLE REFERENCES ONLY. Use them for tone, milestone
  naming, task granularity, and typical technology choices. DO NOT COPY their
  scope, modules or features.
- No grandiose language ("world-class", "cutting-edge", etc). Plain confident
  professional voice.
- Do not invent prices. Use "To be confirmed" for total_cost unless the user
  explicitly provided a number.
- For edits: preserve everything the user did not ask to change.
"""


def _build_user_prompt(requirement, references, current_proposal, messages, company):
    parts = [
        f"COMPANY: {company.get('name', '')}",
        "",
        "=== CLIENT REQUIREMENT ===",
        (requirement or "").strip()[:REQUIREMENT_LIMIT] or "(not provided)",
        "",
        "=== WORKDRIVE REFERENCES (style only — do NOT copy scope) ===",
        (references or "").strip()[:REFERENCES_LIMIT] or "(none)",
        "",
        "=== CURRENT PROPOSAL ===",
        json.dumps(current_proposal, indent=2) if current_proposal else "null",
        "",
        "=== CONVERSATION SO FAR ===",
    ]
    for m in messages:
        role = m.get("role", "user")
        text = (m.get("content") or "").strip()
        parts.append(f"[{role}] {text}")
    parts.append("")
    parts.append("Respond now to the most recent [user] message as a single JSON object.")
    return "\n".join(parts)


def _parse_json_loose(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start:end + 1])
        raise


def run_turn(provider, requirement, references, current_proposal, messages, company):
    """Returns a dict with at least {'type': 'proposal'|'edit'|'chat', ...}."""
    raw = llm.generate(
        provider,
        CHAT_SYSTEM_PROMPT,
        _build_user_prompt(requirement, references, current_proposal, messages, company),
    )
    data = _parse_json_loose(raw)
    t = (data.get("type") or "").lower()

    if t in ("proposal", "edit"):
        # the proposal object may be under "proposal" or directly at the root
        p = data.get("proposal") or data
        content = _coerce(p)
        return {
            "type": t,
            "content": content,
            "changes_summary": data.get("changes_summary"),
        }

    # default to chat
    return {
        "type": "chat",
        "message": data.get("message") or data.get("text") or "",
    }
