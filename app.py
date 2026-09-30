import os
import shutil
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import (  # type: ignore[import-not-found]
    FastAPI, HTTPException, Depends, File, UploadFile, Form,
    Request, status, Cookie,
)
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse  # type: ignore[import-not-found]
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from dotenv import load_dotenv

from models import (
    RegisterUser, UserInDB, Token, UserSession,
    HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput,
)
from auth import (
    hash_password, verify_password, authenticate_user, create_access_token,
    get_token, get_current_user, get_current_active_user,
    users_db, active_sessions, blacklisted_tokens,
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES,
)
from gemini_utils import (
    get_home_recommendations, get_party_recommendations, get_jewelry_recommendations,
)
from history import save_to_history, get_history_for_user, get_recommendation_by_id

load_dotenv()

# ---------------------------------------------------------------------------
# FastAPI app initialization
# ---------------------------------------------------------------------------
app = FastAPI(title="PocketSmart: AI Budget Planner")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)  # allow optional token

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
os.makedirs(os.path.join(BASE_DIR, "static", "uploads"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
print("BASE_DIR =", BASE_DIR)
print("TEMPLATES TYPE =", type(templates))
print("TEMPLATES PATH =", os.path.join(BASE_DIR, "templates"))

def save_upload_file(upload_file: UploadFile) -> str:
    """Saves an uploaded outfit image under static/uploads and returns its path."""
    ext = os.path.splitext(upload_file.filename or "")[1] or ".png"
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    dest_path = os.path.join(BASE_DIR, "static", "uploads", filename)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return dest_path


# ===========================================================================
# Activity 2.3 / 3.1: Auth routes — /register, /login, /logout, /token
# ===========================================================================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page"""
    # Check if user is already logged in
    try:
        token = await get_token(request)
        if token:
            user = await get_current_user(request, token)
            if user:
                return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except Exception:
        pass

    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve the registration page"""
    try:
        token = await get_token(request)
        if token:
            user = await get_current_user(request, token)
            if user:
                return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except Exception:
        pass

    return templates.TemplateResponse(request=request, name="register.html")


@app.post("/register")
async def register_user(user: RegisterUser):
    """Handles new user registration by accepting and securely storing user credentials."""
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="Username already registered")

    users_db[user.username] = UserInDB(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        hashed_password=hash_password(user.password),
    )
    return {"message": "User registered successfully"}


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get access token"""
    user = authenticate_user(users_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    # Create or update session for the user
    existing_user_data: Dict[str, Any] = {}
    if user.username in active_sessions:
        existing_user_data = active_sessions[user.username].user_data
        # If there's an old token, blacklist it
        old_token = active_sessions[user.username].token
        blacklisted_tokens.add(old_token)

    active_sessions[user.username] = UserSession(
        username=user.username,
        login_time=datetime.utcnow(),
        last_activity=datetime.utcnow(),
        token=access_token,
        user_data=existing_user_data,
    )

    # Return response with cookie
    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,  # Store token directly without Bearer prefix
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return response


@app.post("/login")
async def login_form(username: str = Form(...), password: str = Form(...)):
    """Convenience endpoint so the HTML login form can POST directly (without OAuth2 form encoding quirks)."""
    user = authenticate_user(users_db, username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)

    existing_user_data: Dict[str, Any] = {}
    if user.username in active_sessions:
        existing_user_data = active_sessions[user.username].user_data
        blacklisted_tokens.add(active_sessions[user.username].token)

    active_sessions[user.username] = UserSession(
        username=user.username,
        login_time=datetime.utcnow(),
        last_activity=datetime.utcnow(),
        token=access_token,
        user_data=existing_user_data,
    )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return response


@app.post("/register-form")
async def register_form(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    full_name: Optional[str] = Form(None),
    password: str = Form(...),
):
    """Convenience endpoint so the HTML register form can POST directly."""
    if username in users_db:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Username already registered"},
            status_code=400,
        )

    users_db[username] = UserInDB(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
    )
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.post("/logout")
async def logout(request: Request):
    """Logout user by blacklisting their token and clearing session"""
    token = await get_token(request)

    if token:
        # Add token to blacklist
        blacklisted_tokens.add(token)

        try:
            from jose import jwt as _jwt
            payload = _jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username and username in active_sessions:
                del active_sessions[username]
        except Exception:
            pass

    # Use RedirectResponse instead of JSONResponse for proper redirection
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response


@app.get("/logout")
async def logout_get(request: Request):
    """Allow logging out via a plain link/GET as well."""
    return await logout(request)


# ===========================================================================
# Activity 2.4: Session info
# ===========================================================================
@app.get("/session-info")
async def get_session_info(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Get current user's session information"""
    if current_user.username in active_sessions:
        session = active_sessions[current_user.username]
        return {
            "username": session.username,
            "login_time": session.login_time,
            "last_activity": session.last_activity,
            "session_duration": (datetime.utcnow() - session.login_time).total_seconds() // 60,  # in minutes
            "user_data": session.user_data,
        }
    raise HTTPException(status_code=404, detail="No active session found")


@app.post("/session-data")
async def update_session_data(
    data: Dict[str, Any],
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Update user's session data"""
    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data.update(data)
        active_sessions[current_user.username].last_activity = datetime.utcnow()
        return {"message": "Session data updated", "data": active_sessions[current_user.username].user_data}
    raise HTTPException(status_code=404, detail="No active session found")


# ===========================================================================
# Page routes for each planner + dashboard + history
# ===========================================================================
@app.get("/")
async def index(request: Request):
    print("TYPE =", type(templates))
    print("VALUE =", templates)

    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """User dashboard: recent activity + links to planners"""
    history = get_history_for_user(current_user.username)[:5]
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"user": current_user, "history": history},
    )


@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Home budget planner page"""
    return templates.TemplateResponse(
        request=request, name="home_planner.html", context={"user": current_user}
    )


@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Party budget planner page"""
    return templates.TemplateResponse(
        request=request, name="party_planner.html", context={"user": current_user}
    )


@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Jewelry budget planner page"""
    return templates.TemplateResponse(
        request=request, name="jewelry_planner.html", context={"user": current_user}
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """History page to view past recommendations"""
    history = get_history_for_user(current_user.username)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={"user": current_user, "history": history},
    )


# ===========================================================================
# Activity 3.1 / 3.2: Recommendation generation endpoints
# ===========================================================================
@app.post("/home-budget")
async def plan_home_budget(
    budget_input: HomeBudgetInput,
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Generate home budget recommendations"""
    # Store last budget planning in session data
    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data["last_home_budget"] = {
            "timestamp": datetime.utcnow().isoformat(),
            "budget": budget_input.total_budget,
            "requirements": {
                "lights": budget_input.num_lights,
                "fans": budget_input.num_fans,
                "furniture": budget_input.num_furniture,
                "dining_tables": budget_input.num_dining_tables,
            },
        }

    # Get recommendations
    result = get_home_recommendations(budget_input)

    # Save to history
    save_to_history(
        username=current_user.username,
        recommendation_type="home",
        input_data=budget_input.dict(),
        result=result,
    )

    return result


@app.post("/party-budget")
async def plan_party_budget(
    budget_input: PartyBudgetInput,
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Generate party budget recommendations"""
    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data["last_party_budget"] = {
            "timestamp": datetime.utcnow().isoformat(),
            "budget": budget_input.total_budget,
            "party_type": budget_input.party_type,
            "guests": budget_input.num_guests,
        }

    result = get_party_recommendations(budget_input)

    save_to_history(
        username=current_user.username,
        recommendation_type="party",
        input_data=budget_input.dict(),
        result=result,
    )

    return result


@app.post("/jewelry-budget")
async def plan_jewelry_budget(
    total_budget: float = Form(...),
    occasion: str = Form(...),
    preferences: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    request: Request = None,
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Generate jewelry budget recommendations with optional outfit image"""
    budget_input = JewelryBudgetInput(
        total_budget=total_budget,
        occasion=occasion,
        preferences=preferences,
    )

    image_path = None
    if image and image.filename:
        image_path = save_upload_file(image)

    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data["last_jewelry_budget"] = {
            "timestamp": datetime.utcnow().isoformat(),
            "budget": budget_input.total_budget,
            "occasion": budget_input.occasion,
            "has_image": image_path is not None,
        }

    result = get_jewelry_recommendations(budget_input, image_path)

    input_data = budget_input.dict()
    if image_path:
        input_data["image"] = os.path.basename(image_path)

    save_to_history(
        username=current_user.username,
        recommendation_type="jewelry",
        input_data=input_data,
        result=result,
    )

    return result


@app.get("/recommendation-history")
async def get_recommendation_history(
    request: Request, current_user: UserInDB = Depends(get_current_active_user)
):
    """Get the user's recommendation history"""
    history = get_history_for_user(current_user.username)
    if not history:
        return {"history": []}

    history_data = [
        {
            "id": item.id,
            "timestamp": item.timestamp,
            "type": item.recommendation_type,
            "input": item.input_summary,
            "summary": item.result_summary,
        }
        for item in history
    ]
    return {"history": history_data}


@app.get("/recommendation-details/{recommendation_id}")
async def get_recommendation_details(
    recommendation_id: str,
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Get the full details of a specific recommendation"""
    item = get_recommendation_by_id(current_user.username, recommendation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    return {
        "id": item.id,
        "timestamp": item.timestamp,
        "type": item.recommendation_type,
        "input": item.input_summary,
        "full_result": item.full_result,
    }


# ===========================================================================
# Startup: background task to clean up expired sessions
# ===========================================================================
@app.on_event("startup")
async def setup_session_cleanup():
    """Background task to clean up expired sessions"""

    async def cleanup_expired_sessions():
        while True:
            current_time = datetime.utcnow()
            # Check for sessions that have been inactive for more than 30 minutes
            expired_sessions = [
                username
                for username, session in active_sessions.items()
                if (current_time - session.last_activity).total_seconds() > 1800  # 30 minutes
            ]

            # Remove expired sessions
            for username in expired_sessions:
                if username in active_sessions:
                    active_sessions.pop(username, None)

            # Wait 5 minutes before checking again
            await asyncio.sleep(300)

    # Start the background task
    asyncio.create_task(cleanup_expired_sessions())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    print("Starting PocketSmart: AI Budget Planner...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
