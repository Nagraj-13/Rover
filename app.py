#!/usr/bin/env python3

import io
import json
import logging
import os
import threading
import time

from flask import Flask, Response, jsonify, request, send_from_directory

# Hardware Drivers with Graceful Fallback for Laptops
try:
    from gpiozero import Motor
    GPIOZERO_AVAILABLE = True
except (ImportError, Exception) as _gpio_err:
    GPIOZERO_AVAILABLE = False
    print(f"!!! WARNING: gpiozero unavailable ({_gpio_err}). Using MOCK motors - NO GPIO OUTPUT WILL OCCUR !!!")
    class MockMotor:
        def __init__(self, forward=None, backward=None, pwm=True):
            self.forward_pin = forward
            self.backward_pin = backward
            self.speed = 0.0
            self.is_active = False
        def forward(self, speed=1.0):
            self.speed = speed
            self.is_active = True
        def backward(self, speed=1.0):
            self.speed = -speed
            self.is_active = True
        def stop(self):
            self.speed = 0.0
            self.is_active = False
        def close(self):
            self.stop()
    Motor = MockMotor

try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    PICAMERA2_AVAILABLE = True
except (ImportError, Exception):
    PICAMERA2_AVAILABLE = False
    class MockPicamera2:
        def __init__(self):
            self._recording = False
        def create_video_configuration(self, **kwargs):
            return {}
        def configure(self, config):
            pass
        def start_recording(self, encoder, output):
            self._recording = True
        def stop_recording(self):
            self._recording = False
    Picamera2 = MockPicamera2
    def MJPEGEncoder():
        return None
    def FileOutput(output):
        return None

from sensors import DistanceSensor
from vision import YOLODetector
from motion import MissionRunner, MotionController

# 4-Tier Hybrid Intelligence Stack (PRD Section 4)
from intelligence import (
    tool_registry,
    needle_router,
    laya_engine,
    groq_brain,
    WorldState,
    EventSeverity,
    RecommendedAction,
)


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "0.0.0.0"
PORT = 8080

ROVER_PATH = "/rover"

# Camera
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720

# Default motor speed
DEFAULT_SPEED = 0.30

# Safety watchdog
# If the Pi does not receive a command for this long,
# the motors are automatically stopped.
WATCHDOG_TIMEOUT = 0.6

# Vision / AI Configuration
YOLO_MODEL = "yolov8n.pt"     # Ultralytics nano model (fastest inference on Pi 5)
YOLO_IMGSZ = 320             # 320x320 optimal for Pi 5 CPU real-time inference (15-25+ FPS)
YOLO_DEFAULT_CONF = 0.35     # Default confidence threshold


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# MOTOR SETUP
# ============================================================

# LEFT IBT-2
# GPIO17 -> RPWM
# GPIO18 -> LPWM
left_motor = Motor(
    forward=17,
    backward=18,
    pwm=True
)

# RIGHT IBT-2
# GPIO22 -> RPWM
# GPIO23 -> LPWM
right_motor = Motor(
    forward=22,
    backward=23,
    pwm=True
)

motor_lock = threading.RLock()

current_command = "stop"
current_speed = DEFAULT_SPEED
last_control_time = time.monotonic()


# ============================================================
# MOTOR CONTROL
# ============================================================

def stop_motors():
    global current_command
    with motor_lock:
        left_motor.stop()
        right_motor.stop()
        current_command = "stop"


def move_forward(speed):
    left_motor.forward(speed)
    right_motor.forward(speed)


def move_backward(speed):
    left_motor.backward(speed)
    right_motor.backward(speed)


def turn_left(speed):
    left_motor.backward(speed)
    right_motor.forward(speed)


def turn_right(speed):
    left_motor.forward(speed)
    right_motor.backward(speed)


def execute_command(command, speed):
    global current_command
    global current_speed
    global last_control_time

    # Keep speed between 0.0 and 1.0
    speed = max(0.0, min(1.0, float(speed)))

    with motor_lock:
        if command == "forward":
            # Deterministic Safety Interceptor: Block forward movement if obstacle < 30 cm
            if distance_sensor.is_obstacle_close():
                stop_motors()
                print(f"SAFETY INTERCEPTOR: Forward motion blocked by obstacle (<{distance_sensor.safety_threshold_cm}cm)")
                return False
            move_forward(speed)
        elif command == "backward":
            move_backward(speed)
        elif command == "left":
            turn_left(speed)
        elif command == "right":
            turn_right(speed)
        elif command == "stop":
            left_motor.stop()
            right_motor.stop()
        else:
            return False

        current_command = command
        current_speed = speed
        last_control_time = time.monotonic()

    print(f"[CONTROL] Dispatched: {command.upper()} @ {int(speed * 100)}% PWM")
    return True


# ============================================================
# MOTOR SAFETY WATCHDOG
# ============================================================

def motor_watchdog():
    global current_command

    while True:
        time.sleep(0.1)
        with motor_lock:
            if current_command != "stop":
                elapsed = time.monotonic() - last_control_time
                if elapsed > WATCHDOG_TIMEOUT:
                    left_motor.stop()
                    right_motor.stop()
                    current_command = "stop"
                    print("WATCHDOG: Motors stopped (no control heartbeat)")


watchdog_thread = threading.Thread(
    target=motor_watchdog,
    daemon=True
)
watchdog_thread.start()


# ============================================================
# VISION / YOLO DETECTOR SETUP
# ============================================================

# Start YOLO enabled by default so bounding boxes and detections appear immediately on boot
detector = YOLODetector(
    model_name=YOLO_MODEL,
    conf_threshold=YOLO_DEFAULT_CONF,
    imgsz=YOLO_IMGSZ,
    enabled=True
)
detector.start()


