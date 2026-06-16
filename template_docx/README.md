# The Word template

The app fills `template_docx/template.docx` with the AI content, so every
proposal comes out in your company format. The active template is the
**milestone-based** layout (matches your past Zoho proposals):

    {{ project_title }}

    Objective
    {{ objective }}

    {%p for milestone in milestones %}
    {{ milestone.title }}
    {%p for task in milestone.scope %}
    {{ task }}
    {%p endfor %}
    {%p endfor %}

    Effort & Cost
    Total Estimated Effort: {{ total_effort }}
    Total Project Cost: {{ total_cost }}

## Fields the AI fills
- `project_title` — e.g. "Proposal: Inventory & Billing System Implementation"
- `objective` — 2–4 plain sentences on what the solution does
- `milestones` — list; each has `title` (e.g. "Milestone 1: System Setup") and
  `scope` (a list of granular tasks)
- `total_effort` — conservative estimate (e.g. "5–6 weeks")
- `total_cost` — stays "To be confirmed" unless you provide a figure

## Notes
- `{%p ... %}` is docxtpl's paragraph-level loop tag — keep each loop tag on its
  own line/paragraph in Word.
- Static text like "Effort & Cost" with an `&` is preserved correctly.
- `template2.docx` is your original copy of this template, kept for reference.
- To change the layout/branding, just restyle `template.docx` in Word — keep the
  placeholder names the same. No code changes needed.
- Remove `template.docx` entirely and the app falls back to a clean default layout.
