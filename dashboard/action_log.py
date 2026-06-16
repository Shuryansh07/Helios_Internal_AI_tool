"""
Local, in-app Action Log — keeps meeting action items inside our website.

Nothing here touches Zoho. When the user generates action items from a meeting,
they can be saved here (output/action_log.json) tagged with the client name, and
then surfaced next to the relevant Zoho project's tasks in the Insights drawer.
"""
import json
import os
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(_BASE, "output", "action_log.json")


def _load() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("items", [])
    except Exception:
        return []


def _save(items: list) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, indent=1)


def _new_id(seed: str) -> str:
    return f"{int(time.time() * 1000)}-{abs(hash(seed)) % 100000}"


def add(client: str, items: list) -> int:
    """Append meeting action items for a client. Skips exact duplicates. Returns added count."""
    log = _load()
    existing = {(i.get("client", "").lower(), i.get("description", "").lower()) for i in log}
    added = 0
    for it in items or []:
        desc = str(it.get("description") or "").strip()
        if not desc:
            continue
        key = ((client or "").lower(), desc.lower())
        if key in existing:
            continue
        existing.add(key)
        log.append({
            "id": _new_id(desc),
            "client": (client or "").strip(),
            "source": "meeting",
            "description": desc,
            "owner": str(it.get("owner") or it.get("assigned_to") or "").strip(),
            "priority": str(it.get("priority") or "Medium").capitalize(),
            "due_date": str(it.get("due_date") or "").strip(),
            "done": False,
            "created": int(time.time()),
        })
        added += 1
    _save(log)
    return added


def all_items() -> list:
    return sorted(_load(), key=lambda x: (x.get("done", False), -x.get("created", 0)))


def for_client(name: str) -> list:
    """Action items whose client name matches the given project/client name."""
    n = (name or "").lower().strip()
    if not n:
        return []
    toks = [t for t in n.replace("-", " ").split() if len(t) > 2]
    out = []
    for it in _load():
        c = (it.get("client") or "").lower()
        if not c:
            continue
        if c in n or n in c or (toks and any(t in c for t in toks)):
            out.append(it)
    return sorted(out, key=lambda x: (x.get("done", False), -x.get("created", 0)))


def toggle(item_id: str) -> bool:
    log = _load()
    found = False
    for it in log:
        if it.get("id") == item_id:
            it["done"] = not it.get("done", False)
            found = True
            break
    if found:
        _save(log)
    return found


def stats() -> dict:
    items = _load()
    return {"total": len(items), "open": sum(1 for i in items if not i.get("done"))}
