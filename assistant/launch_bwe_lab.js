const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const fs = require('fs');

let notepadWindow = null;
let pyEngine = null;
let footmoBackend = null;
let footmoFrontend = null;

// Increase GPU tile memory limit to prevent "tile memory limits exceeded" errors
app.commandLine.appendSwitch('force-gpu-mem-available-mb', '4096');
app.commandLine.appendSwitch('ignore-gpu-blocklist');
app.commandLine.appendSwitch('disable-gpu-disk-cache');

function spawnFootMo2() {
  const backendPath = path.join(__dirname, 'footmo2-v2', 'backend', 'server.js');
  const frontendCwd = path.join(__dirname, 'footmo2-v2', 'frontend');
  const viteJs = path.join(frontendCwd, 'node_modules', 'vite', 'bin', 'vite.js');

  console.log("[BWE Lab] Spawning FootMo2 v2 Backend...");
  footmoBackend = spawn('node', [backendPath], {
    cwd: path.dirname(backendPath),
    stdio: 'pipe'
  });

  console.log("[BWE Lab] Spawning FootMo2 v2 Frontend (Vite)...");
  footmoFrontend = spawn('node', [viteJs], {
    cwd: frontendCwd,
    stdio: 'pipe'
  });
}

function spawnEngine() {
  const venvPython = path.join(__dirname, 'venv312', 'Scripts', 'python.exe');
  const pyCmd = fs.existsSync(venvPython) ? venvPython : 'python';
  console.log("[BWE Lab] Spawning Python engine using command:", pyCmd);
  
  pyEngine = spawn(pyCmd, ['main.py', '--lab-mode'], {
    cwd: __dirname,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: true
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
        if (msg.type === "hardware_result") {
          if (notepadWindow) notepadWindow.webContents.send('hardware-result', msg.value);
        } else if (msg.type === "token_status") {
          global.cachedTokenStatus = msg.value;
          if (notepadWindow) notepadWindow.webContents.send('token-status', msg.value);
        } else if (msg.type === "trained_device") {
          if (notepadWindow) notepadWindow.webContents.send('trained-device', msg.value);
        } else if (msg.type === "connected_nodes") {
          if (notepadWindow) notepadWindow.webContents.send('connected-nodes', msg.value);
        } else if (msg.type === "flash_progress") {
          if (notepadWindow) notepadWindow.webContents.send('flash-progress', msg.value);
        } else if (msg.type === "flash_status") {
          if (notepadWindow) notepadWindow.webContents.send('flash-status', msg.value);
        } else if (msg.type === "online_search_results") {
          if (notepadWindow) notepadWindow.webContents.send('online-search-results', msg);
        } else if (msg.type === "bwe_pin_write") {
          if (notepadWindow) notepadWindow.webContents.send('bwe-pin-write', { pin: msg.pin, val: msg.val });
        } else if (msg.type === "bwe_esp32_stats") {
          if (notepadWindow) notepadWindow.webContents.send('bwe-esp32-stats', msg.value);
        }
      } catch (e) {
        // console.log("From Python:", line);
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

function createLabWindow() {
  console.log("[BWE Lab] Creating Main Dashboard Window");
  notepadWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    frame: false, // Frameless design to match the visual custom top bar of notepad.html
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false
    }
  });

  const filePath = path.join(__dirname, 'notepad.html');
  notepadWindow.loadFile(filePath);

  notepadWindow.webContents.on('did-finish-load', () => {
    // Send initial refresh statuses
    sendCommand('refresh_keys');
    sendCommand('refresh_nodes');
  });

  notepadWindow.on('closed', () => {
    notepadWindow = null;
    app.quit();
  });
}

function cleanupBackgroundBupi() {
  if (process.platform === 'win32') {
    console.log("[BWE Lab] Cleaning up background Bupi companion processes...");
    try {
      // 1. Kill any python.exe running main.py
      execSync('powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name = \'python.exe\' AND CommandLine LIKE \'%main.py%\'\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"', { stdio: 'ignore' });
    } catch(e) {}
    try {
      // 2. Kill any python.exe running run_mode2.py
      execSync('powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name = \'python.exe\' AND CommandLine LIKE \'%run_mode2.py%\'\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"', { stdio: 'ignore' });
    } catch(e) {}
    try {
      // 3. Kill any electron.exe running main.js (mascot app)
      execSync('powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name = \'electron.exe\' AND CommandLine LIKE \'%main.js%\'\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"', { stdio: 'ignore' });
    } catch(e) {}
  }
}

app.name = 'BWELab';

app.whenReady().then(() => {
  cleanupBackgroundBupi();
  createLabWindow();
  spawnEngine();
  spawnFootMo2();

  // Setup same window manipulation IPC events
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
    console.log("Lab Dashboard saved:", data.title);
  });

  ipcMain.on('notepad-process-hardware', (event, code) => {
    sendCommand('process_hardware', { code: code });
  });

  ipcMain.on('notepad-flash-hardware', (event, code) => {
    sendCommand('flash_hardware', { code: code });
  });

  ipcMain.on('search-components-online', (event, query) => {
    sendCommand('search_components', { query: query });
  });

  ipcMain.on('request-token-status', () => {
    if (global.cachedTokenStatus && notepadWindow) {
      notepadWindow.webContents.send('token-status', global.cachedTokenStatus);
    }
    sendCommand('refresh_keys');
  });

  ipcMain.on('request-connected-nodes', () => {
    sendCommand('refresh_nodes');
  });

  ipcMain.on('bwe-pin-update', (event, data) => {
    sendCommand('bwe_pin_update', { pin: data.pin, val: data.val });
  });

  // Zero-latency Gemini Key retrieval
  ipcMain.handle('secure-get-gemini-key', async () => {
    let key = process.env.GEMINI_API_KEY || '';
    if (!key) {
      try {
        const envPath = path.join(__dirname, '.env');
        if (fs.existsSync(envPath)) {
          const data = fs.readFileSync(envPath, 'utf8');
          const match = data.match(/GEMINI_API_KEY\s*=\s*(["']?)(.*?)\1(?:\s|$)/);
          if (match) key = match[2];
        }
      } catch (e) {}
    }
    return key.trim();
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('will-quit', () => {
  if (pyEngine) pyEngine.kill();
  if (footmoBackend) footmoBackend.kill();
  if (footmoFrontend) footmoFrontend.kill();
});
