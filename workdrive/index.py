"""
Local semantic index of past proposals pulled from Zoho WorkDrive.

- sync(): list folder, download new/changed files, extract text, embed via OpenAI,
  cache to disk. Idempotent — unchanged files are skipped.
- search(query): cosine-similarity ranking over the index, returns top-K.

Cache lives at output/workdrive_index.json (one file, easy to inspect/delete).
"""
import json
import math
import os
import time
from datetime import datetime

from proposal.text_extract import extract_text, SUPPORTED
from .zoho_apps import read_zoho_sheet, is_zoho_native, SHEET_TYPES, WRITER_TYPES

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(_BASE, "output", "workdrive_index.json")


def _embed(text: str) -> list:
    """OpenAI text-embedding-3-small. Truncate to stay under the 8k-token cap."""
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for WorkDrive semantic indexing.")
    client = OpenAI(api_key=api_key)
    r = client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:25000],
    )
    return r.data[0].embedding


def _cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class ProposalIndex:
    def __init__(self, client):
        self.wd = client
        self.folder_id = os.getenv("ZOHO_WORKDRIVE_FOLDER_ID", "")
        self.items = {}        # file_id -> {name, text, embedding, modified_time}
        self.last_sync = None
        self.last_error = None
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if not os.path.exists(INDEX_PATH):
            return
        try:
            with open(INDEX_PATH, "r", encoding="utf-8") as f:
                j = json.load(f)
            self.items = j.get("items", {}) or {}
            self.last_sync = j.get("last_sync")
            self.last_error = j.get("last_error")
        except Exception as e:
            self.last_error = f"index load failed: {e}"

    def _save(self):
        os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "items": self.items,
                "last_sync": self.last_sync,
                "last_error": self.last_error,
                "folder_id": self.folder_id,
            }, f)

    # ---------- ops ----------
    def status(self) -> dict:
        return {
            "configured": self.wd.configured() and bool(self.folder_id),
            "count": len(self.items),
            "last_sync": self.last_sync,
            "last_error": self.last_error,
            "folder_id": self.folder_id or None,
        }

    def sync(self) -> dict:
        """Incrementally sync the folder. Returns counts."""
        if not self.wd.configured():
            raise RuntimeError("Zoho credentials missing in .env (ZOHO_CLIENT_ID / SECRET / REFRESH_TOKEN).")
        if not self.folder_id:
            raise RuntimeError("ZOHO_WORKDRIVE_FOLDER_ID is not set in .env.")

        files = self.wd.list_folder_files(self.folder_id)
        seen = set()
        added = updated = skipped = errored = 0
        errors = []

        for f in files:
            ext = "." + (f["extn"] or "")
            ftype = f.get("type") or ""
            # Allow either supported extensions OR Zoho-native types (which lose extension semantics)
            if ext not in SUPPORTED and not is_zoho_native(ftype):
                continue
            fid = f["id"]
            if not fid:
                continue
            seen.add(fid)
            cached = self.items.get(fid)
            if cached and str(cached.get("modified_time")) == str(f["modified_time"]):
                skipped += 1
                continue

            try:
                # Route by file type. Zoho-native files (auto-converted on upload)
                # need their own API; plain files use /download/{id}.
                if ftype in SHEET_TYPES:
                    text = read_zoho_sheet(fid, self.wd._headers())
                elif ftype in WRITER_TYPES:
                    raise RuntimeError(
                        "Zoho Writer file needs ZohoWriter.documentEditor.ALL scope; not granted by your org."
                    )
                else:
                    data = self.wd.download_file(fid)
                    text = extract_text(f["name"], data)

                if not (text or "").strip():
                    errors.append(f"{f['name']}: no readable text")
                    errored += 1
                    continue
                emb = _embed(text)
                self.items[fid] = {
                    "name": f["name"],
                    "text": text,
                    "embedding": emb,
                    "modified_time": f["modified_time"],
                }
                if cached:
                    updated += 1
                else:
                    added += 1
            except Exception as e:
                errors.append(f"{f['name']}: {e}")
                errored += 1

        # prune files no longer in the folder
        removed_ids = [k for k in self.items if k not in seen]
        for k in removed_ids:
            del self.items[k]

        self.last_sync = datetime.utcnow().isoformat() + "Z"
        self.last_error = "; ".join(errors[:5]) if errors else None
        self._save()
        return {
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "errored": errored,
            "removed": len(removed_ids),
            "total": len(self.items),
            "errors": errors,
        }

    def search(self, query_text: str, top_k: int = 3, min_score: float = 0.0) -> list:
        """Return the top_k indexed proposals most relevant to query_text."""
        if not self.items or not query_text.strip():
            return []
        q = _embed(query_text)
        scored = []
        for fid, item in self.items.items():
            sim = _cosine(q, item.get("embedding") or [])
            if sim >= min_score:
                scored.append((sim, fid, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for sim, fid, item in scored[:top_k]:
            out.append({
                "id": fid,
                "name": item["name"],
                "text": item["text"],
                "score": round(float(sim), 4),
            })
        return out
