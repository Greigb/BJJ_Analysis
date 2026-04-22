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
