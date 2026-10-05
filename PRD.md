# EdgeRover — LLM-Assisted Autonomous Surveillance & Inspection Rover
## Product Requirements Document (PRD) & System Architecture Specification

---

## 1. Executive Summary & Vision

**EdgeRover** is an edge-first, intelligent 4-wheel drive (4WD) robotic platform powered by a **Raspberry Pi 5**. It bridges teleoperation, real-time computer vision, local small-language-model (SLM) tool dispatch, deterministic robotics safety, and cloud LLM reasoning into a unified, modular system.

Rather than being a simple "Raspberry Pi car with a camera", EdgeRover is engineered as an **autonomous inspection and surveillance platform** capable of executing high-level natural language objectives, conducting scheduled perimeter patrols, detecting persons/objects, making fast edge decisions, and transmitting telemetry and evidence to a **lightweight, zero-build HTML/CSS/JavaScript web dashboard** and a **Telegram alert channel**.

```text
                                   EDGEROVER SYSTEM
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │                                           │
             MANUAL TELEOP MODE                         AUTONOMOUS MODE
                    │                                           │
          Zero-Latency Web HUD                        Mission Planner / AI
          (HTML5 / Canvas / JS)                       (Patrols, Tracking, Audits)
                    │                                           │
                    └─────────────────────┬─────────────────────┘
                                          │
                                    COMMAND LAYER
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
             Virtual Joystick      Natural Language       Mission Engine
             & Keyboard (WASD)     (Needle / Groq)         (JSON Rules)
                    │                     │                     │
                    └─────────────────────┼─────────────────────┘
                                          ▼
                               COMMAND ROUTER & DISPATCH
                                          ▼
                                    TOOL REGISTRY
                                          ▼
                              SAFETY CONTROLLER (DETERMINISTIC)
                     (Watchdog <600ms, VL53L0X ToF <30cm, Battery Cutoff)
                                          ▼
                                  MOTION CONTROLLER
                                          ▼
                               GPIOZERO / LGPIO DRIVER
                                          ▼
                              DUAL IBT-2 MOTOR DRIVERS
                                          ▼
                                4× 12V GEARED DC MOTORS
```

### Core Value Propositions
1. **Edge-First Autonomy**: Rover operates reliably even if network connectivity drops. Local perception (YOLO) and local decision-making (Needle 2 / Laya) run entirely on the Pi 5.
2. **Quota-Efficient Cloud Reasoning**: Cloud LLM (Groq) is utilized exclusively for strategic mission compilation, incident narration, and post-mission synthesis (2–5 calls per mission), never inside high-frequency motor loops.
3. **Deterministic Safety Guarantees**: Absolute physical boundary checks (obstacle distance, watchdog heartbeat, thermal, and low battery) override all AI commands.
4. **Zero-Dependency Lightweight Frontend**: Eliminates complex frontend frameworks (Next.js, React, Node.js runtime, build pipelines). The Ground Control Station (GCS) is built in pure HTML5, vanilla CSS3, and ES6+ JavaScript, served directly by FastAPI with zero Node overhead on the Raspberry Pi 5.

---

## 2. Cardinal Architecture Rule: Deterministic Decoupling

The most critical architectural principle for EdgeRover is:

```text
❌ FORBIDDEN:   LLM  ──>  Direct GPIO / Motor Pins
✅ MANDATORY:   LLM  ──>  Tool Call  ──>  Controller  ──>  Safety Guard  ──>  Hardware Driver  ──>  Motors
```

### Trace Example:
```text
User Command: "Move forward for 3 seconds at 40% speed"
     │
     ▼
Command Router / Gateway (Needle SLM or Groq LLM)
     │
     ▼
Tool Call Dispatched: move_forward(speed=0.4, duration=3.0)
     │
     ▼
Motion Controller (Validates kinematics, acceleration ramping)
     │
     ▼
Safety Controller (Validates front VL53L0X distance > 30cm, Watchdog OK, Battery > 15%)
     │  ├── IF BLOCKED: Aborts motion, logs obstacle event, raises warning
     │  └── IF CLEAR: Passes command to actuator layer
     ▼
Actuator Driver (GPIOZero Motor interface with hardware/software PWM)
     │
     ▼
IBT-2 H-Bridges (RPWM / LPWM modulation)
     │
     ▼
4WD DC Geared Motors
```

The AI layer **never knows GPIO pin numbers, H-bridge logic, PWM frequencies, or raw hardware registers**. This clean abstraction prevents model hallucinations from causing physical hardware crashes and makes the project robust and academically defensible.

---

## 3. End-to-End System Architecture

