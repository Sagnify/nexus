import { app, BrowserWindow, dialog, globalShortcut, ipcMain, screen, Tray, Menu, nativeImage, session, shell } from 'electron';

import path from 'path';
import { fileURLToPath } from 'url';
import http from 'http';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: BrowserWindow | null = null;
let pillWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let reregisterInterval: ReturnType<typeof setInterval> | null = null;
let loopbackServer: http.Server | null = null;

const WINDOW_WIDTH = 700;
const INITIAL_HEIGHT = 440;

const PILL_WIDTH = 640;
const PILL_COLLAPSED_HEIGHT = 68;
const PILL_TOP_Y = 20;
let lastSyncedTaskState: any = null;
let lastSyncedTeachState: any = null;

// ---------------------------------------------------------------------------
// Hotkeys that ACTUALLY work on Windows reliably (not intercepted by the OS):
//   Alt+N           → safe, almost never claimed by any app
//   Ctrl+Shift+N    → safe globally (only app-level in Chrome, doesn't conflict)
//   Alt+Shift+N     → very safe, rarely used by anything
//   Ctrl+Alt+Space  → safe on Windows (not claimed by OS)
//
// Keys that are BROKEN on Windows — never use:
//   Win+Space       → Language/IME switching (OS level)
//   Ctrl+Space      → IME candidate window (OS level)
//   Alt+Space       → Window system menu (OS level, always intercepted)
//   F13, F14        → Don't exist on most laptops (only F1–F12)
// ---------------------------------------------------------------------------
const PRIMARY_HOTKEYS = [
  'Alt+N',
  'CommandOrControl+Shift+N',
  'Alt+Shift+N',
  'CommandOrControl+Alt+Space',
];

let isTaskRunning = false;

function createSpotlightWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight } = primaryDisplay.workAreaSize;

  const x = Math.round((screenWidth - WINDOW_WIDTH) / 2);
  const y = Math.round(screenHeight * 0.13);

  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    minWidth: WINDOW_WIDTH,
    maxWidth: WINDOW_WIDTH,
    height: INITIAL_HEIGHT,
    minHeight: 80,
    maxHeight: 960,
    x,
    y,
    frame: false,
    transparent: true,
    thickFrame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    hasShadow: false,
    show: false,
    icon: path.join(__dirname, '../public/icon.png'),
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      spellcheck: false,
      backgroundThrottling: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.webContents.on('before-input-event', (_event, input) => {
    if (input.key === 'F12' && input.type === 'keyDown') {
      mainWindow?.webContents.toggleDevTools();
    }
  });

  // Hide on blur (click outside) ONLY for Spotlight window when no task is running
  mainWindow.on('blur', () => {
    if (mainWindow && !mainWindow.webContents.isDevToolsOpened()) {
      if (!isTaskRunning) {
        mainWindow.hide();
        mainWindow.webContents.send('window-blurred');
        mainWindow.webContents.send('window-hidden');
      }
    }
  });

  mainWindow.on('hide', () => {
    mainWindow?.webContents.send('window-hidden');
  });

  mainWindow.on('show', () => {
    mainWindow?.webContents.send('window-shown');
  });

  mainWindow.once('ready-to-show', () => {
    showWindow();
  });
}

function createPillWindow() {
  if (pillWindow) return;

  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth } = primaryDisplay.workAreaSize;

  const x = Math.round((screenWidth - PILL_WIDTH) / 2);
  const y = PILL_TOP_Y;

  pillWindow = new BrowserWindow({
    width: PILL_WIDTH,
    height: PILL_COLLAPSED_HEIGHT,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    movable: true,
    hasShadow: false,
    show: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      spellcheck: false,
      backgroundThrottling: false,
    },
  });

  if (process.platform === 'darwin') {
    pillWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    pillWindow.setAlwaysOnTop(true, 'screen-saver');
  } else {
    pillWindow.setAlwaysOnTop(true);
  }

  const baseUrl = process.env.VITE_DEV_SERVER_URL;
  if (baseUrl) {
    pillWindow.loadURL(`${baseUrl}?view=pill`);
  } else {
    pillWindow.loadFile(path.join(__dirname, '../dist/index.html'), { query: { view: 'pill' } });
  }

  pillWindow.webContents.on('did-finish-load', () => {
    if (lastSyncedTaskState && pillWindow && !pillWindow.isDestroyed()) {
      pillWindow.webContents.send('task-state-updated', lastSyncedTaskState);
    }
    if (lastSyncedTeachState && pillWindow && !pillWindow.isDestroyed()) {
      pillWindow.webContents.send('teach-state-updated', lastSyncedTeachState);
    }
  });

  // CRITICAL: pillWindow NEVER hides on blur! Stays visible during screen automation.
  pillWindow.on('closed', () => {
    pillWindow = null;
  });
}