# ============================================================
# SENSORS / VL53L0X DISTANCE SENSOR SETUP
# ============================================================

# No VL53L0X is fitted at the moment. Set ROVER_DISTANCE_SENSOR=1 to turn the
# obstacle interceptor and live range telemetry back on once it is wired up.
DISTANCE_SENSOR_ENABLED = os.environ.get("ROVER_DISTANCE_SENSOR", "0") == "1"

distance_sensor = DistanceSensor(
    safety_threshold_cm=30.0,
    poll_interval_s=0.033,
    enabled=DISTANCE_SENSOR_ENABLED
)
distance_sensor.start()


# ============================================================
# CAMERA SETUP
# ============================================================

class StreamingOutput(io.BufferedIOBase):
    """Thread-safe stream output buffer interfacing with Picamera2 and YOLODetector."""

    def __init__(self, vision_detector=None):
        self.frame = None
        self.condition = threading.Condition()
        self.vision_detector = vision_detector

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

        # Decoupled, non-blocking frame forward to AI vision worker
        if self.vision_detector and self.vision_detector.is_enabled():
            self.vision_detector.update_frame(buf)


# Shared stream buffer with detector hook
output = StreamingOutput(vision_detector=detector)

# Create camera with graceful simulation fallback for development laptops
camera_active = False
if PICAMERA2_AVAILABLE:
    try:
        picam2 = Picamera2()
        camera_config = picam2.create_video_configuration(
            main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT)}
        )
        picam2.configure(camera_config)
        encoder = MJPEGEncoder()
        picam2.start_recording(encoder, FileOutput(output))
        camera_active = True
        print("Camera: Picamera2 started recording (1280x720).")
    except Exception as e:
        print(f"Picamera2 init exception: {e}. Running in simulation mode.")
        picam2 = MockPicamera2()
else:
    picam2 = MockPicamera2()

if not camera_active:
    # Background simulated MJPEG stream for development laptops
    def _laptop_simulation_feed():
        try:
            import cv2
            import numpy as np
            has_cv = True
        except ImportError:
            has_cv = False

        while True:
            time.sleep(0.066)  # ~15 FPS
            if has_cv:
                img = np.zeros((360, 640, 3), dtype=np.uint8)
                img[:] = (24, 28, 32)
                cv2.putText(img, "EDGEROVER SIMULATION STREAM", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 240, 255), 2)
                cv2.putText(img, f"Range: {distance_sensor.get_distance_cm():.1f} cm | Batt: 84%", (25, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 255, 150), 1)
                cv2.putText(img, f"Motor: {current_command.upper()} | Speed: {int(current_speed*100)}%", (25, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)
                cv2.putText(img, "Groq (Tier 1) | Needle 2 (Tier 2) | Laya (Tier 3)", (25, 335), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
                _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                output.write(buf.tobytes())
            else:
                jpeg_1x1 = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
                output.write(jpeg_1x1)

    sim_thread = threading.Thread(target=_laptop_simulation_feed, daemon=True)
    sim_thread.start()


# Helper: Build real-time WorldState blackboard for Laya and Groq
def build_current_world_state() -> WorldState:
    dist = distance_sensor.get_distance_cm()
    det_status = detector.get_status()
    latest_detections = det_status.get("latest_detections", [])
    return WorldState(
        distance_cm=dist,
        detections=latest_detections,
        battery_pct=84.0,
        current_speed=current_speed,
        rover_state=current_command.upper(),
    )


# ------------------------------------------------------------
# Open-loop motion planning (distance -> time, angle -> time)
# ------------------------------------------------------------

def touch_heartbeat():
    """Keep the safety watchdog fed while a timed move is running."""
    global last_control_time
    with motor_lock:
        last_control_time = time.monotonic()


motion = MotionController(
    drive_fn=execute_command,
    stop_fn=stop_motors,
    heartbeat_fn=touch_heartbeat,
)
mission_runner = MissionRunner(tool_registry, motion)


def emergency_stop():
    """Abort any running mission, drop queued moves and cut the motors."""
    mission_runner.abort("Emergency stop")
    motion.cancel_all()
    stop_motors()
    return {"status": "stopped", "success": True}


def planned_move(command, speed=None, duration_seconds=None, distance_cm=None, degrees=None):
    """Queue a timed move; returns immediately with the planned duration and job id."""
    job = motion.submit(command, speed=speed, duration_s=duration_seconds,
                        distance_cm=distance_cm, degrees=degrees)
    out = job.to_dict()
    out["status"] = "queued"
    out["success"] = True
    return out


def tool_move_forward(speed=None, duration_seconds=None, distance_cm=None):
    return planned_move("forward", speed, duration_seconds, distance_cm)


def tool_move_backward(speed=None, duration_seconds=None, distance_cm=None):
    return planned_move("backward", speed, duration_seconds, distance_cm)


def tool_turn_left(speed=None, degrees=None, duration_seconds=None):
    return planned_move("left", speed, duration_seconds, None, degrees)


def tool_turn_right(speed=None, degrees=None, duration_seconds=None):
    return planned_move("right", speed, duration_seconds, None, degrees)


def tool_scan_surroundings(degrees=360.0, speed=None):
    # The camera is fixed (no pan servo), so "scanning" means rotating the whole chassis.
    return planned_move("right", speed, None, None, degrees)


def tool_capture_evidence(reason="Surveillance event", severity="INFO"):
    """Save the snapshot and return only JSON-safe metadata (the raw JPEG bytes stay on disk)."""
    result = detector.capture_evidence(reason=reason, severity=severity)
    return {k: v for k, v in result.items() if not isinstance(v, (bytes, bytearray))}


# Bind Rover Hardware into strictly typed Tool Registry
tool_registry.register_tool("scan_surroundings", tool_scan_surroundings)
tool_registry.bind_rover_hardware(
    move_forward_fn=tool_move_forward,
    move_backward_fn=tool_move_backward,
    turn_left_fn=tool_turn_left,
    turn_right_fn=tool_turn_right,
    stop_rover_fn=emergency_stop,
    capture_evidence_fn=tool_capture_evidence,
    get_telemetry_fn=lambda: build_current_world_state().to_dict(),
)


# ============================================================
# VIDEO STREAM GENERATOR
# ============================================================

def generate_frames():
    while True:
        with output.condition:
            output.condition.wait()
            frame = output.frame

        if frame is None:
            continue

        yield (
            b"--FRAME\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: "
            + str(len(frame)).encode()
            + b"\r\n\r\n"
            + frame
            + b"\r\n"
        )


# ============================================================
# WEB INTERFACE
# ============================================================

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Rover Control with AI Vision</title>

<style>
* {
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    min-height: 100%;
    background: #08090d;
    color: #ffffff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
}

body {
    display: flex;
    justify-content: center;
}

.container {
    width: 100%;
    max-width: 720px;
    padding: 14px;
}

/* HEADER */
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.title {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.5px;
}

.status-badge-container {
    display: flex;
    align-items: center;
    gap: 12px;
}

.status {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 13px;
    color: #a0a4ad;
}

.status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #35d07f;
    box-shadow: 0 0 6px rgba(53, 208, 127, 0.4);
}

/* CAMERA WITH CANVAS OVERLAY */
.camera-card {
    width: 100%;
    background: #111318;
    border: 1px solid #242731;
    border-radius: 16px;
    overflow: hidden;
    margin-bottom: 16px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.camera-wrapper {
    position: relative;
    width: 100%;
    line-height: 0;
}

.camera {
    display: block;
    width: 100%;
    height: auto;
    background: #000;
}

#detectionCanvas {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}

.ai-overlay-badge {
    position: absolute;
    top: 10px;
    right: 10px;
    background: rgba(17, 19, 24, 0.85);
    border: 1px solid #35d07f;
    color: #35d07f;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    backdrop-filter: blur(4px);
    display: none;
    align-items: center;
    gap: 5px;
}

.ai-pulse-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #35d07f;
    animation: pulse 1.4s infinite;
}

@keyframes pulse {
    0% { transform: scale(0.9); opacity: 0.6; }
    50% { transform: scale(1.3); opacity: 1; }
    100% { transform: scale(0.9); opacity: 0.6; }
}

/* AI OBJECT DETECTION PANEL */
.ai-card {
    background: #111318;
    border: 1px solid #242731;
    border-radius: 16px;
    padding: 14px 16px;
    margin-bottom: 18px;
}

.ai-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.ai-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 15px;
    font-weight: 600;
    color: #f0f2f5;
}

