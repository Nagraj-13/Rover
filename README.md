# EdgeRover — Raspberry Pi 5 AI Rover

An edge-first autonomous and teleoperated 4-wheel drive (4WD) robotic platform powered by a **Raspberry Pi 5**. It bridges real-time **Picamera2** video streaming, dual **IBT-2 (BTS7960)** high-power motor drivers, **VL53L0X Time-of-Flight laser distance safety**, **Ultralytics YOLO object detection with ByteTrack tracking**, and a **lightweight, zero-build HTML5/CSS3/JavaScript Ground Control Station**.

---

## Key Highlights

- **Hardware Acceleration:** Engineered for Raspberry Pi 5 (4GB / 8GB) with quad-core ARM Cortex-A76 processor.
- **Differential Skid-Steer Drive:** Dual IBT-2 (BTS7960) 43A H-bridges controlling 4 geared DC motors with hardware/software PWM speed regulation.
- **Low-Latency Camera Feed:** 720p MJPEG camera stream via the official modern `picamera2` / `libcamera` stack (~30 FPS).
- **Embedded AI Perception:** Real-time YOLO object detection (`yolov8n.pt` / `yolo26n`) running in a decoupled, zero-lag background worker (15–25+ FPS on Pi 5 CPU).
- **Persistent Multi-Object Tracking & Locking:** ByteTrack tracking assigns persistent IDs (`#1`, `#2`) across frames; click or tap on any bounding box to lock target.
- **Monocular Distance Estimation:** Pinhole camera geometry calibrated for Pi Camera 3 estimates object distance in centimeters in real-time.
- **Deterministic Hardware Safety Interceptor:**
  - Front **VL53L0X Time-of-Flight laser sensor** automatically suppresses forward drive commands if an obstacle is within `<30 cm`.
  - Software watchdog automatically stops all motors if network control heartbeat is lost for `>600 ms`.
- **Zero-Dependency Lightweight Web GCS:** Built entirely in Vanilla HTML5, modern cyberpunk glassmorphic CSS3, and ES6+ JavaScript. **Zero Node.js, zero npm, and zero build compilation required** on the Raspberry Pi.
- **In-Browser Audio Alerts:** Web Audio API synthesizer generates procedural proximity warning chirps and security sirens without external audio files.
- **Surveillance Evidence Capture:** Captures high-resolution annotated snapshots with structured JSON metadata for surveillance audits and Telegram alerting.

---

## Documentation Quick Links

| Document | Purpose |
| :--- | :--- |
| **[PRD.md](PRD.md)** | **Product Requirements Document (PRD) & System Architecture Specification.** Full 4-tier hybrid intelligence design, World State schema, and research roadmap. |
| **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)** | Deep architectural history, motor driver pairing, Picamera2 quirks, and design philosophy. |
| **[circuits/README.md](circuits/README.md)** | Hardware wiring index, system schematics, and electrical safety guidelines. |
| **[circuits/gpio_pinout.md](circuits/gpio_pinout.md)** | Full 40-pin Raspberry Pi 5 GPIO mapping and physical-to-BCM pin allocations. |
| **[circuits/motor_driver_wiring.md](circuits/motor_driver_wiring.md)** | IBT-2 (BTS7960) dual motor driver schematics, logic connections, and motor pairing. |
| **[circuits/sensors_and_camera.md](circuits/sensors_and_camera.md)** | Pi Camera 3 CSI ribbon connection and VL53L0X Time-of-Flight I2C setup. |
| **[circuits/power_distribution.md](circuits/power_distribution.md)** | Dual-rail battery architecture, common ground rules, and fuse protection. |

---

## Hardware Bill of Materials (BOM)

| Component | Specification | Quantity |
| :--- | :--- | :---: |
| **Single Board Computer** | Raspberry Pi 5 (4 GB or 8 GB RAM) | 1 |
| **Camera Module** | Raspberry Pi Camera 3 (IMX708, Autofocus) | 1 |
| **Camera Cable** | 22-pin to 15-pin 0.5mm pitch FPC ribbon cable for Pi 5 | 1 |
| **Motor Drivers** | IBT-2 / BTS7960B 43A High-Power H-Bridge Modules | 2 |
| **Drive Motors** | 12V Geared DC Motors (Chassis: 4WD Skid Steer) | 4 |
| **Distance Sensor** | VL53L0X Time-of-Flight (ToF) Laser Distance Sensor | 1 |
| **Motor Power** | 12V Li-ion / 3S LiPo Battery Pack + 15A Inline Fuse | 1 |
| **Logic Power** | 5V 5A USB-C Power Bank or Step-Down Buck Regulator | 1 |

