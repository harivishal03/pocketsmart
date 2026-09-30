import os
import json
import re
import urllib.parse
from typing import Optional, Dict, Any

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import HTTPException
from PIL import Image

from models import HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput

load_dotenv()

# Configure Google Gemini AI - do this once, with a consistent environment variable name
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    # Try alternative environment variable name
    API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("No Google API key found in environment variables. Please set GOOGLE_API_KEY in your .env file.")

genai.configure(api_key=API_KEY)

# Gemini 1.5 Flash - fast, multimodal (text + image) model used across all three planners
model = genai.GenerativeModel("gemini-3.6-flash")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def extract_json_from_response(text: str) -> dict:
    """
    Pulls the first well-formed JSON object out of a Gemini response, tolerating
    markdown code fences (```json ... ```) around the payload.
    """
    if not text:
        raise ValueError("Empty response from AI model")

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: find the first {...} block via brace matching
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in AI response")

    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                return json.loads(candidate)

    raise ValueError("Could not parse a complete JSON object from AI response")


def usd_to_inr(amount_usd: float, exchange_rate: float = 83.0) -> float:
    """Convert USD amount to INR using the specified exchange rate."""
    return amount_usd * exchange_rate


def _quote(text: str) -> str:
    return urllib.parse.quote_plus(text or "")


def _build_calculation_table(result: dict) -> None:
    """Populates result['calculation_table_inr'] with per-category cost/percentage rollups."""
    result["calculation_table_inr"] = []
    categories: Dict[str, Dict[str, Any]] = {}

    for category in result.get("budget_breakdown", []):
        cat_name = category.get("category", "Misc")
        if cat_name not in categories:
            categories[cat_name] = {"category": cat_name, "items_count": 0, "total_cost": 0, "percentage_of_budget": 0}

        for item in category.get("items", []):
            categories[cat_name]["items_count"] += 1
            categories[cat_name]["total_cost"] += item.get("estimated_price", 0)

        if result.get("total_budget", 0) > 0:
            categories[cat_name]["percentage_of_budget"] = (
                categories[cat_name]["total_cost"] / result["total_budget"]
            ) * 100

    for cat_data in categories.values():
        result["calculation_table_inr"].append(cat_data)


def _fallback_result(total_budget: float, message: str) -> dict:
    """Minimal, safe default returned when the AI response can't be parsed."""
    return {
        "total_budget": total_budget,
        "budget_breakdown": [],
        "calculation_table_inr": [],
        "remaining_budget": total_budget,
        "additional_suggestions": [message, "Please try again or adjust your inputs."],
    }


# ---------------------------------------------------------------------------
# Home Interior Budget Planner
# ---------------------------------------------------------------------------
def get_home_recommendations(budget_input: HomeBudgetInput) -> dict:
    """Generate home interior recommendations within budget, in INR, for the Indian market."""
    try:
        prompt = f"""
        I need interior design product recommendations for a home in India with a total budget of ₹{budget_input.total_budget:.2f}.

        Requirements:
        - {budget_input.num_lights} lights/lighting fixtures
        - {budget_input.num_fans} ceiling fans
        - {budget_input.num_furniture} furniture pieces
        - {budget_input.num_dining_tables} dining tables

        Additional rooms to consider:
        {("- Living room" if budget_input.has_living_room else "")}
        {("- Kitchen" if budget_input.has_kitchen else "")}
        {("- Bedroom" if budget_input.has_bedroom else "")}

        Additional requirements: {budget_input.additional_requirements or "None"}

        Please provide a detailed budget breakdown with product recommendations **available in India**.
        Use **Indian brands** and pricing**. Include **search terms** suitable for Indian shopping platforms.

        Format your response as JSON with the following structure:
        {{
            "total_budget": {budget_input.total_budget:.2f},
            "budget_breakdown": [
                {{
                    "category": "lighting",
                    "allocation": 0.0,
                    "items": [
                        {{
                            "name": "",
                            "description": "",
                            "estimated_price": 0.0,
                            "quantity": 0,
                            "search_terms": ""
                        }}
                    ]
                }}
            ],
            "remaining_budget": 0.0,
            "additional_suggestions": []
        }}

        Ensure total costs stay within budget. Include search terms for each item to find on shopping websites like Flipkart, Amazon India, IKEA India.
        """

        response = model.generate_content(prompt)
        result = extract_json_from_response(response.text)
    except Exception as e:
        result = _fallback_result(budget_input.total_budget, f"Error generating recommendations: {str(e)}")

    _build_calculation_table(result)

    # Add shopping links for each item
    for category in result.get("budget_breakdown", []):
        for item in category.get("items", []):
            search_terms = item.get("search_terms", "")
            if search_terms:
                item["shopping_links"] = {
                    "amazon": f"https://www.amazon.in/s?k={_quote(search_terms)}",
                    "flipkart": f"https://www.flipkart.com/search?q={_quote(search_terms)}",
                    "ikea": f"https://www.ikea.com/in/en/search/?q={_quote(search_terms)}",
                    "myntra": f"https://www.myntra.com/search?q={_quote(search_terms)}",
                    "ajio": f"https://www.ajio.com/search/?text={_quote(search_terms)}",
                }

    return result


