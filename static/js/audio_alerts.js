/**
 * EdgeRover — Web Audio API Procedural Synthesizer.
 * Generates proximity alerts, intrusion sirens, and telemetry audio feedback
 * purely in-browser without requiring external audio files.
 */

class RoverAudioSynthesizer {
    constructor() {
        this.ctx = null;
        this.isMuted = false;
        this.lastBeepTime = 0;
    }

    ensureContext() {
        if (!this.ctx) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            this.ctx = new AudioCtx();
        }
        if (this.ctx.state === "suspended") {
            this.ctx.resume();
        }
    }

    toggleMute() {
        this.isMuted = !this.isMuted;
        return this.isMuted;
    }

    playConnectChime() {
        if (this.isMuted) return;
        this.ensureContext();

        const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
        notes.forEach((freq, idx) => {
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            osc.type = "sine";
            osc.frequency.setValueAtTime(freq, this.ctx.currentTime + idx * 0.08);

            gain.gain.setValueAtTime(0, this.ctx.currentTime + idx * 0.08);
            gain.gain.linearRampToValueAtTime(0.12, this.ctx.currentTime + idx * 0.08 + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + idx * 0.08 + 0.25);

            osc.connect(gain);
            gain.connect(this.ctx.destination);

            osc.start(this.ctx.currentTime + idx * 0.08);
            osc.stop(this.ctx.currentTime + idx * 0.08 + 0.3);
        });
    }

    playObstacleAlert(distanceCm) {
        if (this.isMuted || distanceCm > 60) return;
        this.ensureContext();

        const now = performance.now();
        // Beep frequency interval inversely proportional to distance (faster beeps closer)
        const intervalMs = Math.max(90, distanceCm * 8.0);
        if (now - this.lastBeepTime < intervalMs) return;
        this.lastBeepTime = now;

        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        // Higher pitch closer to collision
        const freq = distanceCm < 30 ? 1100 : 780;
        osc.type = "triangle";
        osc.frequency.setValueAtTime(freq, this.ctx.currentTime);

        const vol = distanceCm < 30 ? 0.22 : 0.10;
        gain.gain.setValueAtTime(vol, this.ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.07);

        osc.connect(gain);
        gain.connect(this.ctx.destination);

        osc.start();
        osc.stop(this.ctx.currentTime + 0.08);
    }

    playIntrusionAlarm() {
        if (this.isMuted) return;
        this.ensureContext();

        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        osc.type = "sawtooth";
        // Frequency sweep siren
        osc.frequency.setValueAtTime(800, this.ctx.currentTime);
        osc.frequency.linearRampToValueAtTime(1400, this.ctx.currentTime + 0.2);
        osc.frequency.linearRampToValueAtTime(800, this.ctx.currentTime + 0.4);

        gain.gain.setValueAtTime(0.18, this.ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.45);

        osc.connect(gain);
        gain.connect(this.ctx.destination);

        osc.start();
        osc.stop(this.ctx.currentTime + 0.48);
    }

    playEstopSound() {
        if (this.isMuted) return;
        this.ensureContext();

        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        osc.type = "square";
        osc.frequency.setValueAtTime(140, this.ctx.currentTime);
        osc.frequency.linearRampToValueAtTime(70, this.ctx.currentTime + 0.25);

        gain.gain.setValueAtTime(0.2, this.ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.3);

        osc.connect(gain);
        gain.connect(this.ctx.destination);

        osc.start();
        osc.stop(this.ctx.currentTime + 0.32);
    }
}

window.roverAudio = new RoverAudioSynthesizer();
