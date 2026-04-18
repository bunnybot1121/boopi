const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let tray;
let pyEngine;
let currentState = "idle";

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 250,
    height: 250,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    hasShadow: false,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  // Calculate position (bottom right)
  const { screen } = require('electron');
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  mainWindow.setPosition(width - 270, height - 270);
  
  mainWindow.loadFile('index.html');
}

function spawnEngine() {
  // Spawn Python engine
  pyEngine = spawn('python', ['main.py'], {
    cwd: __dirname,
    stdio: ['pipe', 'pipe', 'inherit']
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

function sendCommand(cmd) {
  if (pyEngine && !pyEngine.killed) {
    pyEngine.stdin.write(JSON.stringify({ command: cmd }) + "\n");
  }
}

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

    // Setup System Tray
    const { nativeImage } = require('electron');
    const iconPath = path.join(__dirname, 'assets', 'icon.png');
    tray = new Tray(nativeImage.createFromPath(iconPath));
    tray.setToolTip('Boopy - Desktop Companion');

    const contextMenu = Menu.buildFromTemplate([
      { label: 'Toggle Conversation Mode', click: () => sendCommand('toggle_conversation') },
      { label: 'Clear Memory', click: () => sendCommand('clear_memory') },
      { label: 'Toggle Overlay', click: () => {
          if (mainWindow.isVisible()) mainWindow.hide();
          else mainWindow.show();
        }
      },
      { type: 'separator' },
      { label: 'Quit Boopy', click: () => {
          sendCommand('quit');
          setTimeout(() => app.quit(), 1000);
        }
      }
    ]);
    
    tray.setContextMenu(contextMenu);

    // Global shortcuts
    globalShortcut.register('CommandOrControl+I', () => sendCommand('quit'));

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  app.on('will-quit', () => {
    globalShortcut.unregisterAll();
    if (pyEngine) {
      pyEngine.kill();
    }
  });
}
