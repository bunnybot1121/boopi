const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

const originalConsoleLog = console.log;
const originalConsoleError = console.error;

console.log = (...args) => {
  originalConsoleLog(...args);
  try { fs.appendFileSync('debug_log.txt', args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ') + '\n'); } catch(e){}
};
console.error = (...args) => {
  originalConsoleError(...args);
  try { fs.appendFileSync('debug_log.txt', '[ERROR] ' + args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ') + '\n'); } catch(e){}
};
// Increase GPU tile memory limit to prevent "tile memory limits exceeded" errors
app.commandLine.appendSwitch('force-gpu-mem-available-mb', '4096');
app.commandLine.appendSwitch('ignore-gpu-blocklist');
app.commandLine.appendSwitch('disable-gpu-disk-cache');

let mainWindow;
let tray;
let pyEngine;
let currentState = "idle";
let footmoBackend = null;
let footmoFrontend = null;

function spawnFootMo2() {
  const backendPath = path.join(__dirname, 'footmo2-v2', 'backend', 'server.js');
  const frontendCwd = path.join(__dirname, 'footmo2-v2', 'frontend');
  const viteJs = path.join(frontendCwd, 'node_modules', 'vite', 'bin', 'vite.js');

  console.log("[Main] Spawning FootMo2 v2 Backend...");
  footmoBackend = spawn('node', [backendPath], {
    cwd: path.dirname(backendPath),
    stdio: 'pipe'
  });

  footmoBackend.stdout.on('data', (d) => console.log(`[FootMo2 Backend] ${d.toString().trim()}`));
  footmoBackend.stderr.on('data', (d) => console.error(`[FootMo2 Backend ERROR] ${d.toString().trim()}`));

  console.log("[Main] Spawning FootMo2 v2 Frontend (Vite)...");
  footmoFrontend = spawn('node', [viteJs], {
    cwd: frontendCwd,
    stdio: 'pipe'
  });

  footmoFrontend.stdout.on('data', (d) => console.log(`[FootMo2 Frontend] ${d.toString().trim()}`));
  footmoFrontend.stderr.on('data', (d) => console.error(`[FootMo2 Frontend ERROR] ${d.toString().trim()}`));
}
let notepadWindow = null;
let isDev = process.argv.includes('--dev');
let notepadQueue = [];
let notepadReady = false;
let notepadPendingTitle = null;
let notepadPendingClear = false;

function createNotepadWindow() {
  console.log("[Main] createNotepadWindow called");
  if (notepadWindow) {
    console.log("[Main] notepadWindow already exists, focusing");
    if (notepadWindow.isMinimized()) notepadWindow.restore();
    notepadWindow.focus();
    return;
  }

  console.log("[Main] Creating new notepadWindow");
  notepadReady = false;
  notepadWindow = new BrowserWindow({
    width: 900,
    height: 600,
    minWidth: 600,
    minHeight: 400,
    frame: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  const filePath = path.join(__dirname, 'notepad.html');
  console.log("[Main] Loading notepad file:", filePath);
  notepadWindow.loadFile(filePath);

  notepadWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
    console.log(`[Renderer Notepad] ${message} (at ${sourceId}:${line})`);
  });

  notepadWindow.webContents.on('did-finish-load', () => {
    notepadReady = true;
    
    if (notepadPendingClear) {
      notepadWindow.webContents.send('notepad-clear');
      notepadPendingClear = false;
    }

    // Set pending title if any
    if (notepadPendingTitle) {
      notepadWindow.webContents.send('notepad-title', notepadPendingTitle);
      notepadPendingTitle = null;
    }

    // Flush any pending chunks that arrived before the window loaded
    while (notepadQueue.length > 0) {
      let chunk = notepadQueue.shift();
      notepadWindow.webContents.send('notepad-insert', chunk);
    }
    
    // Request initial keys and nodes status
    sendCommand('refresh_keys');
    sendCommand('refresh_nodes');
  });

  notepadWindow.on('closed', () => {
    notepadWindow = null;
    notepadReady = false;
  });
}

function createWindow() {
  console.log("[Main] createWindow called");
  mainWindow = new BrowserWindow({
    width: 250,
    height: 250,
    minWidth: 100,
    minHeight: 100,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: true,
    hasShadow: false,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false
    }
  });

  // Calculate position (bottom right)
  const { screen } = require('electron');
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  mainWindow.setPosition(width - 270, height - 270);
  
  mainWindow.webContents.on('console-message', (event, ...args) => {
    let message = '';
    let line = 0;
    let sourceId = '';
    if (args.length === 1 && typeof args[0] === 'object') {
      const details = args[0];
      message = details.message;
      line = details.line;
      sourceId = details.sourceId;
    } else {
      message = args[1];
      line = args[2];
      sourceId = args[3];
    }
    console.log(`[Renderer Main] ${message} (at ${sourceId}:${line})`);
  });

  const filePath = path.join(__dirname, 'index.html');
  console.log("[Main] Loading index file:", filePath);
  mainWindow.loadFile(filePath);
}

function spawnEngine() {
  const venvPython = path.join(__dirname, 'venv312', 'Scripts', 'python.exe');
  const pyCmd = fs.existsSync(venvPython) ? venvPython : 'python';
  console.log("[Main] Spawning Python engine using command:", pyCmd);
  
  // Spawn Python engine
  pyEngine = spawn(pyCmd, ['main.py'], {
    cwd: __dirname,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: true
  });

  pyEngine.on('error', (err) => {
    try { fs.appendFileSync('debug_log.txt', "Failed to start python process: " + err + "\n"); } catch(e) {}
  });

  pyEngine.stderr.on('data', (data) => {
    try { fs.appendFileSync('debug_log.txt', "Python STDERR: " + data.toString() + "\n"); } catch(e) {}
  });

  pyEngine.stdout.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach(line => {
      if (!line.trim()) return;
      try {
        const msg = JSON.parse(line);
        if (msg.type === "state") {
          currentState = msg.value;
          if (mainWindow) {
            mainWindow.webContents.send('state-changed', msg.value);
          }
        } else if (msg.type === "speech_text") {
          if (mainWindow) {
            mainWindow.webContents.send('speech-text', msg.value);
          }
        } else if (msg.type === "mode_changed") {
          if (mainWindow) {
            mainWindow.webContents.send('mode-changed', msg.value);
          }
        } else if (msg.type === "draw") {
          if (notepadWindow) {
            notepadWindow.webContents.send('notepad-draw', msg.value);
            if (!notepadWindow.isVisible()) {
              notepadWindow.show();
            }
          }
        } else if (msg.type === "command") {
          if (msg.value === "start_running") {
            startRunningAnimation();
          } else if (msg.value === "stop_running") {
            stopRunningAnimation();
          } else if (msg.value === "open_notepad") {
            createNotepadWindow();
          }
        } else if (msg.type === "notepad_insert") {
          if (!notepadWindow) createNotepadWindow();
          
          if (!notepadReady) {
            notepadQueue.push(msg.value);
          } else {
            notepadWindow.webContents.send('notepad-insert', msg.value);
          }
        } else if (msg.type === "notepad_clear") {
          if (!notepadWindow) createNotepadWindow();
          
          if (!notepadReady) {
            // If window isn't ready yet, clear the pending queue so we start fresh
            notepadQueue = [];
            notepadPendingClear = true;
          } else {
            notepadWindow.webContents.send('notepad-clear');
          }
        } else if (msg.type === "notepad_title") {
          if (!notepadWindow) createNotepadWindow();
          if (!notepadReady) {
            notepadPendingTitle = msg.value;
          } else {
            notepadWindow.webContents.send('notepad-title', msg.value);
          }
        } else if (msg.type === "hardware_result") {
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('hardware-result', msg.value);
          }
        } else if (msg.type === "token_status") {
          // console.log("[Main] Received token_status update:", msg.value);
          global.cachedTokenStatus = msg.value;
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('token-status', msg.value);
          }
        } else if (msg.type === "trained_device") {
          // console.log("[Main] Received trained_device update:", msg.value);
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('trained-device', msg.value);
          }
        } else if (msg.type === "connected_nodes") {
          // console.log("[Main] Received connected_nodes update:", msg.value);
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('connected-nodes', msg.value);
          }
        } else if (msg.type === "flash_progress") {
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('flash-progress', msg.value);
          }
        } else if (msg.type === "flash_status") {
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('flash-status', msg.value);
          }
        } else if (msg.type === "online_search_results") {
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('online-search-results', msg);
          }
        } else if (msg.type === "log") {
          console.log("[Python Log]", msg.message);
        }
      } catch (e) {
        console.log("From Python:", line);
      }
    });
  });

  pyEngine.on('close', (code) => {
    console.log(`Python engine exited with code ${code}`);
    app.quit();
  });
}

