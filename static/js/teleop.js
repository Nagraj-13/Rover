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

            // Touch events for mobile devices (prevents pinch/scroll and ghost cancels)
            button.addEventListener("touchstart", (e) => {
                e.preventDefault();
                this.startMovement(command, button);
            }, { passive: false });

            button.addEventListener("touchend", (e) => {
                e.preventDefault();
                if (this.activeCommand === command) {
                    this.stopMovement();
                }
            }, { passive: false });

            button.addEventListener("touchcancel", (e) => {
                e.preventDefault();
                if (this.activeCommand === command) {
                    this.stopMovement();
                }
            }, { passive: false });

            // Mouse events for desktop browsers
            button.addEventListener("mousedown", (e) => {
                if (e.button !== 0) return; // Left mouse button only
                this.startMovement(command, button);
            });

            button.addEventListener("mouseup", (e) => {
                if (this.activeCommand === command) {
                    this.stopMovement();
                }
            });

            button.addEventListener("mouseleave", (e) => {
                if (this.activeCommand === command) {
                    this.stopMovement();
                }
            });
        });

        // Global safety release if mouse button released outside target
        document.addEventListener("mouseup", () => {
            if (this.activeCommand) this.stopMovement();
        });
        document.addEventListener("touchend", (e) => {
            if (e.touches.length === 0 && this.activeCommand) {
                this.stopMovement();
            }
        });

        // E-stop buttons
        const eStopBtns = document.querySelectorAll(".btn-estop, #eStopBtn");
        eStopBtns.forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                this.stopMovement(true);
                if (window.roverAudio) window.roverAudio.playEstopSound();
            });
            btn.addEventListener("touchstart", (e) => {
                e.preventDefault();
                this.stopMovement(true);
                if (window.roverAudio) window.roverAudio.playEstopSound();
            }, { passive: false });
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
                this.stopMovement(true);
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

    // force=true is for deliberate e-stops: it is sent even when no button is held,
    // which also aborts a running mission. Passive stops (tab blur, button release)
    // only fire when this controller was actually driving, so they never cancel a mission.
    stopMovement(force = false) {
        const wasDriving = this.activeCommand !== null;
        this.activeCommand = null;
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;

        // Clear button active styles
        document.querySelectorAll("[data-command]").forEach(btn => btn.classList.remove("active"));

        // Transmit active stop
        if (wasDriving || force) this.dispatchCommand("stop");
    }

    dispatchCommand(command) {
        if (window.roverWs) {
            window.roverWs.sendDriveCommand(command, this.speed);
        }
    }
}

window.RoverTeleopController = RoverTeleopController;
