import uuid
from datetime import datetime
from typing import Dict, List, Any

from models import RecommendationHistoryItem

# username -> list of RecommendationHistoryItem, newest last
user_recommendations: Dict[str, List[RecommendationHistoryItem]] = {}


def _summarize_input(recommendation_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    if recommendation_type == "home":
        return {
            "budget": input_data.get("total_budget"),
            "rooms": [
                name
                for name, flag in {
                    "Living Room": input_data.get("has_living_room"),
                    "Kitchen": input_data.get("has_kitchen"),
                    "Bedroom": input_data.get("has_bedroom"),
                }.items()
                if flag
            ],
            "lights": input_data.get("num_lights"),
            "fans": input_data.get("num_fans"),
            "furniture": input_data.get("num_furniture"),
        }
    if recommendation_type == "party":
        return {
            "budget": input_data.get("total_budget"),
            "party_type": input_data.get("party_type"),
            "guests": input_data.get("num_guests"),
            "needs": [
                name
                for name, flag in {
                    "Catering": input_data.get("needs_catering"),
                    "Decoration": input_data.get("needs_decoration"),
                    "Entertainment": input_data.get("needs_entertainment"),
                }.items()
                if flag
            ],
        }
    if recommendation_type == "jewelry":
        return {
            "budget": input_data.get("total_budget"),
            "occasion": input_data.get("occasion"),
            "with_outfit_image": bool(input_data.get("image")),
        }
    return input_data


def _summarize_result(recommendation_type: str, result: Dict[str, Any]) -> str:
    total = result.get("total_budget", 0)
    remaining = result.get("remaining_budget", 0)
    if recommendation_type == "jewelry":
        count = len(result.get("jewelry_recommendations", []))
        return f"{count} jewelry item(s) suggested - Budget \u20b9{total:.2f}, Remaining \u20b9{remaining:.2f}"
    count = len(result.get("budget_breakdown", []))
    return f"{count} categories planned - Budget \u20b9{total:.2f}, Remaining \u20b9{remaining:.2f}"


def save_to_history(
    username: str,
    recommendation_type: str,
    input_data: Dict[str, Any],
    result: Dict[str, Any],
) -> RecommendationHistoryItem:
    item = RecommendationHistoryItem(
        id=str(uuid.uuid4()),
        username=username,
        timestamp=datetime.utcnow().isoformat(),
        recommendation_type=recommendation_type,
        input_summary=_summarize_input(recommendation_type, input_data),
        input_data=input_data,
        full_result=result,
        result_summary=_summarize_result(recommendation_type, result),
    )
    user_recommendations.setdefault(username, []).append(item)
    return item


def get_history_for_user(username: str) -> List[RecommendationHistoryItem]:
    return sorted(
        user_recommendations.get(username, []),
        key=lambda x: x.timestamp,
        reverse=True,
    )


def get_recommendation_by_id(username: str, recommendation_id: str) -> RecommendationHistoryItem:
    for item in user_recommendations.get(username, []):
        if item.id == recommendation_id:
            return item
    return None