```text
                                      OPERATOR
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 │                                               │
     Vanilla HTML5/CSS/JS Dashboard                      Telegram Bot
     (Served directly via FastAPI)                 (Critical Alerts & Reports)
                 │                                               │
                 │ HTTP (MJPEG) / WebSocket (Telemetry & Cmds)   │
                 ▼                                               │
     ┌─────────────────────────────────────────────────────────┐ │
     │                  FASTAPI APPLICATION                    │ │
     │  - REST Endpoints        - Telemetry WebSocket          │ │
     │  - MJPEG Video Streamer  - Static Dashboard Host        │ │
     └───────────────────────────┬─────────────────────────────┘ │
                                 │                               │
        ┌────────────────────────┼────────────────────────┐      │
        │                        │                        │      │
        ▼                        ▼                        ▼      │
   Manual Teleop          Command Gateway            Mission     │
     Handler             (Natural Language)          Manager     │
        │                        │                        │      │
        │                  ┌─────┴─────┐                  │      │
        │                  ▼           ▼                  │      │
        │              Needle 2       Groq                │      │
        │             (Local SLM)  (Cloud LLM)            │      │
        │                  │           │                  │      │
        └──────────────────┼───────────┴──────────────────┘      │
                           │                                     │
                           ▼                                     │
                    TOOL REGISTRY ◄──────────────────────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
  Navigation          Perception          Mission Ops
  (Move, Turn,        (Ultralytics        (Snapshots, Events,
   RTH, Patrol)        YOLO26n/v8n)        Reports, Logging)
       │                   │                   │
       │                   ▼                   │
       │            WORLD STATE BLACKBOARD     │
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
                  LAYA DECISION ENGINE
             (Fast probabilistic/rule triage)
                           ▼
               SAFETY CONTROLLER WATCHDOG
         (Distance <30cm, Heartbeat <600ms, Batt)
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
    IBT-2 Drivers     VL53L0X ToF        SQLite DB
      & Motors          & MPU6050       (Telemetry,
        │                  │           Missions, Events)
  4WD DC Motors       I2C Bus (Pins 3,5)
```

---

## 4. The 4-Tier Hybrid Intelligence Stack

EdgeRover implements four complementary layers of intelligence, each operating at its optimal compute envelope:

| Intelligence Layer | Component / Model | Execution Target | Latency | Primary Responsibility |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Cloud Reasoning** | **Groq API** (`llama-3.3-70b-versatile` / `gpt-oss-20b`) | Cloud LPUs via HTTPS | ~300–600 ms | Complex mission planning, ambiguity resolution, long-form natural language reporting, and incident root-cause analysis. |
| **Tier 2: Edge Tool Calling** | **Needle 2** (Cactus Compute 45M SLM) | Local Pi 5 CPU (14 MB binary) | ~20–50 ms | Instant natural language command translation to tool calls ("stop", "turn right", "scan room") without cloud connectivity. |
| **Tier 3: Decision Engine** | **Laya** (Typed decision evaluator) | Local Pi 5 ONNX Runtime | ~5–15 ms | High-speed System-1 decisions (Choice, Score, Noul/Boolean) based on current World State. |
| **Tier 4: Visual Perception** | **Ultralytics YOLO26n / YOLOv8n** | Local Pi 5 NCNN / ONNX | ~40–70 ms (15–25 FPS) | Object detection (`person`, `backpack`, `vehicle`, `fire`, etc.), bounding box coordinates, and visual confidence scoring. |

### Visual Perception Specification (YOLO26n / YOLOv8n)
- **Model Size**: Ultralytics Nano (optimized for embedded ARM64).
- **Inference Pipeline**: Camera MJPEG frame -> Decoupled non-blocking worker -> Pre-scaled 320×320 / 640×640 frame -> NCNN / ONNX runtime -> Normalized bounding boxes.
- **Client-Side Rendering**: Bounding box coordinates (`[ymin, xmin, ymax, xmax, label, conf]`) are piped over WebSockets and rendered via client-side HTML5 Canvas. The video stream itself remains unmodified raw MJPEG, preserving 30 FPS video latency.

### Local Tool Brain (Needle 2)
- **Binary Footprint**: ~14 MB standalone executable / C-library.
- **Memory Footprint**: ~28 MB peak session RAM on Raspberry Pi 5.
- **Throughput**: ~500 tokens/sec decode on ARM Cortex-A76.
- **Role**: Dispatches direct tool invocations instantly when offline or for real-time natural language controls.

### Strategic Cloud Brain (Groq LLM)
- **Protocol**: HTTPS REST calls using official Groq SDK / OpenAI-compatible endpoint with JSON Schema formatting.
- **Invocation Frequency**: Strictly limited to 2–5 requests per mission:
  1. *Mission Ingestion*: NL user prompt -> Structured Mission JSON.
  2. *Critical Anomaly Review*: When high-severity unexplained event occurs.
  3. *Mission Debrief*: Aggregated event database -> Executive summary report.

---

