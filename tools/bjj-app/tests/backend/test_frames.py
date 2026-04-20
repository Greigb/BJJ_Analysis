from pathlib import Path

import pytest

from server.analysis.frames import extract_frames


def test_extract_frames_creates_one_frame_per_second(
    short_video_path: Path, tmp_path: Path
):
    # Fixture: 2s video at 10fps → should produce 2 frames at 1fps.
    out = tmp_path / "frames"
    paths = extract_frames(short_video_path, out, fps=1.0)

    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0
        assert p.suffix == ".jpg"


def test_extract_frames_is_deterministic(short_video_path: Path, tmp_path: Path):
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    paths_a = extract_frames(short_video_path, out_a, fps=1.0)
    paths_b = extract_frames(short_video_path, out_b, fps=1.0)

    assert len(paths_a) == len(paths_b)
    for a, b in zip(paths_a, paths_b):
        assert a.name == b.name


def test_extract_frames_creates_out_dir_if_missing(
    short_video_path: Path, tmp_path: Path
):
    out = tmp_path / "nested" / "frames"
    assert not out.exists()
    paths = extract_frames(short_video_path, out, fps=1.0)
    assert out.is_dir()
    assert all(p.parent == out for p in paths)


def test_extract_frames_raises_on_unreadable_video(tmp_path: Path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(ValueError):
        extract_frames(bad, tmp_path / "frames", fps=1.0)
