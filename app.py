"""
Project Proposal Automation - Flask web app.

Run:  python app.py
Open: http://127.0.0.1:5000
"""
import os
import secrets as _secrets

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, session, url_for

import auth
import llm
from dashboard import dashboard_bp
from proposal import build_proposal
from proposal.chat import run_turn
from proposal.docx_builder import build_docx
from proposal.xlsx_builder import build_xlsx
from proposal.text_extract import extract_text, SUPPORTED
from workdrive import WorkDriveClient, ProposalIndex

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMPLATE_DOCX = os.path.join(BASE_DIR, "template_docx", "template.docx")

# Ensure the output dir exists at import time. Under gunicorn (production) the
# __main__ block below never runs, so we can't rely on it to create OUTPUT_DIR.
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)

# Session signing key. If FLASK_SECRET_KEY isn't set we mint a random one — sessions
# will be valid for this process only (logged-in users have to re-login on restart).
app.secret_key = os.getenv("FLASK_SECRET_KEY") or _secrets.token_hex(32)

# Create the admin account from .env on first run.
auth.bootstrap_admin()

# Meeting Intelligence Dashboard (additive blueprint — does not alter existing routes).
app.register_blueprint(dashboard_bp)

# WorkDrive client + index. Lazily initialised; safe to construct even when
# credentials are missing — the .configured() check gates real API calls.
workdrive_client = WorkDriveClient()
workdrive_index = ProposalIndex(workdrive_client)


def company_info():
    return {
        "name": os.getenv("COMPANY_NAME", "Your Company"),
        "tagline": os.getenv("COMPANY_TAGLINE", ""),
        "email": os.getenv("COMPANY_EMAIL", ""),
        "phone": os.getenv("COMPANY_PHONE", ""),
        "website": os.getenv("COMPANY_WEBSITE", ""),
    }


