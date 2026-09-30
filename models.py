from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------
class RegisterUser(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    password: str


class UserInDB(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    hashed_password: str
    disabled: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserSession(BaseModel):
    username: str
    login_time: Any
    last_activity: Any
    token: str
    user_data: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Home Interior Budget Planner
# ---------------------------------------------------------------------------
class HomeBudgetInput(BaseModel):
    total_budget: float
    num_lights: int = 0
    num_fans: int = 0
    num_furniture: int = 0
    num_dining_tables: int = 0
    has_living_room: bool = False
    has_kitchen: bool = False
    has_bedroom: bool = False
    additional_requirements: Optional[str] = None


# ---------------------------------------------------------------------------
# Party Budget Planner
# ---------------------------------------------------------------------------
class PartyBudgetInput(BaseModel):
    total_budget: float
    num_guests: int
    party_type: str
    venue_type: Optional[str] = None
    needs_catering: bool = True
    needs_decoration: bool = True
    needs_entertainment: bool = True
    additional_requirements: Optional[str] = None


# ---------------------------------------------------------------------------
# Jewelry Budget Planner
# ---------------------------------------------------------------------------
class JewelryBudgetInput(BaseModel):
    total_budget: float
    occasion: str
    preferences: Optional[str] = None


# ---------------------------------------------------------------------------
# Recommendation history
# ---------------------------------------------------------------------------
class RecommendationHistoryItem(BaseModel):
    id: str
    username: str
    timestamp: str
    recommendation_type: str  # "home" | "party" | "jewelry"
    input_summary: Dict[str, Any]
    input_data: Dict[str, Any]
    full_result: Dict[str, Any]
    result_summary: str