function sendCommand(cmd, extraArgs = {}) {
  if (pyEngine && !pyEngine.killed) {
    pyEngine.stdin.write(JSON.stringify({ command: cmd, ...extraArgs }) + "\n");
  }
}

app.name = 'BupiMain';
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', (event, commandLine, workingDirectory) => {
    // Someone tried to run a second instance, we should focus our window.
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    createWindow();
    spawnEngine();
    spawnFootMo2();

    // Setup System Tray
    const { nativeImage } = require('electron');
    const iconPath = path.join(__dirname, 'assets', 'icon.png');
    tray = new Tray(nativeImage.createFromPath(iconPath));
    tray.setToolTip('Bupi - Desktop Companion');

    const contextMenu = Menu.buildFromTemplate([
      { label: 'Open Notepad', click: () => createNotepadWindow() },
      { label: 'Toggle DevTools', click: () => {
          if (mainWindow) {
            if (mainWindow.webContents.isDevToolsOpened()) {
              mainWindow.webContents.closeDevTools();
            } else {
              mainWindow.webContents.openDevTools({ mode: 'detach' });
            }
          }
        }
      },
      { label: 'Toggle Conversation Mode', click: () => sendCommand('toggle_conversation') },
      { label: 'Clear Memory', click: () => sendCommand('clear_memory') },
      { label: 'Toggle Overlay', click: () => {
          if (mainWindow.isVisible()) mainWindow.hide();
          else mainWindow.show();
        }
      },
      { type: 'separator' },
      { label: 'Quit Bupi', click: () => {
          sendCommand('quit');
          setTimeout(() => app.quit(), 1000);
        }
      }
    ]);
    
    tray.setContextMenu(contextMenu);

    // Global shortcuts
    globalShortcut.register('CommandOrControl+I', () => sendCommand('quit'));

    // Handle smooth wheel resizing for frameless windows
    ipcMain.on('resize-window', (event, step) => {
      if (!mainWindow) return;
      const bounds = mainWindow.getBounds();
      let newWidth = bounds.width + step;
      let newHeight = bounds.height + step;
      if (newWidth < 100) newWidth = 100;
      if (newHeight < 100) newHeight = 100;
      
      mainWindow.setBounds({
        x: Math.round(bounds.x - (step / 2)),
        y: Math.round(bounds.y - (step / 2)),
        width: Math.round(newWidth),
        height: Math.round(newHeight)
      });
    });

    // Notepad IPC handlers
    ipcMain.on('notepad-minimize', () => {
      if (notepadWindow) notepadWindow.minimize();
    });
    
    ipcMain.on('notepad-maximize', () => {
      if (notepadWindow) {
        if (notepadWindow.isMaximized()) {
          notepadWindow.unmaximize();
        } else {
          notepadWindow.maximize();
        }
      }
    });

    ipcMain.on('notepad-close', () => {
      if (notepadWindow) notepadWindow.close();
    });

    ipcMain.on('notepad-save', (event, data) => {
      console.log("Notepad saved:", data.title);
    });

    ipcMain.on('notepad-process-hardware', (event, code) => {
      console.log("Notepad: Hardware Ingestion Requested");
      sendCommand('process_hardware', { code: code });
    });

    ipcMain.on('notepad-flash-hardware', (event, code) => {
      console.log("Notepad: Flash Hardware Requested");
      sendCommand('flash_hardware', { code: code });
    });

    ipcMain.on('search-components-online', (event, query) => {
      sendCommand('search_components', { query: query });
    });

    // Zero-latency Gemini Live Voice secure key retrieval
    ipcMain.handle('secure-get-gemini-key', async () => {
      let key = process.env.GEMINI_API_KEY || '';
      if (!key) {
        try {
          const fs = require('fs');
          const path = require('path');
          const envPath = path.join(__dirname, '.env');
          if (fs.existsSync(envPath)) {
            const data = fs.readFileSync(envPath, 'utf8');
            const match = data.match(/GEMINI_API_KEY\s*=\s*(["']?)(.*?)\1(?:\s|$)/);
            if (match) {
              key = match[2];
            }
          }
        } catch (e) {
          console.error("[Main] Error reading GEMINI_API_KEY from .env:", e);
        }
      }
      return key.trim();
    });

    // Voice triggers for automated tab switching and editor insertions
    ipcMain.on('voice-trigger-tab', (event, tabId) => {
      console.log("[Main] Voice triggered tab switch:", tabId);
      if (notepadWindow && notepadReady) {
        notepadWindow.webContents.send('notepad-switch-tab', tabId);
        // Force slide open notepad if minimized or hidden
        if (!notepadWindow.isVisible()) {
          notepadWindow.show();
        }
      } else {
        // Create notepad window and switch tab once ready
        createNotepadWindow();
        setTimeout(() => {
          if (notepadWindow && notepadReady) {
            notepadWindow.webContents.send('notepad-switch-tab', tabId);
          }
        }, 1200);
      }
    });

    ipcMain.on('voice-trigger-insert', (event, content) => {
      console.log("[Main] Voice triggered note insert:", content);
      if (notepadWindow && notepadReady) {
        notepadWindow.webContents.send('notepad-insert', content);
      }
    });



    ipcMain.on('request-token-status', (event) => {
      // console.log("[Main] Token status requested");
      if (global.cachedTokenStatus && notepadWindow && notepadReady) {
        notepadWindow.webContents.send('token-status', global.cachedTokenStatus);
      }
      sendCommand('refresh_keys');
    });

    ipcMain.on('request-connected-nodes', (event) => {
      // console.log("[Main] Connected nodes status requested");
      sendCommand('refresh_nodes');
    });

    let isDraggingWindow = false;
    let dragStartBounds = null;

    ipcMain.on('window-drag-start', () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        isDraggingWindow = true;
        dragStartBounds = mainWindow.getBounds();
      }
    });

    ipcMain.on('window-drag', (event, { deltaX, deltaY }) => {
      if (mainWindow && !mainWindow.isDestroyed() && isDraggingWindow && dragStartBounds) {
        const bounds = mainWindow.getBounds();
        mainWindow.setBounds({
          x: bounds.x + deltaX,
          y: bounds.y + deltaY,
          width: dragStartBounds.width,
          height: dragStartBounds.height
        });
      }
    });

    ipcMain.on('window-drag-end', () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        isDraggingWindow = false;
        dragStartBounds = null;
      }
    });

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  app.on('will-quit', () => {
    stopRunningAnimation();
    globalShortcut.unregisterAll();
    if (pyEngine) {
      pyEngine.kill();
    }
    if (footmoBackend) {
      console.log("[Main] Killing FootMo2 v2 Backend...");
      footmoBackend.kill();
    }
    if (footmoFrontend) {
      console.log("[Main] Killing FootMo2 v2 Frontend...");
      footmoFrontend.kill();
    }
  });
}

