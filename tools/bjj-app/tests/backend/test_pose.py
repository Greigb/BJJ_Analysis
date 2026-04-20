from pathlib import Path

import cv2
import numpy as np
import pytest

from server.analysis.pose import PoseDetector, pose_delta


@pytest.fixture
def blank_image_path(tmp_path: Path) -> Path:
    """A featureless grey image — MediaPipe won't find a pose in it."""
    path = tmp_path / "blank.jpg"
    img = np.full((240, 320, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(path), img)
    return path


def test_pose_detector_returns_none_for_blank_image(blank_image_path: Path):
    detector = PoseDetector()
    try:
        result = detector.detect(blank_image_path)
    finally:
        detector.close()
    assert result is None


def test_pose_detector_returns_none_for_missing_file(tmp_path: Path):
    detector = PoseDetector()
    try:
        with pytest.raises(FileNotFoundError):
            detector.detect(tmp_path / "nope.jpg")
    finally:
        detector.close()


def test_pose_delta_returns_zero_when_either_side_is_none():
    fake_landmarks = [(0.0, 0.0, 0.0)] * 33
    assert pose_delta(None, None) == 0.0
    assert pose_delta(fake_landmarks, None) == 0.0
    assert pose_delta(None, fake_landmarks) == 0.0


def test_pose_delta_returns_zero_for_identical_landmarks():
    lm = [(0.1 * i, 0.1 * i, 0.0) for i in range(33)]
    assert pose_delta(lm, lm) == 0.0


def test_pose_delta_sums_euclidean_distances_across_landmarks():
    # Two landmark sets that differ by (0.1, 0.0) on every landmark.
    a = [(0.0, 0.0, 0.0)] * 33
    b = [(0.1, 0.0, 0.0)] * 33
    # 33 landmarks × 0.1 = 3.3 total delta.
    assert pose_delta(a, b) == pytest.approx(3.3, abs=1e-6)


def test_pose_delta_rejects_mismatched_lengths():
    a = [(0.0, 0.0, 0.0)] * 33
    b = [(0.0, 0.0, 0.0)] * 32
    with pytest.raises(ValueError):
        pose_delta(a, b)
