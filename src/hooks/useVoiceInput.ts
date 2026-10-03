import { useState, useEffect, useCallback, useRef } from 'react';

// Declarations for Web Speech API
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: ((this: SpeechRecognitionInstance, ev: Event) => any) | null;
  onend: ((this: SpeechRecognitionInstance, ev: Event) => any) | null;
  onerror: ((this: SpeechRecognitionInstance, ev: any) => any) | null;
  onresult: ((this: SpeechRecognitionInstance, ev: SpeechRecognitionEvent) => any) | null;
}

declare global {
  interface Window {
    SpeechRecognition?: { new (): SpeechRecognitionInstance };
    webkitSpeechRecognition?: { new (): SpeechRecognitionInstance };
  }
}

interface UseVoiceInputOptions {
  enabled?: boolean;
  wakeWordEnabled?: boolean;
  autoSubmit?: boolean;
  silenceTimeoutMs?: number;
  onTranscript?: (text: string, isFinal: boolean) => void;
  onSubmit?: (finalText: string) => void;
}

const BACKEND_URL = 'http://127.0.0.1:8000';
const DEFAULT_SILENCE_TIMEOUT_MS = 1800;

/**
 * Encodes raw 32-bit float PCM audio samples into a standard 16-bit Mono WAV Blob.
 */
