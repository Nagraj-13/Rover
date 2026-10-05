/**
 * EdgeRover — Canvas HUD & Tactical Computer Vision Overlay.
 * Renders corner brackets, crosshairs, distance estimation tags,
 * and handles interactive touch-to-lock targeting.
 */

class RoverCanvasHUD {
    constructor(canvasId, videoFeedId) {
        this.canvas = document.getElementById(canvasId);
        this.videoFeed = document.getElementById(videoFeedId);
        if (!this.canvas) return;

        this.ctx = this.canvas.getContext("2d");
        this.detections = [];
        this.lockedTrackId = null;
        this.frontDistanceCm = null;

        this.initResizeObserver();
        this.initClickToLock();
    }

    initResizeObserver() {
        const resize = () => {
            if (this.videoFeed && this.videoFeed.clientWidth > 0) {
                this.canvas.width = this.videoFeed.clientWidth;
                this.canvas.height = this.videoFeed.clientHeight;
                this.render();
            }
        };

        const ro = new ResizeObserver(resize);
        if (this.videoFeed) ro.observe(this.videoFeed);
        window.addEventListener("resize", resize);
        if (this.videoFeed) this.videoFeed.addEventListener("load", resize);
    }

    initClickToLock() {
        this.canvas.addEventListener("click", (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const clickX = (e.clientX - rect.left) / this.canvas.width;
            const clickY = (e.clientY - rect.top) / this.canvas.height;

            // Find clicked bounding box
            for (const det of this.detections) {
                const b = det.rel_box;
                if (!b || b.length !== 4) continue;
                if (clickX >= b[0] && clickX <= b[2] && clickY >= b[1] && clickY <= b[3]) {
                    this.toggleLock(det.track_id);
                    return;
                }
            }

            // Clicked empty area -> release lock
            if (this.lockedTrackId !== null) {
                this.toggleLock(null);
            }
        });
    }

