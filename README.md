# Raspberry Pi 5 AI Rover

An autonomous and teleoperated 4-wheel drive rover powered by a **Raspberry Pi 5**, featuring live **Raspberry Pi Camera 3** video streaming, dual **IBT-2 (BTS7960)** high-power motor drivers, real-time **YOLO object detection**, and a responsive mobile web controller interface.

---

## Key Highlights

- **Hardware Acceleration:** Built for Raspberry Pi 5 (4GB / 8GB) with quad-core ARM Cortex-A76 processor.
- **Differential Drive Control:** Dual IBT-2 (BTS7960) H-bridges controlling 4 geared DC motors with hardware/software PWM speed control.
- **Low-Latency Video:** 720p MJPEG camera stream via the official modern `picamera2` / `libcamera` stack.
- **Real-Time AI Vision:** Real-time YOLO object detection (`yolov8n.pt`) with client-side canvas overlay (15–25+ FPS without video latency).
- **Safety Watchdog:** Hardware failsafe automatically halts motors if network communication drops for >600ms.
- **Mobile-First Web UI:** Zero-install touch controller with hold-to-move pointer capture and desktop keyboard shortcuts (WASD / Arrows).

---

## Documentation Quick Links

| Document | Purpose |
| :--- | :--- |
| **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)** | Deep architectural principles, hardware history, design philosophy, and long-term autonomy roadmaps. |
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

Follow these steps to set up and run the rover software on your Raspberry Pi 5.

### 1. Operating System Preparation

Ensure your Raspberry Pi 5 is running **Raspberry Pi OS (64-bit)** (Debian 12 Bookworm or Debian 13 Trixie).

Update the package lists and upgrade all system packages:
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
> The Raspberry Pi 5 uses an ARM64 CPU (not an NVIDIA CUDA GPU). Installing the **CPU-only** PyTorch wheel first prevents pip from downloading 3GB+ of useless NVIDIA CUDA binaries (`nvidia_cudnn`, `nvidia_cublas`, etc.) that fill up your SD card:

```bash
# 1. Install lightweight CPU-only PyTorch for ARM64
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2. Install remaining rover packages
pip install -r requirements.txt
```

---

### 6. Hardware Verification Tests

Before starting the server, run quick diagnostic tests:

#### A. Test Camera Detection
```bash
rpicam-hello --list-cameras
```
*Expected: Detects `imx708` on `CAM/DISP0`.*

#### B. Test Python Picamera2 & GPIO
```bash
python3 -c "from picamera2 import Picamera2; print('Picamera2 OK')"
python3 -c "from gpiozero import Motor; print('GPIOZero OK')"
```
*Expected: Prints `Picamera2 OK` and `GPIOZero OK`.*

#### C. Test YOLO Vision Module
```bash
python3 -c "from vision import YOLODetector; d = YOLODetector(); print('YOLO Available:', d.get_status()['available'])"
```
*Expected: Prints `YOLO Available: True`.*

---

### 7. Run the Rover Application

Start the control server:
```bash
python3 app.py
```

Find your Raspberry Pi's local IP address:
```bash
hostname -I
```

Open a web browser on any phone, tablet, or laptop connected to the same Wi-Fi network:
```text
http://<YOUR_PI_IP>:8080/rover
```

---

## Web Interface & Controls

```text
┌───────────────────────────────────────────────┐
│ Rover Control                    ● Connected  │
├───────────────────────────────────────────────┤
│                                               │
│                 LIVE CAMERA                   │
│             [ YOLO Canvas Overlay ]           │
│                                               │
├───────────────────────────────────────────────┤
│ 🎯 YOLO Object Detection              [ON/OFF]│
│ Inference: 28 ms | Rate: 22 FPS | Objects: 2  │
│ Recognized: [PERSON 89%] [CUP 74%]            │
├───────────────────────────────────────────────┤
│                      ▲                        │
│                   ◀ STOP ▶                    │
│                      ▼                        │
│                                               │
│ Motor Speed: ────●───────── 30%               │
└───────────────────────────────────────────────┘
```

### Driving Controls
- **Touch / Mobile:** Press and hold any direction button (`▲`, `▼`, `◀`, `▶`) to drive. Releasing the button automatically stops the rover.
- **Desktop Keyboard:**
  - `W` or `Arrow Up`: Drive Forward
  - `S` or `Arrow Down`: Drive Backward
  - `A` or `Arrow Left`: Turn Left (pivot)
  - `D` or `Arrow Right`: Turn Right (pivot)
  - Releasing key stops the rover.
- **Speed Slider:** Adjust motor PWM output dynamically from 10% to 100% (default 30%).
- **Emergency STOP:** Large red button instantly stops both motor drivers.

### YOLO AI Detection
- Toggle the switch on the **YOLO Object Detection** card.
- Live bounding boxes, center crosshairs, and confidence percentages render in real-time on the camera feed.
- Fine-tune detection sensitivity with the **Min Confidence** slider (15% to 85%).

---

## Running as a Background Service (Auto-Start on Boot)

To ensure the rover automatically starts whenever the Raspberry Pi powers on, set up a `systemd` service:

1. Create a service file:
```bash
sudo nano /etc/systemd/system/rover.service
```

2. Paste the following configuration (replace `pi` with your username if different):
```ini
[Unit]
Description=Raspberry Pi 5 AI Rover Control Server
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
├── app.py                      # Main Flask web server, Picamera2 stream, and motor API
├── requirements.txt            # Python dependencies (Flask, gpiozero, ultralytics, etc.)
├── README.md                   # Setup guide and quick start documentation (this file)
├── PROJECT_CONTEXT.md          # Comprehensive architectural and project vision context
│
├── vision/                     # Asynchronous YOLO object detection engine
│   ├── __init__.py             # Vision package init
│   └── detector.py             # Optimized zero-latency YOLODetector worker
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
1. **Check Common Ground:** Ensure the 12V battery negative terminal is connected directly to a Raspberry Pi ground pin (Pin 6 or 14).
2. **Check Enable Pins:** Verify that `R_EN` and `L_EN` on both IBT-2 drivers are connected to 5V (Pins 2 and 4).
3. **Check Fuse:** Ensure the 12V motor battery inline fuse is intact.

### Motor turns in reverse
If one side turns backward when driving forward:
- Turn off motor power and swap the `M+` and `M-` wires on that specific motor or driver terminal.

### Camera initialization fails (`picamera2` error)
- Ensure the ribbon cable is seated firmly with contacts facing the motherboard PCB.
- Verify with `rpicam-hello --list-cameras`.
- Do not use `MJPEGEncoder(num_buffers=4)` on Raspberry Pi 5. The codebase uses `MJPEGEncoder()`.

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
3. Install the CPU-only PyTorch wheel:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   ```

---

## License

This project is open-source. Feel free to modify and expand for educational, robotics, and research applications.
