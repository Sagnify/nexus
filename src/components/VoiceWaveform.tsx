import React, { useEffect, useState } from 'react';

interface VoiceWaveformProps {
  isListening?: boolean;
  isSpeaking: boolean;
  isTranscribing: boolean;
  audioLevel: number; // 0.0 to 1.0
  onStop?: () => void;
}

export const VoiceWaveform: React.FC<VoiceWaveformProps> = ({
  isSpeaking,
  isTranscribing,
  audioLevel,
  onStop,
}) => {
  const [tick, setTick] = useState(0);

  // Smooth 60fps tick for continuous fluid sine wave animation
  useEffect(() => {
    let animId: number;
    const update = () => {
      setTick((t) => (t + 1) % 3600);
      animId = requestAnimationFrame(update);
    };
    animId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(animId);
  }, []);

  // 5 elegant equalizer bars with staggered wave phases and vibrant gradient colors
  const bars = [
    { phase: 0.0, weight: 0.65, color: 'from-cyan-400 to-sky-500' },
    { phase: 1.2, weight: 0.90, color: 'from-cyan-300 via-sky-400 to-indigo-500' },
    { phase: 2.4, weight: 1.00, color: 'from-sky-400 via-indigo-500 to-purple-500' },
    { phase: 3.6, weight: 0.90, color: 'from-indigo-400 via-purple-500 to-fuchsia-400' },
    { phase: 4.8, weight: 0.65, color: 'from-purple-400 to-cyan-400' },
  ];

  return (
    <div
      onClick={onStop}
      className="flex items-center gap-[2.5px] h-6 px-2 rounded-full bg-cyan-500/[0.08] hover:bg-cyan-500/[0.14] border border-cyan-400/25 hover:border-cyan-400/40 shadow-[0_0_12px_rgba(56,189,248,0.2)] flex-shrink-0 select-none animate-fadeIn cursor-pointer transition-colors"
      title="Listening to your microphone... Click or press Enter to submit"
    >
      {bars.map((bar, i) => {
        // Continuous organic wave oscillation
        const wave = Math.sin((tick * 0.08) + bar.phase);
        
        let height: number;
        if (isTranscribing) {
          // Shimmering wave when processing
          height = 6 + Math.sin((tick * 0.16) + bar.phase) * 5;
        } else if (isSpeaking || audioLevel > 0.04) {
          // Dynamic voice response: reactive height that pulses with audio level
          const base = 5;
          const dynamicAmp = audioLevel * bar.weight * 16;
          const organicMotion = (wave * 0.5 + 0.5) * 6;
          height = Math.min(20, Math.max(4, base + dynamicAmp + organicMotion));
        } else {
          // Idle breathing wave when silent
          height = 4 + (wave * 0.5 + 0.5) * 4;
        }

        return (
          <div
            key={i}
            className={`w-[2.5px] rounded-full bg-gradient-to-t ${bar.color} transition-all duration-75`}
            style={{
              height: `${Math.round(height)}px`,
              boxShadow: isSpeaking
                ? '0 0 6px rgba(56,189,248,0.8)'
                : '0 0 3px rgba(56,189,248,0.35)',
            }}
          />
        );
      })}
    </div>
  );
};
