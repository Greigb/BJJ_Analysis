from pathlib import Path

import pytest


@pytest.fixture
def sample_vault() -> Path:
    """Path to the fixture vault used by vault.py tests."""
    return Path(__file__).parent / "fixtures" / "sample_vault"


@pytest.fixture
def short_video_path() -> Path:
    """Path to the committed short_video.mp4 fixture (2s, 10fps, 64×48)."""
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


@pytest.fixture
def tmp_project_root(tmp_path: Path) -> Path:
    """A writable project root with an empty assets/ dir for upload tests."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "Roll Log").mkdir()
    return tmp_path
