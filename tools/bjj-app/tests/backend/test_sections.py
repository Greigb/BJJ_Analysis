"""Unit tests for M9 sections pure helpers."""
from __future__ import annotations

import pytest

from server.analysis.sections import build_sample_timestamps


class TestBuildSampleTimestamps:
    def test_simple_1s_interval(self):
        assert build_sample_timestamps(0.0, 4.0, 1.0) == [0.0, 1.0, 2.0, 3.0]

    def test_excludes_end_s(self):
        # end_s is EXCLUSIVE — 4.0 is not part of the list for start=0, end=4, step=1
        result = build_sample_timestamps(0.0, 4.0, 1.0)
        assert 4.0 not in result

    def test_includes_start_s(self):
        result = build_sample_timestamps(3.0, 7.0, 1.0)
        assert result[0] == 3.0

    def test_half_second_interval(self):
        assert build_sample_timestamps(0.0, 2.0, 0.5) == [0.0, 0.5, 1.0, 1.5]

    def test_two_second_interval(self):
        assert build_sample_timestamps(0.0, 10.0, 2.0) == [0.0, 2.0, 4.0, 6.0, 8.0]

    def test_empty_when_start_equals_end(self):
        assert build_sample_timestamps(3.0, 3.0, 1.0) == []

    def test_single_point_when_interval_exceeds_range(self):
        # interval 2.0 > range 1.5 → only start_s is emitted
        assert build_sample_timestamps(3.0, 4.5, 2.0) == [3.0]

    def test_rounds_to_millisecond(self):
        # Guard against floating-point drift: each value rounded to 3 decimal places
        result = build_sample_timestamps(0.0, 1.0, 0.1)
        assert result == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

    def test_raises_when_start_negative(self):
        with pytest.raises(ValueError, match="start_s"):
            build_sample_timestamps(-1.0, 3.0, 1.0)

    def test_raises_when_end_less_than_start(self):
        with pytest.raises(ValueError, match="end_s"):
            build_sample_timestamps(5.0, 3.0, 1.0)

    def test_raises_when_interval_not_positive(self):
        with pytest.raises(ValueError, match="interval_s"):
            build_sample_timestamps(0.0, 3.0, 0.0)
        with pytest.raises(ValueError, match="interval_s"):
            build_sample_timestamps(0.0, 3.0, -1.0)


from pathlib import Path

from server.analysis.frames import extract_frames_at_timestamps


def _short_video_path() -> Path:
    # The repo ships a short fixture at tests/backend/fixtures/short_video.mp4
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


class TestExtractFramesAtTimestamps:
    def test_writes_one_file_per_timestamp(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0, 0.5, 1.0], out_dir=tmp_path
        )
        assert len(paths) == 3
        for p in paths:
            assert p.exists()
            assert p.suffix == ".jpg"

    def test_sequential_filenames_starting_at_zero(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0, 0.5, 1.0], out_dir=tmp_path
        )
        assert paths[0].name == "frame_000000.jpg"
        assert paths[1].name == "frame_000001.jpg"
        assert paths[2].name == "frame_000002.jpg"

    def test_start_index_offsets_filenames(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0, 0.5], out_dir=tmp_path, start_index=10
        )
        assert paths[0].name == "frame_000010.jpg"
        assert paths[1].name == "frame_000011.jpg"

    def test_empty_timestamps_returns_empty(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[], out_dir=tmp_path
        )
        assert paths == []

    def test_out_dir_created_if_missing(self, tmp_path):
        video = _short_video_path()
        nested = tmp_path / "a" / "b" / "c"
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0], out_dir=nested
        )
        assert nested.is_dir()
        assert paths[0].exists()

    def test_missing_video_raises(self, tmp_path):
        import pytest as _pytest
        with _pytest.raises(FileNotFoundError):
            extract_frames_at_timestamps(
                tmp_path / "nope.mp4", timestamps=[0.0], out_dir=tmp_path
            )
