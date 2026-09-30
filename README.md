# PocketSmart AI — Smart Budget & Recommendation Assistant

A GenAI-powered, cross-platform recommendation system built with FastAPI and
Google's Gemini 1.5 Flash. Users register/log in, then get personalized,
budget-based recommendations across three planners:

- **Home Interior Budget Planner** — lighting, fans, furniture, dining tables
- **Party Budget Planner** — venue, catering, decoration, entertainment
- **Jewelry Budget Planner** — text + optional outfit-image input for style-matched jewelry

Every recommendation includes shopping links to platforms like Amazon, Flipkart,
IKEA, Swiggy, Zomato, OYO, BookMyShow, Myntra, and more, and is saved to the
user's history.

## Setup

    python -m venv venv
    source venv/bin/activate        # Windows: venv\Scripts\activate
    pip install -r requirements.txt

Copy `.env.example` to `.env` and fill in your keys:

    cp .env.example .env

- `GOOGLE_API_KEY` — a Gemini API key from https://aistudio.google.com
- `SECRET_KEY` — any long random string, used to sign JWT session tokens

## Run

    uvicorn app:app --reload --port 8000

Then visit http://localhost:8000 — register an account, sign in, and use the
three planners from the dashboard.

## Structure

    pocketsmart/
    ├── requirements.txt
    ├── .env.example
    ├── app.py                 # FastAPI app: auth, pages, planner endpoints, session cleanup
    ├── auth.py                # password hashing, JWT issue/verify, in-memory user/session stores
    ├── models.py               # Pydantic schemas (auth + all 3 planner inputs + history)
    ├── gemini_utils.py         # Gemini 1.5 Flash prompts, JSON extraction, shopping-link injection
    ├── history.py              # in-memory recommendation history (save/list/get-by-id)
    ├── templates/
    │   ├── index.html          # public landing page
    │   ├── login.html / register.html
    │   ├── dashboard.html      # planner cards + recent activity
    │   ├── home_planner.html   # Home Interior Budget Planner (form + live results)
    │   ├── party_planner.html  # Party Budget Planner (form + live results)
    │   ├── jewelry_planner.html# Jewelry Budget Planner (form + image upload + live results)
    │   └── history.html        # past recommendations
    └── static/
        ├── styles.css           # shared navy/orange theme
        └── uploads/             # saved outfit images (created automatically)

## Notes

- **Storage is in-memory** (`users_db`, `active_sessions`, `user_recommendations`
  in `auth.py` / `history.py`) — simple for a demo, but everything resets when
  the server restarts. Swap in a real database for production use.
- Auth uses a JWT stored in an `httponly` cookie (`access_token`); sessions
  auto-expire after 30 minutes of inactivity via a background cleanup task.
- All budgets and shopping links are generated for the **Indian market** (INR
  pricing; Amazon.in, Flipkart, IKEA India, Swiggy, Zomato, OYO Rooms, etc.),
  matching the project brief.
- The Gemini model used is `gemini-1.5-flash` (the brief calls it "Gemini 1.5
  Flash Pro" — Google's current SDK model name is `gemini-1.5-flash`; update
  `gemini_utils.py` if a differently-named model becomes available).