function encodeWAV(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  function writeString(offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM Format
  view.setUint16(22, 1, true); // Mono channel
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // Byte rate
  view.setUint16(32, 2, true); // Block align (1 channel * 2 bytes)
  view.setUint16(34, 16, true); // 16-bit
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  // Pass ArrayBuffer directly so browser constructs raw binary blob
  return new Blob([buffer], { type: 'audio/wav' });
}

/**
 * High quality downsampling from AudioContext native sample rate to 16kHz.
 */
function downsampleTo16k(input: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === 16000) return input;
  const ratio = inputSampleRate / 16000;
  const newLength = Math.round(input.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetInput = 0;

  while (offsetResult < result.length) {
    const nextOffsetInput = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetInput; i < nextOffsetInput && i < input.length; i++) {
      accum += input[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : input[offsetInput] || 0;
    offsetResult++;
    offsetInput = nextOffsetInput;
  }
  return result;
}

export function useVoiceInput({
  enabled = true,
  wakeWordEnabled = true,
  autoSubmit = true,
  silenceTimeoutMs = DEFAULT_SILENCE_TIMEOUT_MS,
  onTranscript,
  onSubmit,
}: UseVoiceInputOptions = {}) {
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [wakeWordDetected, setWakeWordDetected] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  // Microphone device management
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>(() => {
    return localStorage.getItem('nexus_selected_mic_device_id') || '';
  });

  // Spotlight visibility state — "Hey Nexus" only operates when Spotlight is opened via shortcut
  const [isWindowOpen, setIsWindowOpen] = useState(() => {
    if (typeof window !== 'undefined' && window.electronAPI) {
      return false; // Electron starts with Spotlight hidden until global shortcut is pressed
    }
    return typeof document !== 'undefined' ? !document.hidden : true;
  });
  const isWindowOpenRef = useRef(isWindowOpen);
  isWindowOpenRef.current = isWindowOpen;

  const isListeningRef = useRef(false);
  isListeningRef.current = isListening;

  const stopListeningRef = useRef<() => void>(() => {});
  const startListeningRef = useRef<() => void>(() => {});

  const silenceTimeoutMsRef = useRef(silenceTimeoutMs);
  silenceTimeoutMsRef.current = silenceTimeoutMs;

  const autoSubmitRef = useRef(autoSubmit);
  autoSubmitRef.current = autoSubmit;

  const onSubmitRef = useRef(onSubmit);
  onSubmitRef.current = onSubmit;

  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  const currentSpeechTextRef = useRef('');
  const silenceTimerRef = useRef<any>(null);
  const maxSessionTimerRef = useRef<any>(null);
  const speechStartTimestampRef = useRef<number>(0);
  const speechDetectedRef = useRef(false);

  // Adaptive noise floor tracking
  const ambientNoiseRef = useRef(0.005);
  const smoothedLevelRef = useRef(0);

  // Web Speech API references
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const wakeWordActiveRef = useRef(false);
  const wakeCheckInProgressRef = useRef(false);
  const wakeSpeechFramesRef = useRef(0);
  const wakeSilenceFramesRef = useRef(0);
  const wakeSpeechActiveRef = useRef(false);
  const wakeSpeechStartTsRef = useRef(0);
  const wakeCooldownUntilRef = useRef(0);
  const wakeListenDelayTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Raw PCM Audio Rolling Ring Buffer for Wake Word (~3.2s)
  const wakePcmBufferRef = useRef<Float32Array>(new Float32Array(0));

  // Active user speech PCM buffer
  const activeSpeechChunksRef = useRef<Float32Array[]>([]);

  // Hardware Audio Pipeline references
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);

  // Enumerate audio input devices
  const updateDeviceList = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = all.filter(d => d.kind === 'audioinput');
      setDevices(audioInputs);
    } catch (err) {
      console.error('[Voice:Mic] Error enumerating audio devices:', err);
    }
  }, []);

  useEffect(() => {
    updateDeviceList();
    navigator.mediaDevices?.addEventListener?.('devicechange', updateDeviceList);
    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', updateDeviceList);
    };
  }, [updateDeviceList]);

  // Send audio Blob (16kHz WAV) to Groq Whisper Turbo endpoint
  const transcribeAudioBlob = useCallback(async (blob: Blob): Promise<{ text: string; wake_detected: boolean; command: string; error?: string }> => {
    try {
      const formData = new FormData();
      formData.append('file', blob, 'audio.wav');

      console.log(`[Voice:STT] Uploading ${blob.size} bytes (audio.wav) for transcription...`);
      const res = await fetch(`${BACKEND_URL}/api/nexus/transcribe`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const errBody = await res.json();
          if (errBody?.detail) detail = errBody.detail;
        } catch {}
        console.warn(`[Voice:STT] Backend returned error status ${res.status}:`, detail);
        return { text: '', wake_detected: false, command: '', error: `STT Error (${res.status}): ${detail}` };
      }

      const data = await res.json();
      console.log('[Voice:STT] Transcription received:', data);
      return data;
    } catch (err: any) {
      const errorMsg = err?.message || 'Network unreachable';
      console.warn('[Voice:STT] Transcription network request failed:', err);
      return { text: '', wake_detected: false, command: '', error: `STT Network Error: ${errorMsg}` };
    }
  }, []);

  // Cleanup audio hardware pipelines
  const cleanupAudio = useCallback(() => {
    if (scriptProcessorRef.current) {
      try { scriptProcessorRef.current.disconnect(); } catch {}
      scriptProcessorRef.current = null;
    }
    if (sourceNodeRef.current) {
      try { sourceNodeRef.current.disconnect(); } catch {}
      sourceNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (wakeListenDelayTimerRef.current) {
      clearTimeout(wakeListenDelayTimerRef.current);
      wakeListenDelayTimerRef.current = null;
    }
    wakePcmBufferRef.current = new Float32Array(0);
    activeSpeechChunksRef.current = [];
    wakeSpeechFramesRef.current = 0;
    wakeSilenceFramesRef.current = 0;
    wakeSpeechActiveRef.current = false;
    wakeCooldownUntilRef.current = 0;
    smoothedLevelRef.current = 0;
    setAudioLevel(0);
    setIsSpeaking(false);
  }, []);

  // Inspect the rolling PCM buffer for "Hey Nexus"
  const triggerWakeInspection = useCallback(async () => {
    if (wakeCheckInProgressRef.current || isListeningRef.current || !isWindowOpenRef.current) return;

    wakeCheckInProgressRef.current = true;

    try {
      // Short 100ms capture flush to ensure trailing phonemes are in the buffer
      await new Promise(r => setTimeout(r, 100));

      const ctx = audioContextRef.current;
      const rawPcm = wakePcmBufferRef.current;
      const minSamples = ctx ? Math.round(ctx.sampleRate * 0.5) : 8000;

      if (rawPcm.length >= minSamples && ctx) {
        // Compute RMS and peak amplitude across wake buffer
        let sumSquare = 0;
        let peakAbs = 0;
        for (let i = 0; i < rawPcm.length; i++) {
          const val = rawPcm[i];
          sumSquare += val * val;
          const abs = Math.abs(val);
          if (abs > peakAbs) peakAbs = abs;
        }
        const bufferRms = Math.sqrt(sumSquare / rawPcm.length);

        // Skip faint ambient noise or flat silence
        if (bufferRms < 0.012 || peakAbs < 0.032) {
          wakeCooldownUntilRef.current = Date.now() + 400;
          return;
        }

        const pcm16k = downsampleTo16k(rawPcm, ctx.sampleRate);
        const wavBlob = encodeWAV(pcm16k, 16000);

        if (wavBlob.size > 2000) {
          const res = await transcribeAudioBlob(wavBlob);
          // If Spotlight window was closed or hidden during transcription, discard immediately!
          if (!isWindowOpenRef.current) {
            console.log('[Voice:Wake] Spotlight window closed during inspection — discarding wake word');
            return;
          }
          if (res.wake_detected) {
            console.log('[Voice] Wake word confirmed! Payload:', res.command);
            setWakeWordDetected(true);
            setTimeout(() => setWakeWordDetected(false), 2500);

            // Immediately flush buffer and state
            wakePcmBufferRef.current = new Float32Array(0);
            wakeSpeechFramesRef.current = 0;
            wakeSilenceFramesRef.current = 0;
            wakeSpeechActiveRef.current = false;

            // Reveal spotlight window
            window.electronAPI?.wakeSpotlight?.();

            if (wakeListenDelayTimerRef.current) {
              clearTimeout(wakeListenDelayTimerRef.current);
              wakeListenDelayTimerRef.current = null;
            }

            const cleanCmd = (res.command || '').trim();
            // Substantial multi-word command uttered in the same breath (>= 3 chars)
            if (cleanCmd.length >= 3) {
              if (onTranscriptRef.current) onTranscriptRef.current(cleanCmd, true);
              if (autoSubmitRef.current && onSubmitRef.current) onSubmitRef.current(cleanCmd);
            } else {
              // The user called "Hey Nexus" while Spotlight is opened via shortcut.
              // Immediately start active listening for the user's command!
              wakeCooldownUntilRef.current = Date.now() + 400;
              activeSpeechChunksRef.current = [];
              currentSpeechTextRef.current = '';

              if (recognitionRef.current) {
                try {
                  recognitionRef.current.abort();
                } catch {}
              }

              startListeningRef.current();
            }
            return;
          } else {
            // Speech was detected but was not a wake phrase -> set short cooldown
            wakeCooldownUntilRef.current = Date.now() + 750;
          }
        }
      }
    } catch (err) {
      console.warn('[Voice:Wake] Wake inspection failed:', err);
      wakeCooldownUntilRef.current = Date.now() + 1000;
    } finally {
      wakeCheckInProgressRef.current = false;
    }
  }, [transcribeAudioBlob]);

  // Initialize microphone stream with Web Audio ScriptProcessor pipeline
  const initMicrophone = useCallback(async (targetDeviceId?: string) => {
    try {
      const activeId = targetDeviceId ?? selectedDeviceId;

      // Check track readiness, not just stream existence
      const existingStream = mediaStreamRef.current;
      if (existingStream && existingStream.active) {
        const tracks = existingStream.getAudioTracks();
        if (tracks.length > 0 && tracks[0].readyState === 'live') {
          const trackSettings = tracks[0].getSettings();
          if (!activeId || trackSettings.deviceId === activeId) {
            return existingStream;
          }
        }
        existingStream.getTracks().forEach(t => t.stop());
        mediaStreamRef.current = null;
      }

      const constraints: MediaStreamConstraints = {
        audio: activeId
          ? { deviceId: { exact: activeId }, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
          : { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      };

      console.log('[Voice:Mic] Initializing continuous audio pipeline with constraints:', constraints);
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      mediaStreamRef.current = stream;
      setVoiceError(null);

      updateDeviceList();

      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioCtx) {
        let ctx = audioContextRef.current;
        if (!ctx || ctx.state === 'closed') {
          ctx = new AudioCtx();
          audioContextRef.current = ctx;
        }
        if (ctx.state === 'suspended') {
          await ctx.resume();
        }

        // Clean up any previous script processor node
        if (scriptProcessorRef.current) {
          try { scriptProcessorRef.current.disconnect(); } catch {}
          scriptProcessorRef.current = null;
        }

        const source = ctx.createMediaStreamSource(stream);
        sourceNodeRef.current = source;

        // Buffer size 2048 gives ~46ms updates @ 44.1kHz (fast, real-time)
        const processor = ctx.createScriptProcessor(2048, 1, 1);
        scriptProcessorRef.current = processor;

        const maxBufferSamples = Math.round(ctx.sampleRate * 3.2); // 3.2s rolling buffer for wake word

        processor.onaudioprocess = (e) => {
          if (!isWindowOpenRef.current) return;
          const channelData = e.inputBuffer.getChannelData(0);

          // 1. If actively listening, accumulate PCM for user command
          if (isListeningRef.current) {
            activeSpeechChunksRef.current.push(new Float32Array(channelData));
          }

          // 2. Append to rolling PCM buffer for wake word
          const currentBuf = wakePcmBufferRef.current;
          const newLen = currentBuf.length + channelData.length;
          let combined = new Float32Array(newLen);
          combined.set(currentBuf);
          combined.set(channelData, currentBuf.length);

          if (combined.length > maxBufferSamples) {
            combined = combined.subarray(combined.length - maxBufferSamples);
          }
          wakePcmBufferRef.current = combined;

          // 3. Compute RMS volume energy
          let sum = 0;
          for (let i = 0; i < channelData.length; i++) {
            sum += channelData[i] * channelData[i];
          }
          const rms = Math.sqrt(sum / channelData.length);

          const rawLevel = Math.min(1.0, rms * 4.0);
          smoothedLevelRef.current = smoothedLevelRef.current * 0.7 + rawLevel * 0.3;
          setAudioLevel(smoothedLevelRef.current);

          // Adaptive background noise floor
          if (rms < 0.025) {
            ambientNoiseRef.current = ambientNoiseRef.current * 0.95 + rms * 0.05;
          }
          const dynamicThreshold = Math.max(0.016, ambientNoiseRef.current * 2.2);
          const speakingNow = rms > dynamicThreshold;
          setIsSpeaking(speakingNow);

          // 4. Active session silence timer
          if (isListeningRef.current) {
            if (speakingNow) {
              if (!speechDetectedRef.current) {
                speechDetectedRef.current = true;
                speechStartTimestampRef.current = Date.now();
              }
              if (silenceTimerRef.current) {
                clearTimeout(silenceTimerRef.current);
                silenceTimerRef.current = null;
              }
            } else if (speechDetectedRef.current && !silenceTimerRef.current && autoSubmitRef.current) {
              const speechDuration = Date.now() - speechStartTimestampRef.current;
              if (speechDuration > 500) {
                silenceTimerRef.current = setTimeout(() => {
                  if (isListeningRef.current) {
                    console.log('[Voice] Natural silence pause detected, finalizing transcription...');
                    stopListeningRef.current();
                  }
                }, silenceTimeoutMsRef.current);
              }
            }
          }

          // 5. Background Wake Word Detection with robust VAD
          if (!isListeningRef.current && wakeWordActiveRef.current && !wakeCheckInProgressRef.current) {
            const now = Date.now();
            if (now > wakeCooldownUntilRef.current) {
              if (speakingNow) {
                wakeSpeechFramesRef.current += 1;
                wakeSilenceFramesRef.current = 0;

                // User vocalizing for at least 3 frames (~140ms)
                if (wakeSpeechFramesRef.current >= 3 && !wakeSpeechActiveRef.current) {
                  wakeSpeechActiveRef.current = true;
                  wakeSpeechStartTsRef.current = now;
                }

                // Long uninterrupted utterance cap (2.4s)
                if (wakeSpeechActiveRef.current && (now - wakeSpeechStartTsRef.current >= 2400)) {
                  wakeSpeechActiveRef.current = false;
                  wakeSpeechFramesRef.current = 0;
                  wakeSilenceFramesRef.current = 0;
                  triggerWakeInspection();
                }
              } else {
                wakeSpeechFramesRef.current = Math.max(0, wakeSpeechFramesRef.current - 1);

                if (wakeSpeechActiveRef.current) {
                  wakeSilenceFramesRef.current += 1;
                  const speechDuration = now - wakeSpeechStartTsRef.current;

                  // User finished speaking phrase: pause detected (>= 7 frames silence after >= 300ms speech)
                  if (wakeSilenceFramesRef.current >= 7 && speechDuration >= 300) {
                    wakeSpeechActiveRef.current = false;
                    wakeSpeechFramesRef.current = 0;
                    wakeSilenceFramesRef.current = 0;
                    triggerWakeInspection();
                  }
                }
              }
            }
          }
        };

        source.connect(processor);
        // Connect to destination to ensure onaudioprocess continues firing in Web Audio engine
        processor.connect(ctx.destination);
      }
      return stream;
    } catch (err: any) {
      const errName = err?.name || '';
      let errorMsg = `Microphone error: ${err?.message || 'Access failed'}`;
      if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError') {
        errorMsg = 'Microphone permission denied by Windows/Browser';
      } else if (errName === 'NotFoundError' || errName === 'DevicesNotFoundError') {
        errorMsg = 'No audio input microphone detected';
      } else if (errName === 'NotReadableError' || errName === 'TrackStartError') {
        errorMsg = 'Microphone is already in use by another application';
      }
      console.error('[Voice:Mic] Microphone hardware access failed:', errorMsg, err);
      setVoiceError(errorMsg);
      return null;
    }
  }, [selectedDeviceId, updateDeviceList, triggerWakeInspection]);

  // Select a different microphone device ID
  const selectDevice = useCallback((deviceId: string) => {
    console.log('[Voice:Mic] Selecting audio input device:', deviceId);
    setSelectedDeviceId(deviceId);
    localStorage.setItem('nexus_selected_mic_device_id', deviceId);
    cleanupAudio();
    setTimeout(() => {
      initMicrophone(deviceId);
    }, 120);
  }, [cleanupAudio, initMicrophone]);

  // Stop listening and finalize transcript with Groq Whisper Turbo via WAV
  const stopListening = useCallback(async () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (maxSessionTimerRef.current) {
      clearTimeout(maxSessionTimerRef.current);
      maxSessionTimerRef.current = null;
    }
    if (wakeListenDelayTimerRef.current) {
      clearTimeout(wakeListenDelayTimerRef.current);
      wakeListenDelayTimerRef.current = null;
    }

    if (recognitionRef.current) {
      const r = recognitionRef.current;
      recognitionRef.current = null;
      try { r.stop(); } catch (err) {
        console.warn('[Voice:WebSpeech] Error stopping WebSpeech recognition:', err);
      }
    }

    if (!isListeningRef.current) return;
    isListeningRef.current = false;
    setIsListening(false);
    setIsTranscribing(true);

    try {
      const chunks = activeSpeechChunksRef.current;
      activeSpeechChunksRef.current = [];

      let totalLen = 0;
      for (const c of chunks) totalLen += c.length;

      const ctx = audioContextRef.current;
      let finalCommand = '';

      let sttError: string | null = null;

      // Primary: High-accuracy Groq Whisper Turbo via 16kHz WAV
      if (totalLen > 4000 && ctx) {
        const merged = new Float32Array(totalLen);
        let offset = 0;
        for (const c of chunks) {
          merged.set(c, offset);
          offset += c.length;
        }

        const pcm16k = downsampleTo16k(merged, ctx.sampleRate);
        const wavBlob = encodeWAV(pcm16k, 16000);

        if (wavBlob.size > 800) {
          const res = await transcribeAudioBlob(wavBlob);
          finalCommand = res.command || res.text || '';
          if (res.error) {
            sttError = res.error;
          }
        }
      }

      // Automatic Fallback: Google Web Speech API if Groq returned empty or failed
      if (!finalCommand && currentSpeechTextRef.current.trim()) {
        console.log('[Voice:STT] Auto-switching to Google Web Speech API fallback:', currentSpeechTextRef.current.trim());
        finalCommand = currentSpeechTextRef.current.trim();
        // Since Google Web Speech fallback succeeded, suppress Whisper network/HTTP error!
        sttError = null;
      }

      if (finalCommand) {
        setVoiceError(null);
        console.log('[Voice] Final command accepted:', finalCommand);
        if (onTranscriptRef.current) onTranscriptRef.current(finalCommand, true);
        if (autoSubmitRef.current && onSubmitRef.current) onSubmitRef.current(finalCommand);
      } else if (sttError) {
        // Only show error if BOTH Whisper and Google STT failed to produce text
        setVoiceError(sttError);
      }
    } catch (err) {
      console.error('[Voice] Error finalizing audio transcription, checking Google STT fallback:', err);
      if (currentSpeechTextRef.current.trim()) {
        const fallback = currentSpeechTextRef.current.trim();
        setVoiceError(null);
        console.log('[Voice:STT] Recovered using Google Web Speech fallback:', fallback);
        if (onTranscriptRef.current) onTranscriptRef.current(fallback, true);
        if (autoSubmitRef.current && onSubmitRef.current) onSubmitRef.current(fallback);
      } else {
        setVoiceError('Voice transcription failed');
      }
    } finally {
      setIsTranscribing(false);
      wakePcmBufferRef.current = new Float32Array(0);
      wakeSpeechFramesRef.current = 0;
      wakeSilenceFramesRef.current = 0;
      wakeSpeechActiveRef.current = false;
      wakeCooldownUntilRef.current = Date.now() + 500;
      wakeCheckInProgressRef.current = false;
    }
  }, [transcribeAudioBlob]);

  // Start active speech capture
  const startListening = useCallback(async () => {
    if (!enabled) return;

    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (maxSessionTimerRef.current) {
      clearTimeout(maxSessionTimerRef.current);
      maxSessionTimerRef.current = null;
    }

    currentSpeechTextRef.current = '';
    speechDetectedRef.current = false;
    speechStartTimestampRef.current = 0;
    activeSpeechChunksRef.current = [];

    setVoiceError(null);
    setIsListening(true);
    isListeningRef.current = true;
    setIsTranscribing(false);

    const stream = await initMicrophone();
    if (!stream) {
      setIsListening(false);
      isListeningRef.current = false;
      return;
    }

    // Auto-finalize after 15 seconds max duration safety cap
    maxSessionTimerRef.current = setTimeout(() => {
      if (isListeningRef.current) {
        console.log('[Voice] Maximum 15s session reached, stopping...');
        stopListening();
      }
    }, 15000);

    // Web Speech API for live interim display if available
    const SpeechRecClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecClass) {
      try {
        const recognition = new SpeechRecClass();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        recognition.onresult = (event: SpeechRecognitionEvent) => {
          let accumulated = '';
          for (let i = 0; i < event.results.length; ++i) {
            accumulated += event.results[i][0].transcript + ' ';
          }
          const trimmed = accumulated.trim();
          if (trimmed) {
            currentSpeechTextRef.current = trimmed;
            if (onTranscriptRef.current) onTranscriptRef.current(trimmed, false);

            if (silenceTimerRef.current) {
              clearTimeout(silenceTimerRef.current);
              silenceTimerRef.current = null;
            }

            if (autoSubmitRef.current) {
              silenceTimerRef.current = setTimeout(() => {
                if (isListeningRef.current) {
                  stopListening();
                }
              }, silenceTimeoutMsRef.current);
            }
          }
        };

        recognition.onerror = (e: any) => {
          console.warn('[Voice:WebSpeech] Speech recognition notice:', e.error, e.message || '');
          if (e.error === 'not-allowed') {
            setVoiceError('Microphone permission denied for speech recognition');
          }
        };

        recognition.onend = () => {
          if (isListeningRef.current && recognitionRef.current === recognition) {
            try { recognition.start(); } catch (err) {
              console.warn('[Voice:WebSpeech] Restart failed:', err);
            }
          }
        };

        recognition.start();
        recognitionRef.current = recognition;
      } catch (err) {
        console.error('[Voice:WebSpeech] Failed to initialize WebSpeech recognition:', err);
      }
    }
  }, [enabled, initMicrophone, stopListening]);

  stopListeningRef.current = stopListening;
  startListeningRef.current = startListening;

  const toggleListening = useCallback(() => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  }, [isListening, startListening, stopListening]);

  // Synchronize window open/hidden lifecycle so voice & Hey Nexus ONLY run when Spotlight is opened via shortcut
  useEffect(() => {
    const handleShow = () => {
      console.log('[Voice] Spotlight opened via shortcut — activating voice & Hey Nexus');
      setIsWindowOpen(true);
      isWindowOpenRef.current = true;
    };

    const handleHide = () => {
      console.log('[Voice] Spotlight closed/hidden — deactivating voice & Hey Nexus, releasing mic');
      setIsWindowOpen(false);
      isWindowOpenRef.current = false;
      if (isListeningRef.current) {
        stopListeningRef.current();
      }
      cleanupAudio();
    };

    const unsubShow = window.electronAPI?.onWindowShow?.(handleShow);
    const unsubHide = window.electronAPI?.onWindowHide?.(handleHide);
    const unsubBlur = window.electronAPI?.onWindowBlur?.(handleHide);

    const handleVisibilityChange = () => {
      if (document.hidden) {
        handleHide();
      } else if (!window.electronAPI) {
        handleShow();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      if (unsubShow) unsubShow();
      if (unsubHide) unsubHide();
      if (unsubBlur) unsubBlur();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [cleanupAudio]);

  // Manage background wake word loop — ONLY active when Spotlight is opened via shortcut and visible
  useEffect(() => {
    if (!enabled || !wakeWordEnabled || !isWindowOpen) {
      wakeWordActiveRef.current = false;
      if (isListeningRef.current) {
        stopListening();
      }
      cleanupAudio();
      return;
    }

    wakeWordActiveRef.current = true;
    initMicrophone();

    return () => {
      wakeWordActiveRef.current = false;
      cleanupAudio();
    };
  }, [enabled, wakeWordEnabled, isWindowOpen, initMicrophone, stopListening, cleanupAudio]);

  // IPC listener for spotlight voice trigger from Electron
  useEffect(() => {
    const cleanup = window.electronAPI?.onVoiceStartCapture?.(() => {
      startListening();
    });
    return () => {
      if (cleanup) cleanup();
    };
  }, [startListening]);

  // Cleanup on component unmount
  useEffect(() => {
    return () => {
      cleanupAudio();
    };
  }, [cleanupAudio]);

  return {
    isListening,
    isSpeaking,
    isTranscribing,
    audioLevel,
    wakeWordDetected,
    voiceError,
    clearVoiceError: () => setVoiceError(null),
    devices,
    selectedDeviceId,
    selectDevice,
    startListening,
    stopListening,
    toggleListening,
  };
}
