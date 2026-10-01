/**
 * EdgeRover — Teleoperation Input Controller.
 * Handles touch pointer capture, keyboard bindings (WASD/Arrows),
 * throttle speed scaling, and deterministic watchdog heartbeats.
 */

class RoverTeleopController {
    constructor() {
        this.activeCommand = null;
        this.speed = 0.35;
        this.heartbeatTimer = null;
        this.heartbeatIntervalMs = 150;

        this.keyMap = {
            "ArrowUp": "forward", "w": "forward", "W": "forward",
            "ArrowDown": "backward", "s": "backward", "S": "backward",
            "ArrowLeft": "left", "a": "left", "A": "left",
            "ArrowRight": "right", "d": "right", "D": "right",
            " ": "stop", "x": "stop", "X": "stop"
        };

        this.initDpadButtons();
        this.initKeyboardControls();
        this.initSpeedSlider();
        this.initSafetyGuards();
    }

    initDpadButtons() {
        const buttons = document.querySelectorAll("[data-command]");
        buttons.forEach(button => {
            const command = button.dataset.command;

            // Pointer down (Touch / Mouse press)
            button.addEventListener("pointerdown", (e) => {
                e.preventDefault();
                try { button.setPointerCapture(e.pointerId); } catch (err) {}
                this.startMovement(command, button);
            });

            // Pointer up (Release)
            button.addEventListener("pointerup", (e) => {
                e.preventDefault();
                this.stopMovement();
            });

            // Pointer cancel / Lost capture
            button.addEventListener("pointercancel", () => this.stopMovement());
            button.addEventListener("lostpointercapture", () => {
                if (this.activeCommand === command) this.stopMovement();
            });
        });

        // E-stop buttons
        const eStopBtns = document.querySelectorAll(".btn-estop, #eStopBtn");
        eStopBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                this.stopMovement();
                if (window.roverAudio) window.roverAudio.playEstopSound();
            });
        });
    }

    initKeyboardControls() {
        document.addEventListener("keydown", (e) => {
            // Ignore if typing in text input
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

            const command = this.keyMap[e.key];
            if (!command) return;

            e.preventDefault();
            if (command === "stop") {
                this.stopMovement();
                if (window.roverAudio) window.roverAudio.playEstopSound();
                return;
            }

            if (this.activeCommand === command) return;

            const button = document.querySelector(`[data-command="${command}"]`);
            this.startMovement(command, button);
        });

        document.addEventListener("keyup", (e) => {
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
            const command = this.keyMap[e.key];
            if (command && this.activeCommand === command) {
                e.preventDefault();
                this.stopMovement();
            }
        });
    }

    initSpeedSlider() {
        const slider = document.getElementById("speedSlider");
        const readout = document.getElementById("speedValueReadout");
        const metricSpeed = document.getElementById("metricSpeed");

        if (slider) {
            slider.addEventListener("input", (e) => {
                const pct = parseInt(e.target.value);
                this.speed = pct / 100.0;
                if (readout) readout.textContent = `${pct}%`;
                if (metricSpeed) metricSpeed.textContent = `${pct}%`;
            });
        }
    }

    initSafetyGuards() {
        // Automatic stop if window loses focus or user switches browser tabs
        window.addEventListener("blur", () => this.stopMovement());
        document.addEventListener("visibilitychange", () => {
            if (document.hidden) this.stopMovement();
        });
    }

    startMovement(command, buttonElement) {
        this.activeCommand = command;

        // Visual feedback
        if (buttonElement) buttonElement.classList.add("active");

        // Transmit immediate drive command
        this.dispatchCommand(command);

        // Maintain continuous heartbeat while held
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = setInterval(() => {
            if (this.activeCommand) {
                this.dispatchCommand(this.activeCommand);
            }
        }, this.heartbeatIntervalMs);
    }

    stopMovement() {
        this.activeCommand = null;
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;

        // Clear button active styles
        document.querySelectorAll("[data-command]").forEach(btn => btn.classList.remove("active"));

        // Transmit active stop
        this.dispatchCommand("stop");
    }

    dispatchCommand(command) {
        if (window.roverWs) {
            window.roverWs.sendDriveCommand(command, this.speed);
        }
    }
}

window.RoverTeleopController = RoverTeleopController;