# ---------------------------------------------------------------------------
# Party Budget Planner
# ---------------------------------------------------------------------------
CATEGORY_PLATFORMS = {
    "venue": ["google", "booking", "makemytrip", "oyorooms", "nobroker"],
    "catering": ["swiggy", "zomato"],
    "food": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
    "drinks": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
    "decoration": ["amazon", "flipkart", "meesho", "myntra"],
    "entertainment": ["bookmyshow", "amazon", "flipkart"],
    "gifts": ["amazon", "flipkart", "myntra", "meesho"],
    "photography": ["google", "amazon", "flipkart"],
    "music": ["amazon", "flipkart", "bookmyshow"],
    "games": ["amazon", "flipkart"],
    "accessories": ["amazon", "flipkart", "myntra", "meesho"],
    "transportation": ["makemytrip", "google"],
    "return_gifts": ["amazon", "flipkart", "myntra", "meesho"],
    "contingency": ["amazon", "flipkart", "google"],
}
DEFAULT_PLATFORMS = ["amazon", "flipkart", "google"]

_PLATFORM_URL_BUILDERS = {
    "amazon": lambda q: f"https://www.amazon.in/s?k={_quote(q)}",
    "flipkart": lambda q: f"https://www.flipkart.com/search?q={_quote(q)}",
    "bigbasket": lambda q: f"https://www.bigbasket.com/ps/?q={_quote(q)}",
    "swiggy": lambda q: f"https://www.swiggy.com/search?query={_quote(q)}",
    "zomato": lambda q: f"https://www.zomato.com/search?q={_quote(q)}",
    "bookmyshow": lambda q: f"https://in.bookmyshow.com/search?q={_quote(q)}",
    "myntra": lambda q: f"https://www.myntra.com/search?q={_quote(q)}",
    "meesho": lambda q: f"https://www.meesho.com/search?q={_quote(q)}",
    "google": lambda q: f"https://www.google.com/search?q={_quote(q)}",
    "booking": lambda q: f"https://www.booking.com/search.html?ss={_quote(q)}",
    "makemytrip": lambda q: f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={_quote(q)}",
    "oyorooms": lambda q: f"https://www.oyorooms.com/search/?location={_quote(q)}",
    "nobroker": lambda q: f"https://www.nobroker.in/property/search?searchTerm={_quote(q)}",
}


def get_party_recommendations(budget_input: PartyBudgetInput) -> dict:
    """Generate party planning recommendations within budget, in INR, for the Indian market."""
    try:
        prompt = f"""
        I need party planning recommendations for India with a total budget of ₹{budget_input.total_budget:.2f}.

        Party details:
        - Type: {budget_input.party_type}
        - Number of guests: {budget_input.num_guests}
        - Venue type: {budget_input.venue_type or "Not specified"}
        - Catering needed: {"Yes" if budget_input.needs_catering else "No"}
        - Decoration needed: {"Yes" if budget_input.needs_decoration else "No"}
        - Entertainment needed: {"Yes" if budget_input.needs_entertainment else "No"}

        Additional requirements: {budget_input.additional_requirements or "None"}

        Please provide a detailed budget breakdown with specific recommendations available in India using INR prices.
        Use Indian brands, services, and typical cost expectations.

        Format your response as JSON with the following structure:
        {{
            "total_budget": {budget_input.total_budget:.2f},
            "budget_breakdown": [
                {{
                    "category": "venue",
                    "allocation": 0.0,
                    "items": [
                        {{
                            "name": "",
                            "description": "",
                            "estimated_price": 0.0,
                            "quantity": 0,
                            "search_terms": ""
                        }}
                    ]
                }}
            ],
            "venue_suggestions": [
                {{
                    "name": "",
                    "type": "",
                    "capacity": 0,
                    "estimated_cost": 0.0,
                    "search_terms": ""
                }}
            ],
            "remaining_budget": 0.0,
            "additional_suggestions": []
        }}

        Ensure all costs are in INR and total does not exceed the given budget.
        Provide search terms suitable for Indian websites such as BookMyShow, Swiggy, Flipkart, etc.
        """

        response = model.generate_content(prompt)
        result = extract_json_from_response(response.text)
    except Exception as e:
        result = _fallback_result(budget_input.total_budget, f"Error generating recommendations: {str(e)}")
        result["venue_suggestions"] = []

    _build_calculation_table(result)

    # Add shopping links for each item, restricted to platforms relevant to its category
    for category in result.get("budget_breakdown", []):
        cat_name = category.get("category", "").lower()
        relevant_platforms = CATEGORY_PLATFORMS.get(cat_name, DEFAULT_PLATFORMS)

        for item in category.get("items", []):
            search_terms = item.get("search_terms", "")
            if search_terms:
                item["shopping_links"] = {
                    platform: _PLATFORM_URL_BUILDERS[platform](search_terms)
                    for platform in relevant_platforms
                    if platform in _PLATFORM_URL_BUILDERS
                }

    # Add search links for venue suggestions
    venue_platforms = ["google", "booking", "makemytrip", "oyorooms", "nobroker"]
    for venue in result.get("venue_suggestions", []):
        search_terms = venue.get("search_terms", "")
        if search_terms:
            venue["search_links"] = {
                platform: _PLATFORM_URL_BUILDERS[platform](search_terms)
                for platform in venue_platforms
            }

    return result


