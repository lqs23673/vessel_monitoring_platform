"""OpenCV image codecs with Python file I/O for Unicode Windows paths."""
from pathlib import Path

import cv2
import numpy as np


def read_image(path: str | Path) -> np.ndarray | None:
    try:
        data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except (OSError, cv2.error):
        return None


def write_image(path: str | Path, image: np.ndarray) -> bool:
    path = Path(path)
    try:
        ok, data = cv2.imencode(path.suffix, image)
        if ok:
            path.write_bytes(data.tobytes())
        return bool(ok)
    except (OSError, cv2.error):
        return False
