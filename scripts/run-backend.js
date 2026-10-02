import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';

const isWin = process.platform === 'win32';
const candidates = [
  path.join(process.cwd(), 'venv', isWin ? 'Scripts/python.exe' : 'bin/python'),
  path.join(process.cwd(), '.venv', isWin ? 'Scripts/python.exe' : 'bin/python'),
  path.join(process.cwd(), 'backend', 'venv', isWin ? 'Scripts/python.exe' : 'bin/python'),
  isWin ? 'python' : 'python3'
];

let pythonCmd = 'python';
for (const cand of candidates) {
  if (fs.existsSync(cand)) {
    pythonCmd = cand;
    break;
  }
}

let child = null;
let isShuttingDown = false;
let consecutiveFailures = 0;
let watchdogInterval = null;
let workerStartedAt = 0;

// How long (ms) to ignore health probe failures after a fresh worker start.
// Uvicorn + FastAPI + DB init can take up to ~10s on first cold boot.
const STARTUP_GRACE_MS = 15000;

function startBackendWorker() {
  if (isShuttingDown) return;

  console.log('[Auto-Healer] 🚀 Starting NEXUS backend worker process...');
  consecutiveFailures = 0;  // Reset so startup connection errors never trigger a kill
  workerStartedAt = Date.now();

  child = spawn(pythonCmd, ['-m', 'backend.main'], {
    stdio: 'inherit',
    shell: false,
    env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
  });

  child.on('exit', (code, signal) => {
    if (isShuttingDown) {
      process.exit(code ?? (signal ? 1 : 0));
      return;
    }
    console.warn(`[Auto-Healer] ⚠️ Backend worker exited unexpectedly (code=${code}, signal=${signal}). Self-healing restart in 1s...`);
    child = null;
    setTimeout(() => {
      if (!isShuttingDown) startBackendWorker();
    }, 1000);
  });
}

function checkBackendHealth() {
  if (isShuttingDown || !child) return;

  const req = http.get('http://127.0.0.1:8000/api/health', { timeout: 3500 }, (res) => {
    if (res.statusCode === 200) {
      consecutiveFailures = 0;
    } else {
      consecutiveFailures++;
      handleFailure(`HTTP status ${res.statusCode}`);
    }
    res.resume();
  });

  req.on('timeout', () => {
    req.destroy();
    consecutiveFailures++;
    handleFailure('Health probe timed out (3.5s ceiling exceeded)');
  });

  req.on('error', (err) => {
    // Initial startup grace period
    consecutiveFailures++;
    handleFailure(`Connection error: ${err.message}`);
  });
}

function handleFailure(reason) {
  // Ignore failures during the startup grace window — server is still booting
  if (Date.now() - workerStartedAt < STARTUP_GRACE_MS) return;

  if (consecutiveFailures >= 3 && child && !isShuttingDown) {
    console.error(`[Auto-Healer] 🚨 Backend unresponsive for 3 consecutive probes (${reason}). Executing emergency self-healing restart...`);
    consecutiveFailures = 0;
    try {
      if (isWin) {
        spawn('taskkill', ['/pid', child.pid.toString(), '/f', '/t'], { stdio: 'ignore' });
      } else {
        child.kill('SIGKILL');
      }
    } catch (_) {}
  }
}

// Start worker
startBackendWorker();

// Health watchdog DISABLED — uncomment to re-enable
// setTimeout(() => {
//   console.log('[Auto-Healer] 🛡️ Autonomous background health watchdog active.');
//   watchdogInterval = setInterval(checkBackendHealth, 5000);
// }, 18000);

// Graceful termination
const shutdown = () => {
  isShuttingDown = true;
  if (watchdogInterval) clearInterval(watchdogInterval);
  if (child) {
    try {
      if (isWin) {
        spawn('taskkill', ['/pid', child.pid.toString(), '/f', '/t'], { stdio: 'ignore' });
      } else {
        child.kill('SIGTERM');
      }
    } catch (_) {}
  }
  process.exit(0);
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
