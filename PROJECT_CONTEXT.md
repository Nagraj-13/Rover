# Raspberry Pi 5 AI Rover — Complete Project Context

## 1. Project Overview

This project is a Raspberry Pi 5 based four-wheel rover with:

* Raspberry Pi 5 4 GB
* Raspberry Pi Camera 3
* Four DC geared motors
* Two IBT-2 / BTS7960B H-bridge motor drivers
* VL53L0X ToF distance sensor
* Wi-Fi connectivity
* A browser-based mobile control interface
* Live camera streaming
* Future obstacle detection, autonomous navigation, computer vision and AI inference

The current architecture intentionally avoids relying on Telegram/OpenClaw as the primary rover-control interface.

The Raspberry Pi itself runs a local web server. A user opens the rover UI from a phone or laptop on the same network using:

`http://<RASPBERRY_PI_IP>:<PORT>/rover`

The web interface provides:

* Live Pi Camera 3 video
* Forward
* Backward
* Left
* Right
* Stop
* Adjustable motor speed
* Keyboard controls when used from a desktop
* Automatic motor stop if the connection is lost

The long-term goal is to turn this into a modular rover platform for:

* Remote surveillance
* Navigation
* Obstacle avoidance
* Abnormal-event detection
* Object detection
* Moving toward a detected object without collision
* Returning to the starting position
* Local AI inference
* Sensor-assisted autonomous movement

---

# 2. Hardware

## Raspberry Pi

Board:

* Raspberry Pi 5
* 4 GB RAM

Current environment:

* Raspberry Pi OS
* Debian Trixie
* Linux kernel in the 6.18.x series
* libcamera 0.7.x
* PiSP 1.7.x
* Python 3.12
* GPIOZero installed
* Picamera2 installed

The Pi has already successfully detected the camera.

---

# 3. Camera

Camera:

* Raspberry Pi Camera 3

The camera is working through the modern libcamera/Picamera2 stack.

Camera detection previously showed the sensor and available modes.

Picamera2 verification currently succeeds:

```bash
python3 -c "from picamera2 import Picamera2; print('Picamera2 OK')"
```

Expected:

```text
Picamera2 OK
```

Current web-stream implementation uses:

* Picamera2
* MJPEGEncoder
* FileOutput
* Flask
* HTTP multipart MJPEG streaming

Important compatibility detail:

The installed Picamera2 version does NOT accept:

```python
MJPEGEncoder(num_buffers=4)
```

The correct constructor for this environment is:

```python
MJPEGEncoder()
```

Do not reintroduce `num_buffers` unless the installed Picamera2 version is explicitly verified to support it.

Current camera web resolution:

```text
1280 × 720
```

The stream is exposed through:

```text
/rover/stream.mjpg
```

---

# 4. Motors

There are four DC motors arranged as a conventional four-wheel rover:

```text
             FRONT

      M1                    M3
   LEFT FRONT            RIGHT FRONT

             ROVER

      M2                    M4
   LEFT REAR             RIGHT REAR

              BACK
```

The rover is controlled as two sides:

```text
LEFT SIDE  = M1 + M2
RIGHT SIDE = M3 + M4
```

Each side uses one IBT-2 motor driver.

Therefore:

```text
IBT-2 #1 → M1 + M2
IBT-2 #2 → M3 + M4
```

The two motors on each side are connected in parallel to the driver's motor output.

---

# 5. Motor Drivers

There are two IBT-2 / BTS7960B H-bridge modules.

## Driver 1

Controls:

```text
LEFT FRONT MOTOR
LEFT REAR MOTOR
```

GPIO control:

```text
GPIO17 → RPWM
GPIO18 → LPWM
```

## Driver 2

Controls:

```text
RIGHT FRONT MOTOR
RIGHT REAR MOTOR
```

GPIO control:

```text
GPIO22 → RPWM
GPIO23 → LPWM
```

The current software therefore creates:

```python
left_motor = Motor(
    forward=17,
    backward=18,
    pwm=True
)

right_motor = Motor(
    forward=22,
    backward=23,
    pwm=True
)
```

