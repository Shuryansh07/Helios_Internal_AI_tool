"""Minutes of Meeting (.docx) — detailed, point-wise. Grounded in the transcript when available."""
from ._common import new_document, out_path, footer_contact
from ..expanders import mom_content


def build_mom(analysis: dict, company: dict, output_dir: str,
              meeting_meta: dict | None = None, transcript: str | None = None) -> str:
    meeting_meta = meeting_meta or {}
    content = mom_content(analysis, transcript)
    client = analysis.get("client_name") or "Client"
    title = f"Minutes of Meeting — {client}"

    meta_bits = []
    if meeting_meta.get("date"):
        meta_bits.append(str(meeting_meta["date"]))
    if meeting_meta.get("duration"):
        meta_bits.append(f"Duration: {meeting_meta['duration']}")

    doc, h = new_document(company, "Minutes of Meeting", title, meta_bits=meta_bits)

    h["h1"]("Overview")
    h["para"](content["overview"] or "—")

    h["h1"]("Attendees")
    h["bullets"](content["attendees"] or ["Not recorded."])

    h["h1"]("Discussion — Agenda & Points")
    if content["agenda"]:
        for i, topic in enumerate(content["agenda"], 1):
            h["h2"](f"{i}. {topic['topic']}")
            h["bullets"](topic["points"] or ["(discussed)"])
    else:
        h["para"]("No agenda topics were captured.")

    h["h1"]("Decisions Made")
    h["bullets"](content["decisions"] or ["None recorded."])

    h["h1"]("Open Issues & Risks")
    if content["open_issues"]:
        for iss in content["open_issues"]:
            line = iss["issue"]
            if iss.get("impact"):
                line += f" — Impact: {iss['impact']}"
            if iss.get("owner"):
                line += f" (Owner: {iss['owner']})"
            h["bullets"]([line])
    else:
        h["para"]("None recorded.")

    h["h1"]("Next Steps")
    h["bullets"](content["next_steps"] or ["None recorded."])

    h["h1"]("Action Items")
    _action_table(doc, content["action_items"])

    footer_contact(doc, company)
    path = out_path("MOM", client, output_dir)
    doc.save(path)
    return path


def _action_table(doc, items):
    if not items:
        doc.add_paragraph("No action items were identified.")
        return
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for c, label in zip(hdr, ("Action Item", "Owner", "Priority", "Due")):
        c.paragraphs[0].add_run(label).bold = True
    for it in items:
        row = table.add_row().cells
        desc = it["description"]
        if it.get("details"):
            desc += "\n" + "\n".join(f"• {d}" for d in it["details"])
        row[0].text = desc
        row[1].text = it.get("owner") or "—"
        row[2].text = it.get("priority") or "Medium"
        row[3].text = it.get("due_date") or "—"
