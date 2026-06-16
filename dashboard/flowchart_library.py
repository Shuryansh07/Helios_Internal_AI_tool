"""
Flowchart style library — "train" on a Zoho WorkDrive folder of example flowchart
images so new flowcharts match the house style.

The folder holds PNG/JPG flowchart images. We read each with an OpenAI vision model,
convert it to Mermaid + style notes, embed a text description, and cache it on disk.
At generation time the closest examples are fed to the model as a house-style
reference (same pattern as the proposal index uses past proposals).

Index file: output/flowchart_index.json
{
  "items": { "<file_id>": {"name","mermaid","style_notes","description","embedding","modified_time"} },
  "last_sync", "last_error", "folder_id"
}
"""
import base64
import io
import json
import math
import os
from datetime import datetime

from workdrive import WorkDriveClient

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(_BASE, "output", "flowchart_index.json")

VISION_MODEL = os.getenv("OPENAI_FLOWCHART_VISION_MODEL", os.getenv("OPENAI_DASHBOARD_MODEL", "gpt-4o-mini"))
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
EMBED_MODEL = "text-embedding-3-small"
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
MAX_DIM = 1500  # downscale large images to bound vision tokens

VISION_PROMPT = (
    "This is a business-process automation flowchart (Zoho implementation). "
    "Study it carefully and return ONE JSON object:\n"
    '{"mermaid": "a faithful Mermaid \'flowchart TD\' reproduction — same nodes, '
    'decisions and branches, with readable labels", '
    '"style_notes": "how it is laid out: grouping/swimlanes (e.g. by Zoho app), '
    'node shapes, color coding, branching pattern", '
    '"description": "what business process it automates, 1-2 sentences, naming the Zoho apps used"}'
)


def _client():
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for the flowchart library.")
    return OpenAI(api_key=key)


def _downscaled_png(data: bytes) -> str:
    """Return base64 PNG, downscaled to bound vision token cost."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None  # trusted WorkDrive files; allow very large exports
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((MAX_DIM, MAX_DIM))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


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


def _cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y; na += x * x; nb += y * y
    return dot / (math.sqrt(na) * math.sqrt(nb)) if na and nb else 0.0


class FlowchartLibrary:
    def __init__(self, client: WorkDriveClient | None = None):
        self.wd = client or WorkDriveClient()
        self.folder_id = os.getenv("ZOHO_FLOWCHART_FOLDER_ID", "")
        self.items = {}
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
            json.dump({"items": self.items, "last_sync": self.last_sync,
                       "last_error": self.last_error, "folder_id": self.folder_id}, f)

    # ---------- vision + embedding ----------
    def _extract(self, data: bytes) -> dict:
        client = _client()
        b64 = _downscaled_png(data)
        r = client.chat.completions.create(
            model=VISION_MODEL, temperature=0.2, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64, "detail": "high"}},
            ]}],
        )
        d = _loose_json(r.choices[0].message.content)
        return {
            "mermaid": str(d.get("mermaid") or "").strip(),
            "style_notes": str(d.get("style_notes") or "").strip(),
            "description": str(d.get("description") or "").strip(),
        }

    def _embed(self, text: str) -> list:
        r = _client().embeddings.create(model=EMBED_MODEL, input=text[:8000])
        return r.data[0].embedding

    def generate_image(self, workflow: str, mermaid: str, style_notes: str = "", size: str = "1536x1024") -> bytes:
        """Render the flowchart as an actual diagram image (gpt-image-2), styled to
        match the trained house flowcharts."""
        style = style_notes or (
            "rounded-rectangle nodes grouped into colored sections / swimlanes by module, "
            "clear directional arrows, modern flat enterprise design, legible sans-serif labels"
        )
        prompt = (
            "Create a clean, professional business-process flowchart diagram in the visual style of an "
            "enterprise Zoho implementation architecture diagram.\n"
            f"Visual style: {style}.\n"
            "Layout top-to-bottom, generously spaced, no overlapping connectors. Every node label must be "
            "spelled correctly and clearly legible.\n"
            f"The diagram must depict EXACTLY this process and structure (given as Mermaid):\n{(mermaid or '')[:3200]}\n"
            f"Process context: {(workflow or '')[:1200]}"
        )
        resp = _client().images.generate(model=IMAGE_MODEL, prompt=prompt, size=size)
        return base64.b64decode(resp.data[0].b64_json)

    # ---------- ops ----------
    def configured(self) -> bool:
        return bool(self.wd.configured() and self.folder_id and os.getenv("OPENAI_API_KEY"))

    def status(self) -> dict:
        return {
            "configured": self.configured(),
            "count": len(self.items),
            "last_sync": self.last_sync,
            "last_error": self.last_error,
            "folder_id": self.folder_id or None,
        }

    def sync(self) -> dict:
        if not self.wd.configured():
            raise RuntimeError("Zoho credentials missing in .env.")
        if not self.folder_id:
            raise RuntimeError("ZOHO_FLOWCHART_FOLDER_ID is not set in .env.")

        files = self.wd.list_folder_files(self.folder_id, max_files=200)
        seen = set()
        added = updated = skipped = errored = 0
        errors = []

        for f in files:
            ext = (f.get("extn") or "").lower()
            if ext not in IMAGE_EXTS:
                continue
            fid = f["id"]
            if not fid:
                continue
            seen.add(fid)
            cached = self.items.get(fid)
            if cached and str(cached.get("modified_time")) == str(f["modified_time"]) and cached.get("embedding"):
                skipped += 1
                continue
            try:
                data = self.wd.download_file(fid)
                ext_data = self._extract(data)
                if not ext_data["mermaid"]:
                    errors.append(f"{f['name']}: no diagram read")
                    errored += 1
                    continue
                emb_text = f"{f['name']}\n{ext_data['description']}\n{ext_data['style_notes']}"
                self.items[fid] = {
                    "name": f["name"],
                    "mermaid": ext_data["mermaid"],
                    "style_notes": ext_data["style_notes"],
                    "description": ext_data["description"],
                    "embedding": self._embed(emb_text),
                    "modified_time": f["modified_time"],
                }
                updated += 1 if cached else 0
                added += 0 if cached else 1
            except Exception as e:
                errors.append(f"{f['name']}: {e}")
                errored += 1

        removed = [k for k in self.items if k not in seen]
        for k in removed:
            del self.items[k]

        self.last_sync = datetime.utcnow().isoformat() + "Z"
        self.last_error = "; ".join(errors[:5]) if errors else None
        self._save()
        return {"added": added, "updated": updated, "skipped": skipped,
                "errored": errored, "removed": len(removed), "total": len(self.items),
                "errors": errors}

    def search(self, query: str, top_k: int = 2) -> list:
        if not self.items or not (query or "").strip():
            return []
        q = self._embed(query)
        scored = []
        for fid, it in self.items.items():
            sim = _cosine(q, it.get("embedding") or [])
            scored.append((sim, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{
            "name": it["name"], "mermaid": it.get("mermaid", ""),
            "style_notes": it.get("style_notes", ""), "description": it.get("description", ""),
            "score": round(float(sim), 4),
        } for sim, it in scored[:top_k]]