GPIO numbering is BCM numbering.

---

# 6. Raspberry Pi GPIO Mapping

Current intended mapping:

| Raspberry Pi GPIO | Physical pin | Function                             |
| ----------------- | -----------: | ------------------------------------ |
| GPIO17            |       Pin 11 | Left IBT-2 RPWM                      |
| GPIO18            |       Pin 12 | Left IBT-2 LPWM                      |
| GPIO22            |       Pin 15 | Right IBT-2 RPWM                     |
| GPIO23            |       Pin 16 | Right IBT-2 LPWM                     |
| 5V                |   Pin 2 or 4 | Driver enable/control power as wired |
| GND               |        Pin 6 | Common ground                        |

Do not confuse BCM GPIO numbering with physical pin numbers.

Software uses:

```text
17
18
22
23
```

not physical pin numbers.

---

# 7. Power Architecture

Motor power is separate from Raspberry Pi power.

The motor supply provides the motor driver's power.

General architecture:

```text
12 V MOTOR SUPPLY
      │
      ├──────────────► IBT-2 #1 power
      │
      └──────────────► IBT-2 #2 power

12 V NEGATIVE
      │
      ├──────────────► IBT-2 #1 GND / B-
      ├──────────────► IBT-2 #2 GND / B-
      └──────────────► Raspberry Pi GND
```

The Raspberry Pi must NOT power the motors.

The motor supply negative and Raspberry Pi ground must share a common reference for the control signals.

Important electrical consideration:

The motors are described as 12 V motors that can also operate at 6 V.

Because two motors are connected in parallel to each IBT-2, the driver and wiring must handle the combined current.

Startup current and stall current matter much more than the normal unloaded running current.

Never assume that the marketing "43 A" printed on an IBT-2 means 43 A of continuous practical capability.

Initial testing should therefore be conservative.

---

# 8. Motor Control Model

The rover uses differential drive.

## Forward

```text
LEFT  → forward
RIGHT → forward
```

## Backward

```text
LEFT  → backward
RIGHT → backward
```

## Turn Left

Current software implementation:

```text
LEFT  → backward
RIGHT → forward
```

This creates an in-place rotation.

## Turn Right

```text
LEFT  → forward
RIGHT → backward
```

## Stop

```text
LEFT  → stop
RIGHT → stop
```

Later, this can be changed to smoother differential steering instead of pivot turning.

---

# 9. Proven Motor-Control API

A single-side motor was already successfully tested using GPIOZero:

```python
from gpiozero import Motor

motor = Motor(
    forward=17,
    backward=18,
    pwm=True
)
```

The test supported:

```text
f = forward
b = backward
s = stop

1 = 20%
2 = 40%
3 = 60%
4 = 80%
5 = 100%

q = quit
```

That test successfully demonstrated that:

```text
GPIO17 / GPIO18 → IBT-2 → motor
```

works with GPIOZero.

The four-motor implementation should therefore continue using GPIOZero rather than unnecessarily switching to a completely different GPIO architecture.

---

# 10. Current Project Directory

The rover project is located at:

```text
/home/pramod/rover
```

Current intended structure:

```text
rover/
├── app.py
├── motor_test.py
├── rover_test.py
└── ...
```

The project should gradually become more modular rather than putting all future AI/sensor functionality into one file.

A future target structure could be:

```text
rover/
├── app.py
├── config.py
│
├── motors/
│   ├── __init__.py
│   └── controller.py
│
├── camera/
│   ├── __init__.py
│   └── stream.py
│
├── sensors/
│   ├── __init__.py
│   └── vl53l0x.py
│
├── navigation/
│   ├── __init__.py
│   └── controller.py
│
├── vision/
│   ├── __init__.py
│   └── detector.py
│
├── web/
│   ├── templates/
│   └── static/
│
└── tests/
```

Do not over-engineer this immediately. Keep the MVP simple first.

---

# 11. Current Web Architecture

The Raspberry Pi runs Flask.

Server:

```text
Flask
0.0.0.0:8080
```

Main URL:

```text
http://<PI-IP>:8080/rover
```

