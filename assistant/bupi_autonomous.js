/**
 * bupi_autonomous.js — BUPI Autonomous Sensor-Fusion System Client for Bupi Hub
 * Controls the Epistemic Ladder, 2D Arena Simulation, and Hardware Telemetry
 */

(() => {
    let ws = null;
    const defaultArena = {
        room: { width_cm: 500, height_cm: 400 },
        humans: [{ id: "person_1", x: 340, y: 140, radius: 18 }],
        obstacles: [{ id: "box_1", x: 240, y: 190, width: 45, height: 45 }],
        fleet: {
            "bupi_01": { bot_id: "bupi_01", role: "SCOUT", x: 120, y: 180, heading: 0.0, distance_cm: 150.0, pir: 0, ultrasonic_fov_deg: 25, pir_fov_deg: 100 },
            "bupi_02": { bot_id: "bupi_02", role: "ENVIRONMENTAL", x: 180, y: 260, heading: 0.0, gas_ppm: 35.0, temp_c: 24.5, ultrasonic_fov_deg: 25 }
        },
        robot: { bot_id: "bupi_01", role: "SCOUT", x: 120, y: 180, heading: 0.0, ultrasonic_fov_deg: 25, pir_fov_deg: 100 }
    };
    let arenaData = defaultArena;
    let isDragging = false;
    let draggedItem = null;
    let breadcrumbs = [];
    let voiceEnabled = true;
    let lastReport = "";

    function getCanvasAndContext() {
        const c = document.getElementById('bupiArenaCanvas');
        if (!c) return { c: null, ctx: null };
        if (c.clientWidth > 0 && (c.width !== c.clientWidth || c.height !== c.clientHeight)) {
            c.width = c.clientWidth;
            c.height = c.clientHeight;
        }
        return { c: c, ctx: c.getContext('2d') };
    }

    function initWebSocket() {
        try {
            ws = new WebSocket('ws://localhost:8767');

            ws.onopen = () => {
                const badge = document.getElementById('autoEngineStatusBadge');
                if (badge) {
                    badge.textContent = 'ONLINE (ws://8767)';
                    badge.style.background = 'rgba(72, 187, 120, 0.18)';
                    badge.style.color = '#276749';
                }
            };

            ws.onclose = () => {
                const badge = document.getElementById('autoEngineStatusBadge');
                if (badge) {
                    badge.textContent = 'OFFLINE (Reconnecting...)';
                    badge.style.background = 'rgba(245, 101, 101, 0.18)';
                    badge.style.color = '#9b2c2c';
                }
                setTimeout(initWebSocket, 2000);
            };

            ws.onerror = (e) => {
                console.warn('[BUPI Auto] WS error:', e);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data && data.type === 'telemetry_update') {
                        updateAutonomousUI(data);
                    }
                } catch (err) {
                    console.error('[BUPI Auto] Error parsing telemetry:', err);
                }
            };
        } catch (e) {
            console.error('[BUPI Auto] WebSocket init failed:', e);
        }
    }

    function sendWs(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
        }
    }

    function updateAutonomousUI(t) {
        const goal = t.goal || {};
        const state = t.state || {};
        const ladder = t.epistemic_ladder || {};
        const inference = t.fusion_inference || {};
        const safety = t.safety_status || {};
        const safeAction = t.safe_action || {};
        arenaData = t.arena;

        // 1. Pipeline Stepper
        setText('autoPipeCmd', goal.raw_command || 'Find a person in this room.');
        setText('autoPipeGoal', goal.intent || 'SEARCH_FOR_PRESENCE');
        setText('autoPipeObs', ladder.observation || 'PIR=LOW; Ping=125cm');
        setText('autoPipeInterp', ladder.inference || ladder.interpretation || 'Corridor clear');
        setText('autoPipeDecision', state.last_decision || 'ADVANCE');
        setText('autoPipeAction', `${safeAction.action || 'MOVE'} (${safeAction.speed || 0}%)`);

        // 2. Status & Telemetry
        setText('autoGoalDesc', goal.goal_description || 'Active autonomous search');
        setText('autoModeVal', state.mode || 'IDLE');

        const env = state.environment || {};
        const distText = `${env.distance_cm || 0} cm (${env.proximity_class || 'far'})`;
        setText('autoDistVal', distText);

        const motionEl = document.getElementById('autoPirVal');
        if (motionEl) {
            motionEl.textContent = env.motion_detected ? 'DETECTED (PIR HIGH)' : 'NO MOTION (PIR LOW)';
            motionEl.style.color = env.motion_detected ? '#dd6b20' : '#4a5568';
        }

        const robot = state.robot || {};
        setText('autoImuVal', `${robot.orientation} (${robot.heading_deg}° heading)`);
        setText('autoSituationVal', inference.summary || 'Area clear.');
        setText('autoDecisionVal', state.last_decision || 'ADVANCE');
        setText('autoActionVal', safeAction.action || 'STOP');

        // 3. Safety Supervisor
        setText('autoSafetyMsg', safety.status_message || 'Nominal');
        setText('autoOverridesCount', safety.total_overrides || 0);
        const safetyBadge = document.getElementById('autoSafetyBadge');
        if (safetyBadge) {
            if (safety.verdict === 'OVERRIDDEN_FORCED_STOP') {
                safetyBadge.textContent = 'OVERRIDE ACTIVE';
                safetyBadge.className = 'mission-badge-status status-cancelled';
            } else if (safety.verdict === 'MODIFIED') {
                safetyBadge.textContent = 'SPEED CLAMPED';
                safetyBadge.className = 'mission-badge-status';
                safetyBadge.style.background = 'rgba(236, 201, 75, 0.2)';
                safetyBadge.style.color = '#b7791f';
            } else {
                safetyBadge.textContent = 'SAFE';
                safetyBadge.className = 'mission-badge-status status-completed';
            }
        }

        // 4. Report Findings & Speech
        if (inference.report_message && inference.report_message !== lastReport) {
            lastReport = inference.report_message;
            setText('autoReportText', `"${lastReport}"`);

            if (voiceEnabled && window.speechSynthesis && inference.possible_human_presence) {
                const utter = new SpeechSynthesisUtterance(lastReport);
                utter.rate = 1.0;
                utter.pitch = 1.05;
                window.speechSynthesis.speak(utter);
            }
        }

        // Record robot position trails per bot
        if (arenaData) {
            const fleet = arenaData.fleet || (arenaData.robot ? { [arenaData.robot.bot_id || 'bupi_01']: arenaData.robot } : {});
            for (let b_id in fleet) {
                const r = fleet[b_id];
                if (!r || !r.x || !r.y) continue;
                if (!breadcrumbs[b_id]) breadcrumbs[b_id] = [];
                breadcrumbs[b_id].push({ x: r.x, y: r.y });
                if (breadcrumbs[b_id].length > 150) breadcrumbs[b_id].shift();
            }
        }

        renderArena();
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function renderArena() {
        const { c, ctx } = getCanvasAndContext();
        if (!c || !ctx || !arenaData) return;

        const room = arenaData.room || { width_cm: 500, height_cm: 400 };
        const scaleX = c.width / room.width_cm;
        const scaleY = c.height / room.height_cm;

        // Clear canvas
        ctx.fillStyle = '#0d1117';
        ctx.fillRect(0, 0, c.width, c.height);

        // Grid lines with coordinate labels
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
        ctx.lineWidth = 1;
        for (let x = 0; x < c.width; x += 50) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, c.height); ctx.stroke();
        }
        for (let y = 0; y < c.height; y += 40) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(c.width, y); ctx.stroke();
        }

        // Sector divider lines
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.12)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(c.width/2, 0); ctx.lineTo(c.width/2, c.height); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, c.height/2); ctx.lineTo(c.width, c.height/2); ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = 'rgba(148, 163, 184, 0.35)';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText('Sector A (NE)', c.width - 70, 15);
        ctx.fillText('Sector B (NW)', 8, 15);
        ctx.fillText('Sector C (SW)', 8, c.height - 8);
        ctx.fillText('Sector D (SE)', c.width - 70, c.height - 8);

        // Trail breadcrumbs per robot
        for (let b_id in breadcrumbs) {
            const trail = breadcrumbs[b_id];
            if (trail && trail.length > 1) {
                const isBot1 = (b_id === 'bupi_01');
                ctx.strokeStyle = isBot1 ? 'rgba(139, 92, 246, 0.45)' : 'rgba(16, 185, 129, 0.45)';
                ctx.lineWidth = 2;
                ctx.setLineDash([3, 3]);
                ctx.beginPath();
                ctx.moveTo(trail[0].x * scaleX, trail[0].y * scaleY);
                for (let i = 1; i < trail.length; i++) {
                    ctx.lineTo(trail[i].x * scaleX, trail[i].y * scaleY);
                }
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }

        // Draw Obstacles
        const obstacles = arenaData.obstacles || [];
        for (let obs of obstacles) {
            const ox = (obs.x - obs.width/2) * scaleX;
            const oy = (obs.y - obs.height/2) * scaleY;
            const ow = obs.width * scaleX;
            const oh = obs.height * scaleY;

            ctx.fillStyle = 'rgba(100, 116, 139, 0.7)';
            ctx.strokeStyle = '#94a3b8';
            ctx.lineWidth = 1.5;
            ctx.fillRect(ox, oy, ow, oh);
            ctx.strokeRect(ox, oy, ow, oh);

            ctx.fillStyle = '#f1f5f9';
            ctx.font = '10px Inter, sans-serif';
            ctx.fillText('Obstacle', ox + 4, oy + 13);
        }

        // Draw Humans (Warm Targets)
        const humans = arenaData.humans || [];
        for (let h of humans) {
            const hx = h.x * scaleX;
            const hy = h.y * scaleY;

            const grad = ctx.createRadialGradient(hx, hy, 4, hx, hy, 30);
            grad.addColorStop(0, 'rgba(244, 63, 94, 0.7)');
            grad.addColorStop(0.6, 'rgba(244, 63, 94, 0.2)');
            grad.addColorStop(1, 'rgba(244, 63, 94, 0)');
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.arc(hx, hy, 30, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#f43f5e';
            ctx.beginPath();
            ctx.arc(hx, hy, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            ctx.fillStyle = '#fff';
            ctx.font = 'bold 10px Inter, sans-serif';
            ctx.fillText('Warm Human', hx + 12, hy + 4);
        }

        // Draw Dual-Robot Fleet (BUPI-01 Scout & BUPI-02 Specialist)
        const fleet = (arenaData.fleet && Object.keys(arenaData.fleet).length > 0)
            ? arenaData.fleet
            : (arenaData.robot ? { [arenaData.robot.bot_id || 'bupi_01']: arenaData.robot } : {});

        for (let b_id in fleet) {
            const robot = fleet[b_id];
            if (!robot) continue;

            const isBot1 = (b_id === 'bupi_01' || robot.role === 'SCOUT');
            const rx = robot.x * scaleX;
            const ry = robot.y * scaleY;
            const rRadius = (robot.radius_cm || 8) * scaleX;
            const headingRad = (robot.heading_deg * Math.PI) / 180;

            const primaryColor = isBot1 ? '#8b5cf6' : '#10b981';
            const botLabel = isBot1 ? 'BUPI-01 [Scout]' : 'BUPI-02 [Specialist]';

            // 1. Bot 1 Specific: PIR FOV Cone (100 degrees, 250cm range, Amber Aura)
            if (isBot1 && (robot.pir_fov_deg || 100) > 0) {
                const pirRangePx = 250 * scaleX;
                const pirFovRad = ((robot.pir_fov_deg || 100) * Math.PI) / 180;
                ctx.save();
                ctx.fillStyle = robot.pir ? 'rgba(245, 158, 11, 0.32)' : 'rgba(245, 158, 11, 0.10)';
                ctx.strokeStyle = robot.pir ? 'rgba(245, 158, 11, 0.9)' : 'rgba(245, 158, 11, 0.35)';
                ctx.lineWidth = robot.pir ? 2.5 : 1.5;
                ctx.beginPath();
                ctx.moveTo(rx, ry);
                ctx.arc(rx, ry, pirRangePx, headingRad - pirFovRad/2, headingRad + pirFovRad/2);
                ctx.closePath();
                ctx.fill();
                ctx.stroke();
                ctx.restore();
            }

            // 2. Bot 2 Specific: Gas / Smoke Hazard Halo (Radial Plume)
            if (!isBot1 && robot.has_gas) {
                const gasVal = robot.gas_ppm || 0;
                const isHighGas = gasVal > 300.0;
                const haloRadius = Math.min(80, 22 + (gasVal / 12.0)) * scaleX;
                const grad = ctx.createRadialGradient(rx, ry, rRadius, rx, ry, haloRadius);
                if (isHighGas) {
                    grad.addColorStop(0, 'rgba(239, 68, 68, 0.5)');
                    grad.addColorStop(1, 'rgba(239, 68, 68, 0)');
                } else {
                    grad.addColorStop(0, 'rgba(16, 185, 129, 0.25)');
                    grad.addColorStop(1, 'rgba(16, 185, 129, 0)');
                }
                ctx.fillStyle = grad;
                ctx.beginPath();
                ctx.arc(rx, ry, haloRadius, 0, Math.PI * 2);
                ctx.fill();
            }

            // 3. Ultrasonic Beam Cone (25 degrees)
            const distCm = robot.distance_cm || 125;
            const usDistPx = distCm * scaleX;
            const usFovRad = ((robot.ultrasonic_fov_deg || 25) * Math.PI) / 180;
            ctx.save();
            ctx.fillStyle = isBot1 ? 'rgba(59, 130, 246, 0.25)' : 'rgba(16, 185, 129, 0.25)';
            ctx.strokeStyle = isBot1 ? 'rgba(59, 130, 246, 0.75)' : 'rgba(16, 185, 129, 0.75)';
            ctx.lineWidth = 1.8;
            ctx.beginPath();
            ctx.moveTo(rx, ry);
            ctx.arc(rx, ry, usDistPx, headingRad - usFovRad/2, headingRad + usFovRad/2);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();
            ctx.restore();

            // 4. Robot Chassis Body
            ctx.fillStyle = primaryColor;
            ctx.beginPath();
            ctx.arc(rx, ry, rRadius, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Direction Heading Indicator
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.moveTo(rx, ry);
            ctx.lineTo(rx + Math.cos(headingRad) * (rRadius + 8), ry + Math.sin(headingRad) * (rRadius + 8));
            ctx.stroke();

            // Robot Label & Quick Readout Badge
            ctx.fillStyle = primaryColor;
            ctx.font = 'bold 11px Inter, sans-serif';
            ctx.fillText(botLabel, rx - 35, ry - rRadius - 6);

            ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
            ctx.font = '9.5px Inter, sans-serif';
            const statusLine = isBot1
                ? `${distCm.toFixed(0)}cm | PIR:${robot.pir ? 'HIGH' : 'LOW'}`
                : `${distCm.toFixed(0)}cm | Gas:${(robot.gas_ppm || 0).toFixed(0)}ppm`;
            ctx.fillText(statusLine, rx - 30, ry + rRadius + 14);
        }
    }

    function setupCanvasMouseInteraction() {
        const c = document.getElementById('bupiArenaCanvas');
        if (!c) return;

        c.addEventListener('mousedown', (e) => {
            if (!arenaData) return;
            const rect = c.getBoundingClientRect();
            const mouseX = (e.clientX - rect.left) * (c.width / rect.width);
            const mouseY = (e.clientY - rect.top) * (c.height / rect.height);

            const scaleX = c.width / arenaData.room.width_cm;
            const scaleY = c.height / arenaData.room.height_cm;

            // Check humans
            for (let h of arenaData.humans || []) {
                const hx = h.x * scaleX;
                const hy = h.y * scaleY;
                if (Math.hypot(mouseX - hx, mouseY - hy) <= 24) {
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

        c.addEventListener('mousemove', (e) => {
            if (!isDragging || !draggedItem || !arenaData) return;
            const rect = c.getBoundingClientRect();
            const mouseX = (e.clientX - rect.left) * (c.width / rect.width);
            const mouseY = (e.clientY - rect.top) * (c.height / rect.height);

            const scaleX = c.width / arenaData.room.width_cm;
            const scaleY = c.height / arenaData.room.height_cm;

            const roomX = mouseX / scaleX;
            const roomY = mouseY / scaleY;

            if (draggedItem.type === 'human') {
                sendWs({ type: 'move_human', id: draggedItem.id, x: roomX, y: roomY });
            } else if (draggedItem.type === 'obstacle') {
                sendWs({ type: 'move_obstacle', id: draggedItem.id, x: roomX, y: roomY });
            }
        });

        window.addEventListener('mouseup', () => {
            isDragging = false;
            draggedItem = null;
        });
    }

    function setupDOMEvents() {
        const form = document.getElementById('autoCmdForm');
        const input = document.getElementById('autoCmdInput');
        if (form && input) {
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                const cmd = input.value.trim();
                if (cmd) {
                    sendWs({ type: 'command', text: cmd });
                }
            });
        }

        document.querySelectorAll('.auto-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.getAttribute('data-cmd');
                if (input) input.value = cmd;
                sendWs({ type: 'command', text: cmd });
            });
        });

        const testSafetyBtn = document.getElementById('autoBtnTestSafety');
        if (testSafetyBtn) {
            testSafetyBtn.addEventListener('click', () => {
                sendWs({ type: 'inject_obstacle', distance_cm: 11.5 });
            });
        }

        const spawnObsBtn = document.getElementById('autoBtnSpawnObs');
        if (spawnObsBtn) {
            spawnObsBtn.addEventListener('click', () => {
                if (arenaData && arenaData.robot) {
                    const rad = (arenaData.robot.heading_deg * Math.PI) / 180;
                    const ox = arenaData.robot.x + Math.cos(rad) * 35;
                    const oy = arenaData.robot.y + Math.sin(rad) * 35;
                    sendWs({ type: 'move_obstacle', id: 'box_1', x: ox, y: oy });
                }
            });
        }

        const resetArenaBtn = document.getElementById('autoBtnResetArena');
        if (resetArenaBtn) {
            resetArenaBtn.addEventListener('click', () => {
                sendWs({ type: 'move_human', id: 'person_1', x: 340, y: 200 });
                sendWs({ type: 'move_obstacle', id: 'box_1', x: 220, y: 80 });
                breadcrumbs = [];
            });
        }

        const speechBtn = document.getElementById('autoBtnToggleVoice');
        if (speechBtn) {
            speechBtn.addEventListener('click', () => {
                voiceEnabled = !voiceEnabled;
                speechBtn.textContent = voiceEnabled ? '🔊 Voice On' : '🔇 Voice Off';
            });
        }
    }

    // Expose renderArena globally so notepad.js and external callers can refresh the canvas
    window.renderBupiArena = renderArena;
    window.addEventListener('resize', () => {
        renderArena();
    });

    document.addEventListener('DOMContentLoaded', () => {
        setupDOMEvents();
        setupCanvasMouseInteraction();
        initWebSocket();
        renderArena();
        setTimeout(renderArena, 150);
        setTimeout(renderArena, 600);
    });
})();
