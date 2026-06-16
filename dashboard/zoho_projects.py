"""
Zoho Projects client (API v3) — powers the Insights / Portfolio Intelligence page.

Gated like the other Zoho integrations: reuses the shared ZOHO_* OAuth (the
refresh token already carries ZohoProjects scopes). configured() guards every
call so the app is fine without it.
"""
import os
import time
from datetime import date

import requests


class ZohoProjectsClient:
    def __init__(self):
        self.dc = (os.getenv("ZOHO_DC") or "com").lower()
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.base = f"https://projectsapi.zoho.{self.dc}/api/v3"
        self.auth_base = f"https://accounts.zoho.{self.dc}/oauth/v2"
        self.portal_id = os.getenv("ZOHO_PROJECTS_PORTAL", "")
        self.last_error = None
        self._token = None
        self._token_expiry = 0.0

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    # ---- auth ----
    def _access(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        r = requests.post(f"{self.auth_base}/token", params={
            "refresh_token": self.refresh_token, "client_id": self.client_id,
            "client_secret": self.client_secret, "grant_type": "refresh_token",
        }, timeout=20)
        body = {}
        try:
            body = r.json()
        except Exception:
            pass
        if "access_token" not in body:
            raise RuntimeError(f"Zoho token refresh failed ({r.status_code}): {body or r.text[:200]}")
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {self._access()}"}

    def _portal(self) -> str:
        if self.portal_id:
            return self.portal_id
        r = requests.get(f"{self.base.replace('/api/v3', '/restapi')}/portals/",
                         headers=self._headers(), timeout=30)
        r.raise_for_status()
        portals = (r.json() or {}).get("portals", [])
        if not portals:
            raise RuntimeError("No Zoho Projects portal found for this account.")
        self.portal_id = str(portals[0].get("id_string") or portals[0].get("id"))
        return self.portal_id

    # ---- projects ----
    @staticmethod
    def _norm(p: dict) -> dict:
        st = p.get("status") or {}
        if isinstance(st, str):
            st = {"name": st}
        tasks = p.get("tasks") or {}
        issues = p.get("issues") or {}
        ms = p.get("milestones") or {}
        owner = p.get("owner") or {}
        end = p.get("end_date") or ""
        name_l = (st.get("name") or "").lower()
        is_completed = bool(
            p.get("is_completed") or st.get("is_closed_type")
            or any(w in name_l for w in ("closed", "finish", "complete", "cancel", "done"))
        )
        overdue = False
        if end and not is_completed:
            try:
                overdue = date.fromisoformat(end) < date.today()
            except ValueError:
                overdue = False
        return {
            "id": str(p.get("id") or ""),
            "name": p.get("name") or "Untitled",
            "status": st.get("name") or "Unknown",
            "status_color": st.get("color_hexcode") or st.get("color") or "#859397",
            "is_completed": is_completed,
            "percent": int(p.get("percent_complete") or 0),
            "open_tasks": int(tasks.get("open_count") or 0),
            "closed_tasks": int(tasks.get("closed_count") or 0),
            "open_issues": int(issues.get("open_count") or 0),
            "open_milestones": int(ms.get("open_count") or 0),
            "start_date": p.get("start_date") or "",
            "end_date": end,
            "overdue": overdue,
            "owner": owner.get("full_name") or owner.get("name") or "",
            "group": (p.get("project_group") or {}).get("name") or "",
        }

    def list_projects(self) -> list:
        pid = self._portal()
        r = requests.get(f"{self.base}/portal/{pid}/projects", headers=self._headers(), timeout=40)
        if r.status_code >= 400:
            raise RuntimeError(f"Zoho Projects list failed ({r.status_code}): {r.text[:200]}")
        data = r.json()
        projs = data if isinstance(data, list) else (data.get("projects") or data.get("data") or [])
        return [self._norm(p) for p in projs]

    def portfolio(self) -> dict:
        """Projects + computed portfolio stats. Returns {} (+ last_error) on failure."""
        if not self.configured():
            return {"configured": False, "projects": []}
        try:
            projects = self.list_projects()
            by_status, by_status_color = {}, {}
            for p in projects:
                by_status[p["status"]] = by_status.get(p["status"], 0) + 1
                by_status_color[p["status"]] = p["status_color"]
            active = [p for p in projects if not p["is_completed"]]
            stats = {
                "total": len(projects),
                "active": len(active),
                "completed": sum(1 for p in projects if p["is_completed"]),
                "overdue": sum(1 for p in projects if p["overdue"]),
                "open_tasks": sum(p["open_tasks"] for p in projects),
                "open_milestones": sum(p["open_milestones"] for p in projects),
                "avg_percent": round(sum(p["percent"] for p in active) / len(active)) if active else 0,
                "by_status": [{"name": k, "count": v, "color": by_status_color[k]} for k, v in
                              sorted(by_status.items(), key=lambda kv: -kv[1])],
            }
            self.last_error = None
            return {"configured": True, "stats": stats, "projects": projects}
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"configured": True, "projects": [], "error": self.last_error}

    # ---- tasks ----
    @staticmethod
    def _norm_task(t: dict) -> dict:
        st = t.get("status") or {}
        owners = ((t.get("owners_and_work") or {}).get("owners") or [])
        owner = owners[0].get("name") if owners else ""
        if owner in ("Unassigned User", "Unassigned"):
            owner = ""
        return {
            "id": str(t.get("id") or ""),
            "name": t.get("name") or "Task",
            "status": st.get("name") or "Open",
            "status_color": st.get("color_hexcode") or st.get("color") or "#74cb80",
            "priority": (t.get("priority") or "none").capitalize(),
            "percent": int(t.get("completion_percentage") or 0),
            "owner": owner,
            "is_completed": bool(t.get("is_completed") or st.get("is_closed_type")),
        }

    def get_tasks(self, project_id: str) -> list:
        pid = self._portal()
        r = requests.get(f"{self.base}/portal/{pid}/projects/{project_id}/tasks",
                         headers=self._headers(), timeout=40)
        if r.status_code >= 400:
            raise RuntimeError(f"Zoho Projects tasks failed ({r.status_code}): {r.text[:200]}")
        data = r.json()
        tasks = data if isinstance(data, list) else (data.get("tasks") or data.get("data") or [])
        return [self._norm_task(t) for t in tasks]

    def find_projects(self, query: str) -> list:
        """Match projects by name for linking a meeting to a project."""
        projects = self.list_projects()
        q = (query or "").lower().strip()
        if not q:
            return projects[:12]
        toks = [t for t in q.replace("-", " ").split() if len(t) > 2]
        scored = []
        for p in projects:
            nl = p["name"].lower()
            if q in nl:
                scored.append((3, p))
            elif toks and any(t in nl for t in toks):
                scored.append((2, p))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:12]] or projects[:12]

    def status(self) -> dict:
        return {"configured": self.configured(), "last_error": self.last_error,
                "portal_id": self.portal_id or None}