## 5. Hardware Specifications & Physical Pinout

### System Bill of Materials (BOM)
- **Single Board Computer**: Raspberry Pi 5 (4 GB or 8 GB RAM) running Raspberry Pi OS 64-bit (Debian Trixie / Bookworm, Linux kernel 6.18+).
- **Vision Sensor**: Raspberry Pi Camera 3 (IMX708 sensor, Autofocus, 720p/1080p mode) connected via dedicated 22-pin to 15-pin 0.5mm FPC ribbon cable.
- **Motor Controllers**: 2× IBT-2 (BTS7960B) 43A High-Power H-Bridge motor driver modules.
- **Drive Train**: 4× 12V Geared DC Motors configured in 4WD Skid-Steer / Differential Drive mode (Left side wired in parallel to Driver 1; Right side wired in parallel to Driver 2).
- **Range Finding**: 1× VL53L0X Time-of-Flight (ToF) Laser Distance Sensor (I2C address `0x29`).
- **Inertial Measurement (Future/Phase 2)**: 1× MPU6050 6-Axis IMU (I2C address `0x68`).
- **Power Delivery**: Dual isolated rails:
  - *Logic Rail*: 5V / 5A regulated buck converter or USB-C PD power bank to Raspberry Pi 5.
  - *Motor Rail*: 12V 3S Li-ion / LiPo battery pack with 15A inline fuse and common ground tied to Pi GND.

### Raspberry Pi 5 GPIO Pin Allocation (BCM Numbering)

| BCM Pin | Physical Pin | Direction | Connected Subsystem | Functional Role |
| :--- | :--- | :--- | :--- | :--- |
| **GPIO17** | Pin 11 | Output | Left IBT-2 | Left Motor RPWM (Forward PWM) |
| **GPIO18** | Pin 12 | Output | Left IBT-2 | Left Motor LPWM (Backward PWM) |
| **GPIO22** | Pin 15 | Output | Right IBT-2 | Right Motor RPWM (Forward PWM) |
| **GPIO23** | Pin 16 | Output | Right IBT-2 | Right Motor LPWM (Backward PWM) |
| **GPIO2** | Pin 3 | I/O (I2C1) | VL53L0X / MPU6050 | I2C SDA (Data) |
| **GPIO3** | Pin 5 | Output (I2C1) | VL53L0X / MPU6050 | I2C SCL (Clock) |
| **5V** | Pins 2, 4 | Power | Sensors & Driver Logic | 5V Logic Power Rail |
| **GND** | Pins 6, 9, 14, 20 | Ground | Common Ground | Unified logic and motor ground |

---

## 6. Deterministic Safety Controller & Guardrails

The Safety Controller runs as an independent high-priority thread that enforces hard limits regardless of whether commands originate from manual teleoperation, Needle, Groq, or the Mission Engine.

```text
                               SAFETY WATCHDOG EVALUATION LOOP (100 Hz)
                                                 │
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │ Check 1: Network Heartbeat Timeout    │
                             │ (Has a control ping arrived in 600ms?)│
                             └───────────────────┬───────────────────┘
                                                 │
                                     YES ────────┴──────── NO ──> [HALT MOTORS: WATCHDOG_EXPIRED]
                                     │
                                     ▼
                             ┌───────────────────────────────────────┐
                             │ Check 2: Front Distance (VL53L0X ToF) │
                             │ (Is front obstacle < 30 cm?)          │
                             └───────────────────┬───────────────────┘
                                                 │
                        NO / BACKING ────────────┴──────── YES & FWD ──> [INTERCEPT & STOP: OBSTACLE_NEAR]
                                     │
                                     ▼
                             ┌───────────────────────────────────────┐
                             │ Check 3: Battery Voltage Cutoff       │
                             │ (Is battery level < 15%?)             │
                             └───────────────────┬───────────────────┘
                                                 │
                                     NO ─────────┴──────── YES ──> [ABORT MISSION: FORCE_RTH]
                                     │
                                     ▼
                             ┌───────────────────────────────────────┐
                             │ Check 4: Emergency Stop (E-Stop) State│
                             │ (Has software or physical E-Stop set?)│
                             └───────────────────┬───────────────────┘
                                                 │
                                     NO ─────────┴──────── YES ──> [LOCK MOTORS: ESTOP_ENGAGED]
                                     │
                                     ▼
                               PASS COMMAND TO MOTORS
```