---

## Step-by-Step Raspberry Pi Setup Guide

Follow these steps to set up and run EdgeRover on your Raspberry Pi 5.

### 1. Operating System Preparation

Ensure your Raspberry Pi 5 is running **Raspberry Pi OS (64-bit)** (Debian 12 Bookworm or Debian 13 Trixie).

Update package lists and upgrade system packages:
```bash
sudo apt update && sudo apt full-upgrade -y
```

Enable the **I2C interface** (required for the VL53L0X distance sensor):
```bash
sudo raspi-config
# Navigate to: Interface Options -> I2C -> Enable -> Finish
```

---

### 2. Install System-Level Dependencies

The official Raspberry Pi camera (`picamera2`) and GPIO libraries depend on native system bindings (`libcamera` and `libgpiod`). Install them via `apt`:

```bash
sudo apt install -y \
    python3-picamera2 \
    python3-opencv \
    python3-gpiozero \
    python3-lgpio \
    i2c-tools \
    python3-smbus \
    git
```

---

### 3. Clone the Repository

Clone the project to your home directory:
```bash
cd ~
git clone https://github.com/Nagraj-13/Rover.git
cd Rover
```

---

### 4. Set Up Python Virtual Environment

> [!IMPORTANT]
> Always pass `--system-site-packages` when creating the virtual environment. This allows your virtual environment to seamlessly access the native `picamera2`, `libcamera`, and `opencv` bindings installed by `apt`.

```bash
# Create virtual environment inheriting system packages
python3 -m venv --system-site-packages venv

# Activate the virtual environment
source venv/bin/activate
```

---

### 5. Install Python Packages

> [!TIP]
> The Raspberry Pi 5 uses an ARM64 CPU. Installing the **CPU-only** PyTorch wheel first prevents pip from downloading 3GB+ of unnecessary NVIDIA CUDA binaries (`nvidia_cudnn`, `nvidia_cublas`, etc.):

```bash
# 1. Install lightweight CPU-only PyTorch for ARM64
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2. Install remaining rover packages (Ultralytics YOLO, VL53L0X driver, Flask)
pip install -r requirements.txt
```

---

### 6. Hardware Verification Tests

Run these quick diagnostic commands to verify all connected hardware before launching the server:

#### A. Test Camera Detection
```bash
rpicam-hello --list-cameras
```
*Expected: Detects `imx708` on `CAM/DISP0` (or `CAM/DISP1`).*

#### B. Test VL53L0X Distance Sensor on I2C
```bash
i2cdetect -y 1
```
*Expected: Address `29` appears on the I2C grid.*

#### C. Test Python Libraries & Drivers
```bash
python3 -c "from picamera2 import Picamera2; print('Picamera2 OK')"
python3 -c "from gpiozero import Motor; print('GPIOZero OK')"
python3 -c "from sensors import DistanceSensor; s = DistanceSensor(); s.start(); import time; time.sleep(0.1); print('Distance:', s.get_distance_cm(), 'cm'); s.stop()"
```

#### D. Run the Vision Subsystem Test Suite
```bash
python -u -m vision.test_detector
```
*Expected: Executes the 6-stage test suite validating coordinate normalization, target locking, steering error math, and evidence capture.*

---

### 7. Optional: Optimize YOLO for Maximum Pi 5 Speed (NCNN Export)

To achieve the fastest possible inference (~67ms / 15+ FPS) on the Pi 5's Cortex-A76 CPU, convert the PyTorch model to **NCNN**:
```bash
python -m vision.export --model yolov8n.pt --format ncnn --imgsz 320
```
This automatically exports `yolov8n_ncnn_model` and runs a local benchmark.

---

### 8. Run the Rover Application

Start the server:
```bash
python3 app.py
```

Find your Raspberry Pi's local IP address:
```bash
hostname -I
```

Open a web browser on any phone, tablet, or laptop on the same Wi-Fi network:
```text
http://<YOUR_PI_IP>:8080/
# or
http://<YOUR_PI_IP>:8080/rover
```

---

## Ground Control Station (GCS) User Guide