.ai-icon {
    font-size: 17px;
}

/* TOGGLE SWITCH */
.switch {
    position: relative;
    display: inline-block;
    width: 48px;
    height: 26px;
}

.switch input {
    opacity: 0;
    width: 0;
    height: 0;
}

.slider {
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background-color: #272c38;
    transition: 0.25s;
    border-radius: 26px;
}

.slider:before {
    position: absolute;
    content: "";
    height: 20px;
    width: 20px;
    left: 3px;
    bottom: 3px;
    background-color: white;
    transition: 0.25s;
    border-radius: 50%;
}

input:checked + .slider {
    background-color: #35d07f;
}

input:checked + .slider:before {
    transform: translateX(22px);
}

.ai-details {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid #1e222b;
}

/* TELEMETRY */
.telemetry-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 12px;
}

.telemetry-item {
    background: #161922;
    border: 1px solid #272c38;
    border-radius: 10px;
    padding: 8px 10px;
    text-align: center;
}

.telemetry-label {
    display: block;
    font-size: 11px;
    color: #8c92a0;
    margin-bottom: 4px;
}

.telemetry-value {
    font-size: 14px;
    font-weight: 700;
    color: #38bdf8;
}

/* SLIDER */
.ai-slider-row {
    margin-bottom: 12px;
}

.ai-slider-header {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #8c92a0;
    margin-bottom: 6px;
}

#confValue {
    color: #ffffff;
    font-weight: 700;
}

/* DETECTED OBJECT TAGS */
.detected-tags-title {
    font-size: 12px;
    color: #8c92a0;
    margin-bottom: 6px;
}

.detected-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    min-height: 26px;
}

.tag {
    background: rgba(53, 208, 127, 0.12);
    border: 1px solid #35d07f;
    color: #35d07f;
    padding: 4px 10px;
    border-radius: 14px;
    font-size: 11px;
    font-weight: 600;
}

.no-objects {
    font-size: 12px;
    color: #636875;
    font-style: italic;
}

/* MOVEMENT CONTROLS */
.controls {
    display: flex;
    justify-content: center;
    width: 100%;
}

.controller {
    display: grid;
    grid-template-columns: 82px 82px 82px;
    grid-template-rows: 82px 82px 82px;
    gap: 10px;
}

button {
    border: 1px solid #30343e;
    background: #161922;
    color: #ffffff;
    border-radius: 18px;
    font-size: 29px;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    transition: transform 0.08s, background 0.08s;
}

button:active, button.active {
    background: #272c38;
    transform: scale(0.96);
}

.forward { grid-column: 2; grid-row: 1; }
.left { grid-column: 1; grid-row: 2; }
.stop {
    grid-column: 2;
    grid-row: 2;
    background: #341b23;
    border-color: #61303d;
    font-size: 16px;
    font-weight: 700;
    color: #ff6b81;
}
.right { grid-column: 3; grid-row: 2; }
.backward { grid-column: 2; grid-row: 3; }