### Safety Rules Summary
1. **Network Watchdog (`WATCHDOG_TIMEOUT = 0.6s`)**: If no command/heartbeat packet arrives from the browser within 600 ms, the watchdog thread automatically sets motor PWM to 0.
2. **Proximity Interceptor (`OBSTACLE_THRESHOLD = 30cm`)**: If the forward distance reported by VL53L0X drops below 30 cm, any forward movement (`forward`, `forward_left`, `forward_right`) is immediately suppressed; reverse and pivot turns remain permitted to allow backing out.
3. **Low Battery Action (`BATT_CRITICAL = 15%`)**: When battery drops below 15%, ongoing autonomous missions are paused, an alert is dispatched, and the rover initiates an emergency Return-to-Base (RTH) sequence.
4. **Emergency Stop (E-Stop)**: Spacebar on keyboard, tapping the master "STOP" HUD button, or calling `/api/rover/stop` unconditionally breaks the circuit loop and engages active braking.

---

## 7. Central World State Schema (Blackboard)

All subsystems (Perception, Navigation, Sensors, AI Planner, Web Telemetry) communicate asynchronously through a centralized, thread-safe blackboard data structure:

```json
{
  "timestamp": 1775043820.145,
  "rover": {
    "mode": "MANUAL",
    "motion_state": "STOPPED",
    "current_speed": 0.35,
    "battery_percent": 84,
    "battery_voltage": 12.3,
    "cpu_temp_c": 47.8,
    "cpu_usage_pct": 28.4,
    "ram_used_mb": 1140,
    "e_stop": false
  },
  "safety": {
    "watchdog_ok": true,
    "obstacle_warning": false,
    "distance_cm": 124,
    "last_heartbeat": 1775043819.950
  },
  "navigation": {
    "heading_deg": 182.4,
    "pitch_deg": 1.2,
    "roll_deg": -0.8,
    "current_waypoint": 2,
    "total_waypoints": 5
  },
  "vision": {
    "fps": 21.4,
    "detector_enabled": true,
    "detections_count": 1,
    "objects": [
      {
        "id": "obj_01",
        "class": "person",
        "confidence": 0.92,
        "bbox": [0.15, 0.42, 0.78, 0.68],
        "estimated_distance_cm": 160
      }
    ]
  },
  "mission": {
    "active": false,
    "mission_id": null,
    "name": "Idle",
    "step_index": 0,
    "total_steps": 0,
    "elapsed_seconds": 0
  }
}
```

---

## 8. Tool Registry & Function Calling Schemas

Both Needle (local) and Groq (cloud) interface with the rover through a strictly typed Tool Registry. Each tool exposes an OpenAPI/JSON Schema signature:

```python
ROVER_TOOLS = [
    # Actuator & Movement Tools
    {
        "name": "move_forward",
        "description": "Drive rover forward a set distance (preferred) or time. Open loop: the controller converts distance to motor-on time from calibration.json",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "minimum": 0.1, "maximum": 1.0},
                "distance_cm": {"type": "number", "minimum": 1.0, "maximum": 5000.0},
                "duration_seconds": {"type": "number", "minimum": 0.1, "maximum": 60.0}
            }
        }
    },
    {
        "name": "move_backward",
        "description": "Drive rover in reverse a set distance (preferred) or time",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "minimum": 0.1, "maximum": 1.0},
                "distance_cm": {"type": "number", "minimum": 1.0, "maximum": 5000.0},
                "duration_seconds": {"type": "number", "minimum": 0.1, "maximum": 30.0}
            }
        }
    },
    {
        "name": "turn_left",
        "description": "Pivot or spin rover to the left",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "default": 0.35},
                "degrees": {"type": "number", "description": "Degrees to pivot in place (default 90); converted to motor-on time"}
            }
        }
    },
    {
        "name": "turn_right",
        "description": "Pivot or spin rover to the right",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "default": 0.35},
                "degrees": {"type": "number", "description": "Optional degrees to turn (approximate)"}
            }
        }
    },
    {
        "name": "stop_rover",
        "description": "Immediately stop all motor motion and hold position",
        "parameters": {"type": "object", "properties": {}}
    },
    # Perception & Evidence Tools
    {
        "name": "capture_evidence",
        "description": "Capture a high-resolution snapshot and record a timestamped surveillance event",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for evidence capture (e.g. 'unauthorized person')"},
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"]}
            },
            "required": ["reason"]
        }
    },
    # Telemetry & State Tools
    {
        "name": "get_rover_telemetry",
        "description": "Retrieve current battery, obstacle distance, camera detections, and location state",
        "parameters": {"type": "object", "properties": {}}
    },
    # Alerting Tools
    {
        "name": "send_telegram_alert",
        "description": "Dispatch a priority alert message with snapshot to Telegram security channel",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "attach_photo": {"type": "boolean", "default": true}
            },
            "required": ["message"]
        }
    }
]
```

---

## 9. Operating Modes Specification

### Mode A: Manual Teleoperation (Zero Latency)
- **Primary Use**: Precision navigation, staging, manual inspection, direct override.
- **Controls**:
  - *Touch UI*: On-screen Directional Touch Pad / Virtual Joystick with Pointer Capture.
  - *Desktop Keyboard*: `W`/`Up` (Forward), `S`/`Down` (Backward), `A`/`Left` (Spin Left), `D`/`Right` (Spin Right), `Spacebar`/`X` (Emergency Stop).
  - *Speed Slider*: Linear hardware throttle from 15% to 100%.
  - *Camera Stream*: Real-time 720p MJPEG stream at ~30 FPS with responsive canvas overlay.

### Mode B: Semi-Autonomous Natural Language Control
- **Primary Use**: High-level tactical commands given via typed or voice prompt.
- **Examples**:
  - *"Turn right 90 degrees and move forward 2 meters."*
  - *"Back up slowly until distance is greater than 100 cm."*
  - *"Scan the room and tell me if you see a person."*
- **Execution Flow**:
  1. User enters text in Dashboard command prompt.
  2. Gateway checks command complexity:
     - **Simple Tool Dispatch**: Needle 2 interprets directly in <50ms -> calls tool.
     - **Complex/Multi-step Task**: Sent to Groq -> decompiled into step array.
  3. Steps execute sequentially with safety validation between each step.

### Mode C: Fully Autonomous Mission Mode
- **Primary Use**: Scheduled perimeter patrols, intrusion detection, night-shift facility audits.
- **Lifecycle**:
  ```text
  [ MISSION SUBMISSION ] ──> Groq parses NL into JSON Mission Spec
           │
           ▼
  [ PRE-FLIGHT CHECKS  ] ──> Battery > 30%? Sensors online? Camera active?
           │
           ▼
  [ PATROL EXECUTION   ] ──> Sequentially traverses waypoints / search grids
           │
     ┌─────┴──────────────────────────────────┐
     ▼                                        ▼
  [ NORMAL PATROL ]                   [ OBJECT / ANOMALY DETECTED ]
  Perceive, update state,             Laya evaluates event severity
  log waypoint progress.              ├── INFO: Record in DB, continue
                                      ├── WARNING: Pause, capture snapshot, audit
                                      └── CRITICAL: Lock camera, snap photo,
                                          alert Telegram, sound warning
     │                                        │
     └─────────────────┬──────────────────────┘
                       ▼
  [ POST-MISSION SYNTHESIS ] ──> Rover returns to base dock
                                 Event DB aggregated -> Groq writes debrief summary
                                 Summary sent to Dashboard & Telegram
  ```

---

## 10. Lightweight Frontend Architecture (HTML5 + CSS3 + Vanilla JS)

### Design Philosophy
Unlike heavy single-page application (SPA) frameworks like Next.js or React that require a Node.js runtime, gigabytes of `node_modules`, complex bundling steps, and hydration delays, EdgeRover's Ground Control Station (GCS) is built in **standard-compliant Vanilla HTML5, CSS3, and ES6+ JavaScript**.

### Key Frontend Advantages:
1. **Zero Node.js Dependency on Raspberry Pi**: The entire dashboard is served directly by FastAPI via `StaticFiles` or inline routes. Zero CPU or RAM overhead on the Pi.
2. **Instant Boot**: 0.05-second page load time; zero build compilation required.
3. **Zero-Latency Teleoperation**: Direct native WebSocket connection with sub-10ms packet transmission.
4. **Hardware-Accelerated Canvas Overlay**: Dynamic HUD bounding boxes rendered via `<canvas>` directly on top of the MJPEG stream at native display refresh rates.
5. **Universal Compatibility**: Works flawlessly across mobile Safari (iOS), Chrome (Android), Firefox, and desktop browsers without platform-specific wrappers.

### Directory Structure
```text
d:\Rover\
├── static/
│   ├── index.html          # Core single-page Ground Control Station layout
│   ├── css/
│   │   └── dashboard.css   # Modern dark-mode glassmorphic design system
│   └── js/
│       ├── app.js          # Master controller & tab manager
│       ├── teleop.js       # Touch pointer events, virtual joystick & keyboard bindings
│       ├── websocket.js    # Bi-directional WebSocket telemetry & command client
│       ├── canvas_hud.js   # Canvas bounding-box and reticle overlay engine
│       └── audio_alerts.js # Web Audio API procedural warning synthesizer
```