    toggleLock(trackId) {
        fetch("/rover/api/vision/lock", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ track_id: trackId })
        }).then(res => res.json()).then(data => {
            this.lockedTrackId = data.locked ? data.locked_track_id : null;
            const lockPill = document.getElementById("hudTargetLockPill");
            if (lockPill) {
                if (this.lockedTrackId !== null) {
                    lockPill.classList.add("active");
                    lockPill.textContent = `TARGET LOCKED: #${this.lockedTrackId}`;
                } else {
                    lockPill.classList.remove("active");
                }
            }
            this.render();
        }).catch(err => console.error("Lock error:", err));
    }

    updateTelemetry(detections, lockedTrackId, frontDistanceCm) {
        this.detections = detections || [];
        this.lockedTrackId = lockedTrackId !== undefined ? lockedTrackId : this.lockedTrackId;
        this.frontDistanceCm = frontDistanceCm !== undefined ? frontDistanceCm : this.frontDistanceCm;
        this.render();
    }

    render() {
        let cw = this.canvas.width;
        let ch = this.canvas.height;
        if (cw === 0 || ch === 0) {
            if (this.videoFeed && this.videoFeed.clientWidth > 0) {
                this.canvas.width = this.videoFeed.clientWidth;
                this.canvas.height = this.videoFeed.clientHeight;
                cw = this.canvas.width;
                ch = this.canvas.height;
            } else {
                return;
            }
        }

        this.ctx.clearRect(0, 0, cw, ch);

        // 1. Draw Center Tactical Reticle
        this.drawCenterReticle(cw, ch);

        // 2. Draw Proximity Radar Arc
        if (this.frontDistanceCm !== null) {
            this.drawProximityArc(cw, ch, this.frontDistanceCm);
        }

        // 3. Render Object Bounding Boxes
        for (const det of this.detections) {
            this.drawBoundingBox(det, cw, ch);
        }
    }

    drawCenterReticle(cw, ch) {
        const cx = cw / 2;
        const cy = ch / 2;
        const len = 14;

        this.ctx.strokeStyle = "rgba(56, 189, 248, 0.4)";
        this.ctx.lineWidth = 1.5;

        // Crosshairs
        this.ctx.beginPath();
        this.ctx.moveTo(cx - len, cy);
        this.ctx.lineTo(cx - 4, cy);
        this.ctx.moveTo(cx + 4, cy);
        this.ctx.lineTo(cx + len, cy);
        this.ctx.moveTo(cx, cy - len);
        this.ctx.lineTo(cx, cy - 4);
        this.ctx.moveTo(cx, cy + 4);
        this.ctx.lineTo(cx, cy + len);
        this.ctx.stroke();

        // Subtle center dot
        this.ctx.beginPath();
        this.ctx.arc(cx, cy, 1.5, 0, 2 * Math.PI);
        this.ctx.fillStyle = "rgba(56, 189, 248, 0.8)";
        this.ctx.fill();
    }

    drawProximityArc(cw, ch, distanceCm) {
        const cx = cw / 2;
        const cy = ch - 20;

        let color = "rgba(53, 208, 127, 0.4)";
        if (distanceCm < 30) {
            color = "rgba(244, 63, 94, 0.9)";
        } else if (distanceCm < 60) {
            color = "rgba(245, 158, 11, 0.75)";
        }

        this.ctx.save();
        this.ctx.beginPath();
        this.ctx.arc(cx, cy, 40, Math.PI, 2 * Math.PI);
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 4;
        this.ctx.stroke();

        // Distance text
        this.ctx.font = "bold 11px sans-serif";
        this.ctx.fillStyle = color;
        this.ctx.textAlign = "center";
        this.ctx.fillText(`${Math.round(distanceCm)} cm`, cx, cy - 48);
        this.ctx.restore();
    }

    drawBoundingBox(det, cw, ch) {
        const rel = det.rel_box;
        if (!rel || rel.length !== 4) return;

        const x1 = rel[0] * cw;
        const y1 = rel[1] * ch;
        const x2 = rel[2] * cw;
        const y2 = rel[3] * ch;
        const w = x2 - x1;
        const h = y2 - y1;

        const isLocked = (det.track_id !== undefined && det.track_id !== null && det.track_id === this.lockedTrackId);
        const primaryColor = isLocked ? "#f59e0b" : "#35d07f";
        const cornerLen = Math.max(8, Math.min(22, Math.min(w, h) * 0.25));

        this.ctx.save();

        // 1. Semi-transparent fill
        this.ctx.fillStyle = isLocked ? "rgba(245, 158, 11, 0.12)" : "rgba(53, 208, 127, 0.08)";
        this.ctx.fillRect(x1, y1, w, h);

        // 2. Corner Brackets
        this.ctx.strokeStyle = primaryColor;
        this.ctx.lineWidth = isLocked ? 3.0 : 2.0;
        this.ctx.shadowColor = primaryColor;
        this.ctx.shadowBlur = isLocked ? 10 : 5;

        // Top-left
        this.ctx.beginPath();
        this.ctx.moveTo(x1, y1 + cornerLen);
        this.ctx.lineTo(x1, y1);
        this.ctx.lineTo(x1 + cornerLen, y1);
        // Top-right
        this.ctx.moveTo(x2 - cornerLen, y1);
        this.ctx.lineTo(x2, y1);
        this.ctx.lineTo(x2, y1 + cornerLen);
        // Bottom-left
        this.ctx.moveTo(x1, y2 - cornerLen);
        this.ctx.lineTo(x1, y2);
        this.ctx.lineTo(x1 + cornerLen, y2);
        // Bottom-right
        this.ctx.moveTo(x2 - cornerLen, y2);
        this.ctx.lineTo(x2, y2);
        this.ctx.lineTo(x2, y2 - cornerLen);
        this.ctx.stroke();

        // 3. Center Crosshair on Target
        const bxCx = (x1 + x2) / 2;
        const bxCy = (y1 + y2) / 2;
        this.ctx.beginPath();
        this.ctx.arc(bxCx, bxCy, 3, 0, 2 * Math.PI);
        this.ctx.fillStyle = primaryColor;
        this.ctx.fill();

        // 4. Label Badge
        this.ctx.shadowBlur = 0;
        const trackPrefix = (det.track_id !== undefined && det.track_id !== null) ? `#${det.track_id} ` : "";
        const distSuffix = det.estimated_distance_cm ? ` [${Math.round(det.estimated_distance_cm)}cm]` : "";
        const labelText = `${trackPrefix}${det.label.toUpperCase()} ${Math.round(det.confidence * 100)}%${distSuffix}`;

        this.ctx.font = "bold 11px sans-serif";
        const metrics = this.ctx.measureText(labelText);
        const bgW = metrics.width + 12;
        const bgH = 18;
        const badgeY = Math.max(0, y1 - bgH);

        this.ctx.fillStyle = primaryColor;
        this.ctx.fillRect(x1, badgeY, bgW, bgH);

        this.ctx.fillStyle = "#08090d";
        this.ctx.fillText(labelText, x1 + 6, badgeY + 13);

        this.ctx.restore();
    }
}

window.RoverCanvasHUD = RoverCanvasHUD;
