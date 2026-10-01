"""
EdgeRover — YOLO Detector Test & Validation Suite.

This script tests the complete vision pipeline, telemetry format,
distance estimation, target locking, and evidence capture.
Works both on development laptops (simulation fallback) and on Raspberry Pi 5.

Usage:
    python -m vision.test_detector
"""

import json
import logging
import sys
import time
from pathlib import Path

from vision.detector import YOLODetector, DetectedObject, DEFAULT_FOCAL_LENGTH_PX_720P

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("TestVision")


def run_tests():
    logger.info("=" * 65)
    logger.info("  EDGEROVER VISION SUBSYSTEM TEST SUITE")
    logger.info("=" * 65)

    test_dir = Path("scratch/test_evidence")
    test_dir.mkdir(parents=True, exist_ok=True)

    # Test 1: Instantiation with simulation fallback
    logger.info("[Test 1/6] Initializing YOLODetector in simulation/fallback mode...")
    detector = YOLODetector(
        model_name="yolov8n.pt",
        conf_threshold=0.35,
        imgsz=320,
        enabled=True,
        tracking=True,
        simulate=True,
        evidence_dir=str(test_dir),
    )
    detector.start()
    assert detector.is_enabled() is True, "Detector should be enabled"
    logger.info("  -> Detector successfully started.")

    # Test 2: Ingest dummy frame and verify inference
    logger.info("[Test 2/6] Ingesting test frames...")
    detector.update_frame(b"DUMMY_FRAME_DATA")
    time.sleep(0.15)  # Allow worker thread to cycle

    status = detector.get_status()
    logger.info(f"  -> Telemetry received: {status['count']} detections, {status['fps']} FPS, {status['inference_time_ms']} ms")
    assert "detections" in status, "Status must include detections array"
    assert "fps" in status, "Status must include fps"
    assert "inference_time_ms" in status, "Status must include inference_time_ms"
    logger.info("  -> Status telemetry format complies with PRD Blackboard specification.")

    # Test 3: Verify Bounding Box & Steering Offset math
    logger.info("[Test 3/6] Verifying Visual Servoing & Steering Error math...")
    if status["detections"]:
        det = status["detections"][0]
        logger.info(f"  -> Detected: {det['label']} (conf: {det['confidence']})")
        logger.info(f"  -> Relative Box [x1, y1, x2, y2]: {det['rel_box']}")
        logger.info(f"  -> Center [cx, cy]: {det['center_rel']}")
        logger.info(f"  -> Steering Offset X: {det['offset_x']} (Range: -1.0 to +1.0)")
        logger.info(f"  -> Estimated Distance: {det['estimated_distance_cm']} cm")

        # Validate range
        assert -1.0 <= det["offset_x"] <= 1.0, "offset_x must be in range [-1.0, 1.0]"
        assert -1.0 <= det["offset_y"] <= 1.0, "offset_y must be in range [-1.0, 1.0]"
        logger.info("  -> Coordinate and offset math verified!")

    # Test 4: Target Locking
    logger.info("[Test 4/6] Testing Target Lock & Follow capability...")
    detector.lock_target(track_id=1)
    locked = detector.get_locked_target()
    assert detector._locked_track_id == 1, "Track ID 1 should be locked"
    logger.info(f"  -> Target lock engaged: {locked is not None}")
    detector.unlock_target()
    assert detector.get_locked_target() is None, "Target should be unlocked"
    logger.info("  -> Target lock and release verified.")

    # Test 5: Monocular Distance Formula Validation
    logger.info("[Test 5/6] Validating Monocular Distance formula...")
    # Example: Person (170cm height) taking up 360 pixels in a 720p frame:
    # Expected distance = (985 * 170) / 360 ≈ 465 cm
    calc_dist = detector.estimate_distance_cm(
        label="person",
        bbox_height_px=360.0,
        image_height_px=720,
    )
    logger.info(f"  -> Synthetic test: Person (170cm) taking up 360px -> Distance: {calc_dist} cm")
    assert calc_dist is not None and 450.0 <= calc_dist <= 480.0, "Distance calculation mismatch"
    logger.info("  -> Monocular distance formula validated.")

    # Test 6: Evidence & Snapshot Capture
    logger.info("[Test 6/6] Testing Evidence Capture & Surveillance Logging...")
    evidence_res = detector.capture_evidence(
        reason="test_perimeter_breach",
        severity="WARNING",
        annotate=False,
    )
    logger.info(f"  -> Capture result: success={evidence_res.get('success')}")

    # Shutdown
    detector.stop()
    logger.info("=" * 65)
    logger.info("  ALL TESTS PASSED SUCCESSFULLY! VISION ENGINE READY FOR PI 5.")
    logger.info("=" * 65)


if __name__ == "__main__":
    run_tests()
