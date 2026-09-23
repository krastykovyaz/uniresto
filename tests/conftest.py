from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def altius_html() -> str:
    return (FIXTURES_DIR / "altius_week0.html").read_text(encoding="utf-8")


@pytest.fixture
def brasserie_johns_html() -> str:
    return (FIXTURES_DIR / "brasserie_johns_week0.html").read_text(encoding="utf-8")


@pytest.fixture
def altius_closed_week_html() -> str:
    return (FIXTURES_DIR / "altius_closed_week.html").read_text(encoding="utf-8")


@pytest.fixture
def altius_config():
    from restopolis.config import load_restaurants

    return load_restaurants()["UDL-CKB-ALTIUS"]


@pytest.fixture
def fixture_today():
    """The real-world date the live fixtures were captured on."""
    import datetime

    return datetime.date(2026, 9, 23)
