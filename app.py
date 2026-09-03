import os
import json
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from dotenv import load_dotenv
from google import genai
from google.genai import types

from authlib.integrations.flask_client import OAuth
import boto3

load_dotenv()

# ---------------------------------------------------------------------------
# Gemini setup (unchanged from before)
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key "
        "(get one free at https://aistudio.google.com/apikey)."
    )

client = genai.Client(api_key=API_KEY)

MODEL_CANDIDATES = ["gemini-flash-latest", "gemini-flash-lite-latest"]

# ---------------------------------------------------------------------------
# Flask app + session secret
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

# ---------------------------------------------------------------------------
# Cognito / OAuth setup
# ---------------------------------------------------------------------------
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN")  # e.g. https://ap-south-1vx3jduldi.auth.ap-south-1.amazoncognito.com
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

if not all([COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, COGNITO_CLIENT_SECRET, COGNITO_DOMAIN]):
    raise RuntimeError(
        "Missing Cognito config. Make sure COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, "
        "COGNITO_CLIENT_SECRET and COGNITO_DOMAIN are set in your .env file."
    )

oauth = OAuth(app)
oauth.register(
    name="oidc",
    authority=f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}",
    client_id=COGNITO_CLIENT_ID,
    client_secret=COGNITO_CLIENT_SECRET,
    server_metadata_url=(
        f"https://cognito-idp.{AWS_REGION}.amazonaws.com/"
        f"{COGNITO_USER_POOL_ID}/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "email openid phone"},
)

# ---------------------------------------------------------------------------
# DynamoDB setup
# ---------------------------------------------------------------------------
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "UserAnalyses")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
analyses_table = dynamodb.Table(DYNAMODB_TABLE)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(f):
    """For JSON API routes: returns a 401 JSON error if not signed in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "You must be signed in to do that."}), 401
        return f(*args, **kwargs)
    return decorated


def login_required_page(f):
    """For normal page routes: redirects to /login if not signed in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_user():
    # Makes `current_user` available in every Jinja template automatically
    return {"current_user": session.get("user")}


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/login")
def login():
    redirect_uri = url_for("callback", _external=True)
    return oauth.oidc.authorize_redirect(redirect_uri)


@app.route("/callback")
def callback():
    token = oauth.oidc.authorize_access_token()
    userinfo = token.get("userinfo") or {}
    session["user"] = {
        "sub": userinfo.get("sub"),          # stable unique user id
        "email": userinfo.get("email"),
        "name": userinfo.get("name") or userinfo.get("email"),
    }
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    logout_url = (
        f"{COGNITO_DOMAIN}/logout"
        f"?client_id={COGNITO_CLIENT_ID}"
        f"&logout_uri={url_for('index', _external=True)}"
    )
    return redirect(logout_url)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
@login_required_page
def dashboard():
    user_id = session["user"]["sub"]
    items = []
    try:
        response = analyses_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(user_id)
        )
        raw_items = response.get("Items", [])
        raw_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        for it in raw_items:
            analysis = it.get("analysis", {}) or {}
            plan = analysis.get("learning_plan", []) or []
            progress = it.get("progress", {}) or {}
            total = len(plan)
            done = 0
            for i in range(total):
                step_progress = progress.get(str(i)) or progress.get(i) or {}
                if step_progress.get("watched") and step_progress.get("practiced"):
                    done += 1

            items.append({
                "analysis_id": it.get("analysis_id"),
                "created_at": it.get("created_at", ""),
                "job_description": it.get("job_description", ""),
                "match_percent": analysis.get("overall_match_percent", "–"),
                "steps_done": done,
                "steps_total": total,
            })
    except Exception:
        items = []

    return render_template("dashboard.html", analyses=items)


# ---------------------------------------------------------------------------
# Gemini analysis (unchanged logic, just wrapped in the same route)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a career/skills coach. Given a JOB DESCRIPTION and a
person's CURRENT SKILLS/COURSEWORK, do three things:

1. Identify the skill gaps: skills clearly required or implied by the job
   description that are missing or weak based on the person's current
   skills/coursework.
2. Build a short, prioritized, actionable learning plan to close those gaps.
   Each step should be concrete (a topic to learn, a type of resource, or a
   small project idea) - not vague advice. For each step, also suggest the
   BEST TYPE of resource for learning it (e.g. "official documentation",
   "YouTube tutorial", "interactive course", "practice platform") and a
   short, specific search phrase someone could use to find it themselves -
   do NOT invent exact URLs, since you cannot verify they are real or still
   online.
