# Project Proposal Assistant

A local web app: paste a client requirement, tag 1–3 similar past projects, pick a
model (OpenAI / Gemini / Claude), and get a **Word (.docx) proposal** that stays
realistic and on-brand — no grandiose, infeasible scope.

## Setup (Windows)

```powershell
# 1. From the project folder, create a virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure keys: copy the example and edit it
copy .env.example .env
notepad .env        # paste your OPENAI_API_KEY and edit COMPANY_NAME etc.

# 4. Run
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## How it works

1. You paste the **client requirement** and **similar past projects** in the chat.
2. The chosen model writes the proposal as structured content. A strict system
   prompt forces it to stay within what was asked and anchor to your past work —
   it will not invent buzzword scope or sweeping claims. (Temperature is kept low.)
3. The content is rendered to a `.docx` you can download from the chat.
   Files are saved in `output/`.

## Models

- **OpenAI** works today (set `OPENAI_API_KEY`).
- **Gemini** and **Claude** appear in the dropdown and work as soon as you add
  `GEMINI_API_KEY` / `CLAUDE_API_KEY` to `.env`. No code changes needed.

## Matching your company template

Put your Word template at `template_docx/template.docx`. See
`template_docx/README.md` for the placeholder list. If no template is present,
the app generates a clean default layout.
