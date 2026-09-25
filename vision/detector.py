"""
YOLO Object Detection Engine for Raspberry Pi 5 Rover.

Optimized for ARM Cortex-A76 (Raspberry Pi 5):
- Asynchronous background worker thread (decoupled from camera & web stream).
- Zero-latency buffer: Drops stale frames and only infers on the freshest frame.
- Configurable inference resolution (default 320x320 for 15-25+ FPS on Pi 5 CPU).
- Thread-safe telemetry, relative target coordinates, and dynamic toggling.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("RoverVision")

# Graceful import of vision libraries
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) or NumPy is not installed. YOLO detection will be disabled.")

try:
    import torch
    # Set number of threads to match Raspberry Pi 5's 4 CPU cores
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


class YOLODetector:
    """
    Asynchronous, non-blocking YOLO object detector optimized for Raspberry Pi 5.
    """

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        conf_threshold: float = 0.35,
        imgsz: int = 320,
        enabled: bool = False,
        target_classes: Optional[List[str]] = None,
    ):
        """
        Initialize the detector.

        Args:
            model_name: Path or name of YOLO model (e.g. 'yolov8n.pt', 'yolo11n.pt').
            conf_threshold: Minimum detection confidence (0.0 to 1.0).
            imgsz: Inference image size (320 or 416 recommended for Pi 5).
            enabled: Initial enabled state.
            target_classes: Optional list of class names to filter (None detects all).
        """
        self.model_name = model_name
        self.conf_threshold = conf_threshold
        self.imgsz = imgsz
        self._enabled = enabled and ULTRALYTICS_AVAILABLE and CV2_AVAILABLE
        self._target_classes: Optional[Set[str]] = (
            set(c.lower() for c in target_classes) if target_classes else None
        )

        # Threading and buffers
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._stop_event = threading.Event()
        self._pending_frame: Optional[bytes] = None

        # Model state
        self._model = None
        self._model_loading = False
        self._model_loaded = False
        self._model_error: Optional[str] = None

        # Telemetry & results
        self._latest_detections: List[Dict[str, Any]] = []
        self._inference_time_ms: float = 0.0
        self._fps: float = 0.0
        self._last_inference_time: float = 0.0
        self._frame_count: int = 0
        self._last_fps_calc_time: float = time.monotonic()
        self._last_annotated_jpeg: Optional[bytes] = None

        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background detector worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="YOLODetectorWorker",
            daemon=True
        )
        self._worker_thread.start()
        logger.info("YOLODetector worker thread started.")

    def stop(self) -> None:
        """Signal the worker thread to stop and wait for completion."""
        self._stop_event.set()
        self._frame_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
        logger.info("YOLODetector worker thread stopped.")

    def update_frame(self, frame_bytes: bytes) -> None:
        """
        Submit a new JPEG frame for inference.
        This drops any previous unprocessed frame to guarantee zero latency buildup.
        """
        if not self._enabled:
            return

        with self._lock:
            self._pending_frame = frame_bytes

        self._frame_event.set()

    def is_enabled(self) -> bool:
        """Return True if detection is currently enabled."""
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        """Enable or disable object detection at runtime."""
        if not (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE):
            with self._lock:
                self._enabled = False
            return False

        with self._lock:
            self._enabled = enabled
            if not enabled:
                self._latest_detections = []
                self._pending_frame = None

        logger.info(f"YOLODetector enabled set to {enabled}")
        return True

    def set_confidence(self, conf: float) -> None:
        """Update confidence threshold (clamped between 0.1 and 0.95)."""
        with self._lock:
            self.conf_threshold = max(0.1, min(0.95, float(conf)))

    def set_imgsz(self, imgsz: int) -> None:
        """Update inference image size (e.g. 256, 320, 416, 640)."""
        with self._lock:
            self.imgsz = int(imgsz)

    def set_target_classes(self, classes: Optional[List[str]]) -> None:
        """Set or clear class filter."""
        with self._lock:
            self._target_classes = (
                set(c.lower() for c in classes) if classes else None
            )

    def get_status(self) -> Dict[str, Any]:
        """
        Get current telemetry and status of the vision engine.
        Safe to call from web API handlers.
        """
        with self._lock:
            return {
                "available": ULTRALYTICS_AVAILABLE and CV2_AVAILABLE,
                "enabled": self._enabled,
                "model_name": self.model_name,
                "model_loaded": self._model_loaded,
                "model_loading": self._model_loading,
                "model_error": self._model_error,
                "conf_threshold": self.conf_threshold,
                "imgsz": self.imgsz,
                "target_classes": list(self._target_classes) if self._target_classes else None,
                "inference_time_ms": self._inference_time_ms,
                "fps": round(self._fps, 1),
                "count": len(self._latest_detections),
                "detections": list(self._latest_detections),
                "timestamp": self._last_inference_time,
            }

    def _load_model(self) -> bool:
        """Load YOLO model inside the worker thread (avoids blocking main thread)."""
        if not (ULTRALYTICS_AVAILABLE and CV2_AVAILABLE):
            self._model_error = "Required libraries (ultralytics, opencv, numpy) not installed."
            return False

        self._model_loading = True
        try:
            logger.info(f"Loading YOLO model '{self.model_name}'...")
            self._model = YOLO(self.model_name)
            self._model_loaded = True
            self._model_error = None
            logger.info(f"YOLO model '{self.model_name}' loaded successfully.")
            return True
        except Exception as e:
            self._model_error = str(e)
            logger.error(f"Failed to load YOLO model: {e}", exc_info=True)
            return False
        finally:
            self._model_loading = False

    def _worker_loop(self) -> None:
        """Background thread loop performing continuous inference on latest frames."""
        while not self._stop_event.is_set():
            # Wait for a new frame event or timeout
            if not self._frame_event.wait(timeout=0.2):
                continue

            self._frame_event.clear()

            # If stopped, exit immediately
            if self._stop_event.is_set():
                break

            # If not enabled, skip processing
            if not self._enabled:
                continue

            # Grab latest pending frame and clear the slot
            with self._lock:
                frame_data = self._pending_frame
                self._pending_frame = None

            if not frame_data:
                continue

            # Ensure model is loaded
            if not self._model_loaded:
                if not self._load_model():
                    # Sleep slightly on error to avoid busy loop
                    time.sleep(1.0)
                    continue

            # Perform inference
            try:
                # Decode JPEG byte stream into NumPy array
                np_arr = np.frombuffer(frame_data, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue

                h_orig, w_orig = img.shape[:2]

                t_start = time.monotonic()

                # Optimized inference:
                # - imgsz=320 minimizes memory footprint and latency on Pi 5 CPU
                # - verbose=False suppresses stdout overhead
                results = self._model.predict(
                    source=img,
                    imgsz=self.imgsz,
                    conf=self.conf_threshold,
                    verbose=False,
                )

                t_infer = (time.monotonic() - t_start) * 1000.0

                parsed_detections: List[Dict[str, Any]] = []

                if results and len(results) > 0 and results[0].boxes is not None:
                    boxes = results[0].boxes
                    names = results[0].names

                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        label = names.get(cls_id, f"id_{cls_id}")

                        # Class filter
                        if self._target_classes and label.lower() not in self._target_classes:
                            continue

                        conf = float(box.conf[0].item())
                        xyxy = box.xyxy[0].tolist()  # [x1, y1, x2, y2]

                        # Bounding box in original pixels
                        x1 = max(0.0, min(float(w_orig), xyxy[0]))
                        y1 = max(0.0, min(float(h_orig), xyxy[1]))
                        x2 = max(0.0, min(float(w_orig), xyxy[2]))
                        y2 = max(0.0, min(float(h_orig), xyxy[3]))

                        # Relative / normalized coordinates (0.0 to 1.0)
                        # Ideal for client-side responsive canvas and future autonomous navigation
                        x1_rel = round(x1 / w_orig, 4)
                        y1_rel = round(y1 / h_orig, 4)
                        x2_rel = round(x2 / w_orig, 4)
                        y2_rel = round(y2 / h_orig, 4)
                        cx_rel = round((x1_rel + x2_rel) / 2.0, 4)
                        cy_rel = round((y1_rel + y2_rel) / 2.0, 4)
                        box_width_rel = round(x2_rel - x1_rel, 4)
                        box_height_rel = round(y2_rel - y1_rel, 4)

                        parsed_detections.append({
                            "label": label,
                            "confidence": round(conf, 3),
                            "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                            "rel_box": [x1_rel, y1_rel, x2_rel, y2_rel],
                            "center_rel": [cx_rel, cy_rel],
                            "size_rel": [box_width_rel, box_height_rel],
                        })

                # Calculate FPS using Exponential Moving Average
                now = time.monotonic()
                self._frame_count += 1
                dt_fps = now - self._last_fps_calc_time
                if dt_fps >= 0.5:
                    current_fps = self._frame_count / dt_fps
                    if self._fps == 0.0:
                        self._fps = current_fps
                    else:
                        self._fps = 0.7 * self._fps + 0.3 * current_fps
                    self._frame_count = 0
                    self._last_fps_calc_time = now

                # Update shared telemetry
                with self._lock:
                    self._latest_detections = parsed_detections
                    self._inference_time_ms = round(t_infer, 1)
                    self._last_inference_time = now

            except Exception as e:
                logger.error(f"Error during YOLO inference: {e}", exc_info=True)
                time.sleep(0.1)

    @staticmethod
    def annotate_image(
        img: Any,
        detections: List[Dict[str, Any]],
        color: Tuple[int, int, int] = (53, 208, 127),  # Neon green (BGR)
    ) -> Any:
        """
        Utility to render bounding boxes onto an OpenCV image (if server-side rendering is needed).
        """
        if not CV2_AVAILABLE or img is None:
            return img

        annotated = img.copy()
        for det in detections:
            box = det.get("box")
            if not box or len(box) != 4:
                continue

            x1, y1, x2, y2 = [int(v) for v in box]
            label = det.get("label", "obj")
            conf = int(det.get("confidence", 0) * 100)
            caption = f"{label} {conf}%"

            # Draw box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Caption background tag
            (text_w, text_h), baseline = cv2.getTextSize(
                caption, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            cv2.rectangle(
                annotated,
                (x1, max(0, y1 - text_h - 6)),
                (x1 + text_w + 8, y1),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                caption,
                (x1 + 4, max(text_h + 2, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        return annotated
