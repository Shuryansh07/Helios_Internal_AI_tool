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

# 3. Configure keys: create a .env file in the project root and add your keys.
#    At minimum: OPENAI_API_KEY, ADMIN_EMAIL, ADMIN_INITIAL_PASSWORD, COMPANY_NAME.
#    See the "Deploy to Render" section below for the full list of variables.
notepad .env

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

## Deploy to Render (no database needed)

This app stores nothing permanently — generated files are downloaded by the user
in-session, so there's no database. The admin login is recreated from your env vars
on each deploy. Steps:

1. **Push to GitHub.** This folder isn't a git repo yet:
   ```powershell
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   (`.env`, `venv/`, and `output/` are gitignored — your secrets are not pushed.)

2. **Create the service on Render.** New&nbsp;+ → **Blueprint** → pick the repo.
   Render reads [`render.yaml`](render.yaml) and configures everything (Python 3.12,
   `gunicorn`, start command).

3. **Set the secret env vars** when prompted (these are `sync: false` in the blueprint):
   - `OPENAI_API_KEY` — required
   - `ADMIN_EMAIL`, `ADMIN_INITIAL_PASSWORD` — your login (recreated each deploy)
   - `COMPANY_NAME` — appears on proposals
   - Optional: `GEMINI_API_KEY`, `CLAUDE_API_KEY`, SMTP (`SMTP_USER`/`SMTP_APP_PASSWORD`
     for password-reset emails), and Zoho WorkDrive keys (for auto-matching past proposals).

   `FLASK_SECRET_KEY` and `PORT` are handled automatically — don't set them by hand.

4. **Deploy.** Render runs `gunicorn app:app` and gives you a public URL. Log in with
   the `ADMIN_EMAIL` / `ADMIN_INITIAL_PASSWORD` you set.

**Things to know (because there's no storage):**
- A password changed via "Forgot password" resets to `ADMIN_INITIAL_PASSWORD` on the next
  deploy — change that env var instead for a permanent new password.
- The WorkDrive index is rebuilt in memory; click **Sync** again after a deploy/restart.
- On Render's free plan the service sleeps after inactivity and the first request after
  a cold start is slow (the app re-bootstraps from env).

## Matching your company template

Put your Word template at `template_docx/template.docx`. See
`template_docx/README.md` for the placeholder list. If no template is present,
the app generates a clean default layout.
