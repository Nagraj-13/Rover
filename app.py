#!/usr/bin/env python3

import io
import threading
import time

from flask import Flask, Response, jsonify, request
from gpiozero import Motor

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput


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


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# MOTOR SETUP
# ============================================================

# LEFT IBT-2
#
# GPIO17 -> RPWM
# GPIO18 -> LPWM

left_motor = Motor(
    forward=17,
    backward=18,
    pwm=True
)


# RIGHT IBT-2
#
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

    # Keep speed between 0 and 1
    speed = max(
        0.0,
        min(1.0, float(speed))
    )

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

                elapsed = (
                    time.monotonic()
                    - last_control_time
                )

                if elapsed > WATCHDOG_TIMEOUT:

                    left_motor.stop()
                    right_motor.stop()

                    current_command = "stop"

                    print(
                        "WATCHDOG: Motors stopped"
                    )


watchdog_thread = threading.Thread(
    target=motor_watchdog,
    daemon=True
)

watchdog_thread.start()


# ============================================================
# CAMERA
# ============================================================

class StreamingOutput(io.BufferedIOBase):

    def __init__(self):

        self.frame = None

        self.condition = threading.Condition()


    def write(self, buf):

        with self.condition:

            self.frame = buf

            self.condition.notify_all()


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


# Shared stream buffer
output = StreamingOutput()


# IMPORTANT:
# Do NOT use num_buffers here.
encoder = MJPEGEncoder()


# Start camera recording
picam2.start_recording(
    encoder,
    FileOutput(output)
)


# ============================================================
# VIDEO STREAM
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
            + b"\r\n"
            b"\r\n"
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

<meta
    name="viewport"
    content="
        width=device-width,
        initial-scale=1.0,
        maximum-scale=1.0,
        user-scalable=no
    "
>

<title>Rover Control</title>


<style>

* {
    box-sizing: border-box;

    -webkit-tap-highlight-color: transparent;
}


html,
body {

    margin: 0;
    padding: 0;

    width: 100%;
    min-height: 100%;

    background: #08090d;

    color: #ffffff;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Arial,
        sans-serif;

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


.header {

    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 12px;

}


.title {

    font-size: 20px;

    font-weight: 700;

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

}


/* =========================================================
   CAMERA
   ========================================================= */

.camera-card {

    width: 100%;

    background: #111318;

    border: 1px solid #242731;

    border-radius: 16px;

    overflow: hidden;

    margin-bottom: 20px;

}


.camera {

    display: block;

    width: 100%;

    height: auto;

    background: #000;

}


/* =========================================================
   CONTROLS
   ========================================================= */

.controls {

    display: flex;

    justify-content: center;

    width: 100%;

}


.controller {

    display: grid;

    grid-template-columns:
        82px 82px 82px;

    grid-template-rows:
        82px 82px 82px;

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

    box-shadow:
        0 4px 12px rgba(0, 0, 0, 0.25);

}


button:active {

    background: #272c38;

    transform: scale(0.96);

}


button.active {

    background: #272c38;

    transform: scale(0.96);

}


.forward {

    grid-column: 2;
    grid-row: 1;

}


.left {

    grid-column: 1;
    grid-row: 2;

}


.stop {

    grid-column: 2;
    grid-row: 2;

    background: #341b23;

    border-color: #61303d;

    font-size: 16px;

    font-weight: 700;

}


.right {

    grid-column: 3;
    grid-row: 2;

}


.backward {

    grid-column: 2;
    grid-row: 3;

}


/* =========================================================
   SPEED
   ========================================================= */

.speed-card {

    margin-top: 22px;

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

        <div class="title">
            Rover Control
        </div>


        <div class="status">

            <span
                class="status-dot"
                id="statusDot"
            ></span>

            <span id="statusText">
                Connected
            </span>

        </div>

    </div>


    <!-- CAMERA -->

    <div class="camera-card">

        <img
            class="camera"
            src="/rover/stream.mjpg"
            alt="Rover Camera"
        >

    </div>


    <!-- MOVEMENT -->

    <div class="controls">

        <div class="controller">


            <button
                class="forward"
                data-command="forward"
            >
                ▲
            </button>


            <button
                class="left"
                data-command="left"
            >
                ◀
            </button>


            <button
                class="stop"
                id="stopButton"
            >
                STOP
            </button>


            <button
                class="right"
                data-command="right"
            >
                ▶
            </button>


            <button
                class="backward"
                data-command="backward"
            >
                ▼
            </button>


        </div>

    </div>


    <!-- SPEED -->

    <div class="speed-card">


        <div class="speed-header">

            <span>
                Motor Speed
            </span>

            <span id="speedValue">
                30%
            </span>

        </div>


        <input
            id="speed"
            type="range"
            min="10"
            max="100"
            value="30"
            step="5"
        >


    </div>


    <div class="info">

        Hold a direction button to move.<br>

        Release it to stop.<br>

        The rover automatically stops if communication is lost.

    </div>


</div>


<script>


// ============================================================
// STATE
// ============================================================

let speed =
    parseInt(
        document.getElementById("speed").value
    ) / 100;


let activeCommand = null;

let heartbeatTimer = null;


// ============================================================
// ELEMENTS
// ============================================================

const speedSlider =
    document.getElementById("speed");


const speedValue =
    document.getElementById("speedValue");


const statusText =
    document.getElementById("statusText");


const statusDot =
    document.getElementById("statusDot");


const movementButtons =
    document.querySelectorAll(
        "button[data-command]"
    );


// ============================================================
// SPEED
// ============================================================

speedSlider.addEventListener(
    "input",
    function () {

        speed =
            parseInt(this.value) / 100;

        speedValue.textContent =
            this.value + "%";

    }
);


// ============================================================
// SEND COMMAND
// ============================================================

async function sendCommand(command) {

    try {

        const response =
            await fetch(
                "/rover/api/control",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        command: command,
                        speed: speed
                    })
                }
            );


        if (!response.ok) {

            throw new Error(
                "Server error"
            );

        }


        statusText.textContent =
            "Connected";

        statusDot.style.background =
            "#35d07f";


    } catch (error) {

        console.error(error);

        statusText.textContent =
            "Disconnected";

        statusDot.style.background =
            "#d9534f";

    }

}


