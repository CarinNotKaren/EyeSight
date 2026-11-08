import cv2
import numpy as np
#detect identical or very similar frames, so the system avoids saving the same view repeatedly.

def compare_frames(
    current_frame: np.ndarray,
    previous_frame: np.ndarray,
    duplicate_threshold: float = 0.02,
) -> dict:
    """Compare a frame with the previous retained frame."""

    if not np.isfinite(duplicate_threshold) or not 0 <= duplicate_threshold <= 1:
        raise ValueError("Duplicate threshold must be between 0 and 1.")

    prepared_frames = []

    for frame in (current_frame, previous_frame):
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError("Each frame must be a non-empty NumPy array.")

        if frame.dtype != np.uint8:
            raise ValueError("Each frame must contain 8-bit pixel values.")

        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Each frame must be a BGR image with 3 channels.")

        # Compare small grayscale copies to reduce calculation time.
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        prepared_frames.append(gray)

    difference = cv2.absdiff(prepared_frames[0], prepared_frames[1])

    # Normalize average pixel difference to the range 0–1.
    novelty_score = float(np.mean(difference) / 255.0)

    return {
        "novelty_score": novelty_score,
        "is_duplicate": novelty_score <= duplicate_threshold,
    }