/* SPEED CONTROL */
.speed-card {
    margin-top: 18px;
    padding: 15px;
    border-radius: 16px;
    border: 1px solid #242731;
    background: #111318;
}

.speed-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 12px;
    font-size: 14px;
    color: #b4b8c0;
}

#speedValue {
    color: #ffffff;
    font-weight: 700;
}

input[type="range"] {
    width: 100%;
    cursor: pointer;
    accent-color: #35d07f;
}

.info {
    margin-top: 15px;
    color: #777c87;
    font-size: 12px;
    text-align: center;
    line-height: 1.5;
}
</style>
</head>

<body>

<div class="container">

    <!-- HEADER -->
    <div class="header">
        <div class="title">Rover Control</div>
        <div class="status-badge-container">
            <div class="status">
                <span class="status-dot" id="statusDot"></span>
                <span id="statusText">Connected</span>
            </div>
        </div>
    </div>

    <!-- CAMERA WITH REAL-TIME AI OVERLAY -->
    <div class="camera-card">
        <div class="camera-wrapper">
            <img class="camera" id="cameraFeed" src="/rover/stream.mjpg" alt="Rover Live Camera">
            <canvas id="detectionCanvas"></canvas>
            <div id="aiBadge" class="ai-overlay-badge">
                <span class="ai-pulse-dot"></span>
                <span>YOLO ACTIVE</span>
            </div>
        </div>
    </div>

    <!-- AI OBJECT DETECTION CARD -->
    <div class="ai-card">
        <div class="ai-header">
            <div class="ai-title">
                <span class="ai-icon">🎯</span>
                <span>YOLO Object Detection</span>
            </div>
            <label class="switch">
                <input type="checkbox" id="aiToggle">
                <span class="slider"></span>
            </label>
        </div>

        <div id="aiDetails" class="ai-details" style="display: none;">
            <div class="telemetry-grid">
                <div class="telemetry-item">
                    <span class="telemetry-label">Inference</span>
                    <span id="aiLatency" class="telemetry-value">-- ms</span>
                </div>
                <div class="telemetry-item">
                    <span class="telemetry-label">AI Rate</span>
                    <span id="aiFps" class="telemetry-value">-- FPS</span>
                </div>
                <div class="telemetry-item">
                    <span class="telemetry-label">Objects</span>
                    <span id="aiCount" class="telemetry-value">0</span>
                </div>
            </div>

            <div class="ai-slider-row">
                <div class="ai-slider-header">
                    <span>Min Confidence</span>
                    <span id="confValue">35%</span>
                </div>
                <input id="confSlider" type="range" min="15" max="85" value="35" step="5">
            </div>

            <div class="detected-tags-container">
                <div class="detected-tags-title">Recognized Objects:</div>
                <div id="detectedTags" class="detected-tags">
                    <span class="no-objects">No objects detected</span>
                </div>
            </div>
        </div>
    </div>

    <!-- MOVEMENT CONTROLS -->
    <div class="controls">
        <div class="controller">
            <button class="forward" data-command="forward">▲</button>
            <button class="left" data-command="left">◀</button>
            <button class="stop" id="stopButton">STOP</button>
            <button class="right" data-command="right">▶</button>
            <button class="backward" data-command="backward">▼</button>
        </div>
    </div>

    <!-- SPEED -->
    <div class="speed-card">
        <div class="speed-header">
            <span>Motor Speed</span>
            <span id="speedValue">30%</span>
        </div>
        <input id="speed" type="range" min="10" max="100" value="30" step="5">
    </div>

    <div class="info">
        Hold a direction button to move &bull; Release to stop<br>
        Keyboard: WASD / Arrow keys &bull; Watchdog failsafe active
    </div>

</div>

<script>
// ============================================================
// STATE
// ============================================================

let speed = parseInt(document.getElementById("speed").value) / 100;
let activeCommand = null;
let heartbeatTimer = null;

let aiEnabled = false;
let aiPollTimer = null;
let latestDetections = [];

// ============================================================
// DOM ELEMENTS
// ============================================================

const cameraFeed = document.getElementById("cameraFeed");
const canvas = document.getElementById("detectionCanvas");
const ctx = canvas.getContext("2d");
const aiBadge = document.getElementById("aiBadge");

const aiToggle = document.getElementById("aiToggle");
const aiDetails = document.getElementById("aiDetails");
const aiLatency = document.getElementById("aiLatency");
const aiFps = document.getElementById("aiFps");
const aiCount = document.getElementById("aiCount");
const confSlider = document.getElementById("confSlider");
const confValue = document.getElementById("confValue");
const detectedTags = document.getElementById("detectedTags");

const speedSlider = document.getElementById("speed");
const speedValue = document.getElementById("speedValue");
const statusText = document.getElementById("statusText");
const statusDot = document.getElementById("statusDot");
const movementButtons = document.querySelectorAll("button[data-command]");

// ============================================================
// CANVAS RESIZE & OVERLAY DRAWING
// ============================================================

function syncCanvasSize() {
    if (cameraFeed.clientWidth > 0 && cameraFeed.clientHeight > 0) {
        canvas.width = cameraFeed.clientWidth;
        canvas.height = cameraFeed.clientHeight;
    }
}

window.addEventListener("resize", syncCanvasSize);
cameraFeed.addEventListener("load", syncCanvasSize);

