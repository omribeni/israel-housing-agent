"""
Claude-powered filtering and classification of raw housing articles.

Sends batches of RawArticles to Claude for relevance filtering,
program-type classification, geographic tagging, and Hebrew summarisation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import anthropic

from src.collectors.base import RawArticle
from src.config import ProgramType, Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProcessedArticle:
    """An article that has been classified and summarised by Claude."""

    raw: RawArticle
    program_type: ProgramType
    area: str
    cities: list[str]
    summary_he: str
    importance: str  # "high" / "medium" / "low"


# ---------------------------------------------------------------------------
# System prompt (Hebrew)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
אתה מערכת ניתוח חדשות נדל"ן המתמחה בשוק הדיור הישראלי, עם דגש על תוכניות ממשלתיות לדיור בר-השגה.

## המשימה שלך

עבור כל כתבה שתקבל, עליך:
1. לקבוע האם הכתבה רלוונטית — כלומר, עוסקת בדירות/פרויקטי מגורים באזורי היעד בלבד.
2. לסווג את סוג התוכנית.
3. לזהות את האזור והערים המוזכרות.
4. לכתוב תקציר קצר בעברית.
5. לדרג את רמת החשיבות.

## אזורי יעד

סמן כתבה כרלוונטית רק אם היא נוגעת לאחד מהאזורים הבאים:

- **מרכז**: תל אביב, רמת גן, גבעתיים, פתח תקווה
- **שרון**: נתניה, הרצליה, רעננה, כפר סבא, הוד השרון
- **גזר**: מועצה אזורית גזר (כולל כרמי יוסף, בית נחמיה, בית עוזיאל, חולדה, יד רמב"ם, כפר ביל"ו, עינב, פדיה)
- **אשדוד והסביבה**: אשדוד, אשקלון, גן יבנה, יבנה
- **גן רווה**: מועצה אזורית גן רווה, באר יעקב, נס ציונה, רחובות, גדרה, קריית עקרון

כתבות שעוסקות בערים או אזורים אחרים (למשל באר שבע, חיפה, ירושלים) — סמן כ-relevant: false.
כתבות כלליות על מדיניות דיור ארצית שאינן מתייחסות לאזור ספציפי — סמן כ-relevant: false.

## סוגי תוכניות (program_type)

- **mechir_lamishtaken** — מחיר למשתכן
- **mechir_mufchat** — מחיר מופחת / מחיר מטרה
- **dira_behagralah** — דירה בהגרלה / דירה בהנחה
- **other_gov_program** — תוכנית ממשלתית אחרת (פינוי-בינוי, תמ"א 38, שיווק קרקעות של רמ"י, וכו')
- **private_deal** — עסקת נדל"ן פרטית / פרויקט של יזם פרטי
- **general_news** — חדשות כלליות על שוק הדיור באזורי היעד

## רמת חשיבות (importance)

- **high** — הגרלה חדשה, פרויקט חדש שנפתח להרשמה, שיווק קרקעות חדש, שינוי מדיניות משמעותי
- **medium** — עדכון על פרויקט קיים, מידע על מחירים, סקירת שוק באזור יעד
- **low** — ידיעה שולית, ציון אזור יעד בהקשר לא ישיר

## פורמט תשובה

עבור כל כתבה, החזר אובייקט JSON עם השדות הבאים:

- `relevant` (boolean) — האם הכתבה רלוונטית לאזורי היעד
- `program_type` (string) — אחד מ: mechir_lamishtaken, mechir_mufchat, dira_behagralah, other_gov_program, private_deal, general_news
- `area` (string) — שם האזור בעברית (מרכז / שרון / גזר / אשדוד והסביבה), או מחרוזת ריקה אם לא רלוונטי
- `cities_mentioned` (array of strings) — רשימת הערים שהוזכרו בכתבה (בעברית)
- `summary_he` (string) — תקציר של 2-3 משפטים בעברית
- `importance` (string) — high / medium / low

החזר מערך JSON עם אובייקט אחד לכל כתבה, באותו סדר שבו הכתבות הוצגו.
"""

# JSON schema for structured output
_RESPONSE_JSON_SCHEMA = {
    "name": "article_classifications",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "relevant": {"type": "boolean"},
                        "program_type": {
                            "type": "string",
                            "enum": [
                                "mechir_lamishtaken",
                                "mechir_mufchat",
                                "dira_behagralah",
                                "other_gov_program",
                                "private_deal",
                                "general_news",
                            ],
                        },
                        "area": {"type": "string"},
                        "cities_mentioned": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "summary_he": {"type": "string"},
                        "importance": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": [
                        "relevant",
                        "program_type",
                        "area",
                        "cities_mentioned",
                        "summary_he",
                        "importance",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["articles"],
        "additionalProperties": False,
    },
}

# ---------------------------------------------------------------------------
# Batch size constant
# ---------------------------------------------------------------------------

_BATCH_SIZE = 15

# Map ProgramType enum member names for quick lookup
_PROGRAM_TYPE_MAP: dict[str, ProgramType] = {pt.value: pt for pt in ProgramType}


# ---------------------------------------------------------------------------
# ClaudeFilter
# ---------------------------------------------------------------------------


class ClaudeFilter:
    """Filters and classifies articles using the Anthropic Claude API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # -- public API ---------------------------------------------------------

    def filter_and_classify(
        self, articles: list[RawArticle]
    ) -> list[ProcessedArticle]:
        """Send *articles* to Claude in batches, return only relevant ones.

        Articles are batched in groups of up to 15.  For each batch the model
        returns a JSON array of classification objects.  Only articles marked
        ``relevant: true`` are kept and wrapped in :class:`ProcessedArticle`.
        """
        if not articles:
            return []

        results: list[ProcessedArticle] = []

        for batch_start in range(0, len(articles), _BATCH_SIZE):
            batch = articles[batch_start : batch_start + _BATCH_SIZE]
            user_message = self._format_batch(batch)

            try:
                response = self._client.messages.create(
                    model=self._settings.claude_model,
                    max_tokens=self._settings.claude_max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                    output_config={
                        "format": {
                            "type": "json_schema",
                            "schema": _RESPONSE_JSON_SCHEMA["schema"],
                        },
                    },
                )

                # Extract text from response content blocks
                raw_text = "".join(
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                )

                parsed = json.loads(raw_text)
                classifications = parsed.get("articles", [])

            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning(
                    "Failed to parse Claude response for batch starting at "
                    "index %d: %s — skipping batch",
                    batch_start,
                    exc,
                )
                continue
            except anthropic.APIError as exc:
                logger.warning(
                    "Anthropic API error for batch starting at index %d: %s "
                    "— skipping batch",
                    batch_start,
                    exc,
                )
                continue

            if len(classifications) != len(batch):
                logger.warning(
                    "Expected %d classifications but got %d for batch "
                    "starting at index %d — skipping batch",
                    len(batch),
                    len(classifications),
                    batch_start,
                )
                continue

            for article, clf in zip(batch, classifications):
                if not clf.get("relevant", False):
                    continue

                # Map program_type string to ProgramType enum, fallback to
                # general_news for unknown values.
                program_type_str = clf.get("program_type", "general_news")
                program_type = _PROGRAM_TYPE_MAP.get(
                    program_type_str, ProgramType.general_news
                )

                importance = clf.get("importance", "low")
                if importance not in ("high", "medium", "low"):
                    importance = "low"

                results.append(
                    ProcessedArticle(
                        raw=article,
                        program_type=program_type,
                        area=clf.get("area", ""),
                        cities=clf.get("cities_mentioned", []),
                        summary_he=clf.get("summary_he", ""),
                        importance=importance,
                    )
                )

        return results

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _format_batch(articles: list[RawArticle]) -> str:
        """Format a batch of articles as numbered items for the user message."""
        parts: list[str] = []
        for idx, article in enumerate(articles, start=1):
            # Prefer full_text (first 800 chars), fall back to snippet (500 chars)
            if article.full_text:
                text = article.full_text[:800]
            else:
                text = article.snippet[:500]

            parts.append(
                f"--- כתבה {idx} ---\n"
                f"כותרת: {article.title}\n"
                f"מקור: {article.source}\n"
                f"טקסט: {text}\n"
                f"קישור: {article.url}\n"
            )

        return "\n".join(parts)