The dashboard is a single-page application organized into **5 dedicated tabs**:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🛰️ EDGEROVER GCS    ● ONLINE (14ms)      [MODE: MANUAL]     🔊 Audio ON     │
├─────────────────────────────────────────────────────────────────────────────┤
│ [ 📹 Live Teleop ]  [ 📋 Missions ]  [ 🚨 Event Log ]  [ 📊 Sensors ]  [ ⚙️ ]│
├─────────────────────────────────────────┬───────────────────────────────────┤
│                                         │ NATURAL LANGUAGE DISPATCH         │
│   LIVE CAMERA STREAM (720p)             │ ┌───────────────────────────┬───┐ │
│   ┌─────────────────────────────────┐   │ │ "Move forward 2s"         │ ▶ │ │
│   │ [#1 PERSON 94% [140cm]]         │   │ └───────────────────────────┴───┘ │
│   │ ┌──────────────┐                │   ├───────────────────────────────────┤
│   │ │              │                │   │ REAL-TIME TELEMETRY               │
│   │ │              │                │   │ Front Distance:   124 cm [CLEAR]  │
│   │ └──────────────┘                │   │ Battery Level:    84% (12.3V)     │
│   │              (+) Reticle        │   │ Motor Throttle:   [====O====] 35% │
│   └─────────────────────────────────┘   ├───────────────────────────────────┤
│   FPS: 22 FPS | Detections: 1           │ DIRECTIONAL D-PAD                 │
│   [ 📷 Snap Evidence ]                  │                ▲ [W]              │
│                                         │         ◀ [A]  ■ STOP   ▶ [D]     │
│   ⚠️ PROXIMITY ALERT (<30cm)            │                ▼ [S]              │
│                                         ├───────────────────────────────────┤
│                                         │ [ 🛑 EMERGENCY MOTOR STOP (SPACE)]│
└─────────────────────────────────────────┴───────────────────────────────────┘
```

### Tab 1: Live Teleop & Tactical HUD
- **Camera Feed:** Real-time 720p low-latency video.
- **Tactical Canvas HUD:** 
  - Dynamic corner brackets with identification badges (`#1 PERSON 94% [140cm]`).
  - Crosshair reticle and range markers.
  - **Proximity Radar Arc:** Warns in amber at `<60cm` and flashes red at `<30cm`.
  - **Touch-to-Lock Target:** Tap or click on any bounding box to lock target for tracking.
- **Driving Controls:**
  - **Mobile Touch:** Press and hold `▲`, `▼`, `◀`, `▶`. The Pointer Events API (`setPointerCapture`) guarantees motors halt even if your finger slides off the button.
  - **Desktop Keyboard:** `W` (Forward), `S` (Backward), `A` (Left), `D` (Right), `Spacebar` (Emergency Stop).
  - **Speed Throttle:** Adjust motor PWM from 15% to 100% dynamically.
  - **Master E-Stop:** Large red button instantly terminates motor PWM.
- **Natural Language Command Bar:** Type instructions like *"move forward"*, *"turn left"*, *"stop"*, or *"capture photo"*.
- **Snap Evidence:** Manually trigger a high-resolution snapshot with bounding box overlays.

### Tab 2: Missions & Autonomy
- Strategic mission prompt input (e.g., *"Patrol warehouse perimeter. Alert if person detected"*).
- Pre-configured mission chips for quick tactical dispatch.
- Visual waypoint checklist and mission execution progress.

### Tab 3: Event Log & Evidence Gallery
- Chronological stream of surveillance events (`INFO`, `WARNING`, `CRITICAL`).
- Displays timestamps, trigger reason, and thumbnail evidence previews.

### Tab 4: Sensors & System Diagnostics
- **VL53L0X Laser Distance Bar:** Real-time visual gauge showing distance and 30cm cutoff indicator.
- **CPU Thermals:** Raspberry Pi 5 temperature readout with thermal throttling indicator.
- **RAM & Disk Utilization:** Real-time system resource health.
- **12V Drive Battery:** Voltage estimation and charge state.

### Tab 5: Settings & Configuration
- YOLO Object Detection toggle (enables/disables inference thread on the fly).
- Confidence threshold slider (10% to 90%).
- External API keys (Groq API, Telegram Bot Token).

---

## Running as a Background Service (Auto-Start on Boot)

To have the rover start automatically whenever the Raspberry Pi powers on, configure a `systemd` service:

1. Create a service file:
```bash
sudo nano /etc/systemd/system/rover.service
```

2. Paste the following configuration (replace `pi` with your username if different):
```ini
[Unit]
Description=EdgeRover Ground Control & AI Vision Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Rover
ExecStart=/home/pi/Rover/venv/bin/python3 /home/pi/Rover/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rover.service
sudo systemctl start rover.service
```

4. Check the service status and logs:
```bash
sudo systemctl status rover.service
journalctl -u rover.service -f
```

---

## Project Structure

```text
Rover/
├── app.py                      # Main control server, Picamera2 stream, motor API & GCS host
├── requirements.txt            # Python dependencies (Flask, gpiozero, ultralytics, ToF driver)
├── README.md                   # Setup guide and user documentation (this file)
├── PRD.md                      # Comprehensive Product Requirements Document & Architecture
├── PROJECT_CONTEXT.md          # Architectural history, hardware design notes, and philosophy
│
├── static/                     # Lightweight, zero-build Ground Control Station (GCS)
│   ├── index.html              # 5-tab responsive HTML5 dashboard
│   ├── css/
│   │   └── dashboard.css       # Modern cyberpunk glassmorphic CSS3 design system
│   └── js/
│       ├── app.js              # Master GCS controller & tab manager
│       ├── teleop.js           # Touch pointer capture & keyboard (WASD) teleoperation
│       ├── websocket.js        # Real-time WebSocket & REST telemetry client
│       ├── canvas_hud.js       # Tactical canvas bounding-box & touch-to-lock engine
│       └── audio_alerts.js     # Web Audio API procedural warning synthesizer
│
├── vision/                     # YOLO AI perception & multi-object tracking engine
│   ├── __init__.py             # Vision package exports
│   ├── detector.py             # Asynchronous YOLODetector worker with ByteTrack & distance estimation
│   ├── export.py               # Model optimization CLI (PyTorch -> NCNN / ONNX on Pi 5)
│   └── test_detector.py        # 6-stage test & validation suite
│
├── sensors/                    # Hardware sensor drivers
│   ├── __init__.py             # Sensors package exports
│   └── distance.py             # VL53L0X ToF laser distance sensor driver with safety cutoff
│
└── circuits/                   # Complete electrical and wiring schematics
    ├── README.md               # Electrical documentation overview & architecture
    ├── gpio_pinout.md          # Raspberry Pi 5 40-pin GPIO allocation table
    ├── motor_driver_wiring.md  # Dual IBT-2 (BTS7960) motor driver connections
    ├── sensors_and_camera.md   # Pi Camera 3 CSI and VL53L0X ToF I2C schematics
    └── power_distribution.md   # Dual-rail battery power & common ground rules
```

---

## Troubleshooting

### Motors don't move or only click
1. **Obstacle Interceptor Active:** If an object is closer than 30 cm to the front VL53L0X sensor, forward drive is automatically blocked by the safety controller. Check the distance readout on the GCS dashboard. Reverse and turns will still work.
2. **Check Common Ground:** Ensure the 12V battery negative terminal is connected directly to a Raspberry Pi ground pin (Pin 6, 9, 14, or 20).
3. **Check Enable Pins:** Verify that `R_EN` and `L_EN` on both IBT-2 drivers are connected to 5V (Pins 2 and 4).
4. **Check Fuse:** Ensure the 12V motor battery inline fuse is intact.

### Motor turns in reverse
If one side turns backward when driving forward:
- Power down the motor battery and swap the `M+` and `M-` wires on that specific driver terminal.

### Camera initialization fails (`picamera2` error)
- Ensure the ribbon cable is seated firmly with contacts facing the motherboard PCB.
- Verify camera detection with `rpicam-hello --list-cameras`.
- Do not use `MJPEGEncoder(num_buffers=4)` on Raspberry Pi 5. The codebase uses `MJPEGEncoder()`.

### Distance sensor not detected
- Check I2C detection with `i2cdetect -y 1`. Address `0x29` must be present.
- Verify wiring: Pin 1 (3.3V), Pin 3 (SDA), Pin 5 (SCL), Pin 9 (GND).

### "No space left on device" during pip install
By default, pip on ARM64 may attempt to download massive NVIDIA CUDA packages (>3 GB) that are unnecessary on Raspberry Pi.
1. Clear cached downloads:
   ```bash
   pip cache purge
   sudo apt clean
   ```
2. If your SD card partition is not fully expanded:
   ```bash
   sudo raspi-config
   # Advanced Options -> Expand Filesystem -> Finish -> Reboot
   ```
3. Install the CPU-only PyTorch wheel first:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   ```

---

## License

This project is open-source. Feel free to modify and expand for educational, robotics, and research applications.
