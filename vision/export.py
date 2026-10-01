"""
EdgeRover — YOLO Model Optimization & NCNN / ONNX Export Tool.

Run this tool directly on the Raspberry Pi 5 to convert PyTorch (.pt) weights
into optimized ARM Cortex-A76 NCNN or ONNX models for maximum real-time inference throughput.

Usage:
    python -m vision.export --model yolov8n.pt --format ncnn --imgsz 320
    python -m vision.export --model yolov8n.pt --format onnx --imgsz 320
"""

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger("YOLOExport")


def export_and_benchmark(model_path: str, export_format: str = "ncnn", imgsz: int = 320, test_runs: int = 15):
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("Ultralytics is not installed. Run 'pip install ultralytics'.")
        sys.exit(1)

    try:
        import numpy as np
    except ImportError:
        logger.error("NumPy is not installed. Run 'pip install numpy'.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("  EDGEROVER YOLO OPTIMIZATION & BENCHMARK TOOL")
    logger.info("=" * 60)
    logger.info(f"Source Model:       {model_path}")
    logger.info(f"Target Format:      {export_format.upper()}")
    logger.info(f"Inference Image:    {imgsz}x{imgsz}")
    logger.info("-" * 60)

    # 1. Load source PyTorch model
    logger.info("Loading source model...")
    t0 = time.monotonic()
    model = YOLO(model_path)
    logger.info(f"Source model loaded in {(time.monotonic() - t0):.2f}s.")

    # 2. Export to target format
    logger.info(f"Exporting to {export_format.upper()} (this may take 1-3 minutes on Pi 5)...")
    t_export_start = time.monotonic()
    try:
        exported_path = model.export(
            format=export_format,
            imgsz=imgsz,
            half=False, # Pi 5 CPU requires full FP32
        )
        export_duration = time.monotonic() - t_export_start
        logger.info(f"Export complete in {export_duration:.2f}s!")
        logger.info(f"Optimized model artifact created at: {exported_path}")
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        sys.exit(1)

    # 3. Benchmark exported model
    logger.info("-" * 60)
    logger.info(f"Benchmarking optimized model on {test_runs} synthetic frames...")
    try:
        opt_model = YOLO(exported_path, task="detect")
        dummy_img = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)

        # Warmup
        for _ in range(3):
            opt_model.predict(source=dummy_img, imgsz=imgsz, verbose=False)

        # Measured runs
        latencies = []
        for _ in range(test_runs):
            t_start = time.monotonic()
            opt_model.predict(source=dummy_img, imgsz=imgsz, verbose=False)
            latencies.append((time.monotonic() - t_start) * 1000.0)

        avg_latency = sum(latencies) / len(latencies)
        fps = 1000.0 / avg_latency if avg_latency > 0 else 0

        logger.info("=" * 60)
        logger.info("  BENCHMARK RESULTS")
        logger.info("=" * 60)
        logger.info(f"Average Inference Latency: {avg_latency:.1f} ms")
        logger.info(f"Estimated Inference Speed: {fps:.1f} FPS")
        logger.info(f"Min Latency:               {min(latencies):.1f} ms")
        logger.info(f"Max Latency:               {max(latencies):.1f} ms")
        logger.info("=" * 60)
        logger.info(f"To use this optimized model in app.py, set:")
        logger.info(f"YOLO_MODEL = '{exported_path}'")
        logger.info("=" * 60)

    except Exception as e:
        logger.warning(f"Benchmark could not complete: {e}")


def main():
    parser = argparse.ArgumentParser(description="EdgeRover YOLO Model Export & Benchmark Tool")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Path to input model (e.g. yolov8n.pt)")
    parser.add_argument("--format", type=str, default="ncnn", choices=["ncnn", "onnx", "openvino"], help="Target format")
    parser.add_argument("--imgsz", type=int, default=320, help="Inference resolution (default: 320)")
    parser.add_argument("--runs", type=int, default=15, help="Number of benchmark iterations")

    args = parser.parse_args()
    export_and_benchmark(args.model, args.format, args.imgsz, args.runs)


if __name__ == "__main__":
    main()
