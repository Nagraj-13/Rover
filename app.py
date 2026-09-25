#!/usr/bin/env python3

import io
import threading
import time

from flask import Flask, Response, jsonify, request
from gpiozero import Motor

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

from vision import YOLODetector


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

motor_lock = threading.Lock()

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

detector = YOLODetector(
    model_name=YOLO_MODEL,
    conf_threshold=YOLO_DEFAULT_CONF,
    imgsz=YOLO_IMGSZ,
    enabled=False
)
detector.start()


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


# Create camera
picam2 = Picamera2()

# Camera configuration
camera_config = picam2.create_video_configuration(
    main={
        "size": (
            CAMERA_WIDTH,
            CAMERA_HEIGHT
        )
    }
)
picam2.configure(camera_config)

# Shared stream buffer with detector hook
output = StreamingOutput(vision_detector=detector)

# IMPORTANT: Do NOT use num_buffers here for Raspberry Pi 5 environment
encoder = MJPEGEncoder()

# Start camera recording
picam2.start_recording(
    encoder,
    FileOutput(output)
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
        const text = `${det.label.toUpperCase()} ${confPct}%`;

        ctx.font = "bold 11px sans-serif";
        const textMetrics = ctx.measureText(text);
        const bgW = textMetrics.width + 12;
        const bgH = 18;

        const badgeY = Math.max(0, y1 - bgH);
        ctx.fillStyle = "#35d07f";
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
            detectedTags.innerHTML = latestDetections.map(d =>
                `<span class="tag">${d.label} ${Math.round(d.confidence * 100)}%</span>`
            ).join("");
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
# HTTP ROUTES
# ============================================================

@app.route(ROVER_PATH)
def rover_page():
    return HTML_PAGE


@app.route(f"{ROVER_PATH}/")
def rover_page_slash():
    return HTML_PAGE


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

    execute_command(command, speed)

    return jsonify({
        "success": True,
        "command": command,
        "speed": speed
    })


# ============================================================
# STATUS API
# ============================================================

@app.route(f"{ROVER_PATH}/api/status")
def status():
    with motor_lock:
        return jsonify({
            "command": current_command,
            "speed": current_speed,
            "vision_enabled": detector.is_enabled()
        })


# ============================================================
# AI VISION APIS
# ============================================================

@app.route(f"{ROVER_PATH}/api/detections")
def get_detections():
    """Returns the latest YOLO object detections and telemetry."""
    return jsonify(detector.get_status())


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


# ============================================================
# CLEAN SHUTDOWN
# ============================================================

def shutdown():
    print()
    print("Shutting down rover...")

    # Stop AI vision engine
    try:
        detector.stop()
    except Exception:
        pass

    # Stop motors
    try:
        stop_motors()
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