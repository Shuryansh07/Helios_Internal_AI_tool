"""
Readers for Zoho-native files in WorkDrive.

When a user uploads a .xlsx/.docx to WorkDrive, Zoho silently converts it into
a Zoho Sheet / Zoho Writer document. The standard /download/{id} API does NOT
return the original bytes for those — we must use Zoho's Sheet/Writer APIs.

Currently implemented: Zoho Sheet (requires the ZohoSheet.dataAPI.READ scope).
Zoho Writer requires its own scope that Zoho's console rejected for this org;
those files raise a clear "needs Writer scope" error and are skipped in the index.
"""
import requests


SHEET_API = "https://sheet.zoho.com/api/v2"


def _fetch_records(base, auth_headers, sheet_name, header_row, timeout):
    return requests.get(base, headers=auth_headers, params={
        "method": "worksheet.records.fetch",
        "worksheet_name": sheet_name,
        "header_row": header_row,
        "record_index": header_row + 1,
        "record_count": 500,
    }, timeout=timeout)


def read_zoho_sheet(file_id: str, auth_headers: dict, timeout: int = 60) -> str:
    """
    Read every worksheet via Zoho Sheet API and render the content as text.

    Many proposal files have a logo/title band before the actual data, so we
    auto-probe header rows 1-5 to find the first row that Sheet API will accept
    as a header. This rescues files where row 1 is merged or blank.
    """
    base = f"{SHEET_API}/{file_id}"

    r = requests.get(base, headers=auth_headers, params={"method": "worksheet.list"}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"Zoho Sheet list failed ({r.status_code}): {r.text[:200]}")
    sheets = r.json().get("worksheet_names") or []
    if not sheets:
        return ""

    out = []
    for s in sheets:
        name = s.get("worksheet_name", "Sheet")
        # Find the first header row that the API will accept.
        records = None
        for hr in (1, 2, 3, 4, 5):
            rr = _fetch_records(base, auth_headers, name, hr, timeout)
            if rr.status_code == 200:
                records = rr.json().get("records") or []
                if records:
                    break
        if not records:
            continue

        # Determine the column-name set, preserving insertion order
        cols = []
        for rec in records:
            for k in rec.keys():
                if k != "row_index" and k not in cols:
                    cols.append(k)
        if not cols:
            continue

        out.append(f"=== Sheet: {name} ===")
        if len(cols) == 1:
            # Single-column data (free-text rows). Render as lines, not a table,
            # because the "column header" is usually noise (title text).
            for rec in records:
                v = rec.get(cols[0])
                if v not in (None, ""):
                    out.append(str(v).strip())
        else:
            out.append(" | ".join(cols))
            for rec in records:
                row = ["" if rec.get(k) is None else str(rec.get(k)) for k in cols]
                if any(v.strip() for v in row):
                    out.append(" | ".join(row))
        out.append("")
    return "\n".join(out).strip()


SHEET_TYPES = {"spreadsheet", "zohosheet", "sheet"}
WRITER_TYPES = {"writer", "zohowriter", "document"}
SHOW_TYPES = {"presentation", "zohoshow", "show"}


def is_zoho_native(file_type: str) -> bool:
    """Zoho file types that need their own API instead of /download/{id}."""
    t = (file_type or "").lower()
    return t in SHEET_TYPES or t in WRITER_TYPES or t in SHOW_TYPES


class WriterScopeMissing(Exception):
    """Raised when we hit a Zoho Writer file but lack ZohoWriter.documentEditor.ALL."""
