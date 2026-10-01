"""
EdgeRover — Real-Time YOLO Object Detection & Perception Engine.
Optimized for Raspberry Pi 5 (ARM Cortex-A76) and Edge Robotics.

Key Capabilities:
- Asynchronous, non-blocking background worker (zero latency on camera/web feed).
- Single-frame zero-lag buffer (drops stale frames to keep perception latency <50ms).
- Persistent multi-object tracking (ByteTrack / BotSort) with persistent track IDs.
- Monocular distance estimation using camera pinhole geometry (calibrated for Pi Camera 3).
- Proportional visual servoing error offsets (offset_x [-1.0, 1.0] for auto-steering).
- Evidence & snapshot capture with high-visibility HUD bounding box annotations.
- Multi-backend support: PyTorch (.pt), NCNN (_ncnn_model), ONNX (.onnx).
- Target locking (lock onto a specific target ID for 'follow that person' missions).
- Graceful offline / headless simulation mode for testing on development laptops.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("EdgeRoverVision")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ==============================================================================
# OPTIONAL DEPENDENCIES IMPORT WITH GRACEFUL FALLBACKS
# ==============================================================================

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) or NumPy is not installed. YOLO vision will run in simulation mode.")

try:
    import torch
    # Restrict PyTorch to the Pi 5's 4 physical CPU cores to prevent thread thrashing
    if hasattr(torch, "set_num_threads"):
        torch.set_num_threads(4)
except ImportError:
    pass

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    logger.warning("Ultralytics YOLO is not installed. Run 'pip install ultralytics'.")


# ==============================================================================
# CAMERA CALIBRATION & REFERENCE OBJECT HEIGHTS (CM)
# ==============================================================================

# Raspberry Pi Camera 3 (IMX708 sensor):
# - Sensor diagonal: 7.4 mm
# - Horizontal FOV: ~66.0 degrees
# - Vertical FOV: ~41.0 degrees
# Focal length in pixels at 720p (1280x720):
#   f_px = (width / 2) / tan(H_FOV / 2) = 640 / tan(33°) ≈ 985 pixels
DEFAULT_FOCAL_LENGTH_PX_720P = 985.0

# Real-world estimated heights of standard COCO classes (in centimeters)
KNOWN_OBJECT_HEIGHTS_CM: Dict[str, float] = {
    "person": 170.0,
    "bicycle": 100.0,
    "car": 150.0,
    "motorcycle": 110.0,
    "airplane": 400.0,
    "bus": 320.0,
    "train": 380.0,
    "truck": 300.0,
    "boat": 180.0,
    "traffic light": 90.0,
    "fire hydrant": 75.0,
    "stop sign": 75.0,
    "bench": 80.0,
    "bird": 20.0,
    "cat": 25.0,
    "dog": 55.0,
    "horse": 160.0,
    "sheep": 70.0,
    "cow": 140.0,
    "elephant": 300.0,
    "bear": 150.0,
    "backpack": 45.0,
    "umbrella": 70.0,
    "handbag": 30.0,
    "suitcase": 65.0,
    "bottle": 25.0,
    "cup": 12.0,
    "chair": 80.0,
    "couch": 85.0,
    "potted plant": 45.0,
    "tv": 60.0,
    "laptop": 22.0,
    "mouse": 4.0,
    "remote": 18.0,
    "keyboard": 3.0,
    "cell phone": 15.0,
}


# ==============================================================================
# DATA STRUCTURES
# ==============================================================================

@dataclass
class DetectedObject:
    """Structured representation of a single detected object."""
    label: str
    confidence: float
    box: List[float]               # [x1, y1, x2, y2] in absolute pixel coordinates
    rel_box: List[float]           # [x1_rel, y1_rel, x2_rel, y2_rel] normalized (0.0 to 1.0)
    center_rel: List[float]        # [cx_rel, cy_rel] normalized (0.0 to 1.0)
    size_rel: List[float]          # [w_rel, h_rel] normalized (0.0 to 1.0)
    offset_x: float                # Proportional horizontal offset from image center (-1.0 left to +1.0 right)
    offset_y: float                # Proportional vertical offset from image center (-1.0 top to +1.0 bottom)
    track_id: Optional[int] = None # Persistent tracking ID across frames (ByteTrack)
    estimated_distance_cm: Optional[float] = None # Monocular pinhole range estimate

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# YOLO DETECTOR ENGINE
# ==============================================================================

class YOLODetector:
    """
    High-performance, asynchronous YOLO object detection and tracking engine
    tailored for edge robotics on the Raspberry Pi 5.
    """

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        conf_threshold: float = 0.35,
        imgsz: int = 320,
        enabled: bool = False,
        tracking: bool = True,
        tracker_type: str = "bytetrack.yaml",
        target_classes: Optional[List[str]] = None,
        focal_length_px: float = DEFAULT_FOCAL_LENGTH_PX_720P,
        evidence_dir: str = "evidence",
        simulate: bool = False,
    ):
        """
        Initialize the YOLODetector.

        Args:
            model_name: Model file or directory (.pt, .onnx, or _ncnn_model).
            conf_threshold: Detection confidence cutoff (0.05 to 0.95).
            imgsz: Input resolution for inference (320 is optimal for Pi 5).
            enabled: Initial operational state.
            tracking: If True, uses ByteTrack multi-object tracking to assign persistent IDs.
            tracker_type: Ultralytics tracker config ('bytetrack.yaml' or 'botsort.yaml').
            target_classes: Optional list of class names to filter.
            focal_length_px: Camera focal length in pixels for distance estimation.
            evidence_dir: Directory where snapshots and surveillance evidence are saved.
            simulate: If True, runs synthetic simulation mode when hardware/models are absent.
        """
        self.model_name = model_name
        self.conf_threshold = max(0.05, min(0.95, float(conf_threshold)))
        self.imgsz = int(imgsz)
        self.tracking = tracking
        self.tracker_type = tracker_type
        self.focal_length_px = focal_length_px
        self.evidence_dir = Path(evidence_dir)
        self.simulate = simulate

        self._target_classes: Optional[Set[str]] = (
            set(c.lower() for c in target_classes) if target_classes else None
        )

        # Threading state & buffers (RLock for re-entrant thread safety)
        self._lock = threading.RLock()
        self._frame_event = threading.Event()
        self._stop_event = threading.Event()
        self._pending_frame: Optional[Union[bytes, np.ndarray]] = None
        self._last_processed_frame: Optional[np.ndarray] = None

        # Model state
        self._model = None
        self._model_loading = False
        self._model_loaded = False
        self._model_error: Optional[str] = None

        # Enabled flag
        self._enabled = enabled and (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE or self.simulate)

        # Active target lock
        self._locked_track_id: Optional[int] = None

        # Telemetry & performance metrics
        self._latest_detections: List[DetectedObject] = []
        self._inference_time_ms: float = 0.0
        self._fps: float = 0.0
        self._last_inference_time: float = 0.0
        self._frame_count: int = 0
        self._last_fps_calc_time: float = time.monotonic()
        self._total_inferences: int = 0

        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None

    # --------------------------------------------------------------------------
    # LIFECYCLE MANAGEMENT
    # --------------------------------------------------------------------------

    def start(self) -> None:
        """Start the background inference worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="EdgeRoverVisionWorker",
            daemon=True
        )
        self._worker_thread.start()
        logger.info("YOLODetector worker thread launched.")

    def stop(self) -> None:
        """Gracefully terminate the background worker thread."""
        self._stop_event.set()
        self._frame_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        logger.info("YOLODetector worker thread stopped.")

    # --------------------------------------------------------------------------
    # FRAME INGESTION & ZERO-LAG BUFFER
    # --------------------------------------------------------------------------

    def update_frame(self, frame: Union[bytes, np.ndarray]) -> None:
        """
        Submit a new frame for inference (accepts JPEG bytes or raw BGR np.ndarray).
        Drops any older unprocessed frame to guarantee zero latency buildup.
        """
        if not self._enabled:
            return

        with self._lock:
            self._pending_frame = frame

        self._frame_event.set()

    # --------------------------------------------------------------------------
    # RUNTIME CONTROLS
    # --------------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True if the detection engine is active."""
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        """Enable or disable vision inference at runtime."""
        can_run = (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE) or self.simulate
        if not can_run and enabled:
            with self._lock:
                self._enabled = False
            logger.warning("Cannot enable YOLO: Required libraries (ultralytics, cv2) missing.")
            return False

        with self._lock:
            self._enabled = enabled
            if not enabled:
                self._latest_detections = []
                self._pending_frame = None

        logger.info(f"YOLODetector state changed: enabled={enabled}")
        return True

    def set_confidence(self, conf: float) -> None:
        """Update detection confidence threshold (clamped to [0.05, 0.95])."""
        with self._lock:
            self.conf_threshold = max(0.05, min(0.95, float(conf)))
            logger.info(f"YOLO confidence threshold updated to {self.conf_threshold:.2f}")

    def set_imgsz(self, imgsz: int) -> None:
        """Set inference image size (e.g. 256, 320, 416, 640)."""
        with self._lock:
            self.imgsz = int(imgsz)
            logger.info(f"YOLO inference resolution set to {self.imgsz}x{self.imgsz}")

    def set_target_classes(self, classes: Optional[List[str]]) -> None:
        """Filter detections to only specific class names (e.g. ['person', 'car'])."""
        with self._lock:
            self._target_classes = set(c.lower() for c in classes) if classes else None
            logger.info(f"YOLO target class filter set to: {self._target_classes}")

    def set_tracking(self, enabled: bool, tracker: Optional[str] = None) -> None:
        """Enable or disable persistent multi-object tracking."""
        with self._lock:
            self.tracking = enabled
            if tracker:
                self.tracker_type = tracker
            logger.info(f"YOLO tracking mode set to {enabled} (tracker={self.tracker_type})")

    # --------------------------------------------------------------------------
    # TARGET LOCKING FOR AUTONOMOUS TRACKING / SERVOING
    # --------------------------------------------------------------------------

    def lock_target(self, track_id: int) -> bool:
        """Lock onto a specific persistent track ID for tracking/following."""
        with self._lock:
            for det in self._latest_detections:
                if det.track_id == track_id:
                    self._locked_track_id = track_id
                    logger.info(f"Locked onto target #{track_id} ({det.label})")
                    return True
            self._locked_track_id = track_id
            return True

    def unlock_target(self) -> None:
        """Release the currently locked target."""
        with self._lock:
            self._locked_track_id = None
            logger.info("Target lock released.")

    def get_locked_target(self) -> Optional[Dict[str, Any]]:
        """Return telemetry of the currently locked target, or None if lost."""
        with self._lock:
            if self._locked_track_id is None:
                return None
            for det in self._latest_detections:
                if det.track_id == self._locked_track_id:
                    return det.to_dict()
            return None

    # --------------------------------------------------------------------------
    # TELEMETRY & WORLD STATE INTEGRATION
    # --------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """
        Retrieve comprehensive vision engine telemetry matching the PRD World State.
        Thread-safe and fast for high-frequency REST or WebSocket polling.
        """
        with self._lock:
            det_dicts = [det.to_dict() for det in self._latest_detections]
            locked_info = self.get_locked_target()

            return {
                "available": (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE) or self.simulate,
                "enabled": self._enabled,
                "model_name": self.model_name,
                "model_loaded": self._model_loaded,
                "model_loading": self._model_loading,
                "model_error": self._model_error,
                "conf_threshold": self.conf_threshold,
                "imgsz": self.imgsz,
                "tracking_enabled": self.tracking,
                "tracker_type": self.tracker_type,
                "locked_track_id": self._locked_track_id,
                "locked_target": locked_info,
                "target_classes": list(self._target_classes) if self._target_classes else None,
                "inference_time_ms": self._inference_time_ms,
                "fps": round(self._fps, 1),
                "count": len(det_dicts),
                "detections": det_dicts,
                "total_inferences": self._total_inferences,
                "timestamp": self._last_inference_time,
            }

    # --------------------------------------------------------------------------
    # DISTANCE ESTIMATION USING PINHOLE CAMERA GEOMETRY
    # --------------------------------------------------------------------------

    def estimate_distance_cm(
        self, label: str, bbox_height_px: float, image_height_px: int
    ) -> Optional[float]:
        """
        Estimate real-world distance in centimeters from bounding box pixel height.
        Formula: Distance = (Focal_Length_px * Real_Height_cm) / Bbox_Height_px
        """
        if bbox_height_px <= 4.0:
            return None

        real_height_cm = KNOWN_OBJECT_HEIGHTS_CM.get(label.lower())
        if not real_height_cm:
            return None

        # Scale focal length if frame height differs from standard 720p
        scaled_focal_length = self.focal_length_px * (image_height_px / 720.0)

        distance = (scaled_focal_length * real_height_cm) / bbox_height_px
        # Clamp to realistic physical range for small surveillance rovers (20cm to 3000cm)
        return round(max(20.0, min(3000.0, distance)), 1)

    # --------------------------------------------------------------------------
    # EVIDENCE & SNAPSHOT CAPTURE
    # --------------------------------------------------------------------------

    def capture_evidence(
        self,
        reason: str = "surveillance_event",
        severity: str = "INFO",
        annotate: bool = True,
    ) -> Dict[str, Any]:
        """
        Capture a high-resolution snapshot with bounding boxes, timestamp, and metadata.
        Saves snapshot to disk and returns metadata and JPEG bytes.
        """
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        filename_base = f"evidence_{timestamp_str}_{severity.lower()}"
        img_path = self.evidence_dir / f"{filename_base}.jpg"
        meta_path = self.evidence_dir / f"{filename_base}.json"

        with self._lock:
            frame = self._last_processed_frame
            detections = list(self._latest_detections)

        if frame is None or not CV2_AVAILABLE:
            # Fallback placeholder if no frame captured yet
            if CV2_AVAILABLE:
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(
                    frame,
                    f"EVIDENCE: {reason}",
                    (50, 360),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.2,
                    (255, 255, 255),
                    2,
                )
            else:
                return {
                    "success": False,
                    "error": "No frame available or OpenCV missing",
                }

        # Render annotations if requested
        if annotate and CV2_AVAILABLE:
            frame_to_save = self.annotate_frame(frame, detections)
        else:
            frame_to_save = frame

        # Encode to JPEG
        success, buffer = cv2.imencode(".jpg", frame_to_save, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not success:
            return {"success": False, "error": "JPEG encoding failed"}

        jpeg_bytes = buffer.tobytes()

        # Write image and metadata to disk
        try:
            with open(img_path, "wb") as f:
                f.write(jpeg_bytes)

            metadata = {
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
                "severity": severity,
                "image_path": str(img_path.resolve()),
                "detections_count": len(detections),
                "detections": [d.to_dict() for d in detections],
                "file_size_bytes": len(jpeg_bytes),
            }

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Evidence captured and saved: {img_path} ({reason})")
            return {
                "success": True,
                "image_path": str(img_path.resolve()),
                "metadata_path": str(meta_path.resolve()),
                "jpeg_bytes": jpeg_bytes,
                "metadata": metadata,
            }
        except Exception as e:
            logger.error(f"Failed to write evidence to disk: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # --------------------------------------------------------------------------
    # ANNOTATION ENGINE FOR EVIDENCE HUD
    # --------------------------------------------------------------------------

    @staticmethod
    def annotate_frame(
        img: np.ndarray,
        detections: List[DetectedObject],
        primary_color: Tuple[int, int, int] = (127, 208, 53),  # Neon Emerald (BGR)
    ) -> np.ndarray:
        """
        Draw high-visibility, cyberpunk tactical corner brackets and HUD tags on frame.
        """
        if not CV2_AVAILABLE or img is None:
            return img

        annotated = img.copy()
        h, w = annotated.shape[:2]

        for det in detections:
            box = det.box
            if not box or len(box) != 4:
                continue

            x1, y1, x2, y2 = [int(v) for v in box]
            bx_w = x2 - x1
            bx_h = y2 - y1

            # Corner bracket size
            c_len = max(8, min(24, int(min(bx_w, bx_h) * 0.25)))

            # Select color (Orange for locked target, green for standard)
            color = (0, 165, 255) if det.track_id is not None else primary_color

            # Draw transparent bounding fill
            overlay = annotated.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            cv2.addWeighted(overlay, 0.12, annotated, 0.88, 0, annotated)

            # Draw bounding box outline
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 1)

            # Top-left corner
            cv2.line(annotated, (x1, y1), (x1 + c_len, y1), color, 3)
            cv2.line(annotated, (x1, y1), (x1, y1 + c_len), color, 3)
            # Top-right corner
            cv2.line(annotated, (x2, y1), (x2 - c_len, y1), color, 3)
            cv2.line(annotated, (x2, y1), (x2, y1 + c_len), color, 3)
            # Bottom-left corner
            cv2.line(annotated, (x1, y2), (x1 + c_len, y2), color, 3)
            cv2.line(annotated, (x1, y2), (x1, y2 - c_len), color, 3)
            # Bottom-right corner
            cv2.line(annotated, (x2, y2), (x2 - c_len, y2), color, 3)
            cv2.line(annotated, (x2, y2), (x2, y2 - c_len), color, 3)

            # Target center crosshair
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            cv2.circle(annotated, (cx, cy), 3, (255, 255, 255), -1)

            # Tag text (e.g., "#1 PERSON 94% [140cm]")
            track_prefix = f"#{det.track_id} " if det.track_id is not None else ""
            dist_suffix = f" [{int(det.estimated_distance_cm)}cm]" if det.estimated_distance_cm else ""
            tag = f"{track_prefix}{det.label.upper()} {int(det.confidence * 100)}%{dist_suffix}"

            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            tag_y = max(th + 6, y1 - 6)
            cv2.rectangle(
                annotated,
                (x1, tag_y - th - 4),
                (x1 + tw + 8, tag_y + 4),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                tag,
                (x1 + 4, tag_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (10, 10, 10),
                1,
                cv2.LINE_AA,
            )

        return annotated

    # --------------------------------------------------------------------------
    # MODEL LOADING & EXPORT UTILITY
    # --------------------------------------------------------------------------

    def _load_model(self) -> bool:
        """Load YOLO model inside the worker thread (avoids blocking main thread)."""
        if not (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE):
            self._model_error = "ultralytics or opencv not installed."
            return False

        self._model_loading = True
        try:
            logger.info(f"Loading YOLO model: '{self.model_name}'...")
            t0 = time.monotonic()
            self._model = YOLO(self.model_name)
            self._model_loaded = True
            self._model_error = None
            logger.info(f"YOLO model '{self.model_name}' loaded in {(time.monotonic() - t0):.2f}s.")
            return True
        except Exception as e:
            self._model_error = str(e)
            logger.error(f"Failed to load YOLO model: {e}", exc_info=True)
            return False
        finally:
            self._model_loading = False

    def export_model(self, export_format: str = "ncnn", imgsz: Optional[int] = None) -> Optional[str]:
        """
        Export current PyTorch model to NCNN or ONNX format for maximum ARM64 acceleration.
        Returns the exported path on success.
        """
        if not (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE):
            logger.error("Cannot export model: Ultralytics not installed.")
            return None

        target_imgsz = imgsz or self.imgsz
        try:
            logger.info(f"Exporting '{self.model_name}' to format '{export_format}' (imgsz={target_imgsz})...")
            if not self._model:
                self._model = YOLO(self.model_name)

            export_path = self._model.export(
                format=export_format,
                imgsz=target_imgsz,
                half=False,  # CPU requires FP32
            )
            logger.info(f"Model exported successfully: {export_path}")
            return str(export_path)
        except Exception as e:
            logger.error(f"Model export failed: {e}", exc_info=True)
            return None

    # --------------------------------------------------------------------------
    # ASYNCHRONOUS WORKER LOOP
    # --------------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Continuous background thread loop executing inference on incoming frames."""
        while not self._stop_event.is_set():
            if not self._frame_event.wait(timeout=0.2):
                continue

            self._frame_event.clear()

            if self._stop_event.is_set():
                break

            if not self._enabled:
                continue

            # Grab pending frame and clear slot
            with self._lock:
                raw_frame = self._pending_frame
                self._pending_frame = None

            if raw_frame is None:
                continue

            # Simulation Mode for development laptops without camera/models
            if self.simulate or not (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE):
                self._run_simulation_step()
                time.sleep(0.05)
                continue

            # Ensure model is initialized
            if not self._model_loaded:
                if not self._load_model():
                    time.sleep(1.0)
                    continue

            # Decode frame
            try:
                if isinstance(raw_frame, bytes):
                    np_arr = np.frombuffer(raw_frame, np.uint8)
                    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                elif isinstance(raw_frame, np.ndarray):
                    img = raw_frame
                else:
                    continue

                if img is None:
                    continue

                h_orig, w_orig = img.shape[:2]
                t_start = time.monotonic()

                # Execute tracking or prediction
                if self.tracking:
                    results = self._model.track(
                        source=img,
                        imgsz=self.imgsz,
                        conf=self.conf_threshold,
                        persist=True,
                        tracker=self.tracker_type,
                        verbose=False,
                    )
                else:
                    results = self._model.predict(
                        source=img,
                        imgsz=self.imgsz,
                        conf=self.conf_threshold,
                        verbose=False,
                    )

                t_infer = (time.monotonic() - t_start) * 1000.0

                parsed_detections: List[DetectedObject] = []

                if results and len(results) > 0 and results[0].boxes is not None:
                    boxes = results[0].boxes
                    names = results[0].names

                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        label = names.get(cls_id, f"id_{cls_id}")

                        # Class filter check
                        if self._target_classes and label.lower() not in self._target_classes:
                            continue

                        conf = float(box.conf[0].item())
                        xyxy = box.xyxy[0].tolist()

                        # Clamped pixel coordinates
                        x1 = max(0.0, min(float(w_orig), xyxy[0]))
                        y1 = max(0.0, min(float(h_orig), xyxy[1]))
                        x2 = max(0.0, min(float(w_orig), xyxy[2]))
                        y2 = max(0.0, min(float(h_orig), xyxy[3]))
                        bx_h = y2 - y1
                        bx_w = x2 - x1

                        # Relative normalized coordinates (0.0 to 1.0)
                        x1_rel = round(x1 / w_orig, 4)
                        y1_rel = round(y1 / h_orig, 4)
                        x2_rel = round(x2 / w_orig, 4)
                        y2_rel = round(y2 / h_orig, 4)
                        cx_rel = round((x1_rel + x2_rel) / 2.0, 4)
                        cy_rel = round((y1_rel + y2_rel) / 2.0, 4)

                        # Proportional steering error (-1.0 to +1.0)
                        offset_x = round((cx_rel - 0.5) * 2.0, 4)
                        offset_y = round((cy_rel - 0.5) * 2.0, 4)

                        # Track ID if available
                        track_id = int(box.id[0].item()) if (box.id is not None) else None

                        # Monocular distance estimation
                        dist_cm = self.estimate_distance_cm(label, bx_h, h_orig)

                        parsed_detections.append(
                            DetectedObject(
                                label=label,
                                confidence=round(conf, 3),
                                box=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                                rel_box=[x1_rel, y1_rel, x2_rel, y2_rel],
                                center_rel=[cx_rel, cy_rel],
                                size_rel=[round(bx_w / w_orig, 4), round(bx_h / h_orig, 4)],
                                offset_x=offset_x,
                                offset_y=offset_y,
                                track_id=track_id,
                                estimated_distance_cm=dist_cm,
                            )
                        )

                # Update rolling FPS
                now = time.monotonic()
                self._frame_count += 1
                self._total_inferences += 1
                dt = now - self._last_fps_calc_time
                if dt >= 0.5:
                    current_fps = self._frame_count / dt
                    self._fps = current_fps if self._fps == 0.0 else (0.7 * self._fps + 0.3 * current_fps)
                    self._frame_count = 0
                    self._last_fps_calc_time = now

                # Thread-safe commit of latest telemetry and frame reference
                with self._lock:
                    self._latest_detections = parsed_detections
                    self._inference_time_ms = round(t_infer, 1)
                    self._last_inference_time = now
                    self._last_processed_frame = img

            except Exception as e:
                logger.error(f"Inference error in worker loop: {e}", exc_info=True)
                time.sleep(0.05)

    def _run_simulation_step(self) -> None:
        """Generate smooth synthetic target motion for development and testing."""
        t = time.monotonic()
        # Simulated wandering person
        cx_rel = 0.5 + 0.25 * math.sin(t * 0.8)
        cy_rel = 0.55 + 0.05 * math.cos(t * 0.6)
        w_rel = 0.18
        h_rel = 0.45

        x1_rel = max(0.0, cx_rel - w_rel / 2)
        y1_rel = max(0.0, cy_rel - h_rel / 2)
        x2_rel = min(1.0, cx_rel + w_rel / 2)
        y2_rel = min(1.0, cy_rel + h_rel / 2)

        sim_det = DetectedObject(
            label="person",
            confidence=0.91,
            box=[x1_rel * 1280, y1_rel * 720, x2_rel * 1280, y2_rel * 720],
            rel_box=[round(x1_rel, 4), round(y1_rel, 4), round(x2_rel, 4), round(y2_rel, 4)],
            center_rel=[round(cx_rel, 4), round(cy_rel, 4)],
            size_rel=[round(w_rel, 4), round(h_rel, 4)],
            offset_x=round((cx_rel - 0.5) * 2.0, 4),
            offset_y=round((cy_rel - 0.5) * 2.0, 4),
            track_id=1,
            estimated_distance_cm=round(180 + 30 * math.sin(t * 0.5), 1),
        )

        with self._lock:
            self._latest_detections = [sim_det]
            self._inference_time_ms = 42.5
            self._fps = 23.5
            self._last_inference_time = t
            self._total_inferences += 1