The server currently provides:

```text
GET  /rover
GET  /rover/
GET  /rover/stream.mjpg

POST /rover/api/control
GET  /rover/api/status
```

---

# 12. Web UI

The interface is designed primarily for mobile.

Current UI components:

## Header

Displays:

```text
Rover Control
Connected
```

## Camera

A live camera card showing Pi Camera 3.

## Direction controls

Layout:

```text
        ▲
     ◀ STOP ▶
        ▼
```

Buttons support touch/pointer input.

## Speed

Slider:

```text
10% → 100%
```

Default:

```text
30%
```

Current default is deliberately conservative.

## Keyboard

Desktop browsers also support:

```text
W / Arrow Up     → forward
S / Arrow Down   → backward
A / Arrow Left   → left
D / Arrow Right  → right
```

---

# 13. Hold-to-Move Behavior

The web controls are deliberately implemented as hold-to-move.

When the user holds:

```text
FORWARD
```

the browser sends:

```text
forward
```

repeatedly.

When the user releases the button:

```text
stop
```

is sent.

This is safer than sending only one command and leaving the rover indefinitely in that movement state.

---

# 14. Motor Watchdog

A server-side safety watchdog is implemented.

Current logic:

```text
Browser sends command
        ↓
Pi receives command
        ↓
last_control_time updated
        ↓
browser keeps sending heartbeat
```

If the Pi stops receiving control updates for approximately:

```text
600 ms
```

the rover automatically stops.

Conceptually:

```text
COMMAND RECEIVED
       │
       ▼
   MOTOR RUNNING
       │
       │ heartbeat
       │ heartbeat
       │ heartbeat
       X connection lost
       │
       ▼
   ~600 ms timeout
       │
       ▼
   STOP MOTORS
```

This is a critical safety feature and should be preserved or strengthened as the project evolves.

---

# 15. Browser Safety

The web UI also stops the rover when:

* The direction button is released
* Pointer capture is cancelled
* The browser loses focus
* The page becomes hidden
* The user presses STOP
* Keyboard control key is released

This provides multiple independent stop paths.

---

# 16. Current Flask Camera Implementation

The current camera architecture is:

```text
Pi Camera 3
     │
     ▼
Picamera2
     │
     ▼
MJPEGEncoder()
     │
     ▼
StreamingOutput
     │
     ▼
Flask
     │
     ▼
HTTP multipart MJPEG
     │
     ▼
Mobile browser
```

The browser displays:

```html
<img src="/rover/stream.mjpg">
```

This is intentionally simple for an MVP.

Later, the camera transport can be replaced with a more efficient WebRTC/WebSocket/video pipeline if low latency becomes important.

---

# 17. Current Known Working Software

Verified:

```bash
python3 -c "from picamera2 import Picamera2; print('Picamera2 OK')"
```

works.

Verified:

```bash
python3 -c "from gpiozero import Motor; print('GPIOZero OK')"
```

works.

Camera initialization has successfully detected:

```text
ov5647
```

and the current libcamera/Picamera2 stack is functional.

---

# 18. Current app.py Requirements

The current `app.py` should:

1. Initialize the left motor.
2. Initialize the right motor.
3. Initialize the Pi Camera 3.
4. Start the MJPEG encoder.
5. Start Flask on `0.0.0.0:8080`.
6. Expose `/rover`.
7. Expose `/rover/stream.mjpg`.
8. Expose the motor control API.
9. Implement motor watchdog safety.
10. Stop motors during shutdown.

Do not use:

```python
MJPEGEncoder(num_buffers=4)
```

for the current environment.

Use:

```python
MJPEGEncoder()
```

---

# 19. Current User Workflow

Typical startup:

```bash
cd ~/rover
python3 app.py
```

Find IP:

```bash
hostname -I
```

Then open:

```text
http://<PI-IP>:8080/rover
```

from a mobile device on the same network.

---

# 20. Current MVP Goal

The immediate MVP target is:

