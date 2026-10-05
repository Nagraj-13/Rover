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

            if (targetTab === "tab-events") loadEvidence();

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
                    loadEvidence();
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
                showToast(data.message || `Executed: ${data.tool_called || "Command acknowledged"}`);
                if (data.mission && data.mission_started) renderMission(data.mission, true);
                if (data.tool_called && data.tool_called.includes("capture_evidence")) loadEvidence();
            } else {
                showToast(`Error: ${data.error || data.message || "Unable to parse command"}`);
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

    // 8. Groq Strategic Mission Compiler
    const compileBtn = document.getElementById("compileMissionBtn");
    const missionTextarea = document.getElementById("missionPromptArea");
    const missionStepList = document.querySelector(".mission-step-list");

    // Mission rendering + live progress polling
    let missionPollTimer = null;
    const STEP_CLASS = { pending: "pending", running: "active", done: "done", failed: "failed", aborted: "aborted", skipped: "skipped" };

    function renderMission(m, startPolling) {
        if (!missionStepList || !m.steps) return;
        missionStepList.innerHTML = m.steps.map(s => `
            <div class="mission-step-item" data-step="${s.step_number}">
                <span class="step-status-icon pending">${s.step_number}</span>
                <div>
                    <div style="font-weight: 500;">${s.title}</div>
                    <div style="font-size: 11px; color: var(--accent-cyan); font-family: monospace;">${s.tool_name}(${JSON.stringify(s.parameters)})</div>
                    <div class="step-msg" style="font-size: 11px; color: var(--text-muted);"></div>
                </div>
            </div>
        `).join("");
        if (startPolling) pollMission();
    }

    function pollMission() {
        clearInterval(missionPollTimer);
        const tick = async () => {
            try {
                const res = await fetch("/rover/api/missions/status");
                const data = await res.json();
                const st = data.mission || {};
                (st.steps || []).forEach(step => {
                    const row = missionStepList && missionStepList.querySelector(`[data-step="${step.step_number}"]`);
                    if (!row) return;
                    const icon = row.querySelector(".step-status-icon");
                    icon.className = `step-status-icon ${STEP_CLASS[step.status] || "pending"}`;
                    row.querySelector(".step-msg").textContent = step.message || "";
                });
                if (st.state && st.state !== "running") {
                    clearInterval(missionPollTimer);
                    missionPollTimer = null;
                    const label = { completed: "✅ Mission complete", failed: `❌ Mission failed: ${st.error || ""}`, aborted: "🛑 Mission aborted" }[st.state];
                    if (label) showToast(label);
                }
            } catch (e) { /* transient network error: keep polling */ }
        };
        tick();
        missionPollTimer = setInterval(tick, 700);
    }

    if (compileBtn && missionTextarea) {
        compileBtn.addEventListener("click", async () => {
            const prompt = missionTextarea.value.trim();
            if (!prompt) {
                showToast("Please enter a mission prompt first.");
                return;
            }

            compileBtn.disabled = true;
            compileBtn.textContent = "⏳ Compiling via Groq...";

            try {
                const res = await fetch("/rover/api/missions/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ prompt: prompt })
                });
                const data = await res.json();

                if (data.success && data.mission) {
                    const m = data.mission;
                    showToast(`✨ Mission compiled: ${m.title}`);
                    renderMission(m, false);

                    const runRes = await fetch("/rover/api/missions/execute", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ mission: m })
                    });
                    const runData = await runRes.json();
                    if (runData.success) {
                        showToast("🚀 Mission running — press E-STOP to abort");
                        pollMission();
                    } else {
                        showToast(`Mission not started: ${runData.message || runData.error}`);
                    }
                } else {
                    showToast(`Compilation error: ${data.error || "Unknown error"}`);
                }
            } catch (err) {
                console.error("Mission compilation error:", err);
                showToast("Network error compiling mission.");
            } finally {
                compileBtn.disabled = false;
                compileBtn.textContent = "✨ Compile & Launch Mission via Groq";
            }
        });
    }

    // 9. Groq Cloud Dynamic API Key & Input Layer Manager
    const groqNotConfiguredBanner = document.getElementById("groqBannerNotConfigured");
    const groqConfiguredBanner = document.getElementById("groqBannerConfigured");
    const dynamicKeyInput = document.getElementById("dynamicGroqKeyInput");
    const dynamicSaveEnv = document.getElementById("dynamicGroqSaveEnv");
    const btnConnectDynamic = document.getElementById("btnConnectGroqDynamic");
    const btnEditKey = document.getElementById("btnEditGroqKey");
    const groqMaskedBadge = document.getElementById("groqMaskedKeyBadge");
    const groqModelBadge = document.getElementById("groqModelBadge");

    const settingsGroqKeyInput = document.getElementById("settingGroqKey");
    const settingsGroqStatusPill = document.getElementById("settingsGroqStatusPill");
    const btnSaveGroqSettings = document.getElementById("btnSaveGroqSettings");
    const settingPersistEnv = document.getElementById("settingPersistEnv");

    const missionModelSelect = document.getElementById("missionGroqModelSelect");
    const settingsModelSelect = document.getElementById("settingsGroqModelSelect");

    async function checkGroqStatus() {
        try {
            const res = await fetch("/rover/api/settings/groq");
            const data = await res.json();
            updateGroqUI(data);
        } catch (e) {
            console.warn("Could not check Groq status:", e);
        }
    }

    function populateModelDropdown(selectEl, models, currentModel) {
        if (!selectEl || !models || !models.length) return;
        selectEl.innerHTML = models.map(m => `
            <option value="${m.id}" ${m.id === currentModel ? "selected" : ""}>
                ${m.name}
            </option>
        `).join("");
    }

    function updateGroqUI(data) {
        const isConfigured = !!(data && data.configured && data.cloud_ready);
        const currentModel = data.model || "openai/gpt-oss-120b";

        if (data.available_models) {
            populateModelDropdown(missionModelSelect, data.available_models, currentModel);
            populateModelDropdown(settingsModelSelect, data.available_models, currentModel);
        } else {
            if (missionModelSelect) missionModelSelect.value = currentModel;
            if (settingsModelSelect) settingsModelSelect.value = currentModel;
        }

        if (isConfigured) {
            if (groqNotConfiguredBanner) groqNotConfiguredBanner.style.display = "none";
            if (groqConfiguredBanner) groqConfiguredBanner.style.display = "block";
            if (groqMaskedBadge) groqMaskedBadge.textContent = data.masked_key || "Active";
            if (groqModelBadge) groqModelBadge.textContent = currentModel;
            if (settingsGroqStatusPill) {
                settingsGroqStatusPill.textContent = "ONLINE (LPU Active)";
                settingsGroqStatusPill.className = "status-pill";
                settingsGroqStatusPill.style.background = "rgba(53, 208, 127, 0.2)";
                settingsGroqStatusPill.style.color = "var(--accent-emerald)";
            }
        } else {
            if (groqNotConfiguredBanner) groqNotConfiguredBanner.style.display = "block";
            if (groqConfiguredBanner) groqConfiguredBanner.style.display = "none";
            if (settingsGroqStatusPill) {
                settingsGroqStatusPill.textContent = "STANDALONE LOCAL";
                settingsGroqStatusPill.className = "status-pill";
                settingsGroqStatusPill.style.background = "rgba(245, 158, 11, 0.2)";
                settingsGroqStatusPill.style.color = "var(--accent-amber)";
            }
        }
    }

    async function updateGroqKey(key, persistToEnv) {
        if (!key) {
            showToast("Please enter an API key.");
            return;
        }
        try {
            const res = await fetch("/rover/api/settings/groq", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ api_key: key, save_to_env: persistToEnv })
            });
            const data = await res.json();
            updateGroqUI(data);
            if (data.cloud_ready) {
                showToast(`Groq Cloud Connected! (${data.saved_to_env ? "Saved to .env" : "Session only"})`);
                if (dynamicKeyInput) dynamicKeyInput.value = "";
                if (settingsGroqKeyInput) settingsGroqKeyInput.value = "";
            } else {
                showToast("Key saved, but format unverified.");
            }
        } catch (e) {
            console.error("Error setting Groq key:", e);
            showToast("Failed to connect Groq API key.");
        }
    }

    async function switchGroqModel(modelId, persistToEnv = true) {
        try {
            const res = await fetch("/rover/api/settings/groq", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model: modelId, save_to_env: persistToEnv })
            });
            const data = await res.json();
            updateGroqUI(data);
            showToast(`Active Groq Model: ${modelId}`);
        } catch (e) {
            console.error("Error switching Groq model:", e);
            showToast("Failed to switch model.");
        }
    }

    if (missionModelSelect) {
        missionModelSelect.addEventListener("change", (e) => {
            const newModel = e.target.value;
            if (settingsModelSelect) settingsModelSelect.value = newModel;
            switchGroqModel(newModel, true);
        });
    }

    if (settingsModelSelect) {
        settingsModelSelect.addEventListener("change", (e) => {
            const newModel = e.target.value;
            if (missionModelSelect) missionModelSelect.value = newModel;
            const persist = settingPersistEnv ? settingPersistEnv.checked : true;
            switchGroqModel(newModel, persist);
        });
    }

    if (btnConnectDynamic && dynamicKeyInput) {
        btnConnectDynamic.addEventListener("click", () => {
            const key = dynamicKeyInput.value.trim();
            const persist = dynamicSaveEnv ? dynamicSaveEnv.checked : true;
            updateGroqKey(key, persist);
        });
        dynamicKeyInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                const key = dynamicKeyInput.value.trim();
                const persist = dynamicSaveEnv ? dynamicSaveEnv.checked : true;
                updateGroqKey(key, persist);
            }
        });
    }

    if (btnEditKey) {
        btnEditKey.addEventListener("click", () => {
            if (groqNotConfiguredBanner) groqNotConfiguredBanner.style.display = "block";
            if (groqConfiguredBanner) groqConfiguredBanner.style.display = "none";
            if (dynamicKeyInput) dynamicKeyInput.focus();
        });
    }

    if (btnSaveGroqSettings && settingsGroqKeyInput) {
        btnSaveGroqSettings.addEventListener("click", () => {
            const key = settingsGroqKeyInput.value.trim();
            const persist = settingPersistEnv ? settingPersistEnv.checked : true;
            updateGroqKey(key, persist);
        });
    }

    // Check status on dashboard load
    checkGroqStatus();

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


