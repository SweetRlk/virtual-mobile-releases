const { app, BrowserWindow, ipcMain, globalShortcut } = require("electron");
const { autoUpdater } = require("electron-updater");
const startTelemetry = require("./telemetry");
const koffi = require("koffi");
const fs = require('fs');
const path = require("path");
const { execSync } = require("child_process");

// Load config
const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
const API_URL = config.api.url;
const APP_VERSION = require('./package.json').version;

// Enable audio capture for VoIP
app.commandLine.appendSwitch('enable-features', 'WebRTCPipeWireCapturer');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');

const user32 = koffi.load("user32.dll");
const GetForegroundWindow = user32.func("void* __stdcall GetForegroundWindow()");
const GetWindowTextW = user32.func("int __stdcall GetWindowTextW(void*, uint16_t*, int)");

let win, interactMode = false, gameInFocus = true, gameRunning = false, cachedHwid = null;

function getHwid() {
  if (cachedHwid) return cachedHwid;
  try {
    const output = execSync('reg query "HKLM\\SOFTWARE\\Microsoft\\Cryptography" /v MachineGuid', { encoding: 'utf8' });
    const match = output.match(/MachineGuid\s+REG_SZ\s+(.+)/);
    const guid = match ? match[1].trim() : '';
    if (!guid) throw new Error("MachineGuid not found");
    cachedHwid = require("crypto").createHash("sha256").update(guid).digest("hex").substring(0, 32);
  } catch (e) {
    cachedHwid = "unknown-" + require("crypto").randomBytes(12).toString("hex");
  }
  return cachedHwid;
}

function getGameInFocus() {
  try {
    const hwnd = GetForegroundWindow();
    if (!hwnd) return true;
    const buf = Buffer.alloc(0x200);
    const len = GetWindowTextW(hwnd, buf, 0x100);
    if (len === 0) return true;
    const title = buf.toString("utf16le", 0, len * 2);
    return /ets2|euro truck|simulator/i.test(title);
  } catch (e) {
    return true;
  }
}

function isGameRunning() {
  try {
    const output = execSync('tasklist /FI "IMAGENAME eq eurotrucks2.exe" /NH', { encoding: 'utf8', timeout: 3000 });
    return /eurotrucks2\.exe/i.test(output);
  } catch (e) {
    return false;
  }
}

setInterval(() => {
  if (!win || win.isDestroyed()) return;
  const running = isGameRunning();
  if (running !== gameRunning) {
    gameRunning = running;
    if (win && !win.isDestroyed() && win.webContents) {
      win.webContents.send("game-running-changed", gameRunning);
      if (!running) {
        gameInFocus = true;
        win.webContents.send("game-focus-changed", true);
        if (interactMode) {
          interactMode = false;
          win.setIgnoreMouseEvents(true, { forward: true });
          win.blur();
          win.webContents.send("interact-mode", false);
        }
      }
    }
  }
}, 3000);

setInterval(async () => {
  if (!win || win.isDestroyed()) return;
  if (!gameRunning && interactMode) {
    interactMode = false;
    win.setIgnoreMouseEvents(true, { forward: true });
    win.blur();
    win.webContents.send("interact-mode", false);
    return;
  }
  if (interactMode) return;
  if (!gameRunning) return;
  const inFocus = getGameInFocus();
  if (inFocus !== gameInFocus) {
    gameInFocus = inFocus;
    if (win && !win.isDestroyed() && win.webContents) {
      win.webContents.send("game-focus-changed", gameInFocus);
    }
  }
}, 500);

app.whenReady().then(() => {
  win = new BrowserWindow({
    fullscreen: true,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: false,
    icon: path.join(__dirname, 'icon.ico'),
    title: 'Virtual Mobile',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      webviewTag: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  win.setIgnoreMouseEvents(true, { forward: true });

  // Allow microphone access for VoIP calls
  win.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === 'media') {
      callback(true);
    } else {
      callback(false);
    }
  });
  win.webContents.session.setPermissionCheckHandler((webContents, permission) => {
    if (permission === 'media') return true;
    return false;
  });

  ipcMain.on("set-ignore-mouse", (e, ignore) => {
    if (interactMode) return;
    if (ignore) {
      win.setIgnoreMouseEvents(true, { forward: true });
    } else {
      win.setIgnoreMouseEvents(false);
    }
  });

  ipcMain.on("power-off", () => {
    app.quit();
  });

  ipcMain.handle("get-hwid", () => getHwid());
  ipcMain.handle("is-game-running", () => gameRunning);
  ipcMain.handle("get-api-url", () => API_URL);
  ipcMain.handle("get-app-version", () => APP_VERSION);

  // Captura DACTE HTML como imagem PNG (base64)
  ipcMain.handle("capture-nota-image", async (event, htmlContent) => {
    let captureWin = null;
    try {
      captureWin = new BrowserWindow({
        width: 500,
        height: 900,
        show: false,
        frame: false,
        transparent: false,
        webPreferences: { offscreen: true }
      });

      const fullHtml = `data:text/html;charset=utf-8,${encodeURIComponent(htmlContent)}`;
      await captureWin.loadURL(fullHtml);

      // Esperar renderizar
      await new Promise(r => setTimeout(r, 300));

      // Pegar altura real do conteúdo
      const dims = await captureWin.webContents.executeJavaScript(
        `JSON.stringify({ w: document.body.scrollWidth, h: document.body.scrollHeight })`
      );
      const { w, h } = JSON.parse(dims);
      captureWin.setSize(Math.max(w, 500), Math.min(h + 20, 2000));
      await new Promise(r => setTimeout(r, 150));

      const image = await captureWin.webContents.capturePage();
      const pngBuffer = image.toPNG();
      return pngBuffer.toString('base64');
    } catch (e) {
      return null;
    } finally {
      if (captureWin && !captureWin.isDestroyed()) captureWin.destroy();
    }
  });

  globalShortcut.register('F9', () => {
    interactMode = !interactMode;
    if (interactMode) {
      win.setIgnoreMouseEvents(false);
      win.focus();
    } else {
      win.setIgnoreMouseEvents(true, { forward: true });
      win.blur();
      gameInFocus = true;
      if (win && !win.isDestroyed() && win.webContents) {
        win.webContents.send("game-focus-changed", true);
      }
    }
    win.webContents.send("interact-mode", interactMode);
  });

  globalShortcut.register('F8', () => {
    win.webContents.send("toggle-phone");
  });

  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true);
  win.loadFile("overlay.html");

  gameRunning = isGameRunning();

  win.webContents.on("did-finish-load", () => {
    win.webContents.send("game-running-changed", gameRunning);
  });

  startTelemetry(win);

  // === AUTO-UPDATER ===
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('update-status', { status: 'downloading', version: info.version, percent: 0 });
    }
  });

  autoUpdater.on('download-progress', (progress) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('update-status', { status: 'progress', percent: Math.round(progress.percent), speed: progress.bytesPerSecond });
    }
  });

  autoUpdater.on('update-downloaded', (info) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('update-status', { status: 'ready', version: info.version });
    }
  });

  autoUpdater.on('error', (err) => {
  });

  ipcMain.on('install-update', () => {
    autoUpdater.quitAndInstall(false, true);
  });

  // Checar updates 3s após iniciar, depois a cada 30 min
  setTimeout(() => { autoUpdater.checkForUpdates().catch(() => {}); }, 3000);
  setInterval(() => { autoUpdater.checkForUpdates().catch(() => {}); }, 30 * 60 * 1000);
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});
