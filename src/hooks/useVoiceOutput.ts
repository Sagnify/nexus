import { useState, useRef, useCallback, useEffect } from 'react';
import { cleanSpokenSentence } from '../utils/speechUtils';

const BACKEND_URL = 'http://127.0.0.1:8000';

export interface VoiceOption {
  id: string;
  name: string;
  gender: string;
  locale: string;
  style: string;
}

export const DEFAULT_CURATED_VOICES: VoiceOption[] = [
  {
    id: 'en-US-AriaNeural',
    name: 'Aria',
    gender: 'Female',
    locale: 'en-US',
    style: 'Warm, expressive & natural (Default)',
  },
  {
    id: 'en-US-GuyNeural',
    name: 'Guy',
    gender: 'Male',
    locale: 'en-US',
    style: 'Relaxed, clear & conversational',
  },
  {
    id: 'en-US-JennyMultilingualNeural',
    name: 'Jenny',
    gender: 'Female',
    locale: 'en-US',
    style: 'Friendly, modern & versatile',
  },
  {
    id: 'en-US-ChristopherNeural',
    name: 'Christopher',
    gender: 'Male',
    locale: 'en-US',
    style: 'Authoritative & smooth',
  },
  {
    id: 'en-GB-SoniaNeural',
    name: 'Sonia',
    gender: 'Female',
    locale: 'en-GB',
    style: 'British warm conversational',
  },
  {
    id: 'en-GB-BrianNeural',
    name: 'Brian',
    gender: 'Male',
    locale: 'en-GB',
    style: 'British natural conversational',
  },
  {
    id: 'en-IN-NeerjaNeural',
    name: 'Neerja',
    gender: 'Female',
    locale: 'en-IN',
    style: 'Indian English natural',
  },
  {
    id: 'en-AU-NatashaNeural',
    name: 'Natasha',
    gender: 'Female',
    locale: 'en-AU',
    style: 'Australian conversational',
  },
];

interface UseVoiceOutputProps {
  defaultVoice?: string;
  defaultSpeed?: string;
}

export function useVoiceOutput({
  defaultVoice = 'en-US-AriaNeural',
  defaultSpeed = '1.0x',
}: UseVoiceOutputProps = {}) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentText, setCurrentText] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const stopSpeaking = useCallback(() => {
    // Abort pending fetch request if in progress
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // Stop HTML5 audio player
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute('src');
      audioRef.current.load();
      audioRef.current = null;
    }

    // Revoke object URL
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }

    // Cancel browser fallback synthesis
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    setIsSpeaking(false);
    setCurrentText(null);
  }, []);

  const speak = useCallback(
    async (
      text: string,
      voiceOverride?: string,
      speedOverride?: string
    ): Promise<boolean> => {
      const clean = (cleanSpokenSentence(text) || text || '').trim();
      if (!clean) return false;

      // Always stop previous speech before playing new
      stopSpeaking();

      const voice = voiceOverride || defaultVoice || 'en-US-AriaNeural';
      const speed = speedOverride || defaultSpeed || '1.0x';

      // Convert speed to edge-tts rate parameter (e.g., '1.0x' -> '+0%', '1.2x' -> '+20%', '0.9x' -> '-10%')
      let rateStr = '+0%';
      const speedNum = parseFloat(speed.replace('x', ''));
      if (!isNaN(speedNum) && speedNum !== 1.0) {
        const pct = Math.round((speedNum - 1.0) * 100);
        rateStr = pct >= 0 ? `+${pct}%` : `${pct}%`;
      }

      setIsSpeaking(true);
      setCurrentText(clean);

      try {
        const controller = new AbortController();
        abortControllerRef.current = controller;

        const res = await fetch(`${BACKEND_URL}/api/nexus/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: clean,
            voice,
            rate: rateStr,
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          throw new Error(`TTS server returned status ${res.status}`);
        }

        const blob = await res.blob();
        if (blob.size < 100) {
          throw new Error('TTS audio blob too small');
        }

        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;

        const audio = new Audio(url);
        audioRef.current = audio;

        return new Promise<boolean>((resolve) => {
          audio.onended = () => {
            stopSpeaking();
            resolve(true);
          };

          audio.onerror = () => {
            console.warn('[Voice:TTS] Audio playback error, falling back to Web Speech synthesis');
            stopSpeaking();
            // Fallback to browser Web Speech API
            fallbackBrowserSpeech(clean, resolve);
          };

          audio.play().catch((err) => {
            console.warn('[Voice:TTS] Playback prevented or interrupted:', err);
            stopSpeaking();
            resolve(false);
          });
        });
      } catch (err: any) {
        if (err.name === 'AbortError') {
          return false;
        }
        console.warn('[Voice:TTS] Backend TTS failed, using browser Web Speech fallback:', err);
        return new Promise<boolean>((resolve) => {
          fallbackBrowserSpeech(clean, resolve);
        });
      }
    },
    [defaultVoice, defaultSpeed, stopSpeaking]
  );

  const fallbackBrowserSpeech = (text: string, onDone: (success: boolean) => void) => {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      setIsSpeaking(false);
      onDone(false);
      return;
    }

    try {
      window.speechSynthesis.cancel();
      // Remove basic markdown syntax for cleaner utterance
      const sanitized = (cleanSpokenSentence(text) || text || '').trim();

      const utterance = new SpeechSynthesisUtterance(sanitized);
      utterance.rate = 1.0;
      utterance.pitch = 1.0;

      utterance.onend = () => {
        setIsSpeaking(false);
        setCurrentText(null);
        onDone(true);
      };

      utterance.onerror = () => {
        setIsSpeaking(false);
        setCurrentText(null);
        onDone(false);
      };

      setIsSpeaking(true);
      window.speechSynthesis.speak(utterance);
    } catch {
      setIsSpeaking(false);
      onDone(false);
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopSpeaking();
    };
  }, [stopSpeaking]);

  return {
    speak,
    stopSpeaking,
    isSpeaking,
    currentText,
  };
}
