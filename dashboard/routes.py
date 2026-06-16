"""
Meeting Intelligence Dashboard blueprint.

All routes are login-gated (reusing the app's auth). Generated files land in the
same output/ directory as proposals, so the existing /download/<file> route
serves them. Nothing here modifies an existing route.
"""
import json
import os
from datetime import date

from flask import Blueprint, render_template, request, jsonify, session

import auth
import llm
from workdrive import WorkDriveClient

from .classifier import (analyze_transcript, generate_flowchart_mermaid,
                         flowchart_from_text, analyze_portfolio, analyze_project_tasks)
from . import action_log
from .transcript import extract_transcript, SUPPORTED as TRANSCRIPT_TYPES
from .zoho_meetings import ZohoMeetingsClient
from .zoho_projects import ZohoProjectsClient
from .flowchart_library import FlowchartLibrary
from .doc_generators import build_srs, build_sow, build_mom, build_action_items, save_flowchart

dashboard_bp = Blueprint("dashboard", __name__)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(_BASE, "output")
INDEX_PATH = os.path.join(OUTPUT_DIR, "workdrive_index.json")

meetings_client = ZohoMeetingsClient()
projects_client = ZohoProjectsClient()
flow_library = FlowchartLibrary()


def company_info() -> dict:
    return {
        "name": os.getenv("COMPANY_NAME", "Your Company"),
        "tagline": os.getenv("COMPANY_TAGLINE", ""),
        "email": os.getenv("COMPANY_EMAIL", ""),
        "phone": os.getenv("COMPANY_PHONE", ""),
        "website": os.getenv("COMPANY_WEBSITE", ""),
    }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _match_client(client_name: str):
    """Best-effort match of an extracted client name against indexed WorkDrive
    proposals — a light stand-in for CRM lookup. Returns a name or None."""
    name = (client_name or "").strip().lower()
    if not name or not os.path.exists(INDEX_PATH):
        return None
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            items = (json.load(f) or {}).get("items", {})
    except Exception:
        return None
    tokens = [t for t in name.replace("-", " ").split() if len(t) > 2]
    for it in items.values():
        pname = (it.get("name") or "").lower()
        if name and name in pname:
            return it.get("name")
        if tokens and any(t in pname for t in tokens):
            return it.get("name")
    return None


def _save_to_workdrive(path: str, client_name: str) -> dict:
    """Upload a generated file to WorkDrive under Meeting Outputs/<Client>/<Date>/."""
    wd = WorkDriveClient()
    if not wd.configured():
        return {"saved": False, "reason": "WorkDrive not configured."}
    root = os.getenv("ZOHO_WORKDRIVE_FOLDER_ID", "")
    if not root:
        return {"saved": False, "reason": "ZOHO_WORKDRIVE_FOLDER_ID not set."}
    try:
        outputs = wd.ensure_folder(root, "Meeting Outputs")
        client_folder = wd.ensure_folder(outputs, client_name or "Unsorted")
        date_folder = wd.ensure_folder(client_folder, date.today().isoformat())
        with open(path, "rb") as f:
            wd.upload_file(date_folder, os.path.basename(path), f.read())
        return {"saved": True, "folder": "Meeting Outputs/%s/%s" % (client_name or "Unsorted", date.today().isoformat())}
    except Exception as exc:
        return {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}


def _respond_file(path: str, analysis: dict, data: dict, extra: dict | None = None):
    filename = os.path.basename(path)
    resp = {"filename": filename, "download_url": f"/download/{filename}"}
    if extra:
        resp.update(extra)
    if data.get("save_to_workdrive"):
        resp["workdrive"] = _save_to_workdrive(path, analysis.get("client_name"))
    return jsonify(resp)


def _get_analysis(data: dict) -> dict:
    analysis = data.get("analysis")
    if not isinstance(analysis, dict) or not analysis:
        return {}
    return analysis


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------
@dashboard_bp.route("/insights")
@auth.login_required
def insights():
    return render_template(
        "insights.html",
        company=company_info(),
        user_email=session.get("user_email"),
        projects_status=projects_client.status(),
    )


@dashboard_bp.route("/api/insights/projects")
@auth.login_required
def api_insights_projects():
    return jsonify(projects_client.portfolio())


@dashboard_bp.route("/api/insights/analyze", methods=["POST"])
@auth.login_required
def api_insights_analyze():
    pf = projects_client.portfolio()
    if not pf.get("projects"):
        return jsonify({"error": pf.get("error") or "No projects to analyze."}), 400
    try:
        return jsonify(analyze_portfolio(pf))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@dashboard_bp.route("/api/insights/projects/<pid>/tasks")