3. Write 5 multiple-choice quiz questions covering the topics the person is
   WEAKEST in (based on the gaps you found), to help them start closing the
   gap right now. Each question needs 4 options, one correct answer, and a
   short explanation.

Respond with ONLY valid JSON, no markdown fences, no commentary, matching
exactly this shape:

{
  "overall_match_percent": <integer 0-100, rough estimate of current fit>,
  "matched_skills": ["skill the person already has that the job wants", ...],
  "skill_gaps": [
    {"skill": "name", "why_it_matters": "1 sentence", "priority": "high|medium|low"}
  ],
  "learning_plan": [
    {
      "step": 1,
      "title": "short title",
      "detail": "1-2 sentences on what to actually do",
      "resource_type": "e.g. official documentation | video tutorial | interactive course | practice platform",
      "resource_query": "a short, specific search phrase to find this resource (do not invent a URL)"
    }
  ],
  "quiz": [
    {
      "question": "text",
      "options": ["A", "B", "C", "D"],
      "correct_index": 0,
      "explanation": "why this is correct, 1 sentence"
    }
  ]
}
"""


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True) or {}
    job_description = (data.get("job_description") or "").strip()
    current_skills = (data.get("current_skills") or "").strip()

    if not job_description or not current_skills:
        return jsonify({"error": "Please provide both a job description and your current skills/coursework."}), 400

    user_prompt = f"""JOB DESCRIPTION:
{job_description}

CURRENT SKILLS / COURSEWORK:
{current_skills}
"""

    try:
        raw_text = call_gemini_with_fallback(user_prompt)
        result = json.loads(raw_text)
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({"error": "The model returned a response that wasn't valid JSON. Please try again."}), 502
    except Exception as e:
        return jsonify({"error": f"Something went wrong calling Gemini: {str(e)}"}), 500


def call_gemini_with_fallback(user_prompt, retries_per_model=2, backoff_seconds=3):
    """Try each candidate model in order, retrying on transient 503s before
    moving to the next model. Raises the last error if everything fails."""
    last_error = None

    for model_name in MODEL_CANDIDATES:
        for attempt in range(retries_per_model):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.4,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                last_error = e
                is_overloaded = "503" in str(e) or "UNAVAILABLE" in str(e)
                if is_overloaded and attempt < retries_per_model - 1:
                    time.sleep(backoff_seconds)
                    continue
                break  # move to the next model candidate

    raise last_error


# ---------------------------------------------------------------------------
# Save / load analyses (DynamoDB) - requires sign-in
# ---------------------------------------------------------------------------
@app.route("/api/save-analysis", methods=["POST"])
@login_required
def save_analysis():
    data = request.get_json(force=True) or {}
    analysis_data = data.get("analysis")
    progress = data.get("progress", {})
    job_description = data.get("job_description", "")

    if not analysis_data:
        return jsonify({"error": "No analysis data provided."}), 400

    user_id = session["user"]["sub"]
    analysis_id = data.get("analysis_id") or str(uuid.uuid4())

    item = {
        "user_id": user_id,
        "analysis_id": analysis_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "job_description": job_description[:2000],  # keep it reasonable
        "analysis": analysis_data,
        "progress": progress,
    }

    try:
        analyses_table.put_item(Item=item)
        return jsonify({"status": "saved", "analysis_id": analysis_id})
    except Exception as e:
        return jsonify({"error": f"Failed to save: {str(e)}"}), 500


@app.route("/api/my-analyses", methods=["GET"])
@login_required
def my_analyses():
    user_id = session["user"]["sub"]
    try:
        response = analyses_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(user_id)
        )
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return jsonify({"analyses": items})
    except Exception as e:
        return jsonify({"error": f"Failed to load: {str(e)}"}), 500


@app.route("/api/analysis/<analysis_id>", methods=["GET"])
@login_required
def get_analysis(analysis_id):
    user_id = session["user"]["sub"]
    try:
        response = analyses_table.get_item(Key={"user_id": user_id, "analysis_id": analysis_id})
        item = response.get("Item")
        if not item:
            return jsonify({"error": "Not found."}), 404
        return jsonify(item)
    except Exception as e:
        return jsonify({"error": f"Failed to load: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)