# ============ AUTH ROUTES ============
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        if auth.authenticate(email, password):
            session["user_email"] = email.strip().lower()
            return redirect(url_for("dashboard.dashboard"))
        return render_template("login.html", error="Invalid email or password.")
    if not auth.has_any_user():
        return render_template("login.html",
            notice="No user account exists yet. Set ADMIN_EMAIL and ADMIN_INITIAL_PASSWORD in .env and restart the app.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "")
        if not auth.user_exists(email):
            # Don't leak whether the account exists. Just proceed to reset page.
            return redirect(url_for("reset", email=email))
        otp, err = auth.generate_otp(email)
        if err:
            return render_template("forgot.html", error=err)
        ok, msg = auth.send_otp_email(email, otp)
        if not ok:
            return render_template("forgot.html", error=msg)
        return redirect(url_for("reset", email=email))
    return render_template("forgot.html")


@app.route("/reset", methods=["GET", "POST"])
def reset():
    email = request.values.get("email", "")
    if request.method == "POST":
        otp = request.form.get("otp", "")
        new_pw = request.form.get("password", "")
        confirm = request.form.get("password2", "")
        if not new_pw or new_pw != confirm:
            return render_template("reset.html", email=email, error="Passwords don't match.")
        if len(new_pw) < 8:
            return render_template("reset.html", email=email, error="Password must be at least 8 characters.")
        if not auth.verify_otp(email, otp):
            return render_template("reset.html", email=email, error="Invalid or expired OTP.")
        if not auth.set_password(email, new_pw):
            return render_template("reset.html", email=email, error="Could not update password for this email.")
        return render_template("login.html", notice="Password updated. Please sign in.")
    return render_template("reset.html", email=email)


# ============ MAIN APP (login required) ============
@app.route("/")
@auth.login_required
def index():
    return render_template(
        "index.html",
        providers=llm.available_providers(),
        company=company_info(),
        user_email=session.get("user_email"),
    )


@app.route("/api/generate", methods=["POST"])
@auth.login_required
def generate():
    data = request.get_json(force=True)
    provider = data.get("provider", "openai")
    requirement = data.get("requirement", "")
    references = data.get("references", "")
    # client can disable auto-match; default on
    use_workdrive = data.get("use_workdrive", True)

    if not requirement.strip() and not references.strip():
        return jsonify({"error": "Please upload the client requirement (and past proposals), or type a brief."}), 400

    # If user supplied NO past-proposal references but the WorkDrive index has
    # entries, semantically match the top 3 most relevant proposals.
    auto_matched = []
    if use_workdrive and not references.strip() and workdrive_index.status()["count"] > 0:
        try:
            top = workdrive_index.search(requirement, top_k=3)
            if top:
                references = "\n\n".join(f"--- {x['name']} (WorkDrive, similarity {x['score']}) ---\n{x['text'][:5000]}" for x in top)
                auto_matched = [{"name": x["name"], "score": x["score"]} for x in top]
        except Exception as exc:
            # Don't fail generation just because matching failed; surface as a soft warning.
            auto_matched = [{"name": f"WorkDrive match failed: {exc}", "score": 0}]

    template_path = TEMPLATE_DOCX if os.path.exists(TEMPLATE_DOCX) else None

    try:
        result = build_proposal(
            provider=provider,
            requirement=requirement,
            references=references,
            company=company_info(),
            output_dir=OUTPUT_DIR,
            template_path=template_path,
        )
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    filename = os.path.basename(result["file_path"])
    return jsonify({
        "content": result["content"],
        "download_url": f"/download/{filename}",
        "filename": filename,
        "used_template": bool(template_path),
        "auto_matched": auto_matched,
    })


# -------- WorkDrive integration endpoints --------
@app.route("/api/workdrive/status")
@auth.login_required
def workdrive_status():
    return jsonify(workdrive_index.status())


@app.route("/api/workdrive/sync", methods=["POST"])
@auth.login_required
def workdrive_sync():
    try:
        stats = workdrive_index.sync()
        return jsonify({"ok": True, **stats, **workdrive_index.status()})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/chat", methods=["POST"])
@auth.login_required
def chat():
    """
    Single endpoint for the conversation. The model decides per turn whether
    to generate a new proposal, edit the existing one, or just answer.
    """
    data = request.get_json(force=True)
    provider = data.get("provider", "openai")
    requirement = (data.get("requirement") or "").strip()
    messages = data.get("messages") or []
    current_proposal = data.get("current_proposal")
    # Output format: "docx" (Word) or "xlsx" (Excel, matching the WorkDrive sheets).
    fmt = (data.get("format") or "docx").lower()
    if fmt not in ("docx", "xlsx"):
        fmt = "docx"

    if not requirement and not messages:
        return jsonify({"error": "Type a message or attach a client requirement."}), 400

    # WorkDrive references: auto-match when a requirement exists.
    references = ""
    auto_matched = []
    if requirement and workdrive_index.status()["count"] > 0:
        try:
            top = workdrive_index.search(requirement, top_k=3)
            if top:
                references = "\n\n".join(
                    f"--- {x['name']} (WorkDrive, similarity {x['score']}) ---\n{x['text'][:5000]}"
                    for x in top
                )
                auto_matched = [{"name": x["name"], "score": x["score"]} for x in top]
        except Exception as exc:
            auto_matched = [{"name": f"WorkDrive match failed: {exc}", "score": 0}]

    try:
        turn = run_turn(provider, requirement, references, current_proposal, messages, company_info())
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    response = {"type": turn["type"]}

    if turn["type"] in ("proposal", "edit"):
        template_path = TEMPLATE_DOCX if os.path.exists(TEMPLATE_DOCX) else None
        try:
            if fmt == "xlsx":
                file_path = build_xlsx(
                    turn["content"], company_info(), OUTPUT_DIR, provider=provider,
                )
                used_template = False  # Excel uses the built-in WorkDrive-style layout
            else:
                file_path = build_docx(
                    turn["content"], company_info(), OUTPUT_DIR,
                    template_path=template_path, provider=provider,
                )
                used_template = bool(template_path)
        except Exception as exc:
            return jsonify({"error": f"Doc build failed: {exc}"}), 500

        filename = os.path.basename(file_path)
        response.update({
            "content": turn["content"],
            "download_url": f"/download/{filename}",
            "filename": filename,
            "format": fmt,
            "used_template": used_template,
            "changes_summary": turn.get("changes_summary"),
            "auto_matched": auto_matched if turn["type"] == "proposal" else [],
        })
    else:  # chat
        response.update({"message": turn.get("message", "")})

    return jsonify(response)


@app.route("/api/extract", methods=["POST"])
@auth.login_required
def extract():
    """Read uploaded files and return their combined plain text."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files received."}), 400

    chunks, errors = [], []
    for f in files:
        try:
            text = extract_text(f.filename, f.read())
            if text:
                chunks.append(f"--- {f.filename} ---\n{text}")
            else:
                errors.append(f"{f.filename}: no readable text found")
        except Exception as exc:
            errors.append(f"{f.filename}: {exc}")

    return jsonify({
        "text": "\n\n".join(chunks),
        "errors": errors,
        "supported": sorted(SUPPORTED),
    })


@app.route("/download/<path:filename>")
@auth.login_required
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    # Local development only. In production, gunicorn serves `app` (see render.yaml)
    # and this block is not executed.
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, port=port)
