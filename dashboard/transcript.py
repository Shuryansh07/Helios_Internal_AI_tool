"""
Transcript extraction for the manual upload path.

Reuses proposal.text_extract for .txt/.docx/.pdf, and adds WebVTT/.srt caption
parsing (strip timestamps + cue numbers, keep speaker text).
"""
import os
import re

from proposal.text_extract import extract_text as _extract_doc

SUPPORTED = {".txt", ".vtt", ".srt", ".docx", ".pdf"}

_TS = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]?\d*\s*-->")
_CUE_NUM = re.compile(r"^\d+$")


def _from_captions(data: bytes) -> str:
    """Parse .vtt/.srt into plain text, dropping timestamps and cue numbers."""
    text = data.decode("utf-8", errors="ignore")
    out, prev = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if _TS.match(line) or "-->" in line:
            continue
        if _CUE_NUM.match(line):
            continue
        # Strip inline VTT tags like <v Speaker> and <00:00:00.000>
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line != prev:  # de-dupe consecutive repeats common in live captions
            out.append(line)
            prev = line
    return "\n".join(out).strip()


def extract_transcript(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".vtt", ".srt"):
        return _from_captions(data)
    if ext in (".txt", ".docx", ".pdf"):
        return _extract_doc(filename, data)
    raise ValueError(f"Unsupported transcript type '{ext}'. Use .txt, .vtt, .srt, .docx or .pdf.")
