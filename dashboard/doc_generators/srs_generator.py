"""Software Requirements Specification (.docx)."""
from ._common import new_document, out_path, footer_contact
from ..expanders import srs_content


def build_srs(analysis: dict, company: dict, output_dir: str, transcript: str | None = None) -> str:
    content = srs_content(analysis, transcript)
    client = analysis.get("client_name") or "Prospect"
    title = f"SRS — {client}"

    doc, h = new_document(company, "Software Requirements Specification", title,
                          meta_bits=[f"Prepared for: {client}"] if analysis.get("client_name") else [])

    h["h1"]("1. Executive Summary")
    h["para"](content["executive_summary"] or "—")

    h["h1"]("2. Functional Requirements")
    if content["functional_requirements"]:
        h["numbered"](content["functional_requirements"])
    else:
        h["para"]("No functional requirements were captured from the meeting.")

    h["h1"]("3. Non-Functional Requirements")
    if content["non_functional_requirements"]:
        h["bullets"](content["non_functional_requirements"])
    else:
        h["para"]("—")

    h["h1"]("4. System Architecture Overview")
    h["para"](content["system_architecture"] or "—")

    h["h1"]("5. Assumptions & Dependencies")
    h["h2"]("Assumptions")
    h["bullets"](content["assumptions"] or ["None recorded."])
    h["h2"]("Dependencies")
    h["bullets"](content["dependencies"] or ["None recorded."])

    h["h1"]("6. Out of Scope")
    h["bullets"](content["out_of_scope"] or ["To be defined."])

    footer_contact(doc, company)
    path = out_path("SRS", client, output_dir)
    doc.save(path)
    return path