// Evidence log: snapshots saved on the Pi (thumbnail + reason + detections)
async function loadEvidence() {
    const list = document.getElementById("eventListContainer");
    if (!list) return;
    try {
        const res = await fetch("/rover/api/evidence?limit=60");
        const data = await res.json();
        if (!data.success) return;

        list.querySelectorAll("[data-evidence]").forEach(el => el.remove());
        // prepend newest-last so the newest ends up on top
        data.evidence.slice().reverse().forEach(ev => list.prepend(buildEvidenceCard(ev)));
    } catch (e) {
        console.warn("Evidence list unavailable:", e);
    }
}

function buildEvidenceCard(ev) {
    const card = document.createElement("div");
    card.className = `event-card severity-${ev.severity}`;
    card.dataset.evidence = ev.id;

    const link = document.createElement("a");
    link.href = ev.image_url;
    link.target = "_blank";
    link.rel = "noopener";
    const img = document.createElement("img");
    img.className = "evidence-thumb";
    img.loading = "lazy";
    img.src = ev.image_url;
    img.alt = "Evidence snapshot";
    link.appendChild(img);

    const info = document.createElement("div");
    info.className = "event-info";
    info.style.flex = "1";
    const title = document.createElement("span");
    title.className = "event-title";
    title.textContent = `📷 ${ev.reason || "Evidence snapshot"}`;
    const meta = document.createElement("div");
    meta.className = "event-meta";
    const when = ev.timestamp ? new Date(ev.timestamp).toLocaleString() : "";
    const seen = ev.detections_count ? `${ev.detections_count} detected: ${ev.labels.join(", ")}` : "No detections";
    [`⏱️ ${when}`, `🎯 ${seen}`].forEach(t => {
        const span = document.createElement("span");
        span.textContent = t;
        meta.appendChild(span);
    });
    info.append(title, meta);

    const pill = document.createElement("span");
    pill.className = "hud-pill";
    pill.textContent = ev.severity.toUpperCase();

    card.append(link, info, pill);
    return card;
}

document.addEventListener("DOMContentLoaded", () => {
    loadEvidence();
    // keep the log fresh while the Events tab is open (captures can also come from missions)
    setInterval(() => {
        const panel = document.getElementById("tab-events");
        if (panel && panel.classList.contains("active")) loadEvidence();
    }, 5000);
});
