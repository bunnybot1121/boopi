/**
 * Hand-Sweep Angle Controller.
 * Solves the "no servo" hardware reality with 4 interactive aiming modes.
 */

export class SweepController {
  constructor(api, onAngleChanged) {
    this.api = api;
    this.onAngleChanged = onAngleChanged;

    this.activeMode = 3; // Default to Mode 3: Manual Dial / Hand Aim (No phantom moving beam)
    this.currentAngle = 90.0;
    this.pacerPeriodS = 6.0;
    this.pacerStartTime = performance.now();

    // Mode 2 state
    this.stepAngle = 90.0;
    this.stepSize = 15.0;
    this.sampleBuffer = [];
    this.isCollectingSamples = false;

    // Mode 4 state
    this.imuAvailable = false;

    // Animation frame for Mode 1
    this.animFrameId = null;
    this.lastSentAngle = -999;
    this.lastSendTime = 0;

    this.startPacerLoop();
  }

  setMode(modeNumber) {
    this.activeMode = modeNumber;
    if (this.onAngleChanged) this.onAngleChanged(this.currentAngle, this.activeMode);
  }

  setPacerPeriod(seconds) {
    this.pacerPeriodS = Math.max(2.0, Math.min(15.0, seconds));
  }

  setManualAngle(angleDeg) {
    this.currentAngle = Math.max(0.0, Math.min(180.0, angleDeg));
    this.notifyBackendAngle(this.currentAngle);
    if (this.onAngleChanged) this.onAngleChanged(this.currentAngle, this.activeMode);
  }

  stepNext() {
    this.stepAngle = Math.min(180.0, this.stepAngle + this.stepSize);
    this.currentAngle = this.stepAngle;
    this.notifyBackendAngle(this.currentAngle);
    if (this.onAngleChanged) this.onAngleChanged(this.currentAngle, this.activeMode);
  }

  stepPrev() {
    this.stepAngle = Math.max(0.0, this.stepAngle - this.stepSize);
    this.currentAngle = this.stepAngle;
    this.notifyBackendAngle(this.currentAngle);
    if (this.onAngleChanged) this.onAngleChanged(this.currentAngle, this.activeMode);
  }

  triggerStepPing(latestDistance) {
    // Collect reading for current step angle and lock into map
    const d = (latestDistance && latestDistance > 0) ? latestDistance : 400.0;
    this.api.sendWs({
      action: "step_ping",
      angle: this.stepAngle,
      d_cm: d
    });
    // Auto advance to next angle
    this.stepNext();
  }

  handleTelemetry(telemetry) {
    if (telemetry.imu && telemetry.yaw !== null) {
      this.imuAvailable = true;
      if (this.activeMode === 4) {
        // Normalize yaw to 0..180 forward sector
        let mapped = ((telemetry.yaw % 360) + 360) % 360;
        if (mapped > 180) mapped = 360 - mapped;
        this.currentAngle = mapped;
        if (this.onAngleChanged) this.onAngleChanged(this.currentAngle, 4);

        // Auto-switch pass layer if pitch is tilted upward (> 18 deg)
        if (telemetry.pitch !== null) {
          if (telemetry.pitch > 18.0 && telemetry.active_pass !== "pass2") {
            this.api.setActivePass("pass2");
          } else if (telemetry.pitch <= 10.0 && telemetry.active_pass !== "pass1") {
            this.api.setActivePass("pass1");
          }
        }
      }
    } else {
      this.imuAvailable = false;
    }
  }

  startPacerLoop() {
    const loop = (timestamp) => {
      if (this.activeMode === 1) {
        // Triangle wave oscillating between 0.0 and 180.0
        const periodMs = this.pacerPeriodS * 1000;
        const phase = (timestamp % periodMs) / periodMs; // 0.0 to 1.0
        // If phase < 0.5: 0 -> 180; if >= 0.5: 180 -> 0
        let angle;
        if (phase < 0.5) {
          angle = (phase * 2.0) * 180.0;
        } else {
          angle = (1.0 - (phase - 0.5) * 2.0) * 180.0;
        }
        this.currentAngle = angle;
        this.throttleSendAngle(angle, timestamp);
        if (this.onAngleChanged) this.onAngleChanged(this.currentAngle, 1);
      }
      this.animFrameId = requestAnimationFrame(loop);
    };
    this.animFrameId = requestAnimationFrame(loop);
  }

  throttleSendAngle(angle, now) {
    // Send to backend at max 20 Hz
    if (now - this.lastSendTime >= 50) {
      if (Math.abs(angle - this.lastSentAngle) >= 0.5) {
        this.notifyBackendAngle(angle);
        this.lastSentAngle = angle;
        this.lastSendTime = now;
      }
    }
  }

  notifyBackendAngle(angle) {
    this.api.sendWs({ action: "set_angle", angle: roundOne(angle) });
  }
}

function roundOne(v) {
  return Math.round(v * 10) / 10;
}