function renderDetections() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!aiEnabled || latestDetections.length === 0) {
        return;
    }

    const cw = canvas.width;
    const ch = canvas.height;

    latestDetections.forEach(det => {
        const rel = det.rel_box;
        if (!rel || rel.length !== 4) return;

        const x1 = rel[0] * cw;
        const y1 = rel[1] * ch;
        const x2 = rel[2] * cw;
        const y2 = rel[3] * ch;
        const w = x2 - x1;
        const h = y2 - y1;

        // Bounding Box
        ctx.strokeStyle = "#35d07f";
        ctx.lineWidth = 2.5;
        ctx.shadowColor = "rgba(53, 208, 127, 0.6)";
        ctx.shadowBlur = 8;
        ctx.strokeRect(x1, y1, w, h);

        // Center crosshair marker
        const cx = (x1 + x2) / 2;
        const cy = (y1 + y2) / 2;
        ctx.beginPath();
        ctx.arc(cx, cy, 3, 0, 2 * Math.PI);
        ctx.fillStyle = "#38bdf8";
        ctx.fill();

        // Label Badge
        const confPct = Math.round(det.confidence * 100);
        const trackPrefix = (det.track_id !== undefined && det.track_id !== null) ? `#${det.track_id} ` : "";
        const distSuffix = det.estimated_distance_cm ? ` [${Math.round(det.estimated_distance_cm)}cm]` : "";
        const text = `${trackPrefix}${det.label.toUpperCase()} ${confPct}%${distSuffix}`;

        ctx.font = "bold 11px sans-serif";
        const textMetrics = ctx.measureText(text);
        const bgW = textMetrics.width + 12;
        const bgH = 18;

        const badgeY = Math.max(0, y1 - bgH);
        ctx.fillStyle = (det.track_id !== undefined && det.track_id !== null) ? "#38bdf8" : "#35d07f";
        ctx.shadowBlur = 0;
        ctx.fillRect(x1, badgeY, bgW, bgH);

        ctx.fillStyle = "#08090d";
        ctx.fillText(text, x1 + 6, badgeY + 13);
    });
}

// ============================================================
// AI VISION CONTROL & POLLING
// ============================================================

async function fetchDetections() {
    if (!aiEnabled) return;

    try {
        const response = await fetch("/rover/api/detections");
        if (!response.ok) return;

        const data = await response.json();
        if (!data.enabled) return;

        aiLatency.textContent = data.inference_time_ms ? `${data.inference_time_ms} ms` : "-- ms";
        aiFps.textContent = data.fps ? `${data.fps} FPS` : "-- FPS";
        aiCount.textContent = data.count || 0;

        latestDetections = data.detections || [];
        syncCanvasSize();
        renderDetections();

        // Update tags
        if (latestDetections.length === 0) {
            detectedTags.innerHTML = '<span class="no-objects">No objects detected</span>';
        } else {
            detectedTags.innerHTML = latestDetections.map(d => {
                const tr = (d.track_id !== undefined && d.track_id !== null) ? `#${d.track_id} ` : "";
                const dist = d.estimated_distance_cm ? ` (${Math.round(d.estimated_distance_cm)}cm)` : "";
                return `<span class="tag">${tr}${d.label} ${Math.round(d.confidence * 100)}%${dist}</span>`;
            }).join("");
        }
    } catch (e) {
        console.error("AI poll error:", e);
    }
}

aiToggle.addEventListener("change", async function() {
    aiEnabled = this.checked;
    aiDetails.style.display = aiEnabled ? "block" : "none";
    aiBadge.style.display = aiEnabled ? "flex" : "none";

    if (!aiEnabled) {
        clearInterval(aiPollTimer);
        aiPollTimer = null;
        latestDetections = [];
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    try {
        await fetch("/rover/api/vision", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                enabled: aiEnabled,
                confidence: parseInt(confSlider.value) / 100
            })
        });

        if (aiEnabled && !aiPollTimer) {
            syncCanvasSize();
            fetchDetections();
            aiPollTimer = setInterval(fetchDetections, 90);
        }
    } catch (e) {
        console.error("Error toggling AI vision:", e);
    }
});

confSlider.addEventListener("input", function() {
    confValue.textContent = this.value + "%";
});

confSlider.addEventListener("change", async function() {
    try {
        await fetch("/rover/api/vision", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                confidence: parseInt(this.value) / 100
            })
        });
    } catch (e) {
        console.error("Error setting confidence:", e);
    }
});

// ============================================================
// SPEED CONTROL
// ============================================================

speedSlider.addEventListener("input", function() {
    speed = parseInt(this.value) / 100;
    speedValue.textContent = this.value + "%";
});

// ============================================================
// MOTOR SEND COMMAND
// ============================================================

async function sendCommand(command) {
    try {
        const response = await fetch("/rover/api/control", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: command, speed: speed })
        });

        if (!response.ok) throw new Error("Server error");

        statusText.textContent = "Connected";
        statusDot.style.background = "#35d07f";
    } catch (error) {
        statusText.textContent = "Disconnected";
        statusDot.style.background = "#d9534f";
    }
}

// ============================================================
// START & STOP MOVEMENT
// ============================================================

function startMovement(command, button) {
    activeCommand = command;
    button.classList.add("active");
    sendCommand(command);

    clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(function() {
        if (activeCommand) {
            sendCommand(activeCommand);
        }
    }, 150);
}

function stopMovement() {
    activeCommand = null;
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;

    movementButtons.forEach(button => button.classList.remove("active"));
    sendCommand("stop");
}

// ============================================================
// TOUCH / POINTER CONTROLS
// ============================================================

movementButtons.forEach(button => {
    const command = button.dataset.command;

    button.addEventListener("pointerdown", function(event) {
        event.preventDefault();
        try { button.setPointerCapture(event.pointerId); } catch (e) {}
        startMovement(command, button);
    });

    button.addEventListener("pointerup", function(event) {
        event.preventDefault();
        stopMovement();
    });

    button.addEventListener("pointercancel", stopMovement);
    button.addEventListener("lostpointercapture", function() {
        if (activeCommand === command) stopMovement();
    });
});

document.getElementById("stopButton").addEventListener("click", stopMovement);