function createTray() {
  // Authentic NEXUS 32x32 ribbon loop icon encoded as base64 PNG
  const iconBase64 =
    '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';

  try {
    const img = nativeImage.createFromDataURL(`data:image/png;base64,${iconBase64}`);
    tray = new Tray(img.resize({ width: 16, height: 16 }));
  } catch {
    // If custom icon fails, use empty image — tray still functional
    tray = new Tray(nativeImage.createEmpty());
  }

  tray.setToolTip('NEXUS  —  Alt+N to open');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '⚡  Open NEXUS',
      click: () => showWindow(),
    },
    { type: 'separator' },
    {
      label: 'Hotkeys: Alt+N  |  Ctrl+Shift+N  |  F13',
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Quit NEXUS',
      click: () => app.quit(),
    },
  ]);

  tray.setContextMenu(contextMenu);

  // Left-click opens directly (right-click shows menu automatically)
  tray.on('click', () => showWindow());

  console.log('[NEXUS] ✅ System tray icon active (always-available fallback)');
}

function startLoopbackServer() {
  if (loopbackServer) return;
  try {
    loopbackServer = http.createServer((req, res) => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

      if (req.method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
      }

      const urlPath = req.url?.split('?')[0] || '';
      if (urlPath === '/show-spotlight') {
        showWindow();
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, status: 'spotlight_shown' }));
        return;
      }

      if (urlPath === '/teach-finish') {
        showWindow();
        hidePillWindow();
        mainWindow?.webContents.send('remote-teach-finished');
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, status: 'teach_finished' }));
        return;
      }

      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
    });

    loopbackServer.on('error', (err: any) => {
      console.warn('[NEXUS] Loopback server error:', err?.message || err);
    });

    loopbackServer.listen(8765, '127.0.0.1', () => {
      console.log('[NEXUS] ⚡ Loopback trigger server active on http://127.0.0.1:8765');
    });
  } catch (e) {
    console.warn('[NEXUS] Could not start loopback server:', e);
  }
}

function showPillWindow() {
  if (!pillWindow || pillWindow.isDestroyed()) createPillWindow();
  if (pillWindow) {
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width: screenWidth } = primaryDisplay.workAreaSize;
    const currentBounds = pillWindow.getBounds();
    const x = Math.round((screenWidth - PILL_WIDTH) / 2);
    const y = PILL_TOP_Y;
    const h = Math.max(currentBounds.height, PILL_COLLAPSED_HEIGHT);
    pillWindow.setBounds({ x, y, width: PILL_WIDTH, height: h }, false);
    if (process.platform === 'darwin') {
      pillWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
      pillWindow.setAlwaysOnTop(true, 'screen-saver');
    } else {
      pillWindow.setAlwaysOnTop(true);
    }
    if (pillWindow.isMinimized()) {
      pillWindow.restore();
    }
    pillWindow.show();
    pillWindow.moveTop();

    if (lastSyncedTaskState && !pillWindow.isDestroyed()) {
      pillWindow.webContents.send('task-state-updated', lastSyncedTaskState);
    }
    if (lastSyncedTeachState && !pillWindow.isDestroyed()) {
      pillWindow.webContents.send('teach-state-updated', lastSyncedTeachState);
    }
  }
}

function hidePillWindow() {
  if (pillWindow && pillWindow.isVisible()) {
    pillWindow.hide();
  }
}

function showWindow() {
  if (!mainWindow) {
    createSpotlightWindow();
    return;
  }

  if (process.platform === 'darwin') {
    mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
    mainWindow.show();
    mainWindow.focus();
    mainWindow.moveTop();
    setTimeout(() => {
      if (mainWindow && mainWindow.isVisible()) {
        mainWindow.setAlwaysOnTop(true, 'pop-up-menu');
        mainWindow.setVisibleOnAllWorkspaces(false);
      }
    }, 350);
  } else {
    // Windows & Linux: Keep alwaysOnTop standard and NEVER cycle setVisibleOnAllWorkspaces
    // or levels via setTimeout. Doing so triggers Windows DWM to re-evaluate layered window
    // composition attributes, which strips the WS_EX_LAYERED alpha transparency and turns the
    // entire window surface into an opaque solid black box.
    mainWindow.setAlwaysOnTop(true);
    mainWindow.show();
    mainWindow.focus();
    mainWindow.moveTop();
  }

  mainWindow.webContents.send('window-shown');
}

function hideWindow() {
  if (!mainWindow) return;
  mainWindow.hide();
  mainWindow.webContents.send('window-hidden');
}