// ============================================================
// START MOVEMENT
// ============================================================

function startMovement(
    command,
    button
) {

    activeCommand = command;

    button.classList.add(
        "active"
    );


    sendCommand(command);


    clearInterval(
        heartbeatTimer
    );


    // Send commands repeatedly while
    // the button is being held.

    heartbeatTimer =
        setInterval(
            function () {

                if (activeCommand) {

                    sendCommand(
                        activeCommand
                    );

                }

            },
            150
        );

}


// ============================================================
// STOP MOVEMENT
// ============================================================

function stopMovement() {

    activeCommand = null;


    clearInterval(
        heartbeatTimer
    );


    heartbeatTimer = null;


    movementButtons.forEach(
        function (button) {

            button.classList.remove(
                "active"
            );

        }
    );


    sendCommand("stop");

}


// ============================================================
// TOUCH / MOUSE CONTROLS
// ============================================================

movementButtons.forEach(
    function (button) {


        const command =
            button.dataset.command;


        button.addEventListener(
            "pointerdown",
            function (event) {

                event.preventDefault();

                try {

                    button.setPointerCapture(
                        event.pointerId
                    );

                } catch (e) {}


                startMovement(
                    command,
                    button
                );

            }
        );


        button.addEventListener(
            "pointerup",
            function (event) {

                event.preventDefault();

                stopMovement();

            }
        );


        button.addEventListener(
            "pointercancel",
            function () {

                stopMovement();

            }
        );


        button.addEventListener(
            "lostpointercapture",
            function () {

                if (
                    activeCommand === command
                ) {

                    stopMovement();

                }

            }
        );

    }
);


// ============================================================
// STOP BUTTON
// ============================================================

document
    .getElementById("stopButton")
    .addEventListener(
        "click",
        function () {

            stopMovement();

        }
    );


// ============================================================
// KEYBOARD CONTROL
// ============================================================

const keyMap = {

    "ArrowUp": "forward",
    "w": "forward",

    "ArrowDown": "backward",
    "s": "backward",

    "ArrowLeft": "left",
    "a": "left",

    "ArrowRight": "right",
    "d": "right"

};


document.addEventListener(
    "keydown",
    function (event) {

        const command =
            keyMap[event.key];


        if (!command) {

            return;

        }


        if (
            activeCommand === command
        ) {

            return;

        }


        event.preventDefault();


        const button =
            document.querySelector(
                `[data-command="${command}"]`
            );


        if (button) {

            startMovement(
                command,
                button
            );

        }

    }
);


document.addEventListener(
    "keyup",
    function (event) {

        if (
            keyMap[event.key]
        ) {

            event.preventDefault();

            stopMovement();

        }

    }
);


// ============================================================
// BROWSER SAFETY
// ============================================================

window.addEventListener(
    "blur",
    function () {

        stopMovement();

    }
);


document.addEventListener(
    "visibilitychange",
    function () {

        if (document.hidden) {

            stopMovement();

        }

    }
);


// ============================================================
// INITIAL STOP
// ============================================================

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

@app.route(
    f"{ROVER_PATH}/stream.mjpg"
)
def video_stream():

    return Response(
        generate_frames(),
        mimetype=(
            "multipart/x-mixed-replace;"
            "boundary=FRAME"
        )
    )


# ============================================================
# MOTOR API
# ============================================================

@app.route(
    f"{ROVER_PATH}/api/control",
    methods=["POST"]
)
def control():

    data = request.get_json(
        silent=True
    ) or {}


    command = data.get(
        "command",
        "stop"
    )


    speed = data.get(
        "speed",
        DEFAULT_SPEED
    )


    try:

        speed = float(speed)

    except (
        TypeError,
        ValueError
    ):

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


    execute_command(
        command,
        speed
    )


    return jsonify({
        "success": True,
        "command": command,
        "speed": speed
    })


# ============================================================
# STATUS API
# ============================================================

@app.route(
    f"{ROVER_PATH}/api/status"
)
def status():

    with motor_lock:

        return jsonify({
            "command": current_command,
            "speed": current_speed
        })


# ============================================================
# CLEAN SHUTDOWN
# ============================================================

def shutdown():

    print()
    print("Stopping motors...")


    try:

        stop_motors()

    except Exception:

        pass


    try:

        picam2.stop_recording()

    except Exception:

        pass


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
    print(
        "=========================================="
    )

    print(
        "       RASPBERRY PI ROVER SERVER"
    )

    print(
        "=========================================="
    )

    print()

    print(
        f"Camera: "
        f"{CAMERA_WIDTH}x{CAMERA_HEIGHT}"
    )

    print(
        f"Default speed: "
        f"{int(DEFAULT_SPEED * 100)}%"
    )

    print()

    print(
        "Motor mapping:"
    )

    print(
        "LEFT  -> GPIO17 / GPIO18"
    )

    print(
        "RIGHT -> GPIO22 / GPIO23"
    )

    print()

    print(
        f"Open:"
    )

    print(
        f"http://<PI-IP>:{PORT}{ROVER_PATH}"
    )

    print()

    print(
        "Press Ctrl+C to stop."
    )

    print()


    # Make absolutely sure motors
    # start stopped.

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
        print(
            "Ctrl+C detected."
        )


    finally:

        shutdown()