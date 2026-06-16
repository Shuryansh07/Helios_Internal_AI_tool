"""
Minimal Zoho WorkDrive client.

Handles:
  - OAuth access-token refresh (using a long-lived refresh token from a Self-Client)
  - Listing files inside a folder
  - Downloading file content

Region is configurable via ZOHO_DC (default 'com'). API base resolves to
https://www.zohoapis.<dc>/workdrive/api/v1
"""
import os
import time
import requests


class WorkDriveClient:
    def __init__(self):
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.dc = (os.getenv("ZOHO_DC") or "com").lower()
        self.api_base = f"https://www.zohoapis.{self.dc}/workdrive/api/v1"
        self.download_base = f"https://download.zoho.{self.dc}/v1/workdrive/download"
        self.auth_base = f"https://accounts.zoho.{self.dc}/oauth/v2"
        self._access_token = None
        self._access_token_expiry = 0.0

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    # -------- auth --------
    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expiry - 60:
            return self._access_token

        r = requests.post(
            f"{self.auth_base}/token",
            params={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        body = {}
        try:
            body = r.json()
        except Exception:
            pass
        token = body.get("access_token")
        if not token:
            raise RuntimeError(
                f"Zoho token refresh failed (status {r.status_code}): {body or r.text[:200]}"
            )
        self._access_token = token
        self._access_token_expiry = time.time() + int(body.get("expires_in", 3600))
        return token

    def _headers(self) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {self._get_access_token()}"}

    # -------- folder listing --------
    def list_folder_files(self, folder_id: str, max_files: int = 300) -> list:
        """Return a flat list of files (not folders) inside the given folder id."""
        out = []
        offset = 0
        page = 50
        while len(out) < max_files:
            r = requests.get(
                f"{self.api_base}/files/{folder_id}/files",
                headers=self._headers(),
                params={"page[limit]": page, "page[offset]": offset},
                timeout=30,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"WorkDrive list failed ({r.status_code}): {r.text[:300]}")
            data = (r.json() or {}).get("data") or []
            if not data:
                break
            for item in data:
                attrs = item.get("attributes", {}) or {}
                # skip folders, keep file-like entries
                if attrs.get("is_folder") or (attrs.get("type") in ("folder", "subfolder")):
                    continue
                out.append({
                    "id": item.get("id"),
                    "name": attrs.get("name") or "",
                    "extn": (attrs.get("extn") or "").lower().lstrip("."),
                    "modified_time": attrs.get("modified_time") or attrs.get("modified_time_in_millisecond"),
                    "type": (attrs.get("type") or "").lower(),  # spreadsheet/writer/document/...
                    "size": attrs.get("storage_info", {}).get("size") if isinstance(attrs.get("storage_info"), dict) else None,
                })
            if len(data) < page:
                break
            offset += page
        return out

    # -------- download --------
    def download_file(self, file_id: str) -> bytes:
        # The download.zoho.<dc> host serves raw file bytes for all file types
        # (the zohoapis /download endpoint 404s for some, e.g. images).
        r = requests.get(
            f"{self.download_base}/{file_id}",
            headers=self._headers(),
            timeout=120,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            # Fall back to the API host for any edge cases.
            r2 = requests.get(f"{self.api_base}/download/{file_id}", headers=self._headers(), timeout=120)
            if r2.status_code >= 400:
                raise RuntimeError(f"WorkDrive download failed ({r.status_code}): {r.text[:200]}")
            return r2.content
        return r.content

    # -------- upload --------
    def upload_file(self, parent_id: str, filename: str, content: bytes) -> dict:
        """Upload bytes as a file into the given WorkDrive folder. Returns the API json."""
        r = requests.post(
            f"{self.api_base}/upload",
            headers=self._headers(),  # multipart boundary is set by requests
            data={"filename": filename, "parent_id": parent_id, "override-name-exist": "true"},
            files={"content": (filename, content)},
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"WorkDrive upload failed ({r.status_code}): {r.text[:200]}")
        return r.json() if r.text else {}

    def ensure_folder(self, parent_id: str, name: str) -> str:
        """Return the id of the sub-folder `name` under `parent_id`, creating it if needed."""
        # Look for an existing sub-folder with this name first.
        r = requests.get(
            f"{self.api_base}/files/{parent_id}/files",
            headers={**self._headers(), "Accept": "application/vnd.api+json"},
            params={"page[limit]": 50},
            timeout=30,
        )
        if r.status_code < 400:
            for item in (r.json() or {}).get("data", []) or []:
                attrs = item.get("attributes", {}) or {}
                is_folder = attrs.get("is_folder") or attrs.get("type") in ("folder", "subfolder")
                if is_folder and (attrs.get("name") == name):
                    return item.get("id")
        # Create it.
        cr = requests.post(
            f"{self.api_base}/files",
            headers={**self._headers(),
                     "Content-Type": "application/vnd.api+json",
                     "Accept": "application/vnd.api+json"},
            json={"data": {"attributes": {"name": name, "parent_id": parent_id}, "type": "files"}},
            timeout=30,
        )
        if cr.status_code >= 400:
            raise RuntimeError(f"WorkDrive folder create failed ({cr.status_code}): {cr.text[:200]}")
        return ((cr.json() or {}).get("data") or {}).get("id")