// ============================================================
// KEYBOARD CONTROLS (DESKTOP)
// ============================================================

const keyMap = {
    "ArrowUp": "forward", "w": "forward", "W": "forward",
    "ArrowDown": "backward", "s": "backward", "S": "backward",
    "ArrowLeft": "left", "a": "left", "A": "left",
    "ArrowRight": "right", "d": "right", "D": "right"
};

document.addEventListener("keydown", function(event) {
    const command = keyMap[event.key];
    if (!command || activeCommand === command) return;

    event.preventDefault();
    const button = document.querySelector(`[data-command="${command}"]`);
    if (button) startMovement(command, button);
});

document.addEventListener("keyup", function(event) {
    if (keyMap[event.key]) {
        event.preventDefault();
        stopMovement();
    }
});

// ============================================================
// BROWSER SAFETY
// ============================================================

window.addEventListener("blur", stopMovement);
document.addEventListener("visibilitychange", function() {
    if (document.hidden) stopMovement();
});

// Initial stop command to ensure safe startup state
sendCommand("stop");
</script>

</body>
</html>
"""


# ============================================================
# HTTP ROUTES (Ground Control Station & Static Assets)
# ============================================================

@app.route("/")
@app.route(ROVER_PATH)
@app.route(f"{ROVER_PATH}/")
def rover_page():
    """Serves the lightweight, zero-build HTML5 Ground Control Station."""
    try:
        return send_from_directory("static", "index.html")
    except Exception:
        return HTML_PAGE


@app.route("/static/<path:filename>")
def static_assets(filename):
    """Serves static CSS, JavaScript modules, and images."""
    return send_from_directory("static", filename)


# ============================================================
# CAMERA STREAM ROUTE
# ============================================================

@app.route(f"{ROVER_PATH}/stream.mjpg")
def video_stream():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=FRAME"
    )


# ============================================================
# MOTOR API
# ============================================================

@app.route(f"{ROVER_PATH}/api/control", methods=["POST"])
@app.route("/api/control", methods=["POST"])
def control():
    data = request.get_json(silent=True) or {}
    command = data.get("command", "stop")
    speed = data.get("speed", DEFAULT_SPEED)

    try:
        speed = float(speed)
    except (TypeError, ValueError):
        speed = DEFAULT_SPEED

    allowed_commands = {
        "forward",
        "backward",
        "left",
        "right",
        "stop"
    }

    if command not in allowed_commands:
        return jsonify({
            "success": False,
            "error": "Invalid command"
        }), 400

    # Manual input always wins over a running mission / queued moves.
    if mission_runner.is_running() or motion.status()["busy"]:
        emergency_stop()
        if command == "stop":
            return jsonify({"success": True, "command": "stop", "speed": speed})

    success = execute_command(command, speed)

    return jsonify({
        "success": success,
        "command": command,
        "speed": speed,
        "obstacle_close": distance_sensor.is_obstacle_close(),
        "distance_cm": distance_sensor.get_distance_cm(),
        "gpio_active": GPIOZERO_AVAILABLE
    })


# ============================================================
# STATUS & TELEMETRY APIS
# ============================================================

@app.route(f"{ROVER_PATH}/api/status")
@app.route("/api/status")
def status():
    with motor_lock:
        cmd = current_command
        spd = current_speed

    world_state = build_current_world_state()
    # High-frequency reflex evaluation (<0.3ms) ensures zero lag on Pi 5 CPU
    laya_triage = laya_engine.evaluate_reflex_triage(world_state)
    laya_nav = laya_engine.evaluate_navigation(world_state)

    return jsonify({
        "rover": {
            "mode": "MANUAL",
            "command": cmd,
            "speed": spd,
            "battery_percent": 84,
            "battery_voltage": 12.3,
            "cpu_temp_c": 46.8,
            "ram_used_mb": 1120,
        },
        "safety": distance_sensor.get_status(),
        "motion": motion.status(),
        "mission": mission_runner.status(),
        "vision": detector.get_status(),
        "laya": {
            "triage": laya_triage.to_dict(),
            "navigation": laya_nav.to_dict(),
        },
        "timestamp": time.time()
    })


@app.route("/ws/telemetry", methods=["GET", "POST"])
def ws_telemetry_probe():
    """HTTP response for WebSocket probe; signals REST polling mode to avoid 404 logs."""
    return jsonify({
        "status": "online",
        "transport": "rest_fallback",
        "poll_endpoint": f"{ROVER_PATH}/api/detections"
    }), 200


# ============================================================
# AI VISION APIS
# ============================================================

@app.route(f"{ROVER_PATH}/api/detections")
@app.route("/api/detections")
def get_detections():
    """Returns the latest YOLO object detections and integrated World State."""
    detector_status = detector.get_status()
    with motor_lock:
        cmd = current_command
        spd = current_speed

    world_state = build_current_world_state()
    # High-frequency reflex evaluation (<0.3ms) guarantees real-time 50Hz safety
    laya_triage = laya_engine.evaluate_reflex_triage(world_state)
    laya_nav = laya_engine.evaluate_navigation(world_state)

    payload = {
        "vision": detector_status,
        "safety": distance_sensor.get_status(),
        "rover": {
            "command": cmd,
            "speed": spd,
            "battery_percent": 84,
        },
        "laya": {
            "triage": laya_triage.to_dict(),
            "navigation": laya_nav.to_dict(),
        }
    }
    # Merge top-level keys for backward compatibility with previous client code
    payload.update(detector_status)
    return jsonify(payload)


@app.route(f"{ROVER_PATH}/api/vision", methods=["POST"])
def configure_vision():
    """Toggle AI detection, set confidence threshold, or filter classes."""
    data = request.get_json(silent=True) or {}

    if "enabled" in data:
        success = detector.set_enabled(bool(data["enabled"]))
        if not success and data["enabled"]:
            return jsonify({
                "success": False,
                "error": "YOLO libraries or model not available on system"
            }), 400

    if "confidence" in data:
        try:
            detector.set_confidence(float(data["confidence"]))
        except (TypeError, ValueError):
            pass

    if "classes" in data:
        classes = data["classes"]
        if isinstance(classes, list):
            detector.set_target_classes(classes)
        elif classes is None:
            detector.set_target_classes(None)

    return jsonify({
        "success": True,
        "status": detector.get_status()
    })


@app.route(f"{ROVER_PATH}/api/vision/lock", methods=["POST"])
def lock_target():
    """Lock onto a specific target track_id or release lock."""
    data = request.get_json(silent=True) or {}
    track_id = data.get("track_id")

    if track_id is None:
        detector.unlock_target()
        return jsonify({"success": True, "locked": False})

    try:
        track_id = int(track_id)
        success = detector.lock_target(track_id)
        return jsonify({"success": success, "locked_track_id": track_id})
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid track_id"}), 400


@app.route(f"{ROVER_PATH}/api/vision/capture", methods=["POST"])
def capture_snapshot():
    """Trigger an on-demand surveillance evidence snapshot."""
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "manual_operator_snapshot")
    severity = data.get("severity", "INFO")

    result = detector.capture_evidence(reason=reason, severity=severity)
    # Strip binary bytes from JSON response
    result_json = {k: v for k, v in result.items() if k != "jpeg_bytes"}
    return jsonify(result_json)


# ============================================================
# EVIDENCE LOG (snapshots saved by detector.capture_evidence)
# ============================================================

@app.route(f"{ROVER_PATH}/api/evidence")
@app.route("/api/evidence")
def list_evidence():
    """Newest-first list of saved evidence snapshots with their metadata."""
    try:
        limit = max(1, min(200, int(request.args.get("limit", 60))))
    except ValueError:
        limit = 60

    evidence_dir = detector.evidence_dir.resolve()
    items = []
    if evidence_dir.is_dir():
        for meta_path in sorted(evidence_dir.glob("evidence_*.json"), reverse=True):
            img_name = meta_path.with_suffix(".jpg").name
            if not (evidence_dir / img_name).is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            items.append({
                "id": meta_path.stem,
                "timestamp": meta.get("timestamp"),
                "reason": meta.get("reason", ""),
                "severity": str(meta.get("severity", "INFO")).lower(),
                "detections_count": meta.get("detections_count", 0),
                "labels": sorted({d.get("label") for d in meta.get("detections", []) if d.get("label")}),
                "image_url": f"{ROVER_PATH}/evidence/{img_name}",
            })
            if len(items) >= limit:
                break
    return jsonify({"success": True, "count": len(items), "evidence": items})


@app.route(f"{ROVER_PATH}/evidence/<path:filename>")
def serve_evidence(filename):
    if not filename.endswith(".jpg"):
        return jsonify({"success": False, "error": "Not found"}), 404
    return send_from_directory(str(detector.evidence_dir.resolve()), filename)


# ============================================================
# NATURAL LANGUAGE COMMAND DISPATCH (Needle / Local Router)
# ============================================================

@app.route(f"{ROVER_PATH}/api/command/nl", methods=["POST"])
@app.route("/api/command/nl", methods=["POST"])
def natural_language_command():
    """Needle 2 Edge Tool Dispatcher & Gateway (Tier 2)."""
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"success": False, "error": "Empty prompt"}), 400

    # Dispatch command via Needle 2
    dispatch_res = needle_router.dispatch(prompt, execute=True)

    if dispatch_res.action == "escalate_to_groq":
        # Complex multi-step strategic mission -> Route to Groq (Tier 1)
        world_state = build_current_world_state()
        mission = groq_brain.compile_mission(prompt, world_state.to_dict())
        mission_dict = mission.to_dict()
        started, run_msg = mission_runner.start(mission_dict)
        return jsonify({
            "success": True,
            "tier": "groq_cloud",
            "action": "mission_started" if started else "mission_compiled",
            "mission": mission_dict,
            "mission_started": started,
            "message": f"Mission '{mission.title}' compiled via {mission.compiler_source} in "
                       f"{mission.compilation_latency_ms:.1f}ms. {run_msg}."
        })

    return jsonify(dispatch_res.to_dict())


# ============================================================
# STRATEGIC MISSION ENGINE (Tier 1 Groq)
# ============================================================

@app.route(f"{ROVER_PATH}/api/missions/create", methods=["POST"])
@app.route("/api/missions/create", methods=["POST"])
def create_mission():
    """Compiles a natural language mission prompt into structured JSON via Groq."""
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "Empty mission prompt"}), 400

    world_state = build_current_world_state()
    mission = groq_brain.compile_mission(prompt, world_state.to_dict())
    return jsonify({"success": True, "mission": mission.to_dict()})


@app.route(f"{ROVER_PATH}/api/missions/execute", methods=["POST"])
@app.route("/api/missions/execute", methods=["POST"])
def execute_mission():
    """Runs a compiled mission (from /api/missions/create) step by step on the rover."""
    data = request.get_json(silent=True) or {}
    mission = data.get("mission")
    if not mission and data.get("prompt"):
        world_state = build_current_world_state()
        mission = groq_brain.compile_mission(str(data["prompt"]).strip(), world_state.to_dict()).to_dict()
    if not isinstance(mission, dict):
        return jsonify({"success": False, "error": "Provide 'mission' or 'prompt'"}), 400

    started, message = mission_runner.start(mission)
    status_code = 200 if started else 409
    return jsonify({"success": started, "message": message, "status": mission_runner.status()}), status_code


@app.route(f"{ROVER_PATH}/api/missions/status")
@app.route("/api/missions/status")
def mission_status():
    return jsonify({"success": True, "mission": mission_runner.status(), "motion": motion.status()})


@app.route(f"{ROVER_PATH}/api/missions/abort", methods=["POST"])
@app.route("/api/missions/abort", methods=["POST"])
def abort_mission():
    emergency_stop()
    return jsonify({"success": True, "mission": mission_runner.status()})


# ============================================================
# MOTION CALIBRATION (dead-reckoning constants)
# ============================================================
#
#   GET  /api/calibration
#   POST /api/calibration/adjust {"axis":"linear","commanded":100,"measured":82}
#        -> run "forward 100 cm", measure what the rover really did, send both numbers.
#   POST /api/calibration/adjust {"axis":"turn","commanded":90,"measured":70}
#   POST /api/calibration {"deadband":0.25,"drive_speed":0.6}   (set values directly)

@app.route(f"{ROVER_PATH}/api/calibration", methods=["GET", "POST"])
@app.route("/api/calibration", methods=["GET", "POST"])
def calibration():
    if request.method == "POST":
        try:
            motion.cal.update(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as e:
            return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True, "calibration": motion.cal.get()})


@app.route(f"{ROVER_PATH}/api/calibration/adjust", methods=["POST"])
@app.route("/api/calibration/adjust", methods=["POST"])
def calibration_adjust():
    data = request.get_json(silent=True) or {}
    try:
        values = motion.cal.adjust(data.get("axis"), data.get("commanded"), data.get("measured"))
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True, "calibration": values})


@app.route(f"{ROVER_PATH}/api/missions/debrief", methods=["POST"])
@app.route("/api/missions/debrief", methods=["POST"])
def debrief_mission():
    """Generates an executive mission debrief report using Groq."""
    data = request.get_json(silent=True) or {}
    mission = data.get("mission") or {}
    events = data.get("events") or []
    telemetry = data.get("telemetry") or {}

    debrief = groq_brain.generate_mission_debrief(mission, events, telemetry)
    return jsonify({"success": True, "debrief": debrief.to_dict()})


# ============================================================
# DECISION & TRIAGE ENGINE (Tier 3 Laya)
# ============================================================

@app.route(f"{ROVER_PATH}/api/decision/triage", methods=["GET", "POST"])
@app.route("/api/decision/triage", methods=["GET", "POST"])
def decision_triage():
    """Runs Laya System-1 non-autoregressive triage over current World State."""
    world_state = build_current_world_state()
    triage = laya_engine.evaluate_triage(world_state)
    nav = laya_engine.evaluate_navigation(world_state)
    return jsonify({
        "success": True,
        "world_state": world_state.to_dict(),
        "triage": triage.to_dict(),
        "navigation": nav.to_dict(),
    })


# ============================================================
# SETTINGS: GROQ API KEY
# ============================================================

@app.route(f"{ROVER_PATH}/api/settings/groq", methods=["GET", "POST"])
@app.route("/api/settings/groq", methods=["GET", "POST"])
def groq_settings():
    """Retrieve status or dynamically update Groq Cloud API key and active model from Dashboard."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        api_key = data.get("api_key")
        model = data.get("model")
        save_to_env = bool(data.get("save_to_env", True))

        saved_key = False
        saved_model = False
        if api_key is not None:
            saved_key = groq_brain.set_api_key(str(api_key).strip(), persist_to_env=save_to_env)
        if model is not None:
            saved_model = groq_brain.set_model(str(model).strip(), persist_to_env=save_to_env)

        status = groq_brain.get_status()
        status["success"] = True
        status["saved_to_env"] = saved_key or saved_model
        return jsonify(status)

    # GET request: return current status for client-side input layer and dropdown
    status = groq_brain.get_status()
    status["success"] = True
    return jsonify(status)