// -------------------------------------------------------------
// Pacing Animation Logic
// -------------------------------------------------------------
let runInterval = null;
let runDirX = -1;
let currentRunX = 0;
let currentRunY = 0;
let originBounds = null;

function startRunningAnimation() {
  if (runInterval) return;
  if (!mainWindow) return;
  
  const { screen } = require('electron');
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  const bounds = mainWindow.getBounds();
  
  // Save original bounds to restore later
  originBounds = { ...bounds };
  
  // Snap to bottom
  currentRunY = height - bounds.height;
  currentRunX = bounds.x;
  runDirX = -1; // Face/Move left
  
  runInterval = setInterval(() => {
    currentRunX += 4 * runDirX;
    
    if (currentRunX <= 0) {
      currentRunX = 0;
      runDirX = 1;
    } else if (currentRunX + bounds.width >= width) {
      currentRunX = width - bounds.width;
      runDirX = -1;
    }
    
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.setPosition(Math.round(currentRunX), Math.round(currentRunY));
    }
  }, 16);
}

function stopRunningAnimation() {
  if (runInterval) {
    clearInterval(runInterval);
    runInterval = null;
  }
  if (mainWindow && !mainWindow.isDestroyed() && originBounds) {
    // Restore original position
    mainWindow.setBounds(originBounds);
  }
}
