/**
 * EdgeRover — High-Frequency Bi-directional Telemetry & WebSocket Client.
 * Manages continuous real-time data streaming, latency tracking, and drive dispatch.
 */

class RoverTelemetryClient {
    constructor() {
        this.socket = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 30;
        this.reconnectInterval = 1000;
        this.pingIntervalMs = 2000;
        this.pingTimer = null;
        this.lastPingSentTime = 0;
        this.latencyMs = 0;

        // Callbacks
        this.telemetryListeners = [];
        this.statusListeners = [];

        // Fallback polling timer (if WebSocket is blocked or not available)
        this.fallbackPollTimer = null;
        this.useFallback = false;
    }

    connect() {
        if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws/telemetry`;

        try {
            this.socket = new WebSocket(wsUrl);
            this.socket.binaryType = "blob";

            this.socket.onopen = () => {
                this.isConnected = true;
                this.wsFailed = false;
                this.reconnectAttempts = 0;
                this.stopFallbackPolling();
                this.notifyStatus(true, this.latencyMs);
                this.startPingLoop();
                console.log("[RoverWS] Connected to telemetry stream.");
            };

            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    if (data.type === "pong") {
                        const now = performance.now();
                        this.latencyMs = Math.round(now - this.lastPingSentTime);
                        this.notifyStatus(true, this.latencyMs);
                        return;
                    }

                    // Standard telemetry packet
                    this.notifyTelemetry(data);
                } catch (e) {
                    console.error("[RoverWS] Failed to parse message:", e);
                }
            };

            this.socket.onerror = (err) => {
                this.wsFailed = true;
                this.startFallbackPolling();
            };

            this.socket.onclose = (event) => {
                this.isConnected = false;
                this.stopPingLoop();
                if (this.wsFailed) {
                    // Backend is in HTTP mode; stay on fast fallback polling without retry spam
                    this.startFallbackPolling();
                    return;
                }
                this.scheduleReconnect();
            };

        } catch (e) {
            this.wsFailed = true;
            this.startFallbackPolling();
        }
    }

    scheduleReconnect() {
        if (this.wsFailed || this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.startFallbackPolling();
            return;
        }

        const delay = Math.min(5000, this.reconnectInterval * Math.pow(1.3, this.reconnectAttempts));
        this.reconnectAttempts++;
        setTimeout(() => this.connect(), delay);
    }

    startPingLoop() {
        this.stopPingLoop();
        this.pingTimer = setInterval(() => {
            if (this.isConnected && this.socket.readyState === WebSocket.OPEN) {
                this.lastPingSentTime = performance.now();
                this.socket.send(JSON.stringify({ action: "ping" }));
            }
        }, this.pingIntervalMs);
    }

    stopPingLoop() {
        if (this.pingTimer) {
            clearInterval(this.pingTimer);
            this.pingTimer = null;
        }
    }

    sendDriveCommand(command, speed) {
        const payload = {
            action: "drive",
            command: command,
            speed: parseFloat(speed),
            client_time: Date.now()
        };

        if (this.isConnected && this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(payload));
        } else {
            // REST Fallback
            fetch("/rover/api/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ command: command, speed: speed })
            }).catch(e => console.error("[RoverWS] REST drive failed:", e));
        }
    }

    sendNLCommand(text) {
        return fetch("/api/command/nl", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: text })
        }).then(res => res.json());
    }

    // Fallback polling for pure Flask or environments where WebSockets are unavailable
    startFallbackPolling() {
        if (this.fallbackPollTimer) return;
        this.useFallback = true;

        this.fallbackPollTimer = setInterval(async () => {
            try {
                const t0 = performance.now();
                const res = await fetch("/rover/api/detections");
                if (res.ok) {
                    const data = await res.json();
                    this.latencyMs = Math.round(performance.now() - t0);
                    this.notifyStatus(true, this.latencyMs);
                    this.notifyTelemetry({ vision: data });
                }
            } catch (e) {
                this.notifyStatus(false, 0);
            }
        }, 120);
    }

    stopFallbackPolling() {
        if (this.fallbackPollTimer) {
            clearInterval(this.fallbackPollTimer);
            this.fallbackPollTimer = null;
        }
        this.useFallback = false;
    }

    onTelemetry(callback) {
        this.telemetryListeners.push(callback);
    }

    onStatus(callback) {
        this.statusListeners.push(callback);
    }

    notifyTelemetry(data) {
        for (const cb of this.telemetryListeners) {
            try { cb(data); } catch (e) { console.error("Telemetry subscriber error:", e); }
        }
    }

    notifyStatus(connected, latency) {
        for (const cb of this.statusListeners) {
            try { cb(connected, latency); } catch (e) { console.error("Status subscriber error:", e); }
        }
    }
}

// Global instance
window.roverWs = new RoverTelemetryClient();