```text
┌──────────────────────────────────────┐
│              MOBILE                  │
│                                      │
│        Browser                       │
│          │                           │
│          │ Wi-Fi                     │
│          ▼                           │
├──────────────────────────────────────┤
│          RASPBERRY PI 5              │
│                                      │
│   Flask Web Server                   │
│       │             │                │
│       │             │                │
│       ▼             ▼                │
│   Motor Control    Camera            │
│       │             │                │
│       ▼             ▼                │
│    IBT-2 ×2       Pi Camera 3        │
│       │                              │
│       ▼                              │
│    4 Motors                          │
└──────────────────────────────────────┘
```

This MVP should work entirely on the local network without requiring cloud services.

---

# 21. VL53L0X

Available sensor:

```text
VL53L0X
```

Purpose:

* Distance measurement
* Front obstacle detection
* Prevent collision
* Future autonomous navigation

Current sensor is not yet integrated into the web-control implementation.

Future basic behavior:

```text
IF obstacle distance < threshold
        ↓
STOP
```

A later implementation can provide:

```text
distance < safe_distance
        ↓
block forward command
        ↓
allow reverse / turning
```

The exact threshold should be configurable rather than hard-coded.

---

# 22. Planned Rover Modes

The architecture should eventually support multiple modes.

## Manual

User directly controls:

```text
Forward
Backward
Left
Right
Stop
Speed
```

## Assisted

User controls the rover, but the Pi prevents unsafe movement.

Example:

```text
User → Forward
          │
          ▼
     Distance sensor
          │
      obstacle
          │
          ▼
        STOP
```

## Autonomous

The Pi makes movement decisions.

Potential pipeline:

```text
Camera
   │
   ▼
Vision / Detection
   │
   ▼
Navigation logic
   │
   ├── Distance sensor
   │
   └── Motor controller
          │
          ▼
       4 motors
```

---

# 23. Planned Computer Vision

Possible future capabilities:

* Object detection
* Person detection
* Vehicle detection
* Fire/smoke detection
* Abnormal-event detection
* Scene analysis
* Object tracking

Vision should be treated as a separate module.

Do not tightly couple an AI model directly to the Flask route handlers.

Preferred architecture:

```text
Camera
  │
  ▼
Frame source
  │
  ├──────────────► Web stream
  │
  └──────────────► Vision pipeline
                       │
                       ▼
                  Detection result
                       │
                       ▼
                  Navigation
```

This allows the live stream to remain usable even if AI inference is enabled.

---

# 24. Local AI Direction

The rover is intended to eventually perform at least some inference locally.

The design should prioritize:

* Low latency
* Low power
* Reduced cloud dependency
* Reasonable thermal load
* Modular model selection

Possible future hardware acceleration may be evaluated separately.

Do not assume that the Raspberry Pi 5 alone is ideal for every vision model.

The software architecture should therefore make inference replaceable.

---

# 25. Navigation Goal

One major long-term behavior is:

```text
Detect object
      ↓
Estimate position/direction
      ↓
Move toward object
      ↓
Check distance continuously
      ↓
Slow down near object
      ↓
Stop at safe distance
```

Another possible behavior:

```text
Start point
    ↓
Navigate
    ↓
Perform task
    ↓
Return
    ↓
Start point
```

This requires integrating:

* Camera
* Distance sensor
* Motor control
* Orientation/odometry or another localization mechanism

A VL53L0X by itself is not sufficient for reliable full-rover localization.

---

# 26. Important Engineering Principles

Future code should follow these rules.

### Safety first

Any uncertain state should result in:

```text
STOP
```

Motor shutdown should happen on:

* Ctrl+C
* Exception
* Browser disconnect/watchdog timeout
* Camera/server failure where appropriate
* Invalid command
* Sensor emergency condition

### Modularity

Keep:

```text
motor control
camera
sensor
vision
navigation
web server
```

separate as the project grows.

### Configurability

Pins and key parameters should eventually live in a configuration file rather than being scattered across source code.

Example:

```python
LEFT_RPWM = 17
LEFT_LPWM = 18
RIGHT_RPWM = 22
RIGHT_LPWM = 23

PORT = 8080

DEFAULT_SPEED = 0.30
WATCHDOG_TIMEOUT = 0.6
```

