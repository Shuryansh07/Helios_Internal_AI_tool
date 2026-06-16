"""Scope of Work (.docx)."""
from ._common import new_document, out_path, footer_contact
from ..expanders import sow_content


def build_sow(analysis: dict, company: dict, output_dir: str, transcript: str | None = None) -> str:
    content = sow_content(analysis, transcript)
    client = analysis.get("client_name") or "Prospect"
    title = f"SOW — {client}"

    doc, h = new_document(company, "Scope of Work", title,
                          meta_bits=[f"Prepared for: {client}"] if analysis.get("client_name") else [])

    h["h1"]("1. Project Overview")
    h["para"](content["project_overview"] or "—")

    h["h1"]("2. Deliverables")
    h["bullets"](content["deliverables"] or ["To be confirmed."])

    h["h1"]("3. Timeline")
    if content["timeline"]:
        for ph in content["timeline"]:
            label = ph["phase"] + (f" ({ph['duration']})" if ph["duration"] else "")
            h["h2"](label)
            h["bullets"](ph["activities"])
    else:
        h["para"]("Timeline to be confirmed.")

    h["h1"]("4. Payment Milestones")
    if content["payment_milestones"]:
        for m in content["payment_milestones"]:
            pct = f" — {m['percentage']}" if m["percentage"] else ""
            h["bullets"]([f"{m['milestone']}{pct} (amount: To be confirmed)"])
    else:
        h["para"]("Payment schedule to be confirmed.")

    h["h1"]("5. Terms & Conditions")
    terms = content["terms"] or [
        "This Scope of Work is valid for 30 days from the date of issue.",
        "Any work outside the agreed deliverables will be treated as a change request.",
        "Final pricing and payment terms are confirmed in the commercial proposal.",
    ]
    h["bullets"](terms)

    footer_contact(doc, company)
    path = out_path("SOW", client, output_dir)
    doc.save(path)
    return path
