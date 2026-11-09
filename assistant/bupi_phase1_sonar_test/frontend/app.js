/**
 * BUPI Phase 1 Sonar Vision System: Main Orchestrator.
 * 100% Real Hardware Data. Viewports start empty.
 * Coordinates Polar Scope, 2D DIP Canvas, 3D Voxel Extrusion, and AI Map Decision Reader.
 */

import { SonarAPI } from './modules/api.js';
import { SweepController } from './modules/sweep_controller.js';
import { PolarScope } from './modules/polar_scope.js';
import { DIPCanvas } from './modules/dip_canvas.js';
import { VoxelWorld } from './modules/voxel_view.js';

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize API & Viewports
  const api = new SonarAPI();

  const polarScope = new PolarScope(document.getElementById('polarScopeCanvas'));
  const dipCanvas = new DIPCanvas(
    document.getElementById('dipCanvas'),
    document.getElementById('dipCoords')
  );
  const voxelWorld = new VoxelWorld(
    document.getElementById('voxelCanvas'),
    document.getElementById('voxelContainer')
  );

  // 2. Initialize Sweep Controller (Mode 0: Hardware Servo Turret by default)
  let latestDistance = 400.0;
  const sweepController = new SweepController(api, (angle, mode, sweepDir) => {
    document.getElementById('statAngle').textContent = `${angle.toFixed(1)}°`;
    const statServoAngle = document.getElementById('statServoAngle');
    const statSweepDir = document.getElementById('statSweepDir');
    if (statServoAngle) {
      statServoAngle.textContent = `${angle.toFixed(0)}°`;
    }
    if (statSweepDir && sweepDir) {
      statSweepDir.textContent = sweepDir;
    }
    if (mode === 2) {
      document.getElementById('stepAngleLabel').textContent = `${angle.toFixed(0)}°`;
    }
    if (mode === 3) {
      document.getElementById('manualAngleValue').textContent = `${angle.toFixed(0)}°`;
      const slider = document.getElementById('manualAngleSlider');
      if (slider && parseFloat(slider.value) !== angle) {
        slider.value = angle;
      }
    }
  });

  // Wire Polar Radar Scope direct click & drag aiming
  polarScope.onAngleAim = (aimDeg) => {
    if (sweepController.activeMode === 3) {
      sweepController.setManualAngle(aimDeg);
    }
  };

  // UI State
  let showDilation = true;
  let activePass = 'pass1';

  // 3. UI Element References
  const portSelect = document.getElementById('portSelect');
  const connectBtn = document.getElementById('connectBtn');
  const refreshPortsBtn = document.getElementById('refreshPortsBtn');
  const scanModeSelect = document.getElementById('scanModeSelect');
  const btnLockBoth90 = document.getElementById('btnLockBoth90');
  const resetBtn = document.getElementById('resetBtn');

  // Dual-Beam Badges
  const badgeD1 = document.getElementById('badgeD1');
  const badgeS1Ang = document.getElementById('badgeS1Ang');
  const badgeD2 = document.getElementById('badgeD2');
  const badgeS2Ang = document.getElementById('badgeS2Ang');
  const badgeDeltaD = document.getElementById('badgeDeltaD');
  const badge3DClass = document.getElementById('badge3DClass');
  const badgeSafety = document.getElementById('badgeSafety');

  // Servo Sector Control Elements
  const btnSectorFocused = document.getElementById('btnSectorFocused');
  const btnSectorCone = document.getElementById('btnSectorCone');
  const btnSectorFull = document.getElementById('btnSectorFull');
  const btnCenterServo = document.getElementById('btnCenterServo');
  const btnResumeSweep = document.getElementById('btnResumeSweep');
  const servoMinSlider = document.getElementById('servoMinSlider');
  const servoMaxSlider = document.getElementById('servoMaxSlider');
  const servoStepSelect = document.getElementById('servoStepSelect');
  const servoMinValue = document.getElementById('servoMinValue');
  const servoMaxValue = document.getElementById('servoMaxValue');

  function updateServoConfig() {
    const minA = parseInt(servoMinSlider.value, 10);
    const maxA = parseInt(servoMaxSlider.value, 10);
    const st = parseInt(servoStepSelect.value, 10);
    servoMinValue.textContent = `${minA}°`;
    servoMaxValue.textContent = `${maxA}°`;
    sweepController.sendServoConfig(minA, maxA, st, 1, 90);
    if (btnResumeSweep) btnResumeSweep.style.display = 'none';
    if (btnCenterServo) btnCenterServo.style.display = 'inline-block';
  }

  if (btnSectorFocused) {
    btnSectorFocused.addEventListener('click', () => {
      servoMinSlider.value = 60;
      servoMaxSlider.value = 120;
      updateServoConfig();
    });
  }

  if (btnSectorCone) {
    btnSectorCone.addEventListener('click', () => {
      servoMinSlider.value = 45;
      servoMaxSlider.value = 135;
      updateServoConfig();
    });
  }

  if (btnSectorFull) {
    btnSectorFull.addEventListener('click', () => {
      servoMinSlider.value = 0;
      servoMaxSlider.value = 180;
      updateServoConfig();
    });
  }

  if (servoMinSlider) servoMinSlider.addEventListener('input', () => updateServoConfig());
  if (servoMaxSlider) servoMaxSlider.addEventListener('input', () => updateServoConfig());
  if (servoStepSelect) servoStepSelect.addEventListener('change', () => updateServoConfig());

  if (btnCenterServo) {
    btnCenterServo.addEventListener('click', () => {
      sweepController.centerServoAt90();
      btnCenterServo.style.display = 'none';
      if (btnResumeSweep) btnResumeSweep.style.display = 'inline-block';
    });
  }

  if (btnResumeSweep) {
    btnResumeSweep.addEventListener('click', () => {
      sweepController.resumeSweep();
      btnResumeSweep.style.display = 'none';
      if (btnCenterServo) btnCenterServo.style.display = 'inline-block';
    });
  }

  // Badges & Telemetry
  const connBadge = document.getElementById('connectionBadge');
  const connText = document.getElementById('connectionText');
  const imuBadge = document.getElementById('imuBadge');
  const imuStatusText = document.getElementById('imuStatusText');

  const statDistance = document.getElementById('statDistance');
  const statDeltaD = document.getElementById('statDeltaD');
  const statPortal = document.getElementById('statPortal');
  const statSafetyStop = document.getElementById('statSafetyStop');
  const statHitCount = document.getElementById('statHitCount');

  // AI Decision Elements
  const aiCommandText = document.getElementById('aiCommandText');
  const asciiMatrixView = document.getElementById('asciiMatrixView');

  const sectorEls = {
    "Left": { dist: document.getElementById('secDistLeft'), stat: document.getElementById('secStatLeft'), trav: document.getElementById('secTravLeft') },
    "Front-Left": { dist: document.getElementById('secDistFrontLeft'), stat: document.getElementById('secStatFrontLeft'), trav: document.getElementById('secTravFrontLeft') },
    "Center": { dist: document.getElementById('secDistCenter'), stat: document.getElementById('secStatCenter'), trav: document.getElementById('secTravCenter') },
    "Front-Right": { dist: document.getElementById('secDistFrontRight'), stat: document.getElementById('secStatFrontRight'), trav: document.getElementById('secTravFrontRight') },
    "Right": { dist: document.getElementById('secDistRight'), stat: document.getElementById('secStatRight'), trav: document.getElementById('secTravRight') }
  };

  // 4. Fetch Available Physical COM Ports
  async function refreshPorts() {
    const data = await api.getPorts();
    const currentVal = portSelect.value;
    portSelect.innerHTML = '';

    if (data.ports && data.ports.length > 0) {
      data.ports.forEach((p) => {
        const opt = document.createElement('option');
        opt.value = p.device;
        opt.textContent = `${p.device} (${p.description || 'ESP32 Device'})`;
        portSelect.appendChild(opt);
      });
      if (currentVal && [...portSelect.options].some((o) => o.value === currentVal)) {
        portSelect.value = currentVal;
      }
    } else {
      const opt = document.createElement('option');
      opt.value = "";
      opt.disabled = true;
      opt.selected = true;
      opt.textContent = "No COM Ports Detected (Plug ESP32 USB)";
      portSelect.appendChild(opt);
    }
  }
  refreshPorts();
  if (refreshPortsBtn) {
    refreshPortsBtn.addEventListener('click', () => refreshPorts());
  }

  // 5. Connect Port Action
  if (connectBtn) {
    connectBtn.addEventListener('click', async () => {
      const port = portSelect.value;
      if (!port) return;
      await api.connectPort(port, 115200);
    });
  }

  // Scan Mode and Hardware Centering
  if (scanModeSelect) {
    scanModeSelect.addEventListener('change', () => {
      const mode = scanModeSelect.value;
      const minA = parseInt(servoMinSlider.value, 10);
      const maxA = parseInt(servoMaxSlider.value, 10);
      const st = parseInt(servoStepSelect.value, 10);
      sweepController.sendScanConfig(mode, minA, maxA, st, 1, 0);
    });
  }

  if (btnLockBoth90) {
    btnLockBoth90.addEventListener('click', () => {
      sweepController.centerBothAt90();
      if (btnResumeSweep) btnResumeSweep.style.display = 'inline-block';
    });
  }

  // 7. Reset Actions
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      await api.resetMap();
    });
  }

  // 9. Real-Time WebSocket Processor
  api.initWebSocket(
    (snapshot) => {
      const tel = snapshot.telemetry || {};
      latestDistance = tel.d_cm || 400.0;

      // Update Sweep Controller with latest telemetry (IMU handling)
      sweepController.handleTelemetry(tel);

      // Connection Status Badge
      const conn = snapshot.connection || {};
      if (conn.connected) {
        connBadge.className = 'status-badge online';
        connText.textContent = `ESP32 (${conn.port})`;
      } else if (conn.is_busy) {
        connBadge.className = 'status-badge amber';
        connText.textContent = `${conn.busy_port || 'COM3'} BUSY (CLOSE ARDUINO SERIAL MONITOR)`;
      } else {
        connBadge.className = 'status-badge error';
        connText.textContent = 'NO ESP32 CONNECTED';
      }

      // IMU Status Badge
      if (tel.imu) {
        imuBadge.className = 'status-badge online';
        imuStatusText.textContent = `IMU: YAW ${tel.yaw !== null ? tel.yaw.toFixed(1) : '--'}° | PITCH ${tel.pitch !== null ? tel.pitch.toFixed(1) : '--'}°`;
      } else {
        imuBadge.className = 'status-badge';
        imuStatusText.textContent = 'IMU: OFF (VIRTUAL PACER)';
      }

      // Active Pass Sync
      if (tel.active_pass && tel.active_pass !== activePass) {
        activePass = tel.active_pass;
        if (activePass === 'pass1') {
          btnPass1.classList.add('active');
          btnPass2.classList.remove('active');
        } else {
          btnPass2.classList.add('active');
          btnPass1.classList.remove('active');
        }
      }

      // Dual-Beam Badges Update
      const d1 = tel.d1_cm !== undefined ? tel.d1_cm : tel.d_cm;
      const d2 = tel.d2_cm !== undefined ? tel.d2_cm : d1;
      const s1 = tel.s1_ang !== undefined ? tel.s1_ang : (tel.s_ang || 90);
      const s2 = tel.s2_ang !== undefined ? tel.s2_ang : s1;

      if (badgeD1) badgeD1.textContent = (tel.valid1 || tel.valid) ? `${d1.toFixed(1)} cm` : '-- cm';
      if (badgeS1Ang) badgeS1Ang.textContent = `@ ${s1.toFixed(0)}°`;
      if (badgeD2) badgeD2.textContent = (tel.valid2 || tel.valid) ? `${d2.toFixed(1)} cm` : '-- cm';
      if (badgeS2Ang) badgeS2Ang.textContent = `@ ${s2.toFixed(0)}°`;

      if (badgeDeltaD && tel.delta_d !== null && tel.delta_d !== undefined) {
        const sign = tel.delta_d >= 0 ? '+' : '';
        badgeDeltaD.textContent = `${sign}${tel.delta_d.toFixed(1)} cm`;
      }

      if (badge3DClass) {
        const c3d = tel.class_3d || "OPEN_CORRIDOR";
        badge3DClass.textContent = c3d;
        badge3DClass.style.color = (
          c3d === 'TALL_SOLID_WALL' ? '#ff3344' :
          c3d === 'LOW_STEP_RUBBLE' ? '#ffb300' :
          c3d === 'OVERHANG_HAZARD' ? '#ff6d00' :
          c3d === 'DOORWAY_DEPTH_PORTAL' ? '#e040fb' : '#00e5ff'
        );
      }

      if (badgeSafety) {
        const isStop = tel.safety_stop === 1;
        badgeSafety.textContent = isStop ? 'CRITICAL STOP (<18cm)' : 'CLEAR (>18cm)';
        badgeSafety.style.color = isStop ? '#ff3344' : '#00e676';
      }

      // Telemetry Bar
      const curServoAng = tel.s_ang !== undefined ? tel.s_ang : tel.angle_deg;
      const statServoAngle = document.getElementById('statServoAngle');
      const statSweepDir = document.getElementById('statSweepDir');
      if (statServoAngle) {
        statServoAngle.textContent = `${curServoAng.toFixed(0)}°`;
      }
      if (statSweepDir && tel.sweep_dir) {
        statSweepDir.textContent = tel.sweep_dir;
        statSweepDir.className = 'status-badge ' + (
          tel.sweep_dir.includes('LEFT') ? 'online' :
          tel.sweep_dir.includes('RIGHT') ? 'amber' : ''
        );
      }

      if (tel.valid) {
        statDistance.textContent = `${tel.d_cm.toFixed(1)} cm`;
        statDistance.className = tel.d_cm < 40 ? 'stat-value red' : 'stat-value green';
      } else {
        statDistance.textContent = 'NO ECHO (TIMEOUT)';
        statDistance.className = 'stat-value amber';
      }

      if (tel.delta_d !== null && tel.delta_d !== undefined) {
        const sign = tel.delta_d >= 0 ? '+' : '';
        statDeltaD.textContent = `${sign}${tel.delta_d.toFixed(1)} cm`;
        statDeltaD.className = Math.abs(tel.delta_d) >= 35 ? 'stat-value amber' : 'stat-value';
      } else {
        statDeltaD.textContent = '--';
        statDeltaD.className = 'stat-value';
      }

      statPortal.textContent = tel.portal_detected ? 'PORTAL EDGE' : 'NONE';
      statPortal.className = tel.portal_detected ? 'stat-value red' : 'stat-value';
      statHitCount.textContent = tel.hit_count || 0;

      if (statSafetyStop) {
        const isStop = tel.safety_stop === 1;
        statSafetyStop.textContent = isStop ? 'STOP (<15cm)' : 'CLEAR';
        statSafetyStop.className = isStop ? 'stat-value red' : 'stat-value green';
      }

      // AI Decision Panel Updates
      const ai = snapshot.ai_decision;
      if (ai) {
        if (ai.steering_command) {
          aiCommandText.textContent = ai.steering_command;
          aiCommandText.style.color = ai.steering_command.includes('STOP') ? '#ff3344' : '#00e676';
        }

        if (ai.sectors) {
          for (const [sname, sdata] of Object.entries(ai.sectors)) {
            const el = sectorEls[sname];
            if (el) {
              el.dist.textContent = `${sdata.min_distance_cm} cm`;
              el.stat.textContent = sdata.status;
              if (el.trav && sdata.traversability_pct !== undefined) {
                el.trav.textContent = `Trav: ${sdata.traversability_pct}%`;
              }
              el.stat.className = 'sector-status ' + (
                sdata.status === 'CLEAR_CORRIDOR' ? 'clear' :
                sdata.status === 'PORTAL_ENTRANCE' || sdata.status === 'DOORWAY_PORTAL' ? 'portal' :
                sdata.status === 'LOW_STEP_CLIMBABLE' || sdata.status === 'LOW_STEP' ? 'step' :
                sdata.status === 'BLOCKED_WALL' ? 'blocked' : ''
              );
            }
          }
        }

        if (ai.ascii_matrix && asciiMatrixView) {
          asciiMatrixView.textContent = ai.ascii_matrix;
        }
      }

      // Update 3 Viewports
      polarScope.updateState(tel, snapshot.polar_history, snapshot.portals);
      dipCanvas.updateSnapshot(snapshot.semantic_image_b64, ai ? ai.astar_path : []);
      voxelWorld.updateSnapshot(snapshot.active_voxels, snapshot.portals, curServoAng, ai ? ai.astar_path : [], tel);
    },
    (isConnected) => {
      if (!isConnected) {
        connBadge.className = 'status-badge error';
        connText.textContent = 'SERVER DISCONNECTED';
      } else {
        connBadge.className = 'status-badge online';
        connText.textContent = 'SERVER CONNECTED';
      }
    }
  );
});
