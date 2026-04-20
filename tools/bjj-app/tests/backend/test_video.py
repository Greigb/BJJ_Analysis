from pathlib import Path

import pytest

from server.analysis.video import read_duration

FIXTURE = Path(__file__).parent / "fixtures" / "short_video.mp4"


def test_read_duration_returns_seconds_for_short_video():
    duration = read_duration(FIXTURE)
    # Fixture is 2.0s but tolerate tiny OpenCV rounding.
    assert 1.8 <= duration <= 2.2


def test_read_duration_raises_on_nonexistent_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_duration(tmp_path / "nope.mp4")


def test_read_duration_raises_on_non_video_file(tmp_path: Path):
    bad = tmp_path / "text.mp4"
    bad.write_text("this is not a video")
    with pytest.raises(ValueError):
        read_duration(bad)