function toggleWindow() {
  if (!mainWindow) {
    createSpotlightWindow();
    return;
  }
  if (mainWindow.isVisible()) {
    hideWindow();
  } else {
    showWindow();
  }
}

function registerHotkeys(silent = false) {
  // Always unregister first so we don't stack duplicate listeners
  globalShortcut.unregisterAll();

  let registered = 0;
  for (const key of PRIMARY_HOTKEYS) {
    try {
      const ok = globalShortcut.register(key, () => toggleWindow());
      if (ok) {
        registered++;
      } else if (!silent) {
        console.warn(`[NEXUS] ⚠️  Hotkey stolen by OS/another app: ${key}`);
      }
    } catch (err) {
      if (!silent) {
        console.warn(`[NEXUS] ❌ Could not register ${key}:`, err);
      }
    }
  }

  if (!silent && registered > 0) {
    console.log(`[NEXUS] ✅ Registered ${registered} global hotkeys: ${PRIMARY_HOTKEYS.join(', ')}`);
  }

  if (registered === 0 && !silent) {
    console.error('[NEXUS] 🚨 ALL hotkeys failed to register — use the system tray to open NEXUS!');
  }

  return registered;
}

interface ExcelWindowInfo {
  hwnd: number | null;
  title: string;
  workbook_name: string;
  workbook_path: string;
  active_sheet: string;
  visible: boolean;
  is_minimized: boolean;
  is_foreground?: boolean;
  rect: { left: number; top: number; right: number; bottom: number; width: number; height: number } | null;
}

const excelCopilotWindows = new Map<number, BrowserWindow>();
let excelTrackInterval: ReturnType<typeof setInterval> | null = null;
let isTrackingExcel = false;

function convertPhysicalRectToDip(physRect: { left: number; top: number; right: number; bottom: number; width?: number; height?: number }) {
  const displays = screen.getAllDisplays();
  const primary = screen.getPrimaryDisplay();

  const physCenterX = (physRect.left + physRect.right) / 2;
  const physCenterY = (physRect.top + physRect.bottom) / 2;

  let targetDisplay = primary;
  for (const d of displays) {
    const scale = d.scaleFactor || 1;
    const physLeft = d.bounds.x * scale;
    const physTop = d.bounds.y * scale;
    const physRight = physLeft + d.bounds.width * scale;
    const physBottom = physTop + d.bounds.height * scale;

    if (physCenterX >= physLeft && physCenterX <= physRight && physCenterY >= physTop && physCenterY <= physBottom) {
      targetDisplay = d;
      break;
    }
  }

  const scale = targetDisplay.scaleFactor || 1;
  const dispPhysX = targetDisplay.bounds.x * scale;
  const dispPhysY = targetDisplay.bounds.y * scale;

  const dipLeft = Math.round(targetDisplay.bounds.x + (physRect.left - dispPhysX) / scale);
  const dipTop = Math.round(targetDisplay.bounds.y + (physRect.top - dispPhysY) / scale);
  const dipRight = Math.round(targetDisplay.bounds.x + (physRect.right - dispPhysX) / scale);
  const dipBottom = Math.round(targetDisplay.bounds.y + (physRect.bottom - dispPhysY) / scale);

  return {
    display: targetDisplay,
    scale,
    left: dipLeft,
    top: dipTop,
    right: dipRight,
    bottom: dipBottom,
    width: dipRight - dipLeft,
    height: dipBottom - dipTop,
  };
}

