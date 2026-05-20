/**
 * Bupi Launcher — System Tray Entry Point
 * 
 * A lightweight system tray application that lets the user
 * launch, stop, and manage Bupi without opening a terminal.
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, screen } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const fs = require('fs');

// Set unique app name so it doesn't conflict with main Bupi process
app.name = 'BupiLauncher';

// Keep only one instance of the launcher
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
  process.exit(0);
}

let tray = null;
let popupWindow = null;
let bupiProcess = null;
let isQuitting = false;

// -----------------------------------------------------------------
// Bupi Process Management
// -----------------------------------------------------------------

function getBupiStatus() {
  if (bupiProcess && !bupiProcess.killed) return 'running';
  return 'stopped';
}

function launchBupi() {
  if (bupiProcess && !bupiProcess.killed) return;

  const bupiDir = __dirname;
  // Directly launch electron.exe with the main entry point — avoids npm spawn issues on Windows
  const electronExe = path.join(bupiDir, 'node_modules', 'electron', 'dist', 'electron.exe');
  const mainEntry = path.join(bupiDir, 'main.js');

  bupiProcess = spawn(electronExe, [mainEntry], {
    cwd: bupiDir,
    stdio: 'pipe',
    detached: false,
    windowsHide: false,
  });

  bupiProcess.on('error', (err) => {
    logMsg(`[Launcher] Failed to start Bupi: ${err}`);
    notifyPopup('bupi-status', 'stopped');
  });

  bupiProcess.on('close', (code) => {
    logMsg(`[Launcher] Bupi exited with code ${code}`);
    bupiProcess = null;
    notifyPopup('bupi-status', 'stopped');
    updateTrayTooltip();
  });

  bupiProcess.stdout.on('data', (d) => logMsg(`[Bupi] ${d.toString().trim()}`));
  bupiProcess.stderr.on('data', (d) => logMsg(`[Bupi STDERR] ${d.toString().trim()}`));

  notifyPopup('bupi-status', 'running');
  updateTrayTooltip();
  logMsg('[Launcher] Bupi started.');
}

function stopBupi() {
  if (!bupiProcess || bupiProcess.killed) {
    notifyPopup('bupi-status', 'stopped');
    return;
  }

  // Try graceful kill on windows
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /PID ${bupiProcess.pid} /T /F`, { stdio: 'ignore' });
    } else {
      bupiProcess.kill('SIGTERM');
    }
  } catch (e) {
    logMsg(`[Launcher] Kill failed: ${e}`);
  }

  bupiProcess = null;
  notifyPopup('bupi-status', 'stopped');
  updateTrayTooltip();
}

// -----------------------------------------------------------------
// Windows Startup (Registry)
// -----------------------------------------------------------------

function isStartupEnabled() {
  if (process.platform !== 'win32') return false;
  try {
    const launcherPath = process.execPath; // electron.exe
    const appName = 'BupiLauncher';
    const regQuery = execSync(
      `reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v ${appName}`,
      { stdio: 'pipe' }
    ).toString();
    return regQuery.includes(appName);
  } catch {
    return false;
  }
}

function setStartupEnabled(enable) {
  if (process.platform !== 'win32') return;
  const appName = 'BupiLauncher';
  const launcherExe = process.execPath;
  const launcherDir = path.dirname(launcherExe);

  try {
    if (enable) {
      // Register the launcher to run at startup
      const cmd = `"${launcherExe}" --launcher "${launcherDir}"`;
      execSync(
        `reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v ${appName} /t REG_SZ /d "${cmd}" /f`,
        { stdio: 'ignore' }
      );
      logMsg('[Launcher] Added to Windows startup.');
    } else {
      execSync(
        `reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v ${appName} /f`,
        { stdio: 'ignore' }
      );
      logMsg('[Launcher] Removed from Windows startup.');
    }
  } catch (e) {
    logMsg(`[Launcher] Startup toggle error: ${e}`);
  }
}

// -----------------------------------------------------------------
// Popup Window
// -----------------------------------------------------------------

function createPopupWindow() {
  if (popupWindow && !popupWindow.isDestroyed()) {
    popupWindow.hide();
    popupWindow.destroy();
    popupWindow = null;
    return;
  }

  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  popupWindow = new BrowserWindow({
    width: 280,
    height: 340,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    show: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });

  // Position: bottom-right above tray
  popupWindow.setPosition(width - 296, height - 356);
  popupWindow.loadFile(path.join(__dirname, 'launcher.html'));

  popupWindow.webContents.once('did-finish-load', () => {
    // Send initial state
    popupWindow.webContents.send('bupi-status', getBupiStatus());
    popupWindow.webContents.send('startup-status', isStartupEnabled());
    popupWindow.show();
    popupWindow.focus();
  });

  popupWindow.on('blur', () => {
    // Auto-close when user clicks away
    if (popupWindow && !popupWindow.isDestroyed()) {
      popupWindow.hide();
      popupWindow.destroy();
      popupWindow = null;
    }
  });
}

function notifyPopup(channel, data) {
  if (popupWindow && !popupWindow.isDestroyed()) {
    popupWindow.webContents.send(channel, data);
  }
}

// -----------------------------------------------------------------
// Tray
// -----------------------------------------------------------------

function updateTrayTooltip() {
  if (!tray) return;
  const status = getBupiStatus() === 'running' ? '● Running' : '○ Stopped';
  tray.setToolTip(`Bupi Companion — ${status}`);
}

function buildContextMenu() {
  const running = getBupiStatus() === 'running';
  return Menu.buildFromTemplate([
    {
      label: running ? '● Bupi is Running' : '○ Bupi is Stopped',
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Launch Bupi',
      enabled: !running,
      click: () => launchBupi(),
    },
    {
      label: 'Stop Bupi',
      enabled: running,
      click: () => stopBupi(),
    },
    { type: 'separator' },
    {
      label: 'Quit Launcher',
      click: () => {
        isQuitting = true;
        stopBupi();
        app.quit();
      },
    },
  ]);
}

// -----------------------------------------------------------------
// IPC Handlers
// -----------------------------------------------------------------

ipcMain.on('get-status', (event) => {
  event.sender.send('bupi-status', getBupiStatus());
  event.sender.send('startup-status', isStartupEnabled());
});

ipcMain.on('launch-bupi', () => {
  launchBupi();
  tray.setContextMenu(buildContextMenu());
});

ipcMain.on('stop-bupi', () => {
  stopBupi();
  tray.setContextMenu(buildContextMenu());
});

ipcMain.on('toggle-startup', (event, enable) => {
  setStartupEnabled(enable);
});

ipcMain.on('open-settings', () => {
  const { shell } = require('electron');
  shell.openPath(path.join(__dirname, '.env'));
});

ipcMain.on('open-logs', () => {
  const { shell } = require('electron');
  shell.openPath(path.join(__dirname, 'debug_log.txt'));
});

ipcMain.on('quit-launcher', () => {
  isQuitting = true;
  stopBupi();
  setTimeout(() => app.quit(), 500);
});

// -----------------------------------------------------------------
// Log helper
// -----------------------------------------------------------------

function logMsg(msg) {
  try {
    fs.appendFileSync(
      path.join(__dirname, 'launcher_log.txt'),
      `[${new Date().toISOString()}] ${msg}\n`
    );
  } catch {}
}

// -----------------------------------------------------------------
// App Init
// -----------------------------------------------------------------

app.whenReady().then(() => {
  // Prevent closing when all windows are closed (we live in the tray)
  app.on('window-all-closed', (e) => {
    if (!isQuitting) e.preventDefault();
  });

  const iconPath = path.join(__dirname, 'assets', 'tray_icon.png');
  const fallbackIconPath = path.join(__dirname, 'assets', 'icon.png');
  let icon;
  try {
    icon = nativeImage.createFromPath(
      fs.existsSync(iconPath) ? iconPath : fallbackIconPath
    );
  } catch {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip('Bupi Companion — Click to manage');

  // Single-click → open popup menu
  tray.on('click', () => {
    createPopupWindow();
    tray.setContextMenu(buildContextMenu());
  });

  // Right-click → classic context menu
  tray.on('right-click', () => {
    tray.popUpContextMenu(buildContextMenu());
  });

  logMsg('[Launcher] Bupi Launcher started.');
});

app.on('before-quit', () => {
  isQuitting = true;
  if (bupiProcess && !bupiProcess.killed) {
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /PID ${bupiProcess.pid} /T /F`, { stdio: 'ignore' });
      } else {
        bupiProcess.kill();
      }
    } catch {}
  }
});