@auth.login_required
def api_project_tasks(pid):
    """Read a project's tasks (actionables) + any linked in-app meeting actions."""
    name = (request.args.get("name") or "").strip()
    try:
        tasks = projects_client.get_tasks(pid)
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"tasks": tasks, "meeting_actions": action_log.for_client(name)})


@dashboard_bp.route("/api/insights/projects/<pid>/focus", methods=["POST"])
@auth.login_required
def api_project_focus(pid):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    try:
        tasks = projects_client.get_tasks(pid)
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    try:
        return jsonify(analyze_project_tasks(name or "Project", tasks, action_log.for_client(name)))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# -------- in-app action log (no Zoho writes) --------
@dashboard_bp.route("/api/actions/save", methods=["POST"])
@auth.login_required
def api_actions_save():
    data = request.get_json(force=True)
    client = (data.get("client") or "").strip()
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "No action items to save."}), 400
    added = action_log.add(client, items)
    return jsonify({"ok": True, "added": added, **action_log.stats()})


@dashboard_bp.route("/api/actions")
@auth.login_required
def api_actions_list():
    client = (request.args.get("client") or "").strip()
    items = action_log.for_client(client) if client else action_log.all_items()
    return jsonify({"items": items, **action_log.stats()})


@dashboard_bp.route("/api/actions/toggle", methods=["POST"])
@auth.login_required
def api_actions_toggle():
    data = request.get_json(force=True)
    ok = action_log.toggle((data.get("id") or "").strip())
    return jsonify({"ok": ok})


@dashboard_bp.route("/capture")
@auth.login_required
def capture():
    from .transcribe import active_provider
    return render_template(
        "capture.html",
        company=company_info(),
        user_email=session.get("user_email"),
        transcribe_info=active_provider(),
    )


@dashboard_bp.route("/api/transcribe", methods=["POST"])
@auth.login_required
def api_transcribe():
    f = request.files.get("audio")
    if not f:
        return jsonify({"error": "No audio received."}), 400
    try:
        from .transcribe import transcribe
        text = transcribe(f.read(), f.filename or "audio.webm")
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"text": text})


@dashboard_bp.route("/flowcharts")
@auth.login_required
def flowcharts():
    return render_template(
        "flowcharts.html",
        company=company_info(),
        user_email=session.get("user_email"),
        providers=llm.available_providers(),
    )


@dashboard_bp.route("/api/flowchart", methods=["POST"])
@auth.login_required
def api_flowchart():
    data = request.get_json(force=True)
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Describe a workflow or upload a document first."}), 400
    # Retrieve the closest house-style reference flowcharts (if the library is trained).
    references, used = [], []
    use_refs = data.get("use_house_style", True)
    if use_refs and flow_library.status()["count"] > 0:
        try:
            references = flow_library.search(prompt, top_k=2)
            used = [{"name": r["name"], "score": r["score"]} for r in references]
        except Exception:
            references = []
    try:
        mermaid = flowchart_from_text(prompt, references)
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"mermaid": mermaid, "references": used})


@dashboard_bp.route("/api/flowchart/image", methods=["POST"])
@auth.login_required
def api_flowchart_image():
    import base64
    data = request.get_json(force=True)
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Describe a workflow or upload a document first."}), 400
    references, used = [], []
    if flow_library.status()["count"] > 0:
        try:
            references = flow_library.search(prompt, top_k=1)
            used = [{"name": r["name"], "score": r["score"]} for r in references]
        except Exception:
            references = []
    try:
        mermaid = flowchart_from_text(prompt, references)
        style = references[0]["style_notes"] if references else ""
        png = flow_library.generate_image(prompt, mermaid, style)
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fname = f"Flowchart_{date.today().isoformat()}_{abs(hash(prompt)) % 100000}.png"
    with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
        f.write(png)
    return jsonify({
        "image": "data:image/png;base64," + base64.b64encode(png).decode(),
        "download_url": f"/download/{fname}", "filename": fname,
        "mermaid": mermaid, "references": used,
    })


@dashboard_bp.route("/api/flowchart/library/status")
@auth.login_required
def api_flowlib_status():
    return jsonify(flow_library.status())


@dashboard_bp.route("/api/flowchart/library/sync", methods=["POST"])
@auth.login_required
def api_flowlib_sync():
    try:
        stats = flow_library.sync()
        return jsonify({"ok": True, **stats, **flow_library.status()})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@dashboard_bp.route("/dashboard")