function trackExcelWindows() {
  if (isTrackingExcel) return;
  isTrackingExcel = true;

  // Collect native HWNDs of open copilot windows so user clicks on copilot keep it active
  const copilotHwnds: number[] = [];
  for (const win of excelCopilotWindows.values()) {
    if (!win.isDestroyed()) {
      try {
        const buf = win.getNativeWindowHandle();
        if (buf && buf.length >= 4) {
          copilotHwnds.push(buf.readInt32LE(0));
        }
      } catch (_) {}
    }
  }

  const endpointUrl = copilotHwnds.length > 0
    ? `http://127.0.0.1:8000/api/nexus/excel/windows?copilot_hwnds=${copilotHwnds.join(',')}`
    : 'http://127.0.0.1:8000/api/nexus/excel/windows';

  http.get(endpointUrl, (res) => {
    let data = '';
    res.on('data', chunk => { data += chunk; });
    res.on('end', () => {
      isTrackingExcel = false;
      try {
        if (res.statusCode !== 200) return;
        const parsed = JSON.parse(data);
        const windows: ExcelWindowInfo[] = parsed.windows || [];
        const activeHwnds = new Set<number>();

        for (const winInfo of windows) {
          if (!winInfo.hwnd) continue;
          activeHwnds.add(winInfo.hwnd);

          const existingWin = excelCopilotWindows.get(winInfo.hwnd);

          // Strictly stay visible ONLY when Excel is visible, not minimized, and either Excel or Copilot is in the foreground
          const shouldBeVisible = winInfo.visible && !winInfo.is_minimized && winInfo.is_foreground === true && !!winInfo.rect;

          if (!shouldBeVisible) {
            if (existingWin && !existingWin.isDestroyed() && existingWin.isVisible()) {
              existingWin.hide();
            }
            continue;
          }

          if (!winInfo.rect) continue;
          const dipRect = convertPhysicalRectToDip(winInfo.rect);
          const defaultWidth = 160;
          const defaultHeight = 48;

          // Target top-right of Excel formula/sheet bar
          let targetX = dipRect.right - defaultWidth - 35;
          let targetY = Math.max(dipRect.top + 160, dipRect.display.workArea.y + 155);

          // Work area clamping to guarantee the pill is always 100% visible on the active monitor
          const minX = dipRect.display.workArea.x + 10;
          const maxX = dipRect.display.workArea.x + dipRect.display.workArea.width - defaultWidth - 15;
          const minY = dipRect.display.workArea.y + 40;
          const maxY = dipRect.display.workArea.y + dipRect.display.workArea.height - defaultHeight - 15;

          targetX = Math.max(minX, Math.min(targetX, maxX));
          targetY = Math.max(minY, Math.min(targetY, maxY));

          if (!existingWin || existingWin.isDestroyed()) {
            console.log(`[Excel Copilot] 🎯 Attaching floating copilot to hwnd=${winInfo.hwnd} (${winInfo.title}) at (${targetX}, ${targetY}) [scaleFactor=${dipRect.scale}]`);
            const copilotWin = new BrowserWindow({
              width: defaultWidth,
              height: defaultHeight,
              x: targetX,
              y: targetY,
              frame: false,
              transparent: true,
              alwaysOnTop: true,
              skipTaskbar: true,
              resizable: false,
              hasShadow: false,
              show: true,
              backgroundColor: '#00000000',
              webPreferences: {
                preload: path.join(__dirname, 'preload.cjs'),
                nodeIntegration: false,
                contextIsolation: true,
                spellcheck: false,
                backgroundThrottling: false,
              },
            });

            copilotWin.setVisibleOnAllWorkspaces(true);
            copilotWin.setAlwaysOnTop(true);

            const queryStr = `view=excel-copilot&hwnd=${winInfo.hwnd}&workbook=${encodeURIComponent(winInfo.workbook_name)}`;
            const baseUrl = process.env.VITE_DEV_SERVER_URL;
            if (baseUrl) {
              const cleanBase = baseUrl.replace(/\/$/, '');
              const urlToLoad = `${cleanBase}/?${queryStr}`;
              console.log(`[Excel Copilot] Loading URL: ${urlToLoad}`);
              copilotWin.loadURL(urlToLoad);
            } else {
              copilotWin.loadFile(path.join(__dirname, '../dist/index.html'), {
                query: {
                  view: 'excel-copilot',
                  hwnd: String(winInfo.hwnd),
                  workbook: winInfo.workbook_name,
                },
                hash: queryStr,
              });
            }

            copilotWin.webContents.on('did-finish-load', () => {
              if (copilotWin && !copilotWin.isDestroyed()) {
                copilotWin.show();
                copilotWin.setAlwaysOnTop(true);
                copilotWin.moveTop();
              }
            });

            copilotWin.webContents.on('did-fail-load', (_e, code, desc) => {
              console.error(`[Excel Copilot] Failed to load copilot webContents: code=${code}, desc=${desc}`);
            });

            copilotWin.on('blur', () => {
              // When user clicks away from copilot, immediately re-check foreground window state
              setTimeout(trackExcelWindows, 60);
            });

            copilotWin.on('closed', () => {
              if (winInfo.hwnd) excelCopilotWindows.delete(winInfo.hwnd);
            });

            excelCopilotWindows.set(winInfo.hwnd, copilotWin);
          } else {
            // Already created: update position if Excel moved and copilot is collapsed
            const curBounds = existingWin.getBounds();
            if (curBounds.width <= 200) {
              if (Math.abs(curBounds.x - targetX) > 5 || Math.abs(curBounds.y - targetY) > 5) {
                existingWin.setBounds({ x: targetX, y: targetY, width: curBounds.width, height: curBounds.height }, false);
              }
            } else {
              // Expanded mode: keep inside Excel window boundaries & workArea
              const expWidth = curBounds.width;
              const expHeight = curBounds.height;
              let expandedX = dipRect.right - expWidth - 30;
              let expandedY = Math.max(dipRect.top + 120, dipRect.display.workArea.y + 100);

              const maxExpX = dipRect.display.workArea.x + dipRect.display.workArea.width - expWidth - 15;
              const maxExpY = dipRect.display.workArea.y + dipRect.display.workArea.height - expHeight - 15;

              expandedX = Math.max(dipRect.display.workArea.x + 10, Math.min(expandedX, maxExpX));
              expandedY = Math.max(dipRect.display.workArea.y + 40, Math.min(expandedY, maxExpY));

              if (Math.abs(curBounds.x - expandedX) > 10 || Math.abs(curBounds.y - expandedY) > 10) {
                existingWin.setBounds({ x: expandedX, y: expandedY, width: curBounds.width, height: curBounds.height }, false);
              }
            }
            if (!existingWin.isVisible()) {
              existingWin.show();
              existingWin.setAlwaysOnTop(true);
              existingWin.moveTop();
            }
          }
        }

        // Clean up closed Excel windows
        for (const [hwnd, win] of excelCopilotWindows.entries()) {
          if (!activeHwnds.has(hwnd)) {
            if (!win.isDestroyed()) {
              win.destroy();
            }
            excelCopilotWindows.delete(hwnd);
          }
        }
      } catch (_) {}
    });
  }).on('error', () => {
    isTrackingExcel = false;
  });
}

