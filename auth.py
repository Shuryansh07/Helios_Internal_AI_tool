"""
Authentication: email + password login, with email-OTP password reset.

- User accounts live in output/users.json (one entry per email, password hashed
  via werkzeug). Single-admin out of the box; schema supports more.
- OTPs are 6-digit codes, 10-minute TTL, in-memory store (per-process).
- Emails go through SMTP (Gmail by default). If SMTP isn't configured the OTP
  is printed to the server console so dev still works.
"""
import json
import os
import secrets
import smtplib
import time
from email.mime.text import MIMEText
from functools import wraps

from flask import session, redirect, url_for
from werkzeug.security import check_password_hash, generate_password_hash

_BASE = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(_BASE, "output", "users.json")

OTP_TTL_SECONDS = 600           # 10 min
OTP_RATE_LIMIT_SECONDS = 45     # don't issue another OTP for same email within 45 s

# In-memory OTP store: {email: (otp, expiry_ts, issued_ts)}
_otp_store: dict = {}


# ---------- users ----------
def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_users(users: dict) -> None:
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def bootstrap_admin() -> None:
    """If users.json is empty and ADMIN_EMAIL+ADMIN_INITIAL_PASSWORD are set,
    create the first user. Idempotent."""
    users = _load_users()
    if users:
        return
    email = _norm(os.getenv("ADMIN_EMAIL", ""))
    password = os.getenv("ADMIN_INITIAL_PASSWORD", "")
    if email and password:
        users[email] = {
            "password_hash": generate_password_hash(password),
            "created_at": int(time.time()),
        }
        _save_users(users)


def has_any_user() -> bool:
    return bool(_load_users())


def user_exists(email: str) -> bool:
    return _norm(email) in _load_users()


def authenticate(email: str, password: str) -> bool:
    rec = _load_users().get(_norm(email))
    if not rec:
        return False
    return check_password_hash(rec["password_hash"], password or "")


def set_password(email: str, new_password: str) -> bool:
    users = _load_users()
    key = _norm(email)
    if key not in users:
        return False
    users[key]["password_hash"] = generate_password_hash(new_password)
    users[key]["password_updated_at"] = int(time.time())
    _save_users(users)
    return True


# ---------- OTP ----------
def generate_otp(email: str):
    key = _norm(email)
    prior = _otp_store.get(key)
    if prior and (time.time() - prior[2]) < OTP_RATE_LIMIT_SECONDS:
        wait = int(OTP_RATE_LIMIT_SECONDS - (time.time() - prior[2]))
        return None, f"Please wait {wait}s before requesting another OTP."
    otp = f"{secrets.randbelow(10 ** 6):06d}"
    _otp_store[key] = (otp, time.time() + OTP_TTL_SECONDS, time.time())
    return otp, None


def verify_otp(email: str, code: str) -> bool:
    key = _norm(email)
    rec = _otp_store.get(key)
    if not rec:
        return False
    otp, expiry, _ = rec
    if time.time() > expiry:
        return False
    if (code or "").strip() != otp:
        return False
    del _otp_store[key]  # one-time use
    return True


# ---------- email ----------
def send_otp_email(to_email: str, otp: str):
    """Send the OTP via SMTP. Falls back to console print if SMTP isn't set."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pwd = os.getenv("SMTP_APP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)

    if not (user and pwd):
        print(f"\n[DEV] SMTP not configured. OTP for {to_email}: {otp}\n", flush=True)
        return True, "OTP printed to server console (SMTP not configured)."

    body = (
        f"Your password reset code: {otp}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you did not request this, ignore this email.\n\n"
        f"— Helios Tech Labs"
    )
    msg = MIMEText(body)
    msg["Subject"] = "Password reset OTP"
    msg["From"] = sender
    msg["To"] = to_email
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return True, "OTP sent to your email."
    except Exception as e:
        return False, f"Email send failed: {e}"


# ---------- Flask decorator ----------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_email"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper
