"""Configuration and constants for the contact finder."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    serper_api_key: str | None = os.getenv("SERPER_API_KEY") or None

    request_delay: float = float(os.getenv("REQUEST_DELAY", "1.0"))
    max_tool_calls: int = int(os.getenv("MAX_TOOL_CALLS", "8"))
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
    default_model: str = os.getenv("DEFAULT_MODEL", "llama-3.1-8b-instant")  # cheaper during development

    user_agent: str = "ContactFinderBot/0.1 (+https://example.com; research only)"

    project_root: Path = Path(__file__).resolve().parents[2]


# Role base scores
ROLE_BASE = {
    "Accounts Payable": 0.95,
    "Owner / Founder": 0.85,
    "CFO / Finance Lead": 0.80,
    "Office Manager": 0.70,
    "Registered Agent": 0.55,
    "Generic Business Contact": 0.50,
}

# Address match multipliers
ADDRESS_MATCH = {
    "exact": 1.00,
    "city_state": 0.90,
    "state_only": 0.75,
    "unknown": 0.50,
}

# Source trust scores
SOURCE_TRUST = {
    "registry": 1.00,
    "website": 0.95,
    "whois": 0.85,
    "maps": 0.80,
    "directory": 0.75,
    "archive": 0.65,
    "web_search": 0.55,
}

CORROBORATION_BONUS = 0.10
MX_BONUS = 0.05

# Consumer email domains to reject
CONSUMER_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "live.com",
    "msn.com",
    "protonmail.com",
    "yandex.com",
    "mail.ru",
    "qq.com",
    "163.com",
}

# Personal/residential keywords for address redaction
RESIDENTIAL_KEYWORDS = [
    "residence",
    "home",
    "apt",
    "unit",
    "apartment",
    "house",
    "condo",
]