interface WordWindowInfo {
  hwnd: number | null;
  title: string;
  document_name: string;
  document_path: string;
  visible: boolean;
  is_minimized: boolean;
  is_foreground?: boolean;
  rect: { left: number; top: number; right: number; bottom: number; width: number; height: number } | null;
}

const wordCopilotWindows = new Map<number, BrowserWindow>();
let wordTrackInterval: ReturnType<typeof setInterval> | null = null;
let isTrackingWord = false;

function trackWordWindows() {
  if (isTrackingWord) return;
  isTrackingWord = true;

  // Collect native HWNDs of open copilot windows so user clicks on copilot keep it active
  const copilotHwnds: number[] = [];
  for (const win of wordCopilotWindows.values()) {
    if (!win.isDestroyed()) {
      try {
        const buf = win.getNativeWindowHandle();
        if (buf && buf.length >= 4) {
          copilotHwnds.push(buf.readInt32LE(0));
        }
      } catch (_) {}
    }
  }

  const queryParts = [`electron_pid=${process.pid}`];
  if (copilotHwnds.length > 0) {
    queryParts.push(`copilot_hwnds=${copilotHwnds.join(',')}`);
  }
  const endpointUrl = `http://127.0.0.1:8000/api/nexus/word/windows?${queryParts.join('&')}`;

  const req = http.get(endpointUrl, (res) => {
    let data = '';
    res.on('data', chunk => { data += chunk; });
    res.on('end', () => {
      isTrackingWord = false;
      try {
        if (res.statusCode !== 200) return;
        const parsed = JSON.parse(data);
        const windows: WordWindowInfo[] = parsed.windows || [];
        const activeHwnds = new Set<number>();

        for (const winInfo of windows) {
          if (!winInfo.hwnd) continue;
          activeHwnds.add(winInfo.hwnd);

          const existingWin = wordCopilotWindows.get(winInfo.hwnd);

          // Strictly stay visible ONLY when Word is visible, not minimized, and either Word or Copilot is in the foreground
          const shouldBeVisible = winInfo.visible && !winInfo.is_minimized && winInfo.is_foreground === true && !!winInfo.rect;

          if (!shouldBeVisible) {
            if (existingWin && !existingWin.isDestroyed() && existingWin.isVisible()) {
              existingWin.hide();
            }
            continue;
          }

          if (!winInfo.rect) continue;
          const dipRect = convertPhysicalRectToDip(winInfo.rect);
          const defaultWidth = 160;
          const defaultHeight = 48;

          // Target top-right of Word document window
          let targetX = dipRect.right - defaultWidth - 35;
          let targetY = Math.max(dipRect.top + 160, dipRect.display.workArea.y + 155);

          // Work area clamping to guarantee the pill is always 100% visible on the active monitor
          const minX = dipRect.display.workArea.x + 10;
          const maxX = dipRect.display.workArea.x + dipRect.display.workArea.width - defaultWidth - 15;
          const minY = dipRect.display.workArea.y + 40;
          const maxY = dipRect.display.workArea.y + dipRect.display.workArea.height - defaultHeight - 15;

          targetX = Math.max(minX, Math.min(targetX, maxX));
          targetY = Math.max(minY, Math.min(targetY, maxY));

          if (!existingWin || existingWin.isDestroyed()) {
            console.log(`[Word Copilot] 🎯 Attaching floating copilot to hwnd=${winInfo.hwnd} (${winInfo.title}) at (${targetX}, ${targetY}) [scaleFactor=${dipRect.scale}]`);
            const copilotWin = new BrowserWindow({
              width: defaultWidth,
              height: defaultHeight,
              x: targetX,
              y: targetY,
              frame: false,
              transparent: true,
              alwaysOnTop: true,
              skipTaskbar: true,
              resizable: false,
              hasShadow: false,
              show: true,
              backgroundColor: '#00000000',
              webPreferences: {
                preload: path.join(__dirname, 'preload.cjs'),
                nodeIntegration: false,
                contextIsolation: true,
                spellcheck: false,
                backgroundThrottling: false,
              },
            });

            copilotWin.setVisibleOnAllWorkspaces(true);
            copilotWin.setAlwaysOnTop(true);

            const queryStr = `view=word-copilot&hwnd=${winInfo.hwnd}&document=${encodeURIComponent(winInfo.document_name)}`;
            const baseUrl = process.env.VITE_DEV_SERVER_URL;
            if (baseUrl) {
              const cleanBase = baseUrl.replace(/\/$/, '');
              const urlToLoad = `${cleanBase}/?${queryStr}`;
              console.log(`[Word Copilot] Loading URL: ${urlToLoad}`);
              copilotWin.loadURL(urlToLoad);
            } else {
              copilotWin.loadFile(path.join(__dirname, '../dist/index.html'), {
                query: {
                  view: 'word-copilot',
                  hwnd: String(winInfo.hwnd),
                  document: winInfo.document_name,
                },
                hash: queryStr,
              });
            }

            copilotWin.webContents.on('did-finish-load', () => {
              if (copilotWin && !copilotWin.isDestroyed()) {
                copilotWin.show();
                copilotWin.setAlwaysOnTop(true);
                copilotWin.moveTop();
              }
            });

            copilotWin.webContents.on('did-fail-load', (_e, code, desc) => {
              console.error(`[Word Copilot] Failed to load copilot webContents: code=${code}, desc=${desc}`);
            });

            copilotWin.on('blur', () => {
              // When user clicks away from copilot, immediately re-check foreground window state
              setImmediate(trackWordWindows);
            });

            copilotWin.on('closed', () => {
              if (winInfo.hwnd) wordCopilotWindows.delete(winInfo.hwnd);
            });

            wordCopilotWindows.set(winInfo.hwnd, copilotWin);
          } else {
            // Already created: update position if Word moved and copilot is collapsed
            const curBounds = existingWin.getBounds();
            if (curBounds.width <= 200) {
              if (Math.abs(curBounds.x - targetX) > 5 || Math.abs(curBounds.y - targetY) > 5) {
                existingWin.setBounds({ x: targetX, y: targetY, width: curBounds.width, height: curBounds.height }, false);
              }
            } else {
              // Expanded mode: keep inside Word window boundaries & workArea
              const expWidth = curBounds.width;
              const expHeight = curBounds.height;
              let expandedX = dipRect.right - expWidth - 30;
              let expandedY = Math.max(dipRect.top + 120, dipRect.display.workArea.y + 100);

              const maxExpX = dipRect.display.workArea.x + dipRect.display.workArea.width - expWidth - 15;
              const maxExpY = dipRect.display.workArea.y + dipRect.display.workArea.height - expHeight - 15;

              expandedX = Math.max(dipRect.display.workArea.x + 10, Math.min(expandedX, maxExpX));
              expandedY = Math.max(dipRect.display.workArea.y + 40, Math.min(expandedY, maxExpY));

              if (Math.abs(curBounds.x - expandedX) > 10 || Math.abs(curBounds.y - expandedY) > 10) {
                existingWin.setBounds({ x: expandedX, y: expandedY, width: curBounds.width, height: curBounds.height }, false);
              }
            }
            if (!existingWin.isVisible()) {
              existingWin.show();
              existingWin.setAlwaysOnTop(true);
              existingWin.moveTop();
            }
          }
        }

        // Clean up closed Word windows
        for (const [hwnd, win] of wordCopilotWindows.entries()) {
          if (!activeHwnds.has(hwnd)) {
            if (!win.isDestroyed()) {
              win.destroy();
            }
            wordCopilotWindows.delete(hwnd);
          }
        }
      } catch (_) {}
    });
  });
  req.on('error', () => {
    isTrackingWord = false;
  });
  req.setTimeout(800, () => {
    req.destroy();
    isTrackingWord = false;
  });
}

