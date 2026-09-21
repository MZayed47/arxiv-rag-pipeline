import os

# The API must not try to reach a database when the test suite imports it.
os.environ.setdefault("RUN_MIGRATIONS_ON_STARTUP", "false")
os.environ.setdefault("DB_POOL_MIN_SIZE", "0")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_feed() -> bytes:
    return (FIXTURES / "arxiv_sample.xml").read_bytes()