@auth.login_required
def dashboard():
    return render_template(
        "dashboard.html",
        company=company_info(),
        user_email=session.get("user_email"),
        meetings_status=meetings_client.status(),
        providers=llm.available_providers(),
    )


# --------------------------------------------------------------------------
# meetings (gated; degrade to manual path)
# --------------------------------------------------------------------------
@dashboard_bp.route("/api/meetings")
@auth.login_required
def api_meetings():
    return jsonify({"meetings": meetings_client.list_meetings(), **meetings_client.status()})


@dashboard_bp.route("/api/meetings/<key>/transcript")
@auth.login_required
def api_meeting_transcript(key):
    try:
        text = meetings_client.get_transcript(key)
    except Exception as exc:
        return jsonify({"error": f"{exc}"}), 400
    return jsonify({"transcript": text})


@dashboard_bp.route("/api/meetings/<key>/analyze", methods=["POST"])
@auth.login_required
def api_meeting_analyze(key):
    try:
        text = meetings_client.get_transcript(key)
    except Exception as exc:
        return jsonify({"error": f"{exc}"}), 400
    return _do_analyze(text, {})


# --------------------------------------------------------------------------
# manual transcript path
# --------------------------------------------------------------------------
@dashboard_bp.route("/api/transcript/upload", methods=["POST"])
@auth.login_required
def api_transcript_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files received."}), 400
    chunks, errors = [], []
    for f in files:
        try:
            text = extract_transcript(f.filename, f.read())
            if text:
                chunks.append(text)
            else:
                errors.append(f"{f.filename}: no readable text")
        except Exception as exc:
            errors.append(f"{f.filename}: {exc}")
    return jsonify({"transcript": "\n\n".join(chunks), "errors": errors,
                    "supported": sorted(TRANSCRIPT_TYPES)})


@dashboard_bp.route("/api/analyze", methods=["POST"])
@auth.login_required
def api_analyze():
    data = request.get_json(force=True)
    transcript = (data.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"error": "Paste or upload a transcript first."}), 400
    return _do_analyze(transcript, data.get("meeting_meta") or {})


def _do_analyze(transcript: str, meeting_meta: dict):
    try:
        analysis = analyze_transcript(transcript, meeting_meta)
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    analysis["matched_crm_record"] = _match_client(analysis.get("client_name"))
    return jsonify(analysis)


# --------------------------------------------------------------------------
# generators
# --------------------------------------------------------------------------
@dashboard_bp.route("/api/generate/srs", methods=["POST"])
@auth.login_required
def api_gen_srs():
    data = request.get_json(force=True)
    analysis = _get_analysis(data)
    if not analysis:
        return jsonify({"error": "Run analysis first."}), 400
    try:
        path = build_srs(analysis, company_info(), OUTPUT_DIR, data.get("transcript"))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return _respond_file(path, analysis, data)


@dashboard_bp.route("/api/generate/sow", methods=["POST"])
@auth.login_required
def api_gen_sow():
    data = request.get_json(force=True)
    analysis = _get_analysis(data)
    if not analysis:
        return jsonify({"error": "Run analysis first."}), 400
    try:
        path = build_sow(analysis, company_info(), OUTPUT_DIR, data.get("transcript"))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return _respond_file(path, analysis, data)


@dashboard_bp.route("/api/generate/mom", methods=["POST"])
@auth.login_required
def api_gen_mom():
    data = request.get_json(force=True)
    analysis = _get_analysis(data)
    if not analysis:
        return jsonify({"error": "Run analysis first."}), 400
    try:
        path = build_mom(analysis, company_info(), OUTPUT_DIR, data.get("meeting_meta") or {}, data.get("transcript"))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return _respond_file(path, analysis, data)


@dashboard_bp.route("/api/generate/action-items", methods=["POST"])
@auth.login_required
def api_gen_action_items():
    data = request.get_json(force=True)
    analysis = _get_analysis(data)
    if not analysis:
        return jsonify({"error": "Run analysis first."}), 400
    try:
        path = build_action_items(analysis, company_info(), OUTPUT_DIR, data.get("transcript"))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return _respond_file(path, analysis, data)


@dashboard_bp.route("/api/generate/flowchart", methods=["POST"])
@auth.login_required
def api_gen_flowchart():
    data = request.get_json(force=True)
    analysis = _get_analysis(data)
    if not analysis:
        return jsonify({"error": "Run analysis first."}), 400
    try:
        mermaid = generate_flowchart_mermaid(analysis)
        path = save_flowchart(mermaid, analysis.get("client_name"), OUTPUT_DIR)
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return _respond_file(path, analysis, data, extra={"mermaid": mermaid})