// Ensure single instance
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  // Enable Web Speech API in Electron Chromium
  app.commandLine.appendSwitch('enable-features', 'WebSpeechAPI');
  app.commandLine.appendSwitch('enable-speech-dispatcher');

  app.on('second-instance', () => {
    showWindow();
  });

  app.whenReady().then(() => {
    // Auto-grant all permissions (media, microphone, audio capture, etc.) for local Spotlight window
    session.defaultSession.setPermissionCheckHandler(() => true);
    session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
      callback(true);
    });

    createSpotlightWindow();
    createPillWindow();  // Pre-create for immediate responsiveness
    createTray();        // System tray = always-available fallback
    startLoopbackServer(); // ⚡ Instant local HTTP trigger on port 8765

    registerHotkeys(false);

    // Heartbeat: silently re-register shortcuts every 30s without console spam.
    // Other apps (games, browsers) can steal global shortcuts at any time.
    // This silently recovers without polluting the terminal.
    reregisterInterval = setInterval(() => {
      registerHotkeys(true);
    }, 30_000);

    // IPC Handlers
    ipcMain.on('window-hide', () => hideWindow());
    ipcMain.on('window-show', () => showWindow());
    ipcMain.on('spotlight-wake', () => {
      showWindow();
    });

    ipcMain.on('window-resize', (_event, { width, height, position }: { width?: number; height: number; position?: string }) => {
      if (mainWindow) {
        const targetWidth = width || WINDOW_WIDTH;
        const primaryDisplay = screen.getPrimaryDisplay();
        const { width: screenWidth, height: screenHeight } = primaryDisplay.workAreaSize;
        const maxH = Math.min(screenHeight - 30, 920);
        const h = Math.min(Math.max(Math.ceil(height), 80), maxH);
        const currentBounds = mainWindow.getBounds();
        if (currentBounds.width === targetWidth && Math.abs(currentBounds.height - h) <= 1 && !position) {
          return; // Dimensions unchanged: prevent Win32 re-layout loops
        }
        const x = Math.round((screenWidth - targetWidth) / 2);
        let targetY = currentBounds.y;
        if (position === 'center') {
          targetY = Math.max(15, Math.round((screenHeight - h) / 2));
        } else if (targetY + h > screenHeight - 15) {
          targetY = Math.max(15, screenHeight - h - 15);
        }
        mainWindow.setBounds({ x, y: targetY, width: targetWidth, height: h }, false);
      }
    });

    ipcMain.on('show-automation-pill', () => showPillWindow());
    ipcMain.on('hide-automation-pill', () => hidePillWindow());

    ipcMain.on('pill-resize', (_event, { height }: { height: number }) => {
      if (pillWindow) {
        const primaryDisplay = screen.getPrimaryDisplay();
        const { width: screenWidth } = primaryDisplay.workAreaSize;
        const h = Math.min(Math.max(Math.ceil(height), 56), 480);
        const x = Math.round((screenWidth - PILL_WIDTH) / 2);
        const y = PILL_TOP_Y;
        pillWindow.setBounds({ x, y, width: PILL_WIDTH, height: h }, false);
      }
    });

    ipcMain.on('sync-task-state', (_event, state) => {
      lastSyncedTaskState = state;
      isTaskRunning = Boolean(
        state?.isRunning ||
        state?.isPaused ||
        state?.pendingPermission !== null ||
        state?.userInputRequest !== null
      );
      if (pillWindow && !pillWindow.isDestroyed()) {
        pillWindow.webContents.send('task-state-updated', state);
        if (state?.userInputRequest) {
          if (!pillWindow.isVisible()) {
            showPillWindow();
          }
          pillWindow.show();
          pillWindow.moveTop();
          pillWindow.focus();
        }
      }
    });

    ipcMain.on('sync-teach-state', (_event, state) => {
      lastSyncedTeachState = state;
      if (state?.isTeaching || state?.isCompilingDraft) {
        isTaskRunning = true;
      } else if (!lastSyncedTaskState?.isRunning) {
        isTaskRunning = false;
      }
      if (pillWindow && !pillWindow.isDestroyed()) {
        pillWindow.webContents.send('teach-state-updated', state);
      }
    });

    ipcMain.on('pill-action', (_event, data) => {
      const action = typeof data === 'string' ? data : data?.action;
      const payload = typeof data === 'object' && data !== null ? data.payload : undefined;
      if (action === 'request-state-sync') {
        if (lastSyncedTaskState && pillWindow && !pillWindow.isDestroyed()) {
          pillWindow.webContents.send('task-state-updated', lastSyncedTaskState);
        }
        if (lastSyncedTeachState && pillWindow && !pillWindow.isDestroyed()) {
          pillWindow.webContents.send('teach-state-updated', lastSyncedTeachState);
        }
      }
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('pill-action-received', { action, payload });
      }
    });

    ipcMain.handle('get-file-icon', async (_event, filePath: string) => {
      try {
        if (!filePath) return null;
        const icon = await app.getFileIcon(filePath, { size: 'normal' });
        return icon.toDataURL();
      } catch (err) {
        return null;
      }
    });

    ipcMain.handle('select-save-path', async (_event, defaultFilename?: string) => {
      try {
        const win = mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
        const result = await dialog.showSaveDialog(win!, {
          title: 'Select Where to Store Presentation',
          defaultPath: defaultFilename || 'presentation.pptx',
          filters: [
            { name: 'PowerPoint Presentations (*.pptx)', extensions: ['pptx'] },
            { name: 'Excel Spreadsheets (*.xlsx)', extensions: ['xlsx'] },
            { name: 'Word Documents (*.docx)', extensions: ['docx'] },
            { name: 'All Files (*.*)', extensions: ['*'] }
          ]
        });
        if (result.canceled || !result.filePath) return null;
        return result.filePath;
      } catch (err) {
        console.error('[NEXUS] select-save-path failed:', err);
        return null;
      }
    });

    ipcMain.handle('select-folder', async () => {
      try {
        const win = mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
        const result = await dialog.showOpenDialog(win!, {
          title: 'Select Folder to Store Presentation',
          properties: ['openDirectory', 'createDirectory']
        });
        if (result.canceled || !result.filePaths.length) return null;
        return result.filePaths[0];
      } catch (err) {
        console.error('[NEXUS] select-folder failed:', err);
        return null;
      }
    });

    ipcMain.handle('show-in-folder', async (_event, filePath: string) => {
      if (filePath) {
        try {
          shell.showItemInFolder(filePath);
          return true;
        } catch (_) {}
      }
      return false;
    });

    ipcMain.handle('open-path', async (_event, filePath: string) => {
      if (filePath) {
        try {
          return await shell.openPath(filePath);
        } catch (_) {}
      }
      return '';
    });

    ipcMain.on('open-external', (_event, url: string) => {
      if (url && (url.startsWith('http://') || url.startsWith('https://'))) {
        shell.openExternal(url);
      }
    });


    ipcMain.on('excel-copilot-resize', (_event, { hwnd, width, height }: { hwnd: number; width: number; height: number }) => {
      let win = excelCopilotWindows.get(Number(hwnd));
      if (!win && excelCopilotWindows.size > 0) {
        win = Array.from(excelCopilotWindows.values())[0];
      }
      if (win && !win.isDestroyed()) {
        const bounds = win.getBounds();
        const newX = bounds.x + bounds.width - width;
        win.setBounds({ x: newX, y: bounds.y, width, height }, false);
      }
    });

    ipcMain.on('word-copilot-resize', (_event, { hwnd, width, height }: { hwnd: number; width: number; height: number }) => {
      let win = wordCopilotWindows.get(Number(hwnd));
      if (!win && wordCopilotWindows.size > 0) {
        win = Array.from(wordCopilotWindows.values())[0];
      }
      if (win && !win.isDestroyed()) {
        const bounds = win.getBounds();
        const newX = bounds.x + bounds.width - width;
        win.setBounds({ x: newX, y: bounds.y, width, height }, false);
      }
    });

    ipcMain.on('app-quit', () => app.quit());

    // Start background tracking of open Excel windows
    trackExcelWindows();
    excelTrackInterval = setInterval(trackExcelWindows, 300);

    // Start background tracking of open Word windows
    trackWordWindows();
    wordTrackInterval = setInterval(trackWordWindows, 150);

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createSpotlightWindow();
        createPillWindow();
      } else {
        showWindow();
      }
    });
  });

  app.on('will-quit', () => {
    globalShortcut.unregisterAll();
    if (reregisterInterval) clearInterval(reregisterInterval);
    if (excelTrackInterval) clearInterval(excelTrackInterval);
    if (wordTrackInterval) clearInterval(wordTrackInterval);
    for (const win of excelCopilotWindows.values()) {
      if (!win.isDestroyed()) win.destroy();
    }
    excelCopilotWindows.clear();
    for (const win of wordCopilotWindows.values()) {
      if (!win.isDestroyed()) win.destroy();
    }
    wordCopilotWindows.clear();
    try {
      loopbackServer?.close();
    } catch (_) {}
  });

  app.on('window-all-closed', () => {
    // On Windows: stay alive in tray when all windows are closed.
    // This means closing the spotlight doesn't kill the process.
    // User must explicitly choose "Quit NEXUS" from the tray menu.
    if (process.platform === 'darwin') app.quit();
  });
}