### Dashboard UI Wireframe & Layout

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🛰️ EDGEROVER GCS    ● CONNECTED (14ms)   [MODE: MANUAL]   🔋 84% (12.3V)   │
├─────────────────────────────────────────────────────────────────────────────┤
│ [ 📹 LIVE TELEOP ]  [ 📋 MISSIONS ]  [ 🚨 EVENT LOG ]  [ 📊 SENSORS ]  [ ⚙️ ]│
├─────────────────────────────────────────┬───────────────────────────────────┤
│                                         │ QUICK TELEMETRY & STATUS          │
│   LIVE VIDEO HUD (1280×720 MJPEG)       ├───────────────────────────────────┤
│   ┌─────────────────────────────────┐   │ Front Distance:   124 cm [CLEAR]  │
│   │ [PERSON 92%]                    │   │ Speed Setting:    [====O====] 35% │
│   │ ┌──────────────┐                │   │ CPU Temp / RAM:   47°C / 1.1 GB   │
│   │ │              │                │   │ AI Vision:        22.4 FPS (YOLO) │
│   │ │              │                │   │ Active Mission:   None (Standby)  │
│   │ └──────────────┘                │   ├───────────────────────────────────┤
│   │                                 │   │ NATURAL LANGUAGE COMMAND BAR      │
│   │                                 │   │ ┌───────────────────────────┬───┐ │
│   │                                 │   │ │ "Inspect north gate"      │ ▶ │ │
│   │              (+) Reticle        │   │ └───────────────────────────┴───┘ │
│   └─────────────────────────────────┘   ├───────────────────────────────────┤
│                                         │ MANUAL D-PAD CONTROLLER           │
│   TOUCH VIRTUAL JOYSTICK / CONTROLS     │                ▲ [W]              │
│   ┌─────────────────────────────────┐   │         ◀ [A]  ■ STOP   ▶ [D]     │
│   │    Hold button or drag stick    │   │                ▼ [S]              │
│   │       to steer rover            │   ├───────────────────────────────────┤
│   └─────────────────────────────────┘   │ [ 🛑 EMERGENCY MOTOR STOP (SPACE)]│
└─────────────────────────────────────────┴───────────────────────────────────┘
```

### Frontend Implementation Modules

#### 1. Real-Time HUD & Canvas Overlay (`canvas_hud.js`)
- An HTML5 `<canvas>` sits overlaid on top of `<img id="camera-stream" src="/rover/stream.mjpg">`.
- When telemetry packets arrive via WebSocket containing YOLO detections (`[ymin, xmin, ymax, xmax, label, conf]`), the canvas draws:
  - High-visibility corner-bracketed bounding boxes.
  - Identification labels with confidence badges (`PERSON 94%`).
  - Target tracking reticle and range estimate.
  - Proximity warning zone overlays (turns Amber at <60cm, flashing Red at <30cm).

#### 2. Teleoperation & Input Manager (`teleop.js`)
- **Pointer Events API**: Directional buttons use `pointerdown` and `pointerup` with `setPointerCapture` to guarantee that motor commands release even if the user slides their finger off the button.
- **Heartbeat Transmission**: While any movement button is held, a heartbeat packet is transmitted every 150 ms over WebSocket:
  ```json
  {"action": "drive", "command": "forward", "speed": 0.35, "seq": 1042}
  ```
- **Active Brake on Release**: Immediately upon `pointerup` or `keyup`, a `{"action": "drive", "command": "stop"}` packet is transmitted.

#### 3. Tab System & Feature Views (`app.js`)
- **Tab 1: Live Teleop**: Camera feed, virtual joystick, D-pad, speed slider, E-Stop, and voice/text prompt bar.
- **Tab 2: Mission Planner**: Natural language mission creator, visual waypoint checklist, mission progress bar, and pause/abort controls.
- **Tab 3: Event Log & Evidence**: Live scrollable feed of detected events with thumbnail previews. Clicking an event opens the full-resolution snapshot.
- **Tab 4: Sensor Telemetry & Diagnostics**: Real-time charts/gauges for battery discharge curve, ToF distance readout, IMU orientation cube, and CPU thermals.
- **Tab 5: System Settings**: Toggle YOLO detector on/off, adjust confidence threshold, configure Groq API key, set Telegram bot token and chat ID.

#### 4. Procedural Audio Synthesizer (`audio_alerts.js`)
- Uses browser native **Web Audio API** (zero sound assets/MP3s required).
- Generates procedural audio chirps:
  - *Obstacle Warning*: Modulated 880Hz alert tone when distance < 40cm.
  - *Critical Intrusion Alert*: Dual-tone siren when unauthorized person detected during mission.
  - *Connection Chime*: Pleasant ascending chord on WebSocket connect.

---

## 11. Backend API & Communication Architecture

### Framework: FastAPI + Uvicorn
FastAPI replaces monolithic Flask for the long-term production architecture to natively provide:
- High-performance asynchronous event loop (`asyncio`).
- Native WebSocket support for bi-directional real-time telemetry.
- Automated OpenAPI/Swagger documentation at `/docs`.
- Strict Pydantic v2 data models for tool validation.

### API Endpoints Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` or `/rover` | Serves the lightweight Vanilla HTML5/CSS/JS Ground Control Station. |
| `GET` | `/rover/stream.mjpg` | Low-latency multipart/x-mixed-replace MJPEG camera stream from Picamera2. |
| `WS` | `/ws/telemetry` | Bi-directional WebSocket connection for telemetry stream and drive commands. |
| `POST` | `/api/rover/drive` | Direct REST drive endpoint (command, speed, optional duration). |
| `POST` | `/api/rover/stop` | Immediate emergency motor stop. |
| `POST` | `/api/command/nl` | Submits a natural language instruction to Needle/Groq gateway. |
| `GET` | `/api/missions` | Retrieves list of saved and active missions. |
| `POST` | `/api/missions/create` | Compiles a natural language mission prompt into structured JSON via Groq. |
| `POST` | `/api/missions/start` | Initiates autonomous execution of a compiled mission. |
| `POST` | `/api/missions/abort` | Aborts current mission and commands rover to stop. |
| `GET` | `/api/events` | Retrieves paginated historical events and captured evidence snapshots. |
| `GET` | `/api/evidence/{filename}` | Serves captured JPEG evidence images. |
| `GET` | `/api/system/health` | Pi 5 hardware metrics (CPU temp, RAM, disk, I2C bus status). |