# ---------------------------------------------------------------------------
# Jewelry Budget Planner (supports optional outfit image, multimodal)
# ---------------------------------------------------------------------------
def get_jewelry_recommendations(budget_input: JewelryBudgetInput, image_path: Optional[str] = None) -> dict:
    """Generate jewelry recommendations based on an optional uploaded outfit image and budget (India-specific)."""
    base_prompt = f"""
    I need jewelry recommendations for India with a total budget of ₹{budget_input.total_budget:.2f}.

    Occasion: {budget_input.occasion}
    Preferences: {budget_input.preferences or "Not specified"}
    Provide only India-relevant styles, availability, and price ranges in INR.
    """

    try:
        if image_path:
            # Include image-based outfit analysis
            img = Image.open(image_path)
            prompt = base_prompt + """

            An image of the outfit is uploaded. Suggest jewelry that complements it, considering color, design, and occasion appropriateness.

            Format the output as JSON:
            {
                "outfit_analysis": {
                    "colors": [],
                    "style": "",
                    "formality": ""
                },
                "total_budget": 0.0,
                "jewelry_recommendations": [
                    {
                        "item_type": "",
                        "description": "",
                        "style": "",
                        "estimated_price": 0.0,
                        "search_terms": ""
                    }
                ],
                "remaining_budget": 0.0,
                "styling_tips": []
            }

            Make sure prices are in INR and stay within budget.
            Include Indian-friendly search terms for shopping.
            """
            response = model.generate_content([prompt, img])
        else:
            # Only text input
            prompt = base_prompt + """

            Format the output as JSON:
            {
                "total_budget": 0.0,
                "jewelry_recommendations": [
                    {
                        "item_type": "",
                        "description": "",
                        "style": "",
                        "estimated_price": 0.0,
                        "search_terms": ""
                    }
                ],
                "remaining_budget": 0.0,
                "styling_tips": []
            }

            Keep prices in INR and relevant to Indian brands.
            """
            response = model.generate_content(prompt)

        result = extract_json_from_response(response.text)
    except Exception as e:
        result = {
            "total_budget": budget_input.total_budget,
            "jewelry_recommendations": [],
            "remaining_budget": budget_input.total_budget,
            "styling_tips": [f"Error generating recommendations: {str(e)}", "Please try again."],
        }

    # Add shopping links for each item (India-specific jewelry platforms)
    for item in result.get("jewelry_recommendations", []):
        search_terms = item.get("search_terms", "")
        if search_terms:
            item["shopping_links"] = {
                "amazon": f"https://www.amazon.in/s?k={_quote(search_terms)}",
                "flipkart": f"https://www.flipkart.com/search?q={_quote(search_terms)}",
                "bluestone": f"https://www.bluestone.com/search.html?query={_quote(search_terms)}",
                "tanishq": f"https://www.tanishq.co.in/search?q={_quote(search_terms)}",
                "caratlane": f"https://www.caratlane.com/search?q={_quote(search_terms)}",
                "melorra": f"https://www.melorra.com/search?q={_quote(search_terms)}",
                "meesho": f"https://www.meesho.com/search?q={_quote(search_terms)}",
            }

    return result
