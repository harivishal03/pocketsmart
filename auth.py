import os
from datetime import datetime, timedelta
from typing import Optional, Dict

from fastapi import HTTPException, Request, status
from jose import jwt, JWTError
from passlib.context import CryptContext

from models import UserInDB, UserSession

SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# In-memory stores (swap for a real database in production)
# ---------------------------------------------------------------------------
users_db: Dict[str, UserInDB] = {}
active_sessions: Dict[str, UserSession] = {}
blacklisted_tokens: set = set()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_user(username: str) -> Optional[UserInDB]:
    return users_db.get(username)


def authenticate_user(users_db: Dict[str, UserInDB], username: str, password: str):
    user = users_db.get(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_token(request: Request) -> Optional[str]:
    """Reads the JWT from the access_token cookie (or Authorization header as fallback)."""
    token = request.cookies.get("access_token")
    if token:
        return token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return None


async def get_current_user(request: Request, token: Optional[str] = None) -> Optional[UserInDB]:
    if token is None:
        token = await get_token(request)
    if not token or token in blacklisted_tokens:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    user = get_user(username)
    return user


async def get_current_active_user(request: Request) -> UserInDB:
    """FastAPI dependency: raises 401 if there's no valid, non-disabled logged-in user."""
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    # Keep the session's last_activity fresh
    if user.username in active_sessions:
        active_sessions[user.username].last_activity = datetime.utcnow()

    return user