### WebSocket Communication Protocol (`/ws/telemetry`)
- **Server -> Client (Pushed at 10 Hz)**:
  Full World State telemetry packet (battery, distance, motor state, active mission, YOLO bounding box list).
- **Client -> Server (On demand / 150ms held)**:
  ```json
  {"action": "drive", "command": "forward", "speed": 0.35}
  ```
  ```json
  {"action": "ping", "client_time": 1775043820100}
  ```
  ```json
  {"action": "nl_command", "text": "turn left 45 degrees"}
  ```

---

## 12. Persistent Database Schema (SQLite)

EdgeRover uses an embedded **SQLite** database (`rover_data.db`) managed via `aiosqlite`. It requires zero external database servers (no PostgreSQL, Redis, or Docker needed).

### Tables Specification

```sql
-- 1. Missions Table
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT CHECK(status IN ('CREATED', 'VALIDATING', 'READY', 'RUNNING', 'PAUSED', 'COMPLETED', 'ABORTED', 'FAILED')),
    mission_json TEXT NOT NULL,
    summary_report TEXT
);

-- 2. Mission Executions
CREATE TABLE IF NOT EXISTS mission_runs (
    run_id TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id),
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_seconds REAL,
    initial_battery INTEGER,
    final_battery INTEGER,
    total_distance_est_cm REAL,
    events_count INTEGER DEFAULT 0,
    status TEXT
);

-- 3. Surveillance Events Table
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    mission_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,          -- e.g. 'PERSON_DETECTED', 'OBSTACLE_AVOIDED'
    severity TEXT NOT NULL,            -- 'INFO', 'WARNING', 'CRITICAL'
    confidence REAL,
    distance_cm REAL,
    evidence_image_path TEXT,
    metadata_json TEXT
);

-- 4. Telemetry Log (Sampled every 5s during missions)
CREATE TABLE IF NOT EXISTS telemetry_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    battery_pct INTEGER,
    front_distance_cm REAL,
    heading_deg REAL,
    rover_state TEXT
);
```

---

## 13. Telegram Security & Alerting Channel

Telegram serves as the remote notification pipeline for off-site operators when the rover operates autonomously:

```text
               ANOMALY DETECTED (YOLO / LAYA / SENSOR)
                                 │
                                 ▼
                    Capture High-Res Evidence Frame
                                 │
                                 ▼
                     Record Event in SQLite DB
                                 │
                                 ▼
                     telegram_notifier.send_alert()
                                 │
            ┌────────────────────┴────────────────────┐
            ▼                                         ▼
   CRITICAL EVENT MESSAGE                      EVIDENCE PHOTO
  "🚨 INTRUSION DETECTED                      (High-Res Snapshot
   Mission: Warehouse Patrol                   with Bounding Boxes)
   Target: Person (Conf: 94%)
   Distance: 140 cm
   Action Taken: Stopped & Auditing"
```

### End-of-Mission Executive Summary:
Upon mission completion, Groq compiles an executive debrief dispatched directly to Telegram:
```text
✅ MISSION COMPLETED: West Perimeter Patrol
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️ Duration: 18 min 24 sec
🔋 Battery Used: 82% ➔ 64% (-18%)
🔍 Detections: 4 (3 Vehicles, 1 Person)
⚠️ Critical Events: 1 (Resolved)
🛡️ Obstacles Safely Avoided: 6
📝 AI Summary: Rover navigated all 8 designated waypoints successfully. One unauthorized individual was detected near the maintenance shed at 21:14; high-resolution evidence captured and logged. Perimeter is currently clear.
```

---

## 14. Academic Research Contributions & Evaluation Methodology

For academic defense and project evaluation, EdgeRover provides empirical comparative benchmarks rather than anecdotal demonstrations:

### Key Experimental Studies:

1. **Cloud Quota & Latency Optimization (Groq Reduction Experiment)**:
   - *Baseline (Naive Architecture)*: LLM queried in loop every 2 seconds during mission -> burns hundreds of API calls, high latency, quota failure.
   - *EdgeRover Architecture*: Needle 2 + Laya + Local YOLO handle 98% of operational loop; Groq invoked only 2–4 times per mission -> **>95% cloud API cost reduction**.
2. **Embedded Object Detection Throughput**:
   - Benchmark YOLO26n/v8n on Pi 5: NCNN vs. ONNX vs. PyTorch CPU at 320×320 and 640×640 input resolutions (FPS, CPU utilization, thermal throttling limits).
3. **Local Tool Dispatch Latency**:
   - Compare Needle 2 (local C/SLM) response latency (~25ms) vs. Cloud LLM tool-calling roundtrip (~450ms).
4. **Deterministic Safety Compliance Rate**:
   - Test 100 random obstacle obstruction scenarios to verify 100% collision prevention via ToF interceptor regardless of rogue software commands.

---

## 15. Phased Implementation Roadmap

### Phase 1: Solidify Hardware & Core Actuation (Current Baseline)
- [x] Raspberry Pi 5 setup with Raspberry Pi OS 64-bit Debian Trixie.
- [x] Dual IBT-2 motor drivers wired to GPIO 17, 18, 22, 23 with common ground.
- [x] Picamera2 MJPEG live camera stream operating at 720p.
- [x] Software safety watchdog with 600ms motor cutoff.
- [ ] Connect VL53L0X ToF sensor to I2C1 (GPIO 2 & 3) and integrate hardware proximity cutoff into motor driver loop.

### Phase 2: Lightweight Ground Control Station (HTML5 / CSS3 / Vanilla JS)
- [ ] Migrate `app.py` from basic Flask to structured **FastAPI** backend with async WebSocket support.
- [ ] Create `static/index.html`, `static/css/dashboard.css`, and `static/js/` modular frontend.
- [ ] Build virtual touch joystick and WASD keyboard controller using Pointer Events with reliable pointer capture.
- [ ] Implement client-side HTML5 Canvas bounding box overlay receiving real-time YOLO coordinates over WebSocket.
- [ ] Implement Web Audio API procedural warning synthesizer.

### Phase 3: Edge AI & Local Tool Calling
- [ ] Package `YOLODetector` worker thread streaming bounding boxes without blocking video feed.
- [ ] Implement typed Python Tool Registry (`move_forward`, `turn_right`, `stop_rover`, `capture_evidence`, `get_telemetry`).
- [ ] Integrate **Needle 2** local binary / lightweight SLM for zero-cloud natural language tool invocation.
- [ ] Integrate **Laya** decision evaluator (ONNX runtime) for rapid state triage.

### Phase 4: Cloud Reasoning & Mission Engine
- [ ] Implement Groq API client with structured JSON Schema output (`create_mission`, `summarize_report`).
- [ ] Build autonomous mission state machine (Waypoints, Search loops, Event triggers).
- [ ] Set up SQLite persistence (`missions`, `mission_runs`, `events`, `telemetry_log`).
- [ ] Connect Telegram Bot for real-time critical photo alerts and mission debrief summaries.

### Phase 5: Testing, Hardening & Academic Evaluation
- [ ] Perform obstacle avoidance stress testing and tune ToF threshold margins.
- [ ] Run comparative latency benchmarks (Needle vs. Groq, NCNN vs. ONNX).
- [ ] Execute continuous 30-minute autonomous perimeter patrol test.
- [ ] Complete final technical paper / project report and demonstration rehearsal.

---

## Addendum: Open-Loop Motion & Hardware Reality (current build)

The current robot has **no distance sensor, encoders, IMU or camera pan/tilt servo**. Consequences for this spec:

- Movement tools take `distance_cm` / `degrees`; `motion.py` converts them to motor-on time with per-robot constants in `calibration.json` (see README, "Open-Loop Motion"). Planners must not compute durations themselves.
- `duration_seconds` is only a fallback when no distance is given. Where both `distance_cm`/`degrees` and a duration are supplied, the distance/angle wins.
- The 30 cm VL53L0X safety interceptor and range telemetry are disabled unless `ROVER_DISTANCE_SENSOR=1`; WorldState reports a fixed 999 cm.
- `scan_surroundings` rotates the whole chassis because the camera cannot pan.
- Missions are executed by `MissionRunner` (sequential, one at a time, abortable); an operator E-STOP or any manual drive command aborts them.
- Safety limits: a single move may not exceed 120 s; the 600 ms control watchdog is fed while a timed move runs.
- Evidence snapshots are listed by `GET /rover/api/evidence` and shown in the GCS Event Log tab.
