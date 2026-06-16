"""
Meeting Intelligence Dashboard.

A self-contained Flask blueprint that processes meeting transcripts (pasted,
uploaded, or — when configured — pulled from Zoho Meetings), classifies the
client as a NEW LEAD or EXISTING CLIENT via OpenAI, extracts structured details,
and routes to the right document generators (SRS / SOW / Flowchart for new leads;
MOM / Action Items for existing clients).

Additive only: registering this blueprint does not change any existing route.
"""
from .routes import dashboard_bp

__all__ = ["dashboard_bp"]
