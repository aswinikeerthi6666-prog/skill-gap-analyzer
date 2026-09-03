# Skill Gap Analyzer

Paste a job description and your current skills/coursework. Get back:

- an estimated match score for the role
- the specific skills you're missing, prioritized
- a step-by-step learning plan to close the gap
- a 5-question quiz on the topics you're weakest in

Built for **MLH Hack Day x AWS SBGL: Build with Gemini & AWS** — Education / Open Innovation track.

## Tech stack

- **Google Gemini API** (`gemini-flash-latest`) via the `google-genai` Python SDK — does the gap analysis, plan generation, and quiz generation in one structured JSON call
- **Flask** — lightweight backend serving the API and the frontend
- Vanilla HTML/CSS/JS frontend (no build step, easy to run anywhere)

## Setup

### 1. Clone and enter the project
```bash
git clone <this-repo-url>
cd skill-gap-analyzer
```

### 2. Create a virtual environment (recommended)
```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Add your Gemini API key
```bash
cp .env.example .env
```
Then open `.env` and paste your key. Get a free one (no credit card needed) at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 5. Run it
```bash
python app.py
```
Open **http://localhost:5000** in your browser.

## How it works

1. The frontend sends the job description and your skills to `/api/analyze`.
2. The Flask backend sends both to Gemini with a system prompt asking for
   structured JSON: match score, skill gaps with priority levels, a
   step-by-step learning plan, and 5 quiz questions targeting your weakest
   areas.
3. The frontend renders the report and runs the quiz interactively in the
   browser — no page reload needed.

## Project structure
```
skill-gap-analyzer/
├── app.py                 # Flask backend + Gemini API call
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── app.js
├── requirements.txt
├── .env.example
└── README.md
```

## Notes

- Your API key never leaves the backend — the frontend only talks to your
  own Flask server, not Gemini directly.
- If you hit a "model not found" error in the future, Google occasionally
  retires older Gemini model names. Swap `MODEL_NAME` in `app.py` for the
  current recommended Flash model at
  [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models).

## Possible next steps

- Let users upload a résumé (PDF) instead of typing skills manually
- Deploy on AWS (Lambda + API Gateway for the backend, Amplify or S3+CloudFront for the frontend) for a live demo link
- Save past analyses per user (AWS DynamoDB) to track skill growth over time
