/**
 * BUPI Autonomous Sensor-Fusion System — Interactive Dashboard & Arena Controller
 */

let ws = null;
let voiceEnabled = true;
let lastReportMessage = "";
let arenaData = null;
let isDragging = false;
let draggedItem = null; // { type: 'human' | 'obstacle', id: string, offsetX: 0, offsetY: 0 }
let breadcrumbs = [];

const canvas = document.getElementById('arenaCanvas');
const ctx = canvas.getContext('2d');

// DOM Elements
const connStatus = document.getElementById('connStatus');
const commandInput = document.getElementById('commandInput');
const commandForm = document.getElementById('commandForm');

// Pipeline elements
const pipeCmdText = document.getElementById('pipeCmdText');
const pipeGoalText = document.getElementById('pipeGoalText');
const pipeObsText = document.getElementById('pipeObsText');
const pipeInterpText = document.getElementById('pipeInterpText');
const pipeDecisionText = document.getElementById('pipeDecisionText');
const pipeActionText = document.getElementById('pipeActionText');

// State elements
const stateGoal = document.getElementById('stateGoal');
const stateMode = document.getElementById('stateMode');
const stateDistance = document.getElementById('stateDistance');
const stateMotion = document.getElementById('stateMotion');
const stateOrientation = document.getElementById('stateOrientation');
const stateSituation = document.getElementById('stateSituation');
const stateDecision = document.getElementById('stateDecision');
const stateAction = document.getElementById('stateAction');
const modeBadge = document.getElementById('modeBadge');

// Safety elements
const safetyBadge = document.getElementById('safetyBadge');
const safetyMessage = document.getElementById('safetyMessage');
const safetyOverridesCount = document.getElementById('safetyOverridesCount');

// Report & Events
const latestReport = document.getElementById('latestReport');
const eventsLog = document.getElementById('eventsLog');
const btnToggleSpeech = document.getElementById('btnToggleSpeech');

// Mode buttons
const btnSimMode = document.getElementById('btnSimMode');
const btnPhysMode = document.getElementById('btnPhysMode');
const btnTestSafetyOverride = document.getElementById('btnTestSafetyOverride');
const btnSpawnObstacle = document.getElementById('btnSpawnObstacle');
const btnResetArena = document.getElementById('btnResetArena');

