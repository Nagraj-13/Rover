"""Vision module for EdgeRover."""

from .detector import (
    YOLODetector,
    DetectedObject,
    KNOWN_OBJECT_HEIGHTS_CM,
    DEFAULT_FOCAL_LENGTH_PX_720P,
)

__all__ = [
    "YOLODetector",
    "DetectedObject",
    "KNOWN_OBJECT_HEIGHTS_CM",
    "DEFAULT_FOCAL_LENGTH_PX_720P",
]
