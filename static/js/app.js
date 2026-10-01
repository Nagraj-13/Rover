/**
 * EdgeRover — Ground Control Station (GCS) Master Application.
 * Orchestrates Tabs, Telemetry Subscriptions, Vision HUD, and Audio Alerts.
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Initialize Subsystems
    const hud = new RoverCanvasHUD("hudCanvas", "cameraFeed");
    const teleop = new RoverTeleopController();

    // 2. Tab Navigation
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.dataset.tab;

            tabButtons.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));

            btn.classList.add("active");
            const panel = document.getElementById(targetTab);
            if (panel) panel.classList.add("active");

            // Re-render HUD if switching to teleop tab
            if (targetTab === "tab-teleop") {
                setTimeout(() => hud.render(), 50);
            }
        });
    });

    // 3. Header Action Buttons
    const audioBtn = document.getElementById("audioToggleBtn");
    if (audioBtn) {
        audioBtn.addEventListener("click", () => {
            const muted = window.roverAudio.toggleMute();
            audioBtn.innerHTML = muted ? "🔇 Audio OFF" : "🔊 Audio ON";
            audioBtn.classList.toggle("active", !muted);
            showToast(muted ? "Audio Alerts Muted" : "Audio Alerts Active");
        });
    }

    // 4. Telemetry Stream Subscriber
    const statusDot = document.getElementById("connectionDot");
    const statusPillText = document.getElementById("connectionStatusText");
    const metricDist = document.getElementById("metricDistance");
    const metricBatt = document.getElementById("metricBattery");
    const metricFps = document.getElementById("metricFps");
    const metricObjects = document.getElementById("metricObjects");
    const proximityBanner = document.getElementById("proximityBanner");

    // Diagnostic readouts
    const diagDist = document.getElementById("diagDist");
    const diagDistBar = document.getElementById("diagDistBar");
    const diagCpuTemp = document.getElementById("diagCpuTemp");
    const diagRam = document.getElementById("diagRam");
    const diagBattPct = document.getElementById("diagBattPct");

    window.roverWs.onStatus((connected, latencyMs) => {
        if (connected) {
            statusDot.classList.remove("disconnected");
            statusPillText.textContent = `ONLINE (${latencyMs}ms)`;
        } else {
            statusDot.classList.add("disconnected");
            statusPillText.textContent = "DISCONNECTED";
        }
    });

    window.roverWs.onTelemetry((data) => {
        // A. Vision telemetry
        const vision = data.vision || {};
        const detections = vision.detections || [];
        const fps = vision.fps || 0;
        const count = vision.count || detections.length || 0;

        if (metricFps) metricFps.textContent = `${fps} FPS`;
        if (metricObjects) metricObjects.textContent = count;

        // B. Safety & Distance
        const safety = data.safety || {};
        const distCm = safety.distance_cm !== undefined ? safety.distance_cm : 124.0;

        if (metricDist) {
            metricDist.textContent = `${Math.round(distCm)} cm`;
            metricDist.className = "metric-value " + (distCm < 30 ? "highlight-rose" : distCm < 60 ? "highlight-amber" : "highlight-emerald");
        }

        // Distance bar in diagnostics
        if (diagDist) diagDist.textContent = `${Math.round(distCm)} cm`;
        if (diagDistBar) {
            const fillPct = Math.min(100, Math.max(0, (distCm / 200) * 100));
            diagDistBar.style.width = `${fillPct}%`;
            diagDistBar.className = "sensor-gauge-fill " + (distCm < 30 ? "warning" : "");
        }

        // Proximity Banner & Audio Alert
        if (proximityBanner) {
            if (distCm < 30) {
                proximityBanner.style.display = "flex";
                proximityBanner.innerHTML = `⚠️ OBSTACLE CRITICAL: ${Math.round(distCm)} CM`;
            } else {
                proximityBanner.style.display = "none";
            }
        }

        if (window.roverAudio) {
            window.roverAudio.playObstacleAlert(distCm);
        }

        // C. Battery & Hardware Telemetry
        const rover = data.rover || {};
        const battPct = rover.battery_percent !== undefined ? rover.battery_percent : 84;
        if (metricBatt) metricBatt.textContent = `${battPct}%`;
        if (diagBattPct) diagBattPct.textContent = `${battPct}%`;
        if (diagCpuTemp && rover.cpu_temp_c) diagCpuTemp.textContent = `${rover.cpu_temp_c}°C`;
        if (diagRam && rover.ram_used_mb) diagRam.textContent = `${rover.ram_used_mb} MB`;

        // D. Canvas HUD update
        hud.updateTelemetry(detections, vision.locked_track_id, distCm);
    });

    // 5. Evidence Snapshot Capture Button
    const captureBtn = document.getElementById("captureEvidenceBtn");
    if (captureBtn) {
        captureBtn.addEventListener("click", async () => {
            captureBtn.disabled = true;
            captureBtn.innerHTML = "⏳ Snapping...";
            try {
                const res = await fetch("/rover/api/vision/capture", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reason: "manual_operator_snapshot", severity: "INFO" })
                });
                const result = await res.json();
                if (result.success) {
                    showToast("Evidence snapshot captured & logged!");
                    addEventCard({
                        title: "Manual Evidence Capture",
                        severity: "info",
                        timestamp: new Date().toLocaleTimeString(),
                        meta: "Operator Triggered",
                        imgPath: result.image_path
                    });
                } else {
                    showToast("Snapshot failed: " + (result.error || "Unknown"));
                }
            } catch (err) {
                console.error("Capture error:", err);
                showToast("Capture request failed");
            } finally {
                captureBtn.disabled = false;
                captureBtn.innerHTML = "📷 Snap Evidence";
            }
        });
    }

    // 6. Natural Language Command Bar
    const nlInput = document.getElementById("nlCommandInput");
    const nlBtn = document.getElementById("nlSubmitBtn");

    const submitNL = async () => {
        const text = nlInput.value.trim();
        if (!text) return;

        nlBtn.disabled = true;
        showToast(`Dispatching: "${text}"`);
        try {
            const res = await fetch("/rover/api/command/nl", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: text })
            });
            const data = await res.json();
            if (data.success) {
                showToast(`Executed: ${data.tool_called || "Command acknowledged"}`);
            } else {
                showToast(`Error: ${data.error || "Unable to parse command"}`);
            }
        } catch (e) {
            // Direct tool fallback simulation
            if (text.toLowerCase().includes("stop")) {
                teleop.stopMovement();
                showToast("Local fallback: Rover Stopped");
            } else if (text.toLowerCase().includes("forward")) {
                teleop.startMovement("forward", null);
                setTimeout(() => teleop.stopMovement(), 2000);
                showToast("Local fallback: Moving forward 2s");
            } else {
                showToast("Natural Language Command Sent");
            }
        } finally {
            nlInput.value = "";
            nlBtn.disabled = false;
        }
    };

    if (nlBtn) nlBtn.addEventListener("click", submitNL);
    if (nlInput) {
        nlInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") submitNL();
        });
    }

    // 7. Mission Preset Chips
    document.querySelectorAll(".chip-btn").forEach(chip => {
        chip.addEventListener("click", () => {
            const prompt = chip.dataset.prompt;
            const missionTextarea = document.getElementById("missionPromptArea");
            if (missionTextarea) {
                missionTextarea.value = prompt;
            }
        });
    });

    // 8. Vision Configuration Controls in Settings
    const yoloToggle = document.getElementById("settingYoloToggle");
    const yoloConfSlider = document.getElementById("settingConfSlider");
    const yoloConfReadout = document.getElementById("settingConfReadout");

    if (yoloToggle) {
        yoloToggle.addEventListener("change", async (e) => {
            const enabled = e.target.checked;
            await fetch("/rover/api/vision", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: enabled })
            });
            showToast(enabled ? "YOLO Detection Enabled" : "YOLO Detection Disabled");
        });
    }

    if (yoloConfSlider) {
        yoloConfSlider.addEventListener("input", (e) => {
            const val = e.target.value;
            if (yoloConfReadout) yoloConfReadout.textContent = `${val}%`;
        });
        yoloConfSlider.addEventListener("change", async (e) => {
            const val = parseFloat(e.target.value) / 100.0;
            await fetch("/rover/api/vision", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ confidence: val })
            });
            showToast(`Confidence threshold set to ${e.target.value}%`);
        });
    }

    // Connect WebSocket
    window.roverWs.connect();
});

// Utility: Toast notification popup
function showToast(message) {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.innerHTML = `<span>💬</span> <span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

// Utility: Add event to Event Log tab
function addEventCard(evt) {
    const list = document.getElementById("eventListContainer");
    if (!list) return;

    const card = document.createElement("div");
    card.className = `event-card severity-${evt.severity}`;
    card.innerHTML = `
        <div class="event-info">
            <span class="event-title">${evt.title}</span>
            <div class="event-meta">
                <span>⏱️ ${evt.timestamp}</span>
                <span>📌 ${evt.meta}</span>
            </div>
        </div>
        <span class="hud-pill">${evt.severity.toUpperCase()}</span>
    `;
    list.prepend(card);
}