function initWebSocket() {
  const host = window.location.hostname || 'localhost';
  ws = new WebSocket(`ws://${host}:8767`);

  ws.onopen = () => {
    connStatus.innerHTML = '<span class="dot"></span> Online (ws://8767)';
    connStatus.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    connStatus.style.color = '#10b981';
    addLogEntry('Connected to BUPI Hub WebSocket.');
  };

  ws.onclose = () => {
    connStatus.innerHTML = '<span class="dot" style="background:#f43f5e; box-shadow:0 0 8px #f43f5e;"></span> Disconnected';
    connStatus.style.borderColor = 'rgba(244, 63, 94, 0.4)';
    connStatus.style.color = '#f43f5e';
    setTimeout(initWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.warn('WS Error:', err);
  };

  ws.onmessage = (event) => {
    try {
      const data = jsonParseSafe(event.data);
      if (data && data.type === 'telemetry_update') {
        handleTelemetry(data);
      }
    } catch (e) {
      console.error('Error handling message:', e);
    }
  };
}

function jsonParseSafe(str) {
  try { return JSON.parse(str); } catch (e) { return null; }
}

function handleTelemetry(t) {
  const state = t.state || {};
  const goal = t.goal || {};
  const ladder = t.epistemic_ladder || {};
  const inference = t.fusion_inference || {};
  const safety = t.safety_status || {};
  const safeAction = t.safe_action || {};
  arenaData = t.arena;

  // 1. Pipeline Display
  pipeCmdText.textContent = goal.raw_command || 'Find a person in this room.';
  pipeGoalText.textContent = goal.intent || 'SEARCH_FOR_PRESENCE';
  pipeObsText.textContent = ladder.observation || 'PIR=LOW; Ping=125cm';
  pipeInterpText.textContent = ladder.inference || ladder.interpretation || 'No motion';
  pipeDecisionText.textContent = state.last_decision || 'ADVANCE';
  pipeActionText.textContent = `${safeAction.action || 'MOVE'} (${safeAction.speed || 0}%)`;

  // 2. State Table (Section 12)
  stateGoal.textContent = goal.goal_description || 'Searching area';
  stateMode.textContent = state.mode || 'IDLE';
  modeBadge.textContent = state.mode || 'IDLE';

  const env = state.environment || {};
  stateDistance.textContent = `${env.distance_cm || 0} cm (${env.proximity_class || 'far'})`;
  stateMotion.textContent = env.motion_detected ? 'DETECTED (PIR HIGH)' : 'NO MOTION (PIR LOW)';
  stateMotion.style.color = env.motion_detected ? '#f59e0b' : '#9ca3af';

  const robot = state.robot || {};
  stateOrientation.textContent = `${robot.orientation} (${robot.heading_deg}° heading)`;
  stateSituation.textContent = inference.summary || 'Area clear.';
  stateDecision.textContent = state.last_decision || 'NONE';
  stateAction.textContent = safeAction.action || 'STOP';

  // 3. Safety Supervisor
  safetyMessage.textContent = safety.status_message || 'Nominal';
  safetyOverridesCount.textContent = safety.total_overrides || 0;
  if (safety.verdict === 'OVERRIDDEN_FORCED_STOP') {
    safetyBadge.className = 'badge badge-danger';
    safetyBadge.textContent = 'OVERRIDE ACTIVE';
  } else if (safety.verdict === 'MODIFIED') {
    safetyBadge.className = 'badge badge-warning';
    safetyBadge.textContent = 'SPEED CLAMPED';
  } else {
    safetyBadge.className = 'badge badge-success';
    safetyBadge.textContent = 'SAFE';
  }

  // 4. Report & Findings
  if (inference.report_message && inference.report_message !== lastReportMessage) {
    lastReportMessage = inference.report_message;
    latestReport.textContent = `"${lastReportMessage}"`;
    addLogEntry(`[REPORT] ${lastReportMessage}`);

    // Voice announcement
    if (voiceEnabled && window.speechSynthesis && inference.possible_human_presence) {
      const utter = new SpeechSynthesisUtterance(lastReportMessage);
      utter.rate = 1.0;
      utter.pitch = 1.05;
      window.speechSynthesis.speak(utter);
    }
  }

  // Record breadcrumb
  if (arenaData && arenaData.robot) {
    breadcrumbs.push({ x: arenaData.robot.x, y: arenaData.robot.y });
    if (breadcrumbs.length > 200) breadcrumbs.shift();
  }

  renderArena();
}

function renderArena() {
  if (!arenaData) return;

  const room = arenaData.room || { width_cm: 500, height_cm: 400 };
  const scaleX = canvas.width / room.width_cm;
  const scaleY = canvas.height / room.height_cm;

  // Clear background
  ctx.fillStyle = '#07090e';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Grid pattern
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
  ctx.lineWidth = 1;
  for (let x = 0; x < canvas.width; x += 50) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
  }
  for (let y = 0; y < canvas.height; y += 40) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  }

  // Breadcrumbs trail
  if (breadcrumbs.length > 1) {
    ctx.strokeStyle = 'rgba(6, 182, 212, 0.25)';
    ctx.lineWidth = 2;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(breadcrumbs[0].x * scaleX, breadcrumbs[0].y * scaleY);
    for (let i = 1; i < breadcrumbs.length; i++) {
      ctx.lineTo(breadcrumbs[i].x * scaleX, breadcrumbs[i].y * scaleY);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Draw Obstacles
  const obstacles = arenaData.obstacles || [];
  for (let obs of obstacles) {
    const ox = (obs.x - obs.width/2) * scaleX;
    const oy = (obs.y - obs.height/2) * scaleY;
    const ow = obs.width * scaleX;
    const oh = obs.height * scaleY;

    ctx.fillStyle = 'rgba(75, 85, 99, 0.6)';
    ctx.strokeStyle = 'rgba(156, 163, 175, 0.6)';
    ctx.lineWidth = 2;
    ctx.fillRect(ox, oy, ow, oh);
    ctx.strokeRect(ox, oy, ow, oh);

    ctx.fillStyle = '#d1d5db';
    ctx.font = '10px Outfit';
    ctx.fillText('Obstacle', ox + 4, oy + 14);
  }

  // Draw Humans (Warm Targets)
  const humans = arenaData.humans || [];
  for (let h of humans) {
    const hx = h.x * scaleX;
    const hy = h.y * scaleY;

    // Glowing warm IR aura
    const grad = ctx.createRadialGradient(hx, hy, 4, hx, hy, 32);
    grad.addColorStop(0, 'rgba(244, 63, 94, 0.6)');
    grad.addColorStop(0.6, 'rgba(244, 63, 94, 0.15)');
    grad.addColorStop(1, 'rgba(244, 63, 94, 0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(hx, hy, 32, 0, Math.PI * 2);
    ctx.fill();

    // Human Center Dot
    ctx.fillStyle = '#f43f5e';
    ctx.beginPath();
    ctx.arc(hx, hy, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = '#fff';
    ctx.font = 'bold 11px Outfit';
    ctx.fillText('Warm Target (Human)', hx + 12, hy + 4);
  }

  // Draw BUPI Robot
  const robot = arenaData.robot;
  if (robot) {
    const rx = robot.x * scaleX;
    const ry = robot.y * scaleY;
    const rRadius = (robot.radius_cm || 8) * scaleX;
    const headingRad = (robot.heading_deg * Math.PI) / 180;

    // 1. Draw PIR Field of View Cone (100 degrees, 250cm)
    const pirRangePx = 250 * scaleX;
    const pirFovRad = ((robot.pir_fov_deg || 100) * Math.PI) / 180;
    ctx.save();
    ctx.fillStyle = 'rgba(245, 158, 11, 0.12)';
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.35)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(rx, ry);
    ctx.arc(rx, ry, pirRangePx, headingRad - pirFovRad/2, headingRad + pirFovRad/2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // 2. Draw Ultrasonic Ray Cone (25 degrees)
    const distCm = (arenaData.sensors && arenaData.sensors.raw_distance_cm) || 125;
    const usDistPx = distCm * scaleX;
    const usFovRad = ((robot.ultrasonic_fov_deg || 25) * Math.PI) / 180;
    ctx.save();
    ctx.fillStyle = 'rgba(59, 130, 246, 0.25)';
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.7)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(rx, ry);
    ctx.arc(rx, ry, usDistPx, headingRad - usFovRad/2, headingRad + usFovRad/2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // 3. Robot Chassis Circle
    ctx.fillStyle = '#06b6d4';
    ctx.beginPath();
    ctx.arc(rx, ry, rRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Heading pointer
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(rx, ry);
    ctx.lineTo(rx + Math.cos(headingRad) * (rRadius + 8), ry + Math.sin(headingRad) * (rRadius + 8));
    ctx.stroke();

    // Label
    ctx.fillStyle = '#06b6d4';
    ctx.font = 'bold 12px Outfit';
    ctx.fillText('BUPI', rx - 14, ry - rRadius - 6);
  }
}

// Mouse Interactivity for Drag & Drop in Arena
canvas.addEventListener('mousedown', (e) => {
  if (!arenaData) return;
  const rect = canvas.getBoundingClientRect();
  const mouseX = (e.clientX - rect.left) * (canvas.width / rect.width);
  const mouseY = (e.clientY - rect.top) * (canvas.height / rect.height);

  const scaleX = canvas.width / arenaData.room.width_cm;
  const scaleY = canvas.height / arenaData.room.height_cm;

  // Check humans
  for (let h of arenaData.humans || []) {
    const hx = h.x * scaleX;
    const hy = h.y * scaleY;
    const dist = Math.hypot(mouseX - hx, mouseY - hy);
    if (dist <= 24) {
      isDragging = true;
      draggedItem = { type: 'human', id: h.id };
      return;
    }
  }

  // Check obstacles
  for (let o of arenaData.obstacles || []) {
    const ox = (o.x - o.width/2) * scaleX;
    const oy = (o.y - o.height/2) * scaleY;
    const ow = o.width * scaleX;
    const oh = o.height * scaleY;
    if (mouseX >= ox && mouseX <= ox + ow && mouseY >= oy && mouseY <= oy + oh) {
      isDragging = true;
      draggedItem = { type: 'obstacle', id: o.id };
      return;
    }
  }
});

canvas.addEventListener('mousemove', (e) => {
  if (!isDragging || !draggedItem || !arenaData) return;
  const rect = canvas.getBoundingClientRect();
  const mouseX = (e.clientX - rect.left) * (canvas.width / rect.width);
  const mouseY = (e.clientY - rect.top) * (canvas.height / rect.height);

  const scaleX = canvas.width / arenaData.room.width_cm;
  const scaleY = canvas.height / arenaData.room.height_cm;

  const roomX = mouseX / scaleX;
  const roomY = mouseY / scaleY;

  if (draggedItem.type === 'human') {
    sendWsMessage({ type: 'move_human', id: draggedItem.id, x: roomX, y: roomY });
  } else if (draggedItem.type === 'obstacle') {
    sendWsMessage({ type: 'move_obstacle', id: draggedItem.id, x: roomX, y: roomY });
  }
});

window.addEventListener('mouseup', () => {
  isDragging = false;
  draggedItem = null;
});

function sendWsMessage(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function addLogEntry(text) {
  const d = new Date();
  const timeStr = `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span class="time">${timeStr}</span> ${text}`;
  eventsLog.appendChild(entry);
  eventsLog.scrollTop = eventsLog.scrollHeight;
}

// User Actions
commandForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const cmd = commandInput.value.trim();
  if (cmd) {
    sendWsMessage({ type: 'command', text: cmd });
    addLogEntry(`[USER] ${cmd}`);
  }
});

document.querySelectorAll('.chip').forEach(btn => {
  btn.addEventListener('click', () => {
    const cmd = btn.getAttribute('data-cmd');
    commandInput.value = cmd;
    sendWsMessage({ type: 'command', text: cmd });
    addLogEntry(`[USER CHIP] ${cmd}`);
  });
});

btnTestSafetyOverride.addEventListener('click', () => {
  // Directly inject a critical distance < 15cm to verify the safety layer overrides planner
  sendWsMessage({ type: 'inject_obstacle', distance_cm: 11.5 });
  addLogEntry('[TEST] Injected Critical Barrier at 11.5 cm!');
});

btnSpawnObstacle.addEventListener('click', () => {
  if (arenaData && arenaData.robot) {
    const rx = arenaData.robot.x;
    const ry = arenaData.robot.y;
    // Place obstacle 30cm directly ahead of BUPI
    const rad = (arenaData.robot.heading_deg * Math.PI) / 180;
    const ox = rx + Math.cos(rad) * 35;
    const oy = ry + Math.sin(rad) * 35;
    sendWsMessage({ type: 'move_obstacle', id: 'box_1', x: ox, y: oy });
    addLogEntry('[ACTION] Spawned obstacle 35cm in front of BUPI!');
  }
});

btnResetArena.addEventListener('click', () => {
  sendWsMessage({ type: 'move_human', id: 'person_1', x: 340, y: 200 });
  sendWsMessage({ type: 'move_obstacle', id: 'box_1', x: 220, y: 80 });
  breadcrumbs = [];
  addLogEntry('[ACTION] Reset arena entities.');
});

btnSimMode.addEventListener('click', () => {
  btnSimMode.classList.add('active');
  btnPhysMode.classList.remove('active');
  sendWsMessage({ type: 'toggle_mode', mode: 'simulation' });
  addLogEntry('[MODE] Switched to Virtual Simulation.');
});

btnPhysMode.addEventListener('click', () => {
  btnPhysMode.classList.add('active');
  btnSimMode.classList.remove('active');
  sendWsMessage({ type: 'toggle_mode', mode: 'physical' });
  addLogEntry('[MODE] Switched to Physical ESP32 Hardware.');
});

btnToggleSpeech.addEventListener('click', () => {
  voiceEnabled = !voiceEnabled;
  btnToggleSpeech.textContent = voiceEnabled ? '🔊 Voice On' : '🔇 Voice Off';
  btnToggleSpeech.style.color = voiceEnabled ? '#10b981' : '#6b7280';
});

// Initialize on Load
window.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
});
