"""
Central configuration hub for the Israel Housing Agent project.

Defines enums, target areas, search keywords, and runtime settings
loaded from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Program types
# ---------------------------------------------------------------------------

class ProgramType(Enum):
    """Government and private housing program categories."""

    mechir_lamishtaken = "mechir_lamishtaken"
    mechir_mufchat = "mechir_mufchat"
    dira_behagralah = "dira_behagralah"
    other_gov_program = "other_gov_program"
    private_deal = "private_deal"
    general_news = "general_news"


# ---------------------------------------------------------------------------
# Area configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AreaConfig:
    """Geographic area with Hebrew and English city names."""

    name_en: str
    name_he: str
    cities_he: list[str]
    cities_en: list[str]


TARGET_AREAS: list[AreaConfig] = [
    AreaConfig(
        name_en="Central",
        name_he="מרכז",
        cities_he=["תל אביב", "רמת גן", "גבעתיים", "פתח תקווה"],
        cities_en=["Tel Aviv", "Ramat Gan", "Givatayim", "Petah Tikva"],
    ),
    AreaConfig(
        name_en="Sharon",
        name_he="שרון",
        cities_he=["נתניה", "הרצליה", "רעננה", "כפר סבא", "הוד השרון"],
        cities_en=["Netanya", "Herzliya", "Raanana", "Kfar Saba", "Hod HaSharon"],
    ),
    AreaConfig(
        name_en="Gezer",
        name_he="גזר",
        cities_he=[
            "מועצה אזורית גזר",
            "גזר",
            "כרמי יוסף",
            "בית נחמיה",
            "בית עוזיאל",
            "חולדה",
            "יד רמב\"ם",
            "כפר ביל\"ו",
            "עינב",
            "פדיה",
            "מזכרת בתיה",
        ],
        cities_en=[
            "Gezer Regional Council",
            "Gezer",
            "Karme Yosef",
            "Beit Nechemya",
            "Beit Uziel",
            "Hulda",
            "Yad Rambam",
            "Kfar Bilu",
            "Einav",
            "Padya",
            "Mazkeret Batya",
        ],
    ),
    AreaConfig(
        name_en="Ashdod Area",
        name_he="אשדוד והסביבה",
        cities_he=["אשדוד", "אשקלון", "גן יבנה", "יבנה"],
        cities_en=["Ashdod", "Ashkelon", "Gan Yavne", "Yavne"],
    ),
]

# Flattened city lists across all target areas
ALL_TARGET_CITIES_HE: list[str] = [
    city for area in TARGET_AREAS for city in area.cities_he
]

ALL_TARGET_CITIES_EN: list[str] = [
    city for area in TARGET_AREAS for city in area.cities_en
]


# ---------------------------------------------------------------------------
# Hebrew search keywords
# ---------------------------------------------------------------------------

SEARCH_KEYWORDS_HE: list[str] = [
    # Government programs
    "מחיר למשתכן",
    "מחיר מופחת",
    "דירה בהנחה",
    "דירה בהגרלה",
    "מחיר מטרה",
    "דיור בר השגה",
    "דיור בהישג יד",
    # General housing
    "פרויקט דירות חדשות",
    "דירות למכירה",
    "פרויקט מגורים חדש",
    "התחדשות עירונית",
    "פינוי בינוי",
    'תמ"א 38',
    # Government bodies
    "רשות מקרקעי ישראל",
    "משרד הבינוי והשיכון",
    'רמ"י מכרז',
    "הגרלת דירות",
    "שיווק קרקעות",
    "מכרז דירות",
]


# ---------------------------------------------------------------------------
# Google News RSS search queries
# ---------------------------------------------------------------------------

GOOGLE_NEWS_QUERIES: list[str] = [
    "מחיר למשתכן דירות חדשות",
    "מחיר מופחת דירה בהגרלה",
    "דירה בהנחה דיור בר השגה",
    "רשות מקרקעי ישראל שיווק קרקעות",
    "משרד הבינוי והשיכון מכרז דירות",
    "פרויקט מגורים חדש מרכז השרון",
    "התחדשות עירונית פינוי בינוי תל אביב",
    "הגרלת דירות מחיר מטרה 2026",
    "דירות למכירה אשדוד יבנה גזר",
]


# ---------------------------------------------------------------------------
# Telegram channel monitoring
# ---------------------------------------------------------------------------

# Government program keywords for filtering Telegram messages.
# Subset of SEARCH_KEYWORDS_HE focused on gov programs only.
TELEGRAM_GOV_KEYWORDS: list[str] = [
    "מחיר למשתכן",
    "מחיר מופחת",
    "דירה בהנחה",
    "דירה בהגרלה",
    "מחיר מטרה",
    "דיור בר השגה",
    "הגרלת דירות",
    "רשות מקרקעי ישראל",
    "משרד הבינוי והשיכון",
    "מכרז דירות",
    "שיווק קרקעות",
]

# Public Telegram channels to monitor for housing program updates.
# Add/remove channels as needed — use the username without the @ prefix.
TELEGRAM_CHANNELS: list[str] = [
    "dira_behanaha",
    "mechir_lamishtaken",
    "nadlan_israel",
    "dira_gov_il",
    "realestate_il",
]


# ---------------------------------------------------------------------------
# Runtime settings (loaded from environment variables)
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """Application settings populated from environment variables.

    Required env vars:
        ANTHROPIC_API_KEY
        TELEGRAM_BOT_TOKEN
        TELEGRAM_CHAT_ID

    Optional env vars (with defaults):
        CLAUDE_MODEL, CLAUDE_MAX_TOKENS, DB_PATH,
        HTTP_TIMEOUT, HTTP_MAX_RETRIES, DEDUP_DAYS
    """

    # API keys & tokens (required)
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ["ANTHROPIC_API_KEY"]
    )
    telegram_bot_token: str = field(
        default_factory=lambda: os.environ["TELEGRAM_BOT_TOKEN"]
    )
    telegram_chat_id: str = field(
        default_factory=lambda: os.environ["TELEGRAM_CHAT_ID"]
    )

    # Claude settings
    claude_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")
    )
    claude_max_tokens: int = field(
        default_factory=lambda: int(os.environ.get("CLAUDE_MAX_TOKENS", "4096"))
    )

    # Database
    db_path: str = field(
        default_factory=lambda: os.environ.get("DB_PATH", "data/housing.db")
    )

    # HTTP client
    http_timeout: int = field(
        default_factory=lambda: int(os.environ.get("HTTP_TIMEOUT", "30"))
    )
    http_max_retries: int = field(
        default_factory=lambda: int(os.environ.get("HTTP_MAX_RETRIES", "3"))
    )
    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "USER_AGENT",
            "IsraelHousingAgent/1.0 (+https://github.com/israel-housing-agent)",
        )
    )

    # Deduplication
    dedup_days: int = field(
        default_factory=lambda: int(os.environ.get("DEDUP_DAYS", "30"))
    )

    # Telegram channel monitoring (optional — collector skipped if not set)
    telegram_api_id: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_API_ID", "")
    )
    telegram_api_hash: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_API_HASH", "")
    )
    telegram_session_path: str = field(
        default_factory=lambda: os.environ.get(
            "TELEGRAM_SESSION_PATH", "data/telegram"
        )
    )
