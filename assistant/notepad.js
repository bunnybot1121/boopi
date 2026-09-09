(() => {
const ipcRenderer = (typeof require !== 'undefined') ? require('electron').ipcRenderer : {
    send: (c, ...a) => console.log('[IPC Mock]', c, ...a),
    on: (c, fn) => console.log('[IPC Mock on]', c)
};
const fs = (typeof require !== 'undefined') ? require('fs') : null;
const path = (typeof require !== 'undefined') ? require('path') : null;

document.addEventListener('DOMContentLoaded', () => {
    // Window controls
    const minBtn = document.getElementById('minBtn');
    const maxBtn = document.getElementById('maxBtn');
    const closeBtn = document.getElementById('closeBtn');

    minBtn.addEventListener('click', () => ipcRenderer.send('notepad-minimize'));
    maxBtn.addEventListener('click', () => ipcRenderer.send('notepad-maximize'));
    closeBtn.addEventListener('click', () => ipcRenderer.send('notepad-close'));

    // -------------------------------------------------------------
    // Quick Component Builder Autocomplete & Ingestion Logic
    // -------------------------------------------------------------
    let allComponents = [];
    let selectedComponents = [];

    try {
        let registryPath = path.join(__dirname, 'footmo2-v2', 'registry.json');
        if (!fs.existsSync(registryPath)) {
            registryPath = path.join(process.cwd(), 'footmo2-v2', 'registry.json');
        }
        if (!fs.existsSync(registryPath)) {
            registryPath = 'C:\\Users\\Sachin\\boopi\\assistant\\footmo2-v2\\registry.json';
        }
        
        if (fs.existsSync(registryPath)) {
            const registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
            if (registry && registry.components) {
                allComponents = Object.keys(registry.components).map(key => ({
                    id: key,
                    name: registry.components[key].type.replace(/_/g, ' ').toUpperCase() + ` (${key})`,
                    spec: registry.components[key]
                }));
            }
        }
    } catch (e) {
        console.error("Failed to load components registry:", e);
    }

    const componentSearchInput = document.getElementById('componentSearchInput');
    const autocompleteDropdown = document.getElementById('autocompleteDropdown');
    const selectedComponentsContainer = document.getElementById('selectedComponentsContainer');

    function updateSelectedTags() {
        if (!selectedComponentsContainer) return;
        selectedComponentsContainer.innerHTML = '';
        if (selectedComponents.length === 0) {
            selectedComponentsContainer.innerHTML = '<span style="font-size: 11px; color: var(--text-light); font-style: italic;">No components selected yet. Start typing to build.</span>';
            return;
        }

        selectedComponents.forEach(compId => {
            const comp = allComponents.find(c => c.id === compId);
            const tag = document.createElement('span');
            tag.style.cssText = 'display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 8px; font-size: 11.5px; font-weight: 600; background: rgba(142, 148, 242, 0.15); border: 1px solid rgba(142, 148, 242, 0.3); color: var(--text-dark); cursor: pointer; transition: all 0.2s;';
            tag.innerHTML = `<span>${comp ? comp.id : compId}</span> <span style="color: #ff5f56; font-weight: 700; margin-left: 4px;">×</span>`;
            tag.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectedComponents = selectedComponents.filter(c => c !== compId);
                updateSelectedTags();
            });
            selectedComponentsContainer.appendChild(tag);
        });
    }

    let searchDebounce = null;
    let onlineComponents = [];

    function renderAutocompleteList(query) {
        if (!autocompleteDropdown) return;
        autocompleteDropdown.innerHTML = '';
        if (!query) {
            autocompleteDropdown.style.display = 'none';
            return;
        }

        // Get local matches
        const localMatches = allComponents.filter(c => 
            (c.id.toLowerCase().includes(query) || c.name.toLowerCase().includes(query)) && 
            !selectedComponents.includes(c.id)
        );

        // Get online matches that aren't already selected or in local matches
        const filteredOnline = onlineComponents.filter(c => 
            !selectedComponents.includes(c.id) &&
            !localMatches.some(lm => lm.id.toLowerCase() === c.id.toLowerCase())
        );

        // Combine them
        const matches = [...localMatches, ...filteredOnline];

        if (matches.length === 0) {
            const noMatch = document.createElement('div');
            noMatch.style.cssText = 'padding: 12px 14px; font-size: 12px; color: var(--text-light); font-style: italic;';
            noMatch.textContent = query.length > 2 ? 'Searching online databases...' : 'Keep typing to search...';
            autocompleteDropdown.appendChild(noMatch);
            autocompleteDropdown.style.display = 'block';
            return;
        }

        matches.forEach(match => {
            const item = document.createElement('div');
            item.style.cssText = 'padding: 10px 14px; font-size: 12.5px; cursor: pointer; color: var(--text-dark); border-bottom: 1px solid rgba(0,0,0,0.03); transition: background 0.2s; font-family: var(--font-family); display: flex; justify-content: space-between; align-items: center; gap: 10px;';
            
            const sourceBadge = match.source ? 
                `<span class="provider-badge" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(142, 148, 242, 0.12); color: var(--primary); font-weight: 700; flex-shrink: 0;">${match.source}</span>` : 
                `<span class="provider-badge" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(0, 0, 0, 0.05); color: var(--text-light); font-weight: 600; flex-shrink: 0;">Local</span>`;
                
            item.innerHTML = `
                <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">
                    <strong style="color:var(--primary); font-family:monospace;">${match.id}</strong> — ${match.name}
                </div>
                ${sourceBadge}
            `;
            
            item.addEventListener('mouseenter', () => item.style.backgroundColor = 'rgba(142, 148, 242, 0.08)');
            item.addEventListener('mouseleave', () => item.style.backgroundColor = 'transparent');
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                
                selectedComponents.push(match.id);
                
                if (!allComponents.some(c => c.id === match.id)) {
                    allComponents.push(match);
                }
                
                updateSelectedTags();
                componentSearchInput.value = '';
                autocompleteDropdown.style.display = 'none';
                onlineComponents = [];
            });
            autocompleteDropdown.appendChild(item);
        });
        autocompleteDropdown.style.display = 'block';
    }

    if (componentSearchInput && autocompleteDropdown) {
        componentSearchInput.addEventListener('input', () => {
            const query = componentSearchInput.value.trim().toLowerCase();
            
            renderAutocompleteList(query);
            
            if (searchDebounce) clearTimeout(searchDebounce);
            
            if (query.length > 2) {
                searchDebounce = setTimeout(() => {
                    ipcRenderer.send('search-components-online', query);
                }, 300);
            } else {
                onlineComponents = [];
            }
        });

        ipcRenderer.on('online-search-results', (event, msg) => {
            const query = componentSearchInput.value.trim().toLowerCase();
            if (msg.query.toLowerCase() !== query) return;
            
            onlineComponents = msg.results || [];
            renderAutocompleteList(query);
        });

        document.addEventListener('click', (e) => {
            if (e.target !== componentSearchInput && !autocompleteDropdown.contains(e.target)) {
                autocompleteDropdown.style.display = 'none';
            }
        });
    }

    // Tab Navigation
    const navItems = document.querySelectorAll('.nav-item');
    const panels = document.querySelectorAll('.content-panel');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // Remove active from all
            navItems.forEach(nav => nav.classList.remove('active'));
            panels.forEach(panel => panel.classList.remove('active'));

            // Add active to clicked
            item.classList.add('active');
            const targetId = item.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');

            if (targetId === 'panel-missions') {
                ipcRenderer.send('request-mission-history');
                ipcRenderer.send('request-mission-status');
            } else if (targetId === 'panel-settings') {
                triggerKeyRefresh();
            } else if (targetId === 'panel-esp') {
                loadRegisteredDevices();
                ipcRenderer.send('request-connected-nodes');
            } else if (targetId === 'panel-trained') {
                loadTrainedDevices();
            } else if (targetId === 'panel-footmo2') {
                const iframe = document.getElementById('footmo2-iframe');
                if (iframe) {
                    iframe.src = iframe.src; // Force refresh iframe
                }
            } else if (targetId === 'panel-autonomous') {
                const canvas = document.getElementById('bupiArenaCanvas');
                if (canvas && canvas.parentElement) {
                    canvas.width = canvas.parentElement.clientWidth || 500;
                    canvas.height = canvas.parentElement.clientHeight || 340;
                }
            } else if (targetId === 'panel-bwe') {
                if (typeof initializeBWE === 'function') {
                    initializeBWE();
                }
            }
        });
    });

    // Notes Logic
    const saveBtn = document.getElementById('saveBtn');
    const noteContent = document.getElementById('noteContent');
    const noteTitle = document.getElementById('noteTitle');
    const wordCount = document.getElementById('wordCount');
    const saveStatus = document.getElementById('saveStatus');

    noteContent.addEventListener('input', () => {
        const text = noteContent.value;
        const words = text.trim() === '' ? 0 : text.trim().split(/\s+/).length;
        wordCount.textContent = words;
        
        saveStatus.textContent = 'Editing...';
        saveStatus.style.color = '#ffbd2e'; // Yellow while editing
    });

    saveBtn.addEventListener('click', () => {
        saveStatus.textContent = 'Saved just now';
        saveStatus.style.color = 'var(--accent-green)'; // Green when saved
        
        ipcRenderer.send('notepad-save', {
            title: noteTitle.value,
            content: noteContent.value
        });
    });

    // ESP32 Logic
    const pingEspBtn = document.getElementById('pingEspBtn');
    if (pingEspBtn) {
        pingEspBtn.addEventListener('click', () => {
            alert("Sent Ping to ESP32! (Backend wiring in progress)");
        });
    }

    // Hardware Ingestion Logic
    const processHardwareBtn = document.getElementById('processHardwareBtn');
    const flashHardwareBtn = document.getElementById('flashHardwareBtn');
    const hardwareInput = document.getElementById('hardwareInput');
    const hardwareOutput = document.getElementById('hardwareOutput');

    if (processHardwareBtn) {
        processHardwareBtn.addEventListener('click', () => {
            let code = '';
            
            if (selectedComponents.length > 0) {
                const specDetails = selectedComponents.map(id => {
                    const comp = allComponents.find(c => c.id === id);
                    return {
                        id: id,
                        ...(comp ? comp.spec : {})
                    };
                });
                
                const purposeInput = document.getElementById('componentPurposeInput');
                const purpose = purposeInput ? purposeInput.value.trim() : '';
                
                code = `AI COMPONENT BUILDER REQUEST:\n` +
                       `Generates compilable minimal ESP32 Arduino client code with local MQTT publishing for these components:\n` +
                       `${JSON.stringify(specDetails, null, 2)}\n\n`;
                       
                if (purpose) {
                    code += `USER APPLICATION PURPOSE AND SCENARIO:\n` +
                            `The user wants to use these components for this specific purpose/application:\n` +
                            `"${purpose}"\n\n`;
                }
                
                code += `CRITICAL INSTRUCTIONS:\n` +
                        `1. Generate fully compiled minimal code using PubSubClient and WiFi libraries.\n` +
                        `2. Use the exact component pin assignments, libraries, and protocols specified in the schema.\n` +
                        `3. Automatically format all incoming/outgoing MQTT topics using footmo2/{device_id}/cmd and footmo2/{device_id}/sensor/{id}.\n` +
                        `4. Include clear, step-by-step physical wiring/connection instructions as a comment block at the very top of the code, explaining exactly which ESP32 pins should connect to which component pins (e.g. VCC, GND, SDA, SCL, analog/digital pins) based on the specs.\n` +
                        `5. Make the code direct and compile-ready without markdown fences or text formatting.`;
                        
                let activeDesc = `[Component Builder Active]\nSelected Components: ${selectedComponents.join(', ')}`;
                if (purpose) {
                    activeDesc += `\nPurpose: ${purpose}`;
                }
                activeDesc += `\n\nAuto-generating client firmware for: \n` + selectedComponents.map(id => `- ${id}`).join('\n');
                hardwareInput.value = activeDesc;
            } else {
                code = hardwareInput.value.trim();
                if (!code) {
                    alert("Please select at least one component from the list, or paste your original robot code first!");
                    return;
                }
            }
            
            processHardwareBtn.textContent = '⏳ Processing...';
            processHardwareBtn.disabled = true;
            hardwareOutput.value = "Analyzing requirements & generating custom minimal C++ code... This may take a few seconds.";
            if (flashHardwareBtn) flashHardwareBtn.disabled = true;
            
            ipcRenderer.send('notepad-process-hardware', code);
        });
    }

    ipcRenderer.on('hardware-result', (event, result) => {
        if (processHardwareBtn) {
            processHardwareBtn.textContent = '⚡ Generate Integration';
            processHardwareBtn.disabled = false;
        }
        
        let cleanCode = result;
        let autoFlashLog = "";
        const logIndex = result.indexOf("--- AUTO FLASHER ---");
        if (logIndex !== -1) {
            cleanCode = result.substring(0, logIndex).trim();
            autoFlashLog = result.substring(logIndex + 20).trim();
        }
        
        if (hardwareOutput) {
            hardwareOutput.value = cleanCode;
            if (flashHardwareBtn && !cleanCode.startsWith("Error")) {
                flashHardwareBtn.disabled = false;
            }
        }
        
        // If there was auto flasher output, show it in the flasher banner
        if (autoFlashLog) {
            const flasherBanner = document.getElementById('flasherStatusBanner');
            const flasherText = document.getElementById('flasherStatusText');
            const flasherIcon = document.getElementById('flasherIcon');
            if (flasherBanner && flasherText) {
                flasherBanner.style.display = 'flex';
                if (autoFlashLog.includes("Error") || autoFlashLog.includes("failed")) {
                    flasherIcon.textContent = '❌';
                    flasherText.textContent = autoFlashLog;
                    flasherBanner.style.background = 'linear-gradient(135deg, #e53e3e, #c53030)';
                } else if (autoFlashLog.includes("success") || autoFlashLog.includes("✅")) {
                    flasherIcon.textContent = '✅';
                    flasherText.textContent = autoFlashLog;
                    flasherBanner.style.background = 'linear-gradient(135deg, var(--accent-green), #38a169)';
                    setTimeout(() => {
                        flasherBanner.style.display = 'none';
                    }, 6000);
                } else {
                    flasherIcon.textContent = '⏳';
                    flasherText.textContent = autoFlashLog;
                    flasherBanner.style.background = 'linear-gradient(135deg, #3182ce, #2b6cb0)';
                }
            }
        }
        
        // Show training success banner
        const banner = document.getElementById('trainingStatusBanner');
        if (banner) {
            banner.style.display = 'flex';
            // Hide the banner after 6 seconds
            setTimeout(() => {
                banner.style.display = 'none';
            }, 6000);
        }

        // Grab the last trained device from memory path and add to session
        try {
            const memoryPath = path.join(__dirname, 'hardware_memory.txt');
            if (fs.existsSync(memoryPath)) {
                const data = fs.readFileSync(memoryPath, 'utf-8');
                const lines = data.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                if (lines.length > 0) {
                    addTrainedDevice(lines[lines.length - 1]);
                }
            }
        } catch (e) {
            console.error("Failed to parse last trained device:", e);
        }

        // Refresh devices
        loadRegisteredDevices();
        if (typeof loadTrainedDevices === 'function') loadTrainedDevices();
    });

    if (flashHardwareBtn) {
        flashHardwareBtn.addEventListener('click', () => {
            let code = hardwareOutput.value.trim();
            const logIndex = code.indexOf("--- AUTO FLASHER ---");
            if (logIndex !== -1) {
                code = code.substring(0, logIndex).trim();
            }
            if (!code || code.startsWith("Error")) {
                alert("No valid generated code to flash!");
                return;
            }
            
            flashHardwareBtn.disabled = true;
            flashHardwareBtn.textContent = '⏳ Flashing...';
            
            const flasherBanner = document.getElementById('flasherStatusBanner');
            const flasherText = document.getElementById('flasherStatusText');
            const flasherIcon = document.getElementById('flasherIcon');
            if (flasherBanner && flasherText) {
                flasherIcon.textContent = '⏳';
                flasherText.textContent = 'Preparing upload...';
                flasherBanner.style.display = 'flex';
                flasherBanner.style.background = 'linear-gradient(135deg, #3182ce, #2b6cb0)';
            }
            
            ipcRenderer.send('notepad-flash-hardware', code);
        });
    }

    ipcRenderer.on('flash-progress', (event, msg) => {
        const flasherText = document.getElementById('flasherStatusText');
        if (flasherText) {
            flasherText.textContent = msg;
        }
        
        // Parse percentage and update the progress bar
        const pctMatch = msg.match(/(\d+)%/);
        const progressContainer = document.getElementById('flasherProgressContainer');
        const progressBar = document.getElementById('flasherProgressBar');
        if (progressContainer && progressBar) {
            if (pctMatch) {
                const pct = pctMatch[1];
                progressContainer.style.display = 'block';
                progressBar.style.width = `${pct}%`;
            } else if (msg.includes("Compiling") || msg.includes("Searching")) {
                progressContainer.style.display = 'none';
                progressBar.style.width = '0%';
            }
        }
    });

    ipcRenderer.on('flash-status', (event, status) => {
        const flashHardwareBtn = document.getElementById('flashHardwareBtn');
        if (flashHardwareBtn) {
            flashHardwareBtn.disabled = false;
            flashHardwareBtn.textContent = '🚀 Flash to ESP32';
        }
        
        const flasherBanner = document.getElementById('flasherStatusBanner');
        const flasherText = document.getElementById('flasherStatusText');
        const flasherIcon = document.getElementById('flasherIcon');
        const progressContainer = document.getElementById('flasherProgressContainer');
        
        if (progressContainer) {
            progressContainer.style.display = 'none';
        }
        
        if (flasherBanner && flasherText) {
            if (status === "SUCCESS") {
                flasherIcon.textContent = '✅';
                flasherText.textContent = 'ESP32 successfully flashed and online!';
                flasherBanner.style.background = 'linear-gradient(135deg, var(--accent-green), #38a169)';
                setTimeout(() => {
                    flasherBanner.style.display = 'none';
                }, 6000);
            } else {
                flasherIcon.textContent = '❌';
                flasherText.textContent = status;
                flasherBanner.style.background = 'linear-gradient(135deg, #e53e3e, #c53030)';
            }
        }
    });

    // Voice triggered tab switcher event receiver
    ipcRenderer.on('notepad-switch-tab', (event, tabId) => {
        const item = document.querySelector(`.nav-item[data-target="${tabId}"]`);
        if (item) {
            item.click();
        }
    });

    // AI IPC Receivers (Compatibility)
    ipcRenderer.on('notepad-insert', (event, text) => {
        const start = noteContent.selectionStart;
        const end = noteContent.selectionEnd;
        const currentText = noteContent.value;
        
        noteContent.value = currentText.substring(0, start) + text + currentText.substring(end);
        noteContent.selectionStart = noteContent.selectionEnd = start + text.length;
        noteContent.dispatchEvent(new Event('input'));
        
        // Auto-switch to notes panel
        document.querySelector('[data-target="panel-notes"]').click();
    });

    ipcRenderer.on('notepad-clear', () => {
        noteContent.value = '';
        noteTitle.value = 'New Note';
        noteContent.dispatchEvent(new Event('input'));
    });

    ipcRenderer.on('notepad-title', (event, title) => {
        noteTitle.value = title;
    });

    ipcRenderer.on('notepad-draw', (event, imageUrl) => {
        const paintArea = document.getElementById('paintArea');
        paintArea.innerHTML = `<img src="${imageUrl}" style="max-width:100%; max-height:100%; object-fit:contain; border-radius:10px;" />`;
        document.querySelector('[data-target="panel-paint"]').click();
    });

    // Settings / API Key Dashboard Logic
    const refreshKeysBtn = document.getElementById('refreshKeysBtn');
    const refreshBtnIcon = document.getElementById('refreshBtnIcon');
    const refreshBtnText = document.getElementById('refreshBtnText');
    const keyGridContainer = document.getElementById('keyGridContainer');
    let isRefreshing = false;

    function triggerKeyRefresh() {
        if (isRefreshing) return;
        isRefreshing = true;
        
        if (refreshBtnIcon) refreshBtnIcon.classList.add('spinning');
        if (refreshKeysBtn) refreshKeysBtn.disabled = true;
        if (refreshBtnText) refreshBtnText.textContent = 'Refreshing...';
        
        ipcRenderer.send('request-token-status');
    }

    if (refreshKeysBtn) {
        refreshKeysBtn.addEventListener('click', triggerKeyRefresh);
    }

    ipcRenderer.on('token-status', (event, keys) => {
        isRefreshing = false;
        if (refreshBtnIcon) refreshBtnIcon.classList.remove('spinning');
        if (refreshKeysBtn) refreshKeysBtn.disabled = false;
        if (refreshBtnText) refreshBtnText.textContent = 'Refresh Status';

        if (!keyGridContainer) return;
        keyGridContainer.innerHTML = '';

        if (!keys || keys.length === 0) {
            keyGridContainer.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-light);">
                    <span style="font-size: 24px;">⚠️</span>
                    <p style="margin: 10px 0 0 0; font-weight: 500;">No API Keys detected in your environment (.env file).</p>
                </div>
            `;
            return;
        }

        keys.forEach(key => {
            const card = document.createElement('div');
            const statusLower = key.status.toLowerCase();
            const isActive = statusLower.includes('active') || statusLower.includes('free tier') || statusLower.includes('configured');
            const isOffline = statusLower.includes('offline') || statusLower.includes('error') || statusLower.includes('invalid') || statusLower.includes('expired');
            
            let statusClass = 'active';
            let cardStatusClass = 'status-active';
            if (isOffline) {
                statusClass = 'error';
                cardStatusClass = 'status-error';
            } else if (statusLower.includes('not configured')) {
                statusClass = 'error';
                cardStatusClass = 'status-warning';
            }

            card.className = `key-card ${cardStatusClass}`;

            let badgeClass = 'or';
            if (key.provider.toLowerCase().includes('gemini')) badgeClass = 'gemini';
            else if (key.provider.toLowerCase().includes('nvidia')) badgeClass = 'nvidia';
            else if (key.provider.toLowerCase().includes('groq')) badgeClass = 'groq';

            const statusIndicator = '●';

            card.innerHTML = `
                <div>
                    <div class="card-header-row">
                        <span class="provider-badge ${badgeClass}">${key.provider}</span>
                        <span class="status-pill ${statusClass}">${statusIndicator} ${key.status}</span>
                    </div>
                    <h3 class="key-name-label">${key.name}</h3>
                    <div class="key-mask-value">${key.key_mask}</div>
                </div>
                <div class="card-stats">
                    <div class="stat-item">
                        <span class="stat-label">Usage / Cost</span>
                        <span class="stat-val">${key.usage}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Limit</span>
                        <span class="stat-val">${key.limit}</span>
                    </div>
                </div>
            `;
            keyGridContainer.appendChild(card);
        });
    });
     // Registered ESP32 Devices Loader
    const { exec } = require('child_process');

    // Save device to session cache when trained
    function addTrainedDevice(deviceLine) {
        let list = [];
        try {
            list = JSON.parse(localStorage.getItem('bupi_session_trained_devices') || '[]');
        } catch(e) {}
        
        // Avoid duplicate lines
        if (!list.includes(deviceLine)) {
            list.push(deviceLine);
            localStorage.setItem('bupi_session_trained_devices', JSON.stringify(list));
        }
    }

    function loadRegisteredDevices() {
        const memoryPath = path.join(__dirname, 'hardware_memory.txt');
        const grid = document.getElementById('espDeviceGrid');
        if (!grid) return;
        
        grid.innerHTML = '';
        
        if (!fs.existsSync(memoryPath)) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-light);">
                    <span style="font-size: 24px;">🔌</span>
                    <p style="margin: 10px 0 0 0; font-weight: 500;">No devices registered yet. Upload code in the Hardware Ingestion tab first!</p>
                </div>
            `;
            return;
        }
        
        try {
            const data = fs.readFileSync(memoryPath, 'utf-8');
            const lines = data.split('\n').map(l => l.trim()).filter(l => l.length > 0);
            
            if (lines.length === 0) {
                grid.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-light);">
                        <span style="font-size: 24px;">🔌</span>
                        <p style="margin: 10px 0 0 0; font-weight: 500;">No devices registered yet. Upload code in the Hardware Ingestion tab first!</p>
                    </div>
                `;
                return;
            }
            
            renderDevicesToList(lines, grid, "registered");
        } catch (e) {
            console.error("Failed to read memory file:", e);
        }
    }

    function loadTrainedDevices() {
        const grid = document.getElementById('trainedDeviceGrid');
        if (!grid) return;
        
        grid.innerHTML = '';
        
        let list = [];
        try {
            list = JSON.parse(localStorage.getItem('bupi_session_trained_devices') || '[]');
        } catch(e) {}
        
        if (list.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-light);">
                    <span style="font-size: 24px;">🧪</span>
                    <p style="margin: 10px 0 0 0; font-weight: 500;">No devices trained in this active workspace yet.</p>
                    <p style="margin: 5px 0 0 0; font-size:12px; color:var(--text-light);">Go to the "Hardware Setup" tab, paste your Arduino code, and click "Generate Integration" to train Bupi on your sensor!</p>
                </div>
            `;
            return;
        }
        
        renderDevicesToList(list, grid, "trained");
    }

    function renderDevicesToList(lines, grid, prefix) {
        lines.forEach((line, index) => {
            let name = "Unknown Device";
            let type = "Actuator";
            let topic = "";
            let actionType = "send";
            let taskDescription = "";
            
            const matchName = line.match(/^-\s*([^:]+):/);
            if (matchName) {
                name = matchName[1].trim();
            }
            
            const colonIndex = line.indexOf(':');
            if (colonIndex !== -1) {
                taskDescription = line.substring(colonIndex + 1).trim();
            }
            
            const nameLower = name.toLowerCase();
            if (nameLower.includes('display') || nameLower.includes('lcd') || nameLower.includes('led') || nameLower.includes('screen')) {
                type = "Display";
            } else if (nameLower.includes('sensor') || nameLower.includes('temp') || nameLower.includes('potentiometer') || nameLower.includes('dht') || nameLower.includes('reading') || nameLower.includes('gas') || nameLower.includes('mq') || nameLower.includes('mpu') || nameLower.includes('smoke') || nameLower.includes('humidity')) {
                type = "Sensor";
            }
            
            const matchSend = line.match(/\[MQTT_SEND:([^:]+):?([^\]]*)\]/);
            const matchSub = line.match(/\[MQTT_(?:SUB|RECEIVE):([^\]]+)\]/);
            
            if (matchSend) {
                topic = matchSend[1];
                actionType = "send";
            } else if (matchSub) {
                topic = matchSub[1];
                actionType = "sub";
            } else {
                const genericMatch = line.match(/bupi\/(?:sensors|actuators|hardware)\/[^\s\]]+/);
                if (genericMatch) {
                    topic = genericMatch[0];
                }
            }
            
            const card = document.createElement('div');
            card.className = 'esp-card';
            card.style.background = 'rgba(255, 255, 255, 0.45)';
            card.style.border = 'var(--glass-border)';
            card.style.borderRadius = '16px';
            card.style.padding = '20px';
            card.style.display = 'flex';
            card.style.flexDirection = 'column';
            card.style.gap = '12px';
            card.style.position = 'relative';
            card.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
            
            let icon = "⚙️";
            let badgeColor = "#e28743";
            if (type === "Display") {
                icon = "📺";
                badgeColor = "var(--primary)";
            } else if (type === "Sensor") {
                icon = "🌡️";
                badgeColor = "var(--accent-green)";
            }
            
            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <span class="provider-badge" style="background:${badgeColor}; font-size:10px; padding:3px 6px; border-radius:4px; font-weight:700;">${type}</span>
                        <h3 style="margin: 8px 0 4px 0; font-size: 16px; font-weight:700; color:var(--text-dark);">${name}</h3>
                    </div>
                    <div style="font-size:24px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.1));">${icon}</div>
                </div>
                
                <div style="font-size:12px; line-height:1.4; color:var(--text-dark); background:rgba(255,255,255,0.4); border:1px solid rgba(0,0,0,0.03); padding:10px; border-radius:8px; margin: 4px 0;">
                    <strong style="font-size:10px; text-transform:uppercase; color:var(--text-light); letter-spacing:0.5px; display:block; margin-bottom:4px;">Task / Action</strong>
                    ${taskDescription || 'No task description available.'}
                </div>

                <div style="font-size:11px; color:var(--text-light); background:rgba(0,0,0,0.03); padding:8px; border-radius:6px; word-break:break-all;">
                    <strong>Topic:</strong> <code style="font-family:monospace; font-weight:600; color:var(--primary);">${topic || 'N/A'}</code>
                </div>
                
                <div style="margin-top:auto; padding-top:8px;">
                    ${actionType === 'send' ? `
                        <div style="display:flex; gap:8px;">
                            <input type="text" id="testMsg-${prefix}-${index}" placeholder="Test payload..." style="flex:1; padding:6px 10px; border-radius:8px; border:1px solid var(--border-color); font-size:12px; outline:none; background:rgba(255,255,255,0.8);" />
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:11px;" id="sendBtn-${prefix}-${index}">Send</button>
                        </div>
                    ` : `
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span id="sensorVal-${prefix}-${index}" style="font-weight:700; font-size:14px; color:var(--text-dark);">No reading yet</span>
                            <button class="btn" style="padding:6px 12px; font-size:11px; border:1px solid var(--border-color); background:rgba(255,255,255,0.6);" id="readBtn-${prefix}-${index}">Read</button>
                        </div>
                    `}
                </div>
            `;
            grid.appendChild(card);

            if (actionType === 'send') {
                const sendBtn = card.querySelector(`#sendBtn-${prefix}-${index}`);
                const inputEl = card.querySelector(`#testMsg-${prefix}-${index}`);
                if (sendBtn && inputEl) {
                    sendBtn.addEventListener('click', () => {
                        const payload = inputEl.value.trim();
                        if (!payload) {
                            alert("Please enter a test payload.");
                            return;
                        }
                        sendBtn.textContent = "Sending...";
                        sendBtn.disabled = true;
                        
                        const pyPath = path.join(__dirname, 'venv312', 'Scripts', 'python.exe');
                        const cmd = `"${pyPath}" -c "
import paho.mqtt.publish as p
p.single('${topic}', '${payload}', hostname='localhost')
"`;
                        
                        exec(cmd, (error, stdout, stderr) => {
                            sendBtn.textContent = "Send";
                            sendBtn.disabled = false;
                            if (error) {
                                console.error(`Error sending command: ${error}`);
                                alert(`Failed to send command: ${error.message}`);
                            } else {
                                alert(`Sent payload '${payload}' to topic '${topic}' successfully!`);
                            }
                        });
                    });
                }
            } else {
                const readBtn = card.querySelector(`#readBtn-${prefix}-${index}`);
                const statusLabel = card.querySelector(`#sensorVal-${prefix}-${index}`);
                if (readBtn && statusLabel) {
                    readBtn.addEventListener('click', () => {
                        statusLabel.textContent = "Reading...";
                        readBtn.disabled = true;
                        
                        const pyPath = path.join(__dirname, 'venv312', 'Scripts', 'python.exe');
                        const cmd = `"${pyPath}" -c "
import paho.mqtt.client as mqtt
import time
val = None
def on_msg(c, u, m):
    global val
    val = m.payload.decode()
    c.disconnect()
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_msg
client.connect('localhost', 1883)
client.subscribe('${topic}')
client.loop_start()
t = time.time()
while val is None and time.time() - t < 2.0:
    time.sleep(0.05)
client.loop_stop()
print(val or 'Timeout')
"`;
                        
                        exec(cmd, (error, stdout, stderr) => {
                            readBtn.disabled = false;
                            if (error) {
                                console.error(`Error reading sensor: ${error}`);
                                statusLabel.textContent = "Error";
                            } else {
                                const val = stdout.trim();
                                statusLabel.textContent = val === "Timeout" ? "Timeout (No Data)" : val;
                            }
                        });
                    });
                }
            }
        });
    }

    const clearTrainedBtn = document.getElementById('clearTrainedBtn');
    if (clearTrainedBtn) {
        clearTrainedBtn.addEventListener('click', () => {
            localStorage.removeItem('bupi_session_trained_devices');
            loadTrainedDevices();
            alert("Cleared active lab session cache!");
        });
    }

    ipcRenderer.on('trained-device', (event, deviceLine) => {
        addTrainedDevice(deviceLine);
        loadTrainedDevices();
    });

    ipcRenderer.on('connected-nodes', (event, nodes) => {
        renderLiveNodes(nodes);
    });

    function renderLiveNodes(nodes) {
        const grid = document.getElementById('liveNodesGrid');
        if (!grid) return;
        
        grid.innerHTML = '';
        
        if (!nodes || nodes.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 30px; color: var(--text-light); background: rgba(255,255,255,0.4); border-radius: 12px; border: var(--glass-border);">
                    <span style="font-size: 18px;">📡</span>
                    <p style="margin: 5px 0 0 0; font-size:12px;">No active ESP32 nodes connected to Bupi Hub.</p>
                </div>
            `;
            return;
        }
        
        nodes.forEach(node => {
            const card = document.createElement('div');
            card.className = 'esp-card';
            card.style.background = 'rgba(255, 255, 255, 0.45)';
            card.style.border = 'var(--glass-border)';
            card.style.borderRadius = '16px';
            card.style.padding = '18px';
            card.style.display = 'flex';
            card.style.flexDirection = 'column';
            card.style.gap = '10px';
            card.style.position = 'relative';
            card.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
            
            const isOnline = node.status === 'online';
            const statusColor = isOnline ? 'var(--accent-green)' : '#718096';
            const pulseClass = isOnline ? 'pulse-active' : '';
            
            // Connection type pill color
            const typeColor = node.type === 'WebSocket' ? '#cce5ff' : '#e8daff';
            const typeTextColor = node.type === 'WebSocket' ? '#004085' : '#4b0082';
            
            const capabilitiesHtml = node.capabilities.map(cap => 
                `<span style="font-size: 9px; font-weight:700; background:rgba(0,0,0,0.05); padding:2px 6px; border-radius:4px; color:var(--text-light); text-transform:uppercase;">${cap}</span>`
            ).join(' ');
            
            const tasksHtml = node.tasks.map(task => 
                `<li style="margin-bottom:3px;">${task}</li>`
            ).join('');
            
            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <div style="display:flex; align-items:center; gap:6px;">
                            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${statusColor};" class="${pulseClass}"></span>
                            <span class="provider-badge" style="background:${typeColor}; color:${typeTextColor}; font-size:9px; padding:2px 5px; border-radius:4px; font-weight:700;">${node.type}</span>
                        </div>
                        <h3 style="margin: 8px 0 2px 0; font-size: 15px; font-weight:700; color:var(--text-dark);">${node.device}</h3>
                    </div>
                    <div style="font-size:22px;">📶</div>
                </div>
                
                <div style="font-size:11px; color:var(--text-light); background:rgba(0,0,0,0.02); padding:6px; border-radius:6px;">
                    <div style="margin-bottom:2px;"><strong>IP Address:</strong> <code style="font-family:monospace; color:var(--primary); font-weight:600;">${node.ip}</code></div>
                    <div><strong>Client ID:</strong> <code style="font-family:monospace; color:var(--text-dark);">${node.id}</code></div>
                </div>
                
                <div style="font-size:12px; line-height:1.4; color:var(--text-dark); background:rgba(255,255,255,0.4); border:1px solid rgba(0,0,0,0.02); padding:8px 10px; border-radius:8px;">
                    <strong style="font-size:10px; text-transform:uppercase; color:var(--text-light); letter-spacing:0.5px; display:block; margin-bottom:4px;">Active Tasks</strong>
                    <ul style="margin: 0; padding-left: 15px; color:var(--text-dark);">
                        ${tasksHtml || '<li>No active tasks documented</li>'}
                    </ul>
                </div>
                
                <div style="display:flex; align-items:center; gap:4px; margin-top:auto; padding-top:4px;">
                    ${capabilitiesHtml}
                </div>
            `;
            grid.appendChild(card);
        });
    }

    // Call it initially in case we load on that tab
    loadRegisteredDevices();
    loadTrainedDevices();
    ipcRenderer.send('request-connected-nodes');
});
})();
