/**
 * missions.js - Bupi Hub Universal Mission Debrief & Reports Dashboard
 * Project-Agnostic Mission Intelligence, Dynamic Telemetry Aggregation & Run History
 */

(() => {
    const { ipcRenderer } = require('electron');

    // -------------------------------------------------------------
    // State
    // -------------------------------------------------------------
    let currentMissionStatus = {
        state: 'idle',
        goal: '',
        project_type: 'Project-Agnostic Engine',
        duration_seconds: 0,
        obstacles_avoided: 0,
        sectors_scanned: 0,
        sensors: {}
    };

    let activeDebriefReport = null;
    let missionsHistory = [];
    let timerInterval = null;
    let timerSeconds = 0;

    // -------------------------------------------------------------
    // Icons & Project Types
    // -------------------------------------------------------------
    const PROJECT_ICONS = {
        'Search & Rescue': '🔍',
        'Hazard & Gas Inspection': '🔥',
        'Perimeter Security Patrol': '🛡️',
        'Environmental Climate Survey': '🌡️',
        'Autonomous Room Exploration': '🗺️',
        'Autonomous Navigation': '🚀'
    };

    function getProjectIcon(projectType) {
        return PROJECT_ICONS[projectType] || '🚀';
    }

    function formatDuration(sec) {
        if (!sec || isNaN(sec)) return '00:00';
        const mins = Math.floor(sec / 60);
        const secs = Math.floor(sec % 60);
        return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }

    // -------------------------------------------------------------
    // Initialization
    // -------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        setupEventListeners();
        setupIPCListeners();

        // Initial fetch if panel is already in DOM
        ipcRenderer.send('request-mission-history');
        ipcRenderer.send('request-mission-status');
    });

    // -------------------------------------------------------------
    // DOM Event Listeners
    // -------------------------------------------------------------
    function setupEventListeners() {
        // Modal Controls
        const launchBtn = document.getElementById('launchMissionBtn');
        const modal = document.getElementById('newMissionModal');
        const closeModalBtn = document.getElementById('closeMissionModalBtn');
        const cancelModalBtn = document.getElementById('cancelMissionModalBtn');
        const confirmStartBtn = document.getElementById('confirmStartMissionBtn');
        const customGoalInput = document.getElementById('customMissionGoalInput');
        const stopBtn = document.getElementById('stopActiveMissionBtn');
        const refreshBtn = document.getElementById('refreshMissionDataBtn');

        if (launchBtn && modal) {
            launchBtn.addEventListener('click', () => {
                modal.classList.add('active');
                if (customGoalInput) {
                    customGoalInput.focus();
                }
            });
        }

        const closeModal = () => {
            if (modal) modal.classList.remove('active');
        };

        if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
        if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

        // Preset Goal Buttons
        document.querySelectorAll('.preset-goal-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const goal = btn.getAttribute('data-goal');
                if (customGoalInput) {
                    customGoalInput.value = goal;
                    customGoalInput.focus();
                }
            });
        });

        // Confirm Start Mission
        if (confirmStartBtn) {
            confirmStartBtn.addEventListener('click', () => {
                const goal = customGoalInput ? customGoalInput.value.trim() : '';
                if (!goal) {
                    alert('Please enter or select a mission goal for Boopi!');
                    return;
                }
                ipcRenderer.send('trigger-mission', goal);
                closeModal();
                if (customGoalInput) customGoalInput.value = '';
            });
        }

        // Emergency / Mission Stop Button
        if (stopBtn) {
            stopBtn.addEventListener('click', () => {
                if (confirm('Are you sure you want to stop the active mission? Boopi will stop driving and compile a debrief.')) {
                    ipcRenderer.send('stop-mission');
                }
            });
        }

        // Refresh Data
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                refreshBtn.classList.add('spinning');
                ipcRenderer.send('request-mission-history');
                ipcRenderer.send('request-mission-status');
                setTimeout(() => refreshBtn.classList.remove('spinning'), 800);
            });
        }

        // History Search Filter
        const searchInput = document.getElementById('missionSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                const query = searchInput.value.toLowerCase().trim();
                filterMissionHistory(query);
            });
        }

        // Action Buttons on Debrief Card
        const copyMarkdownBtn = document.getElementById('copyDebriefMarkdownBtn');
        if (copyMarkdownBtn) {
            copyMarkdownBtn.addEventListener('click', () => {
                if (!activeDebriefReport || !activeDebriefReport.report_markdown) {
                    alert('No debrief report currently loaded to copy.');
                    return;
                }
                navigator.clipboard.writeText(activeDebriefReport.report_markdown).then(() => {
                    const orig = copyMarkdownBtn.innerHTML;
                    copyMarkdownBtn.innerHTML = '✅ Copied!';
                    setTimeout(() => copyMarkdownBtn.innerHTML = orig, 2000);
                });
            });
        }

        const sendToNotesBtn = document.getElementById('sendDebriefToNotesBtn');
        if (sendToNotesBtn) {
            sendToNotesBtn.addEventListener('click', () => {
                if (!activeDebriefReport || !activeDebriefReport.report_markdown) {
                    alert('No debrief report currently loaded to send.');
                    return;
                }
                // Switch to Notes Panel
                switchToTab('panel-notes');
                const noteTitle = document.getElementById('noteTitle');
                const noteContent = document.getElementById('noteContent');
                if (noteTitle) {
                    noteTitle.value = activeDebriefReport.mission_name || `Mission Debrief - ${activeDebriefReport.project_type}`;
                }
                if (noteContent) {
                    noteContent.value = activeDebriefReport.report_markdown;
                    noteContent.dispatchEvent(new Event('input'));
                }
            });
        }

        const exportJsonBtn = document.getElementById('exportDebriefJsonBtn');
        if (exportJsonBtn) {
            exportJsonBtn.addEventListener('click', () => {
                if (!activeDebriefReport) {
                    alert('No debrief report to export.');
                    return;
                }
                const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(activeDebriefReport, null, 2));
                const downloadAnchor = document.createElement('a');
                downloadAnchor.setAttribute("href", dataStr);
                const safeName = (activeDebriefReport.mission_name || 'mission_report').toLowerCase().replace(/[^a-z0-9]/g, '_');
                downloadAnchor.setAttribute("download", `${safeName}.json`);
                document.body.appendChild(downloadAnchor);
                downloadAnchor.click();
                downloadAnchor.remove();
            });
        }
    }

    // -------------------------------------------------------------
    // IPC Listeners
    // -------------------------------------------------------------
    function setupIPCListeners() {
        ipcRenderer.on('mission-status', (event, status) => {
            currentMissionStatus = status;
            renderMissionStatus(status);
        });

        ipcRenderer.on('mission-report', (event, report) => {
            activeDebriefReport = report;
            renderDebriefCard(report);
            // Request refreshed history list so newly compiled report appears
            ipcRenderer.send('request-mission-history');
        });

        ipcRenderer.on('mission-history', (event, history) => {
            missionsHistory = history || [];
            renderMissionHistory(missionsHistory);
            
            // If active debrief card is empty, display latest mission; otherwise if history is empty, reset
            if (missionsHistory.length > 0) {
                if (!activeDebriefReport || !missionsHistory.some(m => m.id === activeDebriefReport.id)) {
                    activeDebriefReport = missionsHistory[0];
                }
                renderDebriefCard(activeDebriefReport);
            } else {
                activeDebriefReport = null;
                resetDebriefCardToStandby();
            }
        });

        ipcRenderer.on('notepad-switch-tab', (event, targetTabId) => {
            switchToTab(targetTabId);
        });
    }

    // -------------------------------------------------------------
    // Tab Navigation Helper
    // -------------------------------------------------------------
    function switchToTab(tabId) {
        const navItems = document.querySelectorAll('.nav-item');
        const panels = document.querySelectorAll('.content-panel');

        navItems.forEach(n => {
            if (n.getAttribute('data-target') === tabId) {
                n.classList.add('active');
            } else {
                n.classList.remove('active');
            }
        });

        panels.forEach(p => {
            if (p.id === tabId) {
                p.classList.add('active');
            } else {
                p.classList.remove('active');
            }
        });

        if (tabId === 'panel-missions') {
            ipcRenderer.send('request-mission-history');
            ipcRenderer.send('request-mission-status');
        }
    }

    function parseTimestamp(raw) {
        if (!raw) return null;
        let num = Number(raw);
        if (!isNaN(num) && num > 0) {
            if (num < 1e11) {
                num *= 1000;
            }
            return new Date(num);
        }
        const d = new Date(raw);
        return isNaN(d.getTime()) ? null : d;
    }

    function resetDebriefCardToStandby() {
        const titleElem = document.getElementById('debriefTitle');
        const typeElem = document.getElementById('debriefProjectType');
        const statusBadge = document.getElementById('debriefStatusBadge');
        const timestampElem = document.getElementById('debriefTimestamp');
        const statDuration = document.getElementById('statDuration');
        const statObstacles = document.getElementById('statObstacles');
        const statSectors = document.getElementById('statSectors');
        const statOutcome = document.getElementById('statOutcome');
        const telemetryBody = document.getElementById('debriefTelemetryBody');
        const timelineContainer = document.getElementById('debriefTimelineContainer');
        const markdownPreview = document.getElementById('debriefMarkdownPreview');

        if (titleElem) titleElem.textContent = 'Mission Standby';
        if (typeElem) typeElem.textContent = 'Awaiting Mission';
        if (statusBadge) {
            statusBadge.className = 'mission-badge-status status-idle';
            statusBadge.textContent = 'STANDBY';
        }
        if (timestampElem) timestampElem.textContent = 'No missions executed yet. Click "Launch Mission" to begin.';
        if (statDuration) statDuration.textContent = '--';
        if (statObstacles) statObstacles.textContent = '--';
        if (statSectors) statSectors.textContent = '--';
        if (statOutcome) statOutcome.textContent = '--';
        if (telemetryBody) {
            telemetryBody.innerHTML = `
                <tr>
                    <td colspan="4" style="text-align: center; color: var(--text-light); padding: 15px;">
                        No sensor telemetry recorded yet.
                    </td>
                </tr>
            `;
        }
        if (timelineContainer) {
            timelineContainer.innerHTML = `
                <div class="timeline-entry">
                    <span class="time">--:--</span>
                    <span class="desc" style="color: var(--text-light); font-style: italic;">No mission timeline recorded.</span>
                </div>
            `;
        }
        if (markdownPreview) {
            markdownPreview.textContent = 'No debrief report generated yet. Run a mission to view the post-mission debrief.';
        }
    }

    // -------------------------------------------------------------
    // Live Mission Status & HUD Rendering
    // -------------------------------------------------------------
    function renderMissionStatus(status) {
        const badge = document.getElementById('missionStatusBadge');
        const badgeDot = document.getElementById('missionStatusDot');
        const badgeText = document.getElementById('missionStatusText');
        const typeBadge = document.getElementById('missionTypeBadge');
        const timerText = document.getElementById('missionTimerText');
        const goalText = document.getElementById('missionGoalText');
        const missionIcon = document.getElementById('missionIcon');
        const stopBtn = document.getElementById('stopActiveMissionBtn');
        const launchBtn = document.getElementById('launchMissionBtn');

        if (!status) return;

        const state = (status.state || 'idle').toLowerCase();
        const isRunning = (state === 'executing' || state === 'avoiding' || state === 'planning' || state === 'scanning');

        // Update Banner Badges
        if (badge && badgeText && badgeDot) {
            badge.className = 'mission-badge-status';
            if (isRunning) {
                badge.classList.add('status-running');
                badgeDot.style.background = '#48bb78';
                badgeText.textContent = state.toUpperCase();
            } else if (state === 'completed') {
                badge.classList.add('status-completed');
                badgeDot.style.background = '#4299e1';
                badgeText.textContent = 'COMPLETED';
            } else if (state === 'cancelled' || state === 'failed') {
                badge.classList.add('status-cancelled');
                badgeDot.style.background = '#f56565';
                badgeText.textContent = state.toUpperCase();
            } else {
                badge.classList.add('status-idle');
                badgeDot.style.background = '#718096';
                badgeText.textContent = 'IDLE';
            }
        }

        if (typeBadge) {
            typeBadge.textContent = status.project_type || 'Autonomous Agentic Robot';
        }

        if (goalText) {
            goalText.textContent = status.goal ? `🎯 ${status.goal}` : 'No active mission running. Select or launch a mission below.';
        }

        if (missionIcon) {
            missionIcon.textContent = getProjectIcon(status.project_type);
        }

        // Live Timer
        if (isRunning) {
            if (!timerInterval) {
                timerSeconds = status.duration_seconds || 0;
                timerInterval = setInterval(() => {
                    timerSeconds += 1;
                    if (timerText) timerText.textContent = formatDuration(timerSeconds);
                }, 1000);
            }
        } else {
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }
            if (timerText) timerText.textContent = formatDuration(status.duration_seconds || 0);
        }

        // Button states
        if (stopBtn) stopBtn.disabled = !isRunning;
        if (launchBtn) launchBtn.disabled = isRunning;

        // Update Sensor HUD
        updateSensorHUD(status);
    }

    function updateSensorHUD(status) {
        const sensors = status.sensors || {};

        // Obstacle Distance
        const distVal = document.getElementById('hudDistanceVal');
        const distStatus = document.getElementById('hudDistanceStatus');
        const distance = sensors['ultrasonic_distance'] !== undefined ? sensors['ultrasonic_distance'] : 
                         (sensors['distance'] !== undefined ? sensors['distance'] : null);

        if (distVal && distStatus) {
            if (distance !== null) {
                distVal.textContent = Math.round(distance);
                if (distance < 20) {
                    distStatus.textContent = '🔴 Obstacle Close';
                    distStatus.style.color = '#f56565';
                } else if (distance < 35) {
                    distStatus.textContent = '🟡 Cautious Proximity';
                    distStatus.style.color = '#ed8936';
                } else {
                    distStatus.textContent = '🟢 Clear Path';
                    distStatus.style.color = 'var(--accent-green)';
                }
            } else {
                distVal.textContent = '--';
                distStatus.textContent = '⚪ Standby';
                distStatus.style.color = 'var(--text-light)';
            }
        }

        // Gas / Air Quality
        const gasVal = document.getElementById('hudGasVal');
        const gasStatus = document.getElementById('hudGasStatus');
        const gas = sensors['mq2_gas'] !== undefined ? sensors['mq2_gas'] : 
                    (sensors['gas'] !== undefined ? sensors['gas'] : null);

        if (gasVal && gasStatus) {
            if (gas !== null) {
                gasVal.textContent = Math.round(gas);
                if (gas > 400) {
                    gasStatus.textContent = '🚨 Hazard Alert!';
                    gasStatus.style.color = '#f56565';
                } else if (gas > 250) {
                    gasStatus.textContent = '🟡 Elevated Gas';
                    gasStatus.style.color = '#ed8936';
                } else {
                    gasStatus.textContent = '🟢 Normal';
                    gasStatus.style.color = 'var(--accent-green)';
                }
            } else {
                gasVal.textContent = '--';
                gasStatus.textContent = '⚪ Normal Air';
                gasStatus.style.color = 'var(--text-light)';
            }
        }

        // Compass / Heading
        const headingVal = document.getElementById('hudHeadingVal');
        const headingStatus = document.getElementById('hudHeadingStatus');
        const heading = sensors['heading'] !== undefined ? sensors['heading'] : 0;
        if (headingVal) headingVal.textContent = Math.round(heading);
        if (headingStatus) headingStatus.textContent = `🧭 Facing ${Math.round(heading)}°`;

        // Avoidances Count
        const avoidCount = document.getElementById('hudAvoidanceCount');
        if (avoidCount) {
            avoidCount.textContent = status.obstacles_avoided || 0;
        }

        // Dynamic Extra Real Sensors Discovery in HUD
        const hudGrid = document.getElementById('missionSensorsGrid');
        if (hudGrid) {
            const IGNORED_KEYS = new Set([
                'ultrasonic_distance', 'distance', 'mq2_gas', 'gas', 'heading',
                'telemetry_fresh', 'timestamp', 'mode', 'device', 'ip', 'status', 'id'
            ]);

            const validKeys = sensors ? Object.keys(sensors).filter(k => !IGNORED_KEYS.has(k) && typeof sensors[k] !== 'boolean') : [];

            // Prune cards for sensors that are no longer active
            const extraCards = hudGrid.querySelectorAll('[id^="hud-extra-"]');
            extraCards.forEach(card => {
                const key = card.id.replace('hud-extra-', '');
                if (!validKeys.includes(key)) {
                    card.remove();
                }
            });

            validKeys.forEach(sensorKey => {
                let existingCard = document.getElementById(`hud-extra-${sensorKey}`);
                if (!existingCard) {
                    existingCard = document.createElement('div');
                    existingCard.className = 'sensor-card';
                    existingCard.id = `hud-extra-${sensorKey}`;
                    hudGrid.appendChild(existingCard);
                }
                const val = sensors[sensorKey];
                existingCard.innerHTML = `
                    <div class="sensor-card-header">
                        <span>📡 ${sensorKey.toUpperCase()}</span>
                        <span style="color: var(--accent-green);">LIVE</span>
                    </div>
                    <div class="sensor-card-val">
                        <span>${typeof val === 'number' ? (Number.isInteger(val) ? val : val.toFixed(1)) : val}</span>
                    </div>
                    <div class="sensor-card-status" style="color: var(--accent-green);">
                        🟢 Active Telemetry
                    </div>
                `;
            });
        }
    }

    // -------------------------------------------------------------
    // Mission Debrief Card Rendering
    // -------------------------------------------------------------
    function renderDebriefCard(report) {
        if (!report) {
            resetDebriefCardToStandby();
            return;
        }

        const titleElem = document.getElementById('debriefTitle');
        const typeElem = document.getElementById('debriefProjectType');
        const statusBadge = document.getElementById('debriefStatusBadge');
        const timestampElem = document.getElementById('debriefTimestamp');
        const statDuration = document.getElementById('statDuration');
        const statObstacles = document.getElementById('statObstacles');
        const statSectors = document.getElementById('statSectors');
        const statOutcome = document.getElementById('statOutcome');
        const telemetryBody = document.getElementById('debriefTelemetryBody');
        const timelineContainer = document.getElementById('debriefTimelineContainer');
        const markdownPreview = document.getElementById('debriefMarkdownPreview');

        // Parse findings JSON
        let findings = {};
        try {
            findings = typeof report.findings_json === 'string' ? JSON.parse(report.findings_json) : (report.findings_json || {});
        } catch (e) {
            findings = {};
        }

        // Basic Info
        if (titleElem) titleElem.textContent = report.mission_name || report.goal || 'Mission Debrief';
        if (typeElem) {
            const pType = report.project_type || 'Project-Agnostic Mission';
            typeElem.innerHTML = `<span>${getProjectIcon(pType)}</span> ${pType}`;
        }
        if (statusBadge) {
            const status = (report.status || 'COMPLETED').toUpperCase();
            statusBadge.className = 'mission-badge-status';
            if (status === 'COMPLETED' || status === 'SUCCESS') {
                statusBadge.classList.add('status-completed');
            } else if (status === 'CANCELLED' || status === 'FAILED') {
                statusBadge.classList.add('status-cancelled');
            } else {
                statusBadge.classList.add('status-running');
            }
            statusBadge.textContent = status;
        }

        if (timestampElem) {
            const d = parseTimestamp(report.started_at);
            const started = d ? d.toLocaleString() : 'Recent';
            timestampElem.textContent = `Executed: ${started} | Goal: "${report.goal || 'Autonomous Run'}"`;
        }

        // Metrics
        if (statDuration) statDuration.textContent = formatDuration(report.duration_seconds);
        if (statObstacles) statObstacles.textContent = findings.obstacles_avoided || '0';
        if (statSectors) statSectors.textContent = findings.sectors_scanned || '0';
        if (statOutcome) {
            const outcome = findings.target_confirmed ? '🎯 Target Verified' : (report.status === 'completed' ? '✅ Finished' : '⏹️ Stopped');
            statOutcome.textContent = outcome;
        }

        // Telemetry Snapshot Table
        if (telemetryBody) {
            const snapshot = findings.telemetry_snapshot || {};
            const keys = Object.keys(snapshot);
            if (keys.length === 0) {
                telemetryBody.innerHTML = `
                    <tr>
                        <td colspan="4" style="text-align: center; color: var(--text-light); padding: 15px;">
                            No sensor snapshot logged for this run.
                        </td>
                    </tr>
                `;
            } else {
                telemetryBody.innerHTML = '';
                keys.forEach(sensorName => {
                    const data = snapshot[sensorName] || {};
                    const val = data.value !== undefined ? data.value : data;
                    const d = parseTimestamp(data.timestamp);
                    const time = d ? d.toLocaleTimeString() : 'Current';
                    
                    let healthStatus = '🟢 Normal';
                    let healthColor = 'var(--accent-green)';
                    if (sensorName.includes('gas') && val > 300) {
                        healthStatus = '🚨 Elevated Gas';
                        healthColor = '#f56565';
                    } else if (sensorName.includes('distance') && val < 25) {
                        healthStatus = '🟡 Obstacle Proximity';
                        healthColor = '#ed8936';
                    }

                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${sensorName}</strong></td>
                        <td><code style="font-family: monospace; font-size: 13px; font-weight: 700; color: #5b4de0;">${val}</code></td>
                        <td style="color: var(--text-light); font-size: 11px;">${time}</td>
                        <td><span style="color: ${healthColor}; font-weight: 600;">${healthStatus}</span></td>
                    `;
                    telemetryBody.appendChild(row);
                });
            }
        }

        // Timeline
        if (timelineContainer) {
            const events = findings.events || [];
            if (events.length === 0) {
                timelineContainer.innerHTML = `
                    <div class="timeline-entry">
                        <span class="time">00:00</span>
                        <span class="desc" style="color: var(--text-light); font-style: italic;">Mission started and concluded normally.</span>
                    </div>
                `;
            } else {
                timelineContainer.innerHTML = '';
                events.forEach(evt => {
                    const entry = document.createElement('div');
                    entry.className = 'timeline-entry';
                    const d = parseTimestamp(evt.timestamp);
                    const timeStr = d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--:--';
                    entry.innerHTML = `
                        <span class="time">[${timeStr}]</span>
                        <span class="desc"><strong>${evt.event_type || 'EVENT'}:</strong> ${evt.description || ''}</span>
                    `;
                    timelineContainer.appendChild(entry);
                });
            }
        }

        // Markdown Report
        if (markdownPreview) {
            markdownPreview.textContent = report.report_markdown || 'No markdown report available.';
        }
    }

    // -------------------------------------------------------------
    // Mission History List
    // -------------------------------------------------------------
    function renderMissionHistory(list) {
        const historyList = document.getElementById('missionHistoryList');
        const countElem = document.getElementById('missionHistoryCount');

        if (!historyList) return;

        if (countElem) {
            countElem.textContent = `${list.length} mission${list.length === 1 ? '' : 's'}`;
        }

        if (!list || list.length === 0) {
            historyList.innerHTML = `
                <div style="text-align: center; padding: 25px 10px; color: var(--text-light); font-size: 12px;">
                    No past missions logged yet.<br>Click "Launch Mission" to run!
                </div>
            `;
            return;
        }

        historyList.innerHTML = '';
        list.forEach(item => {
            const card = document.createElement('div');
            card.className = 'mission-history-card';
            if (activeDebriefReport && activeDebriefReport.id === item.id) {
                card.classList.add('active');
            }

            const pType = item.project_type || 'General Exploration';
            const icon = getProjectIcon(pType);
            const status = (item.status || 'COMPLETED').toUpperCase();
            const d = parseTimestamp(item.started_at);
            const dateStr = d ? d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Recent';

            let statusClass = 'status-completed';
            if (status === 'CANCELLED' || status === 'FAILED') statusClass = 'status-cancelled';
            if (status === 'EXECUTING' || status === 'RUNNING') statusClass = 'status-running';

            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 11px; font-weight: 700; color: #5b4de0; display: flex; align-items: center; gap: 4px;">
                        <span>${icon}</span> ${pType}
                    </span>
                    <span class="mission-badge-status ${statusClass}" style="font-size: 9.5px; padding: 2px 7px;">
                        ${status}
                    </span>
                </div>
                <div style="font-size: 12.5px; font-weight: 700; color: var(--text-dark); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ${item.mission_name || item.goal || 'Autonomous Run'}
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-light);">
                    <span>📅 ${dateStr}</span>
                    <span>⏱️ ${formatDuration(item.duration_seconds)}</span>
                </div>
            `;

            card.addEventListener('click', () => {
                document.querySelectorAll('.mission-history-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                activeDebriefReport = item;
                renderDebriefCard(item);
            });

            historyList.appendChild(card);
        });
    }

    function filterMissionHistory(query) {
        if (!query) {
            renderMissionHistory(missionsHistory);
            return;
        }

        const filtered = missionsHistory.filter(m => {
            const goal = (m.goal || '').toLowerCase();
            const name = (m.mission_name || '').toLowerCase();
            const type = (m.project_type || '').toLowerCase();
            const status = (m.status || '').toLowerCase();
            return goal.includes(query) || name.includes(query) || type.includes(query) || status.includes(query);
        });

        renderMissionHistory(filtered);
    }

})();
