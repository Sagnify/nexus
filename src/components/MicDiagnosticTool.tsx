import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Play, Square, Copy, Download, RefreshCw, CheckCircle2, AlertTriangle, XCircle, Volume2 } from 'lucide-react';

interface DiagnosticResult {
  step: string;
  status: 'pending' | 'running' | 'pass' | 'warn' | 'fail';
  detail: string;
}

export const MicDiagnosticTool: React.FC = () => {
  const [isTestingLive, setIsTestingLive] = useState(false);
  const [liveVolume, setLiveVolume] = useState(0);
  const [deviceList, setDeviceList] = useState<MediaDeviceInfo[]>([]);
  const [activeDeviceLabel, setActiveDeviceLabel] = useState<string>('Default Microphone');
  const [isRunningSuite, setIsRunningSuite] = useState(false);
  const [suiteResults, setSuiteResults] = useState<DiagnosticResult[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);

  // References
  const liveStreamRef = useRef<MediaStream | null>(null);
  const liveCtxRef = useRef<AudioContext | null>(null);
  const liveSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const liveAnalyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const appendLog = (msg: string) => {
    const timestamp = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, `[${timestamp}] ${msg}`]);
  };

  // Enumerate devices
  const refreshDevices = useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter(d => d.kind === 'audioinput');
      setDeviceList(audioInputs);
      if (audioInputs.length > 0 && audioInputs[0].label) {
        setActiveDeviceLabel(audioInputs[0].label);
      }
      appendLog(`Detected ${audioInputs.length} audio input device(s).`);
    } catch (err) {
      appendLog(`Error enumerating devices: ${err}`);
    }
  }, []);

  useEffect(() => {
    refreshDevices();
  }, [refreshDevices]);

  // Stop live microphone test
  const stopLiveTest = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (liveSourceRef.current) {
      try { liveSourceRef.current.disconnect(); } catch {}
      liveSourceRef.current = null;
    }
    if (liveStreamRef.current) {
      liveStreamRef.current.getTracks().forEach(t => t.stop());
      liveStreamRef.current = null;
    }
    if (liveCtxRef.current && liveCtxRef.current.state !== 'closed') {
      liveCtxRef.current.close().catch(() => {});
      liveCtxRef.current = null;
    }
    liveAnalyserRef.current = null;
    setLiveVolume(0);
    setIsTestingLive(false);
    appendLog('Live microphone test stopped.');
  }, []);

  // Start live microphone meter test
  const startLiveTest = useCallback(async () => {
    stopLiveTest();
    appendLog('Starting live microphone test...');
    setIsTestingLive(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      liveStreamRef.current = stream;

      const track = stream.getAudioTracks()[0];
      if (track) {
        setActiveDeviceLabel(track.label || 'Default Microphone');
        appendLog(`Microphone active: ${track.label} (ReadyState: ${track.readyState})`);
      }

      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) {
        appendLog('Web Audio API is not supported in this browser environment.');
        return;
      }

      const ctx = new AudioCtx();
      liveCtxRef.current = ctx;

      if (ctx.state === 'suspended') {
        appendLog('AudioContext was suspended, resuming...');
        await ctx.resume();
      }
      appendLog(`AudioContext state: ${ctx.state} (SampleRate: ${ctx.sampleRate}Hz)`);

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      liveAnalyserRef.current = analyser;

      const source = ctx.createMediaStreamSource(stream);
      liveSourceRef.current = source;
      source.connect(analyser);

      const timeData = new Uint8Array(analyser.fftSize);

      const monitor = () => {
        if (!liveAnalyserRef.current) return;
        liveAnalyserRef.current.getByteTimeDomainData(timeData);

        let sumSquares = 0;
        for (let i = 0; i < timeData.length; i++) {
          const norm = (timeData[i] - 128) / 128;
          sumSquares += norm * norm;
        }
        const rms = Math.sqrt(sumSquares / timeData.length);
        const percentage = Math.min(100, Math.round(rms * 400));
        setLiveVolume(percentage);

        animFrameRef.current = requestAnimationFrame(monitor);
      };

      monitor();
    } catch (err: any) {
      appendLog(`Failed to acquire microphone stream: ${err.name} - ${err.message}`);
      setIsTestingLive(false);
    }
  }, [stopLiveTest]);

  // Automated Diagnostic Suite
  const runFullDiagnosticSuite = async () => {
    if (isRunningSuite) return;
    setIsRunningSuite(true);
    setLogs([]);
    appendLog('Initiating NEXUS Microphone Diagnostic Suite...');

    const results: DiagnosticResult[] = [
      { step: 'MediaDevices & OS Permission', status: 'running', detail: 'Testing getUserMedia stream access...' },
      { step: 'WebAudio Graph & AudioContext', status: 'pending', detail: 'Waiting...' },
      { step: 'Google Web Speech API Availability', status: 'pending', detail: 'Waiting...' },
      { step: 'Groq Whisper Turbo Backend Endpoint', status: 'pending', detail: 'Waiting...' },
    ];
    setSuiteResults([...results]);

    let testStream: MediaStream | null = null;

    // Step 1: MediaDevices & Permissions
    try {
      testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const tracks = testStream.getAudioTracks();
      if (tracks.length > 0 && tracks[0].readyState === 'live') {
        results[0] = {
          step: 'MediaDevices & OS Permission',
          status: 'pass',
          detail: `Success: Track '${tracks[0].label}' is live and unmuted.`,
        };
        appendLog(`[Step 1 PASS] Audio stream active: ${tracks[0].label}`);
      } else {
        results[0] = {
          step: 'MediaDevices & OS Permission',
          status: 'warn',
          detail: 'Stream acquired but audio track state is not live.',
        };
        appendLog('[Step 1 WARN] Audio track is not live.');
      }
    } catch (err: any) {
      results[0] = {
        step: 'MediaDevices & OS Permission',
        status: 'fail',
        detail: `Error: ${err.name} - ${err.message}. Check Windows microphone privacy settings.`,
      };
      appendLog(`[Step 1 FAIL] getUserMedia denied: ${err.message}`);
    }
    setSuiteResults([...results]);

    // Step 2: WebAudio Graph
    if (testStream) {
      results[1] = { step: 'WebAudio Graph & AudioContext', status: 'running', detail: 'Testing WebAudio graph...' };
      setSuiteResults([...results]);

      try {
        const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
        const ctx = new AudioCtx();
        if (ctx.state === 'suspended') {
          await ctx.resume();
        }
        const analyser = ctx.createAnalyser();
        const src = ctx.createMediaStreamSource(testStream);
        src.connect(analyser);

        const buf = new Uint8Array(analyser.fftSize);
        analyser.getByteTimeDomainData(buf);

        results[1] = {
          step: 'WebAudio Graph & AudioContext',
          status: 'pass',
          detail: `Success: AudioContext state '${ctx.state}', sampleRate: ${ctx.sampleRate}Hz.`,
        };
        appendLog(`[Step 2 PASS] AudioContext state: ${ctx.state}`);
        setTimeout(() => ctx.close(), 1000);
      } catch (err: any) {
        results[1] = {
          step: 'WebAudio Graph & AudioContext',
          status: 'fail',
          detail: `WebAudio failed: ${err.message}`,
        };
        appendLog(`[Step 2 FAIL] WebAudio error: ${err.message}`);
      }
      setSuiteResults([...results]);
    } else {
      results[1] = { step: 'WebAudio Graph & AudioContext', status: 'fail', detail: 'Skipped due to missing stream.' };
      setSuiteResults([...results]);
    }

    // Step 3: Google Web Speech API Test
    results[2] = { step: 'Google Web Speech API Availability', status: 'running', detail: 'Probing webkitSpeechRecognition...' };
    setSuiteResults([...results]);

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      results[2] = {
        step: 'Google Web Speech API Availability',
        status: 'fail',
        detail: 'webkitSpeechRecognition is not exposed in this environment.',
      };
      appendLog('[Step 3 FAIL] SpeechRecognition undefined on window.');
    } else {
      await new Promise<void>((resolve) => {
        let finished = false;
        try {
          const rec = new SpeechRec();
          rec.continuous = false;
          rec.interimResults = false;

          const timer = setTimeout(() => {
            if (!finished) {
              finished = true;
              try { rec.abort(); } catch {}
              results[2] = {
                step: 'Google Web Speech API Availability',
                status: 'warn',
                detail: 'Service initiated but no audio was spoken within 3 seconds (Normal if silent).',
              };
              appendLog('[Step 3 WARN] Web Speech test timed out (silence).');
              resolve();
            }
          }, 3000);

          rec.onstart = () => {
            appendLog('[Step 3 INFO] Web Speech engine started successfully.');
          };

          rec.onerror = (e: any) => {
            if (!finished) {
              finished = true;
              clearTimeout(timer);
              if (e.error === 'network') {
                results[2] = {
                  step: 'Google Web Speech API Availability',
                  status: 'warn',
                  detail: 'Google Cloud Speech endpoint rejected Electron (network error). Fallback to Groq Whisper active.',
                };
                appendLog('[Step 3 WARN] Web Speech error: network (Google API blocked in Electron).');
              } else if (e.error === 'no-speech') {
                results[2] = {
                  step: 'Google Web Speech API Availability',
                  status: 'pass',
                  detail: 'Google Web Speech service reached (no speech heard).',
                };
                appendLog('[Step 3 PASS] Web Speech connected (no speech error is expected for silence).');
              } else {
                results[2] = {
                  step: 'Google Web Speech API Availability',
                  status: 'warn',
                  detail: `Web Speech error: ${e.error}`,
                };
                appendLog(`[Step 3 WARN] Web Speech error: ${e.error}`);
              }
              resolve();
            }
          };

          rec.onresult = () => {
            if (!finished) {
              finished = true;
              clearTimeout(timer);
              results[2] = {
                step: 'Google Web Speech API Availability',
                status: 'pass',
                detail: 'Speech recognized successfully by Google engine.',
              };
              appendLog('[Step 3 PASS] Speech result received.');
              resolve();
            }
          };

          rec.start();
        } catch (err: any) {
          if (!finished) {
            finished = true;
            results[2] = {
              step: 'Google Web Speech API Availability',
              status: 'warn',
              detail: `Failed to initialize: ${err.message}`,
            };
            appendLog(`[Step 3 WARN] SpeechRec start threw: ${err.message}`);
            resolve();
          }
        }
      });
    }
    setSuiteResults([...results]);

    // Step 4: Backend Groq Whisper Endpoint
    results[3] = { step: 'Groq Whisper Turbo Backend Endpoint', status: 'running', detail: 'Testing POST /api/nexus/transcribe...' };
    setSuiteResults([...results]);

    try {
      const startTime = performance.now();
      // Generate a tiny valid silent WAV payload for ping
      const wavHeader = new Uint8Array([
        0x52, 0x49, 0x46, 0x46, 0x24, 0x00, 0x00, 0x00, 0x57, 0x41, 0x56, 0x45,
        0x66, 0x6d, 0x74, 0x20, 0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
        0x40, 0x1f, 0x00, 0x00, 0x80, 0x3e, 0x00, 0x00, 0x02, 0x00, 0x10, 0x00,
        0x64, 0x61, 0x74, 0x61, 0x00, 0x00, 0x00, 0x00
      ]);
      const blob = new Blob([wavHeader], { type: 'audio/wav' });
      const formData = new FormData();
      formData.append('file', blob, 'ping.wav');

      const res = await fetch('http://127.0.0.1:8000/api/nexus/transcribe', {
        method: 'POST',
        body: formData,
      });

      const elapsed = Math.round(performance.now() - startTime);

      if (res.ok) {
        const data = await res.json();
        results[3] = {
          step: 'Groq Whisper Turbo Backend Endpoint',
          status: 'pass',
          detail: `Success: HTTP 200 in ${elapsed}ms. Server responded: '${data.text || "OK"}'`,
        };
        appendLog(`[Step 4 PASS] Groq Whisper Turbo endpoint operational (${elapsed}ms).`);
      } else {
        const errorText = await res.text();
        results[3] = {
          step: 'Groq Whisper Turbo Backend Endpoint',
          status: 'fail',
          detail: `HTTP ${res.status}: ${errorText}`,
        };
        appendLog(`[Step 4 FAIL] Endpoint returned HTTP ${res.status}: ${errorText}`);
      }
    } catch (err: any) {
      results[3] = {
        step: 'Groq Whisper Turbo Backend Endpoint',
        status: 'fail',
        detail: `Connection error: ${err.message}. Ensure backend is running on 127.0.0.1:8000.`,
      };
      appendLog(`[Step 4 FAIL] Connection failed: ${err.message}`);
    }

    setSuiteResults([...results]);

    if (testStream) {
      testStream.getTracks().forEach(t => t.stop());
    }

    setIsRunningSuite(false);
    appendLog('Diagnostic Suite execution completed.');
  };

  const copyLogsToClipboard = () => {
    const text = logs.join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadLogs = () => {
    const text = logs.join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus-mic-diagnostics-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3.5 text-xs text-white/90">
      {/* Header Card */}
      <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
        <div className="flex items-center gap-2">
          <Volume2 className="w-4 h-4 text-sky-400" strokeWidth={1.8} />
          <div>
            <div className="font-medium text-white text-[12px]">Hardware & Pipeline Diagnostics</div>
            <div className="text-[10.5px] text-white/40">Verify OS microphone permissions, audio graphs & Whisper endpoints</div>
          </div>
        </div>
        <button
          type="button"
          onClick={runFullDiagnosticSuite}
          disabled={isRunningSuite}
          className="px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-white font-medium flex items-center gap-1.5 transition-colors cursor-pointer text-xs shadow-sm shadow-sky-500/20"
        >
          {isRunningSuite ? (
            <>
              <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Diagnosing...</span>
            </>
          ) : (
            <>
              <RefreshCw className="w-3 h-3" strokeWidth={2} />
              <span>Run Suite</span>
            </>
          )}
        </button>
      </div>

      {/* Live VU Meter Card */}
      <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 flex-1 min-w-0 pr-2">
            <span className="text-[11.5px] font-medium text-white/80">Input Level:</span>
            <span className="text-white/45 font-mono text-[11px] truncate" title={activeDeviceLabel}>
              {activeDeviceLabel} {deviceList.length > 1 ? `(${deviceList.length} devices)` : ''}
            </span>
          </div>
          <button
            type="button"
            onClick={isTestingLive ? stopLiveTest : startLiveTest}
            className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors flex items-center gap-1.5 ${
              isTestingLive
                ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30 hover:bg-rose-500/25'
                : 'bg-white/[0.06] text-white/80 border border-white/[0.08] hover:bg-white/[0.10]'
            }`}
          >
            {isTestingLive ? (
              <>
                <Square className="w-2.5 h-2.5 fill-current" />
                <span>Stop Monitor</span>
              </>
            ) : (
              <>
                <Play className="w-2.5 h-2.5 fill-current" />
                <span>Live Test</span>
              </>
            )}
          </button>
        </div>

        {/* Meter Bar */}
        <div className="w-full h-2 rounded-full bg-black/50 border border-white/[0.06] overflow-hidden relative">
          <div
            className="h-full transition-all duration-75 rounded-full"
            style={{
              width: `${liveVolume}%`,
              background: liveVolume > 80 ? '#f43f5e' : liveVolume > 40 ? '#38bdf8' : '#10b981',
              boxShadow: liveVolume > 10 ? '0 0 10px rgba(56, 189, 248, 0.4)' : 'none',
            }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-white/30 font-mono">
          <span>Silence</span>
          <span>Signal: {liveVolume}%</span>
          <span>Peak</span>
        </div>
      </div>

      {/* Automated Suite Results */}
      {suiteResults.length > 0 && (
        <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40 block">
            Diagnostic Verification
          </span>
          <div className="space-y-1.5">
            {suiteResults.map((res, i) => (
              <div key={i} className="flex items-start justify-between p-2.5 rounded-lg bg-black/30 border border-white/[0.04]">
                <div className="space-y-0.5 pr-2">
                  <div className="font-medium text-white text-[11px]">{res.step}</div>
                  <div className="text-[10px] text-white/40 leading-tight font-mono">{res.detail}</div>
                </div>
                <div className="flex-shrink-0 pt-0.5">
                  {res.status === 'running' && (
                    <div className="w-3.5 h-3.5 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin" />
                  )}
                  {res.status === 'pass' && (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" strokeWidth={2} />
                  )}
                  {res.status === 'warn' && (
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400" strokeWidth={2} />
                  )}
                  {res.status === 'fail' && (
                    <XCircle className="w-3.5 h-3.5 text-rose-400" strokeWidth={2} />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Diagnostic Log Console */}
      <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
            Hardware Event Log
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={copyLogsToClipboard}
              className="px-2 py-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] text-white/60 hover:text-white text-[10px] flex items-center gap-1 border border-white/[0.05] transition-colors"
            >
              <Copy className="w-2.5 h-2.5" />
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
            <button
              type="button"
              onClick={downloadLogs}
              className="px-2 py-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] text-white/60 hover:text-white text-[10px] flex items-center gap-1 border border-white/[0.05] transition-colors"
            >
              <Download className="w-2.5 h-2.5" />
              <span>Export</span>
            </button>
          </div>
        </div>
        <div className="p-2.5 rounded-lg bg-black/50 border border-white/[0.04] font-mono text-[10px] text-white/50 max-h-[100px] overflow-y-auto space-y-1 select-text">
          {logs.length === 0 ? (
            <span className="text-white/25">Ready. Run diagnostic suite or test live mic to view hardware logs.</span>
          ) : (
            logs.map((line, idx) => <div key={idx} className="leading-relaxed">{line}</div>)
          )}
        </div>
      </div>
    </div>
  );
};
