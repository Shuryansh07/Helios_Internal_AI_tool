"""
Zoho Meetings client — gated and best-effort.

This is built to Zoho Meeting's real API shape but stays DISABLED until you opt in
(set ZOHO_MEETINGS_ENABLED=true) and have done two things Zoho requires:
  1. Re-authorised your Zoho OAuth refresh token to include the Meeting scopes
     (ZohoMeeting.meeting.READ, ZohoMeeting.recording.READ). The current token only
     has WorkDrive scopes, so live calls will 401 until then.
  2. Set ZOHO_MEETINGS_ZSOID to your Zoho org id (the Meeting API is org-scoped).

Until enabled, configured() returns False and the dashboard uses the manual
paste/upload path. All network calls are wrapped so a failure never crashes the app.
"""
import os
import time

import requests


class ZohoMeetingsClient:
    def __init__(self):
        self.enabled = os.getenv("ZOHO_MEETINGS_ENABLED", "").lower() in ("1", "true", "yes")
        self.dc = (os.getenv("ZOHO_DC") or "com").lower()
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.zsoid = os.getenv("ZOHO_MEETINGS_ZSOID", "")
        self.base = os.getenv("ZOHO_MEETINGS_BASE_URL") or f"https://meeting.zoho.{self.dc}"
        self.auth_base = f"https://accounts.zoho.{self.dc}/oauth/v2"
        self.last_error = None
        self._token = None
        self._token_expiry = 0.0

    def configured(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret
                    and self.refresh_token and self.zsoid)

    # ---- auth (mirrors the WorkDrive client) ----
    def _access(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        r = requests.post(f"{self.auth_base}/token", params={
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }, timeout=20)
        body = {}
        try:
            body = r.json()
        except Exception:
            pass
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"Zoho token refresh failed ({r.status_code}): {body or r.text[:200]}")
        self._token = token
        self._token_expiry = time.time() + int(body.get("expires_in", 3600))
        return token

    def _headers(self) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {self._access()}"}

    def _api(self, path: str) -> str:
        return f"{self.base}/api/v2/{self.zsoid}/{path}"

    # ---- recordings (carry transcript-availability flags) ----
    def _recordings_map(self, limit: int) -> dict:
        """meetingKey -> {has_transcript, recording_id, download_url, play_url}."""
        out = {}
        try:
            r = requests.get(self._api("recordings.json"), headers=self._headers(),
                             params={"index": 1, "count": limit}, timeout=30)
            if r.status_code < 400:
                for rec in (r.json() or {}).get("recordings", []) or []:
                    mk = str(rec.get("meetingKey") or "")
                    if not mk:
                        continue
                    out[mk] = {
                        "has_transcript": bool(rec.get("isTranscriptGenerated")),
                        "recording_id": rec.get("recordingId") or rec.get("id"),
                        "download_url": rec.get("downloadUrl"),
                        "play_url": rec.get("playUrl"),
                        "topic": rec.get("topic"),
                        "date": rec.get("datenTime"),
                        "duration": rec.get("durationInMins"),
                        "creator": rec.get("creatorName"),
                    }
        except Exception:
            pass
        return out

    # ---- meetings ----
    def list_meetings(self, limit: int = 25) -> list:
        """Return recent meetings (merged with recording/transcript info), normalised.
        Returns [] (and sets last_error) on failure so the UI degrades gracefully."""
        if not self.configured():
            return []
        try:
            rec_map = self._recordings_map(limit)
            r = requests.get(self._api("sessions.json"), headers=self._headers(),
                             params={"index": 1, "count": limit}, timeout=30)
            if r.status_code >= 400:
                raise RuntimeError(f"Zoho Meetings list failed ({r.status_code}): {r.text[:200]}")
            sessions = (r.json() or {}).get("session", []) or []
            out, seen = [], set()
            for s in sessions[:limit]:
                mk = str(s.get("meetingKey") or "")
                seen.add(mk)
                rec = rec_map.get(mk, {})
                out.append(self._normalise(mk, s, rec))
            # Include recorded meetings that weren't in the recent-sessions window.
            for mk, rec in rec_map.items():
                if mk not in seen:
                    out.append(self._normalise(mk, {}, rec))
            self.last_error = None
            return out[:limit]
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

    @staticmethod
    def _normalise(mk: str, s: dict, rec: dict) -> dict:
        dur = s.get("duration")
        mins = None
        try:
            mins = int(round(int(dur) / 60000)) if dur else rec.get("duration")
        except (TypeError, ValueError):
            mins = rec.get("duration")
        return {
            "key": mk,
            "title": s.get("topic") or rec.get("topic") or "Meeting",
            "host": s.get("presenterFullName") or s.get("presenterEmail") or rec.get("creator") or "",
            "date": s.get("startTime") or rec.get("date") or "",
            "duration": (f"{mins} min" if mins else (s.get("durationInHours") or "")),
            "has_recording": bool(rec),
            "has_transcript": bool(rec.get("has_transcript")),
            "recording_id": rec.get("recording_id"),
            "play_url": rec.get("play_url"),
        }

    def _recording_detail(self, meeting_key: str) -> dict:
        """Recording detail for a meeting (carries transcription/summary download URLs)."""
        r = requests.get(self._api(f"recordings/{meeting_key}.json"),
                         headers=self._headers(), timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"Could not load recording ({r.status_code}): {r.text[:160]}")
        recs = (r.json() or {}).get("recordings") or []
        if not recs:
            raise RuntimeError("No recording found for this meeting.")
        return recs[0]

    def _download_text(self, url: str) -> str:
        d = requests.get(url, headers=self._headers(), timeout=120)
        if d.status_code >= 400:
            raise RuntimeError(f"Download failed ({d.status_code}).")
        return d.content.decode("utf-8", errors="ignore").strip()

    def get_transcript(self, meeting_key: str) -> str:
        """Fetch a meeting's transcript text via the recording's transcriptionDownloadUrl."""
        if not self.configured():
            raise RuntimeError("Zoho Meetings is not enabled. Use manual transcript input.")
        rec = self._recording_detail(meeting_key)
        url = rec.get("transcriptionDownloadUrl")
        if not (rec.get("isTranscriptGenerated") and url):
            raise RuntimeError(
                "No transcript has been generated for this meeting yet "
                "(enable meeting transcription in Zoho, or paste it manually)."
            )
        return self._download_text(url)

    def get_summary(self, meeting_key: str) -> str:
        """Fetch Zoho's AI-generated meeting summary, if available."""
        rec = self._recording_detail(meeting_key)
        url = rec.get("summaryDownloadUrl")
        if not (rec.get("isSummaryGenerated") and url):
            raise RuntimeError("No summary available for this meeting.")
        return self._download_text(url)

    def status(self) -> dict:
        return {
            "configured": self.configured(),
            "enabled": self.enabled,
            "last_error": self.last_error,
        }