### Hardware abstraction

Higher-level code should eventually call:

```python
rover.forward(speed)
rover.backward(speed)
rover.turn_left(speed)
rover.turn_right(speed)
rover.stop()
```

rather than directly manipulating GPIO pins.

---

# 27. Troubleshooting Rules

## Camera error

First verify:

```bash
rpicam-hello
```

and:

```bash
python3 -c "from picamera2 import Picamera2; print('Picamera2 OK')"
```

Also check:

```bash
rpicam-hello --list-cameras
```

Do not immediately change camera libraries if Picamera2 is already working.

---

## Motor error

Since GPIOZero has already been proven for GPIO17/18, test each side independently.

Left:

```text
GPIO17
GPIO18
```

Right:

```text
GPIO22
GPIO23
```

Check wiring before changing software.

---

## Direction reversed

If one physical motor spins opposite to the others, first determine whether the issue is:

* motor polarity
* physical wiring
* left/right software inversion

Do not randomly change multiple GPIO assignments.

---

# 28. Current Testing Strategy

Testing should happen in stages.

### Stage 1

Camera only:

```text
Camera → web browser
```

### Stage 2

Left motor:

```text
GPIO17/18 → IBT-2 → M1/M2
```

### Stage 3

Right motor:

```text
GPIO22/23 → IBT-2 → M3/M4
```

### Stage 4

All four motors:

```text
Forward
Backward
Stop
```

### Stage 5

Turning:

```text
Left
Right
```

### Stage 6

Web control:

```text
Phone → Pi → motors
```

### Stage 7

Camera + motors simultaneously.

### Stage 8

VL53L0X.

### Stage 9

Assisted obstacle avoidance.

### Stage 10

Vision and autonomous navigation.

---

# 29. Current Hardware Control Model

The current rover is intentionally simple:

```text
One IBT-2 per side

LEFT:
GPIO17 + GPIO18
        ↓
    IBT-2 #1
        ↓
    M1 + M2

RIGHT:
GPIO22 + GPIO23
        ↓
    IBT-2 #2
        ↓
    M3 + M4
```

This is preferable to controlling four motors completely independently for the initial rover because it naturally maps to differential-drive navigation.

Independent four-motor control can be added later if required.

---

# 30. Future Web Dashboard

The current control page should eventually evolve into a richer rover dashboard.

Potential UI:

```text
┌─────────────────────────────────────────────┐
│ ROVER                        ● CONNECTED     │
├─────────────────────────────────────────────┤
│                                             │
│             LIVE CAMERA                     │
│                                             │
├─────────────────────────────────────────────┤
│                                             │
│                  ▲                          │
│               ◀ STOP ▶                      │
│                  ▼                          │
│                                             │
│ Speed ───────────●──── 40%                  │
│                                             │
├─────────────────────────────────────────────┤
│ Distance: 84 cm                             │
│ Battery:   --                               │
│ Mode:      MANUAL                           │
│                                             │
└─────────────────────────────────────────────┘
```

Future status information may include:

* Distance
* Battery voltage
* Motor state
* CPU temperature
* CPU usage
* Memory usage
* Camera state
* AI inference state
* Current mode
* Network status

---

# 31. Future API Design

Keep the existing simple API compatible while expanding it.

Current:

```text
POST /rover/api/control
```

Example:

```json
{
  "command": "forward",
  "speed": 0.4
}
```

Future APIs could include:

```text
GET  /rover/api/status
GET  /rover/api/sensors
POST /rover/api/mode
POST /rover/api/stop
GET  /rover/api/health
```

Potential future modes:

```text
manual
assisted
autonomous
```

---

# 32. Security Considerations

The current rover interface is intended for use on a trusted local network.

It should NOT be exposed directly to the public Internet in its current form.

Before Internet exposure, add:

* Authentication
* Authorization
* HTTPS
* Rate limiting
* Command validation
* Session management
* CSRF protection as appropriate
* Network isolation
* Emergency stop handling

The rover should always fail safe.

---

# 33. Development Philosophy

