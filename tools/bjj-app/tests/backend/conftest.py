from pathlib import Path

import pytest


@pytest.fixture
def sample_vault() -> Path:
    """Path to the fixture vault used by vault.py tests."""
    return Path(__file__).parent / "fixtures" / "sample_vault"