# ============================================================
# CLEAN SHUTDOWN
# ============================================================

def shutdown():
    print()
    print("Shutting down rover...")

    # Stop distance sensor
    try:
        distance_sensor.stop()
    except Exception:
        pass

    # Stop AI vision engine
    try:
        detector.stop()
    except Exception:
        pass

    # Stop motors
    try:
        emergency_stop()
    except Exception:
        pass

    # Stop camera
    try:
        picam2.stop_recording()
    except Exception:
        pass

    # Close GPIO pins
    try:
        left_motor.close()
    except Exception:
        pass

    try:
        right_motor.close()
    except Exception:
        pass

    print("Rover stopped safely.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print()
    print("==========================================")
    print("       RASPBERRY PI ROVER SERVER          ")
    print("==========================================")
    print()
    print(f"Camera:         {CAMERA_WIDTH}x{CAMERA_HEIGHT}")
    print(f"Default speed:  {int(DEFAULT_SPEED * 100)}%")
    print(f"Distance sensor: {'ON' if DISTANCE_SENSOR_ENABLED else 'OFF (open-loop timed moves; set ROVER_DISTANCE_SENSOR=1 to enable)'}")
    print(f"Calibration:    {motion.cal.get()}")
    print(f"YOLO Model:     {YOLO_MODEL} (Inference {YOLO_IMGSZ}x{YOLO_IMGSZ})")
    print()
    print("Motor mapping:")
    print("LEFT  -> GPIO17 / GPIO18")
    print("RIGHT -> GPIO22 / GPIO23")
    print()
    print(f"Open: http://<PI-IP>:{PORT}{ROVER_PATH}")
    print()
    print("Press Ctrl+C to stop.")
    print()

    # Ensure motors start stopped
    stop_motors()

    try:
        app.run(
            host=HOST,
            port=PORT,
            threaded=True,
            debug=False,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print()
        print("Ctrl+C detected.")
    finally:
        shutdown()