The project should progress incrementally.

Do not add:

* AI
* database
* cloud
* complex frontend frameworks
* autonomous navigation
* multiple services

until the hardware and basic web control are stable.

Current priority:

```text
4 motors
+
Camera
+
Mobile web control
```

Then:

```text
VL53L0X
```

Then:

```text
Obstacle avoidance
```

Then:

```text
Computer vision
```

Then:

```text
Autonomous navigation
```

---

# 34. Current Definition of Done for MVP

The immediate MVP is complete when all of the following work together:

```text
1. Raspberry Pi boots
2. Camera initializes
3. Flask server starts
4. Mobile opens /rover
5. Camera stream is visible
6. Forward moves all four motors
7. Backward moves all four motors
8. Left works
9. Right works
10. Stop works
11. Speed slider works
12. Browser release stops motion
13. Connection loss stops motion
14. Ctrl+C stops motors
15. Camera and motor control can operate simultaneously
```

---

# 35. Agent Instructions

When modifying this project:

* Preserve the currently working GPIO mapping unless explicitly changing hardware.
* Use BCM GPIO numbering.
* Continue using GPIOZero for the current motor abstraction.
* Continue using Picamera2 for the Pi Camera 3.
* Do not replace Picamera2 with legacy `picamera`.
* Do not use `MJPEGEncoder(num_buffers=4)` with the current environment.
* Keep motor safety mechanisms intact.
* Never remove the emergency stop behavior.
* Avoid exposing motor control directly to arbitrary HTTP input.
* Keep the web UI usable from a mobile browser.
* Prefer incremental modifications over rewriting working subsystems.
* Test camera and motors independently when debugging.
* Keep hardware pin definitions centralized.
* Do not assume motor direction without testing the physical rover.
* Be careful with two motors operating in parallel on one driver.
* Treat current 12 V motor power as a separate power domain from the Raspberry Pi.
* Always stop motors during exceptions and shutdown.
* Do not expose the control server to the Internet without authentication/security work.

---

# 36. Current Technology Stack

```text
Hardware
────────
Raspberry Pi 5 4 GB
Pi Camera 3
4 × DC motors
2 × IBT-2 / BTS7960B
VL53L0X
Motor power supply

Software
────────
Raspberry Pi OS / Debian Trixie
Python 3.12
GPIOZero
Picamera2
libcamera
Flask
MJPEG streaming
HTML/CSS/JavaScript

Network
───────
Local Wi-Fi / LAN
HTTP
Port 8080
Path /rover
```

---

# 37. Current Architecture Summary

```text
                         MOBILE / LAPTOP
                               │
                               │ HTTP
                               ▼
                    ┌─────────────────────┐
                    │   Raspberry Pi 5    │
                    │                     │
                    │       Flask         │
                    │         │           │
                    │    ┌────┴────┐      │
                    │    │         │      │
                    │    ▼         ▼      │
                    │ Camera     Control  │
                    │ Stream       API    │
                    │    │         │      │
                    │    ▼         ▼      │
                    │ Pi Camera   GPIOZero│
                    │    3         │      │
                    │              │      │
                    └──────────────┼──────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
              IBT-2 #1                       IBT-2 #2
              LEFT SIDE                      RIGHT SIDE
             GPIO17/18                       GPIO22/23
                  │                              │
               ┌──┴──┐                        ┌──┴──┐
               │     │                        │     │
              M1     M2                       M3    M4
          LEFT FRONT LEFT REAR            RIGHT FRONT RIGHT REAR

                    VL53L0X
                       │
                       ▼
                Future obstacle
                   detection
```

---

# 38. Long-Term Vision

The rover should evolve from:

```text
Remote-controlled four-wheel rover
```

into:

```text
Camera + sensors
      ↓
Perception
      ↓
Decision / navigation
      ↓
Safe motor control
      ↓
Autonomous rover
```

The web interface should remain useful even after autonomy is introduced, becoming the rover's monitoring and override console.

The architecture should therefore keep **manual control, perception, safety, and autonomy as separate layers** rather than building the entire system as one monolithic Python script.

