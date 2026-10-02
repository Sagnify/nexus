import React, { useRef, useState, useEffect, useCallback } from 'react';
import { X, Settings as SettingsIcon, Mic, ChevronDown, Check, History, AlertCircle, Volume2, User, LogIn, LogOut, GraduationCap, BookOpen, Zap, CalendarClock, Blocks, ChevronRight } from 'lucide-react';
import { SpotlightMode } from './ModePills';
import { useVoiceInput } from '../hooks/useVoiceInput';
import { TargetSelector } from './TargetSelector';
import { useAuth } from '../context/AuthContext';
import { VoiceWaveform } from './VoiceWaveform';
import { useSkills } from '../hooks/useSkills';
import { UserAvatar } from './UserAvatar';
import nexusLogo from '../assets/nexus-logo.png';
import { NexusLogoMedia } from './NexusLogoMedia';

interface SpotlightBarProps {
  query: string;
  setQuery: (query: string) => void;
  onRawInputChange?: (typedText: string) => void;
  onArrowDown?: () => boolean;
  onArrowUp?: () => boolean;
  onEscape?: () => boolean;
  onTargetChange?: (target: any, context?: any) => void;
  mode: SpotlightMode;
  onSubmit: (query: string, isVoice?: boolean) => void;
  onClear: () => void;
  isLoading?: boolean;
  onToggleSettings?: () => void;
  isSettingsOpen?: boolean;
  onToggleHistory?: () => void;
  isHistoryOpen?: boolean;
  onToggleSkills?: (initialTab?: 'library' | 'teach') => void;
  isSkillsOpen?: boolean;
  onToggleSchedule?: () => void;
  isScheduleOpen?: boolean;
  onToggleConnectors?: () => void;
  isConnectorsOpen?: boolean;
  voiceEnabled?: boolean;
  wakeWordEnabled?: boolean;
  autoSubmitVoice?: boolean;
  onInterruptSpeech?: () => void;
  onOpenAuthModal?: () => void;
  isAgentActive?: boolean;
  isInputDisabled?: boolean;
  disabledReason?: string;
}

export const SpotlightBar: React.FC<SpotlightBarProps> = ({
  query,
  setQuery,
  onRawInputChange,
  onArrowDown,
  onArrowUp,
  onEscape,
  onTargetChange,
  mode,
  onSubmit,
  onClear,
  isLoading = false,
  onToggleSettings,
  isSettingsOpen = false,
  onToggleHistory,
  isHistoryOpen = false,
  onToggleSkills,
  isSkillsOpen = false,
  onToggleSchedule,
  isScheduleOpen = false,
  onToggleConnectors,
  isConnectorsOpen = false,
  voiceEnabled = true,
  wakeWordEnabled = true,
  autoSubmitVoice = true,
  onInterruptSpeech,
  onOpenAuthModal,
  isAgentActive = false,
  isInputDisabled = false,
  disabledReason = '',
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const [isMicMenuOpen, setIsMicMenuOpen] = useState(false);
  const micMenuRef = useRef<HTMLDivElement>(null);
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  const { user, dbUser, logout, isGuest } = useAuth();
  const { teachMode, skills } = useSkills();

  // ── Inline skill hint matcher ──────────────────────────────────────
  // Performs fast client-side token overlap match against loaded skills.
  const [skillHint, setSkillHint] = useState<{ name: string; id: string } | null>(null);

  const computeSkillHint = useCallback(
    (q: string) => {
      if (!q || q.trim().length < 3 || isLoading || isAgentActive || !skills?.length) {
        setSkillHint(null);
        return;
      }
      const qNorm = q.toLowerCase().trim().replace(/[^a-z0-9\s]/g, '');
      const qTokens = new Set(qNorm.split(/\s+/).filter(Boolean));
      let best: { name: string; id: string; score: number } | null = null;

      for (const skill of skills) {
        if (!skill.is_active || skill.health_status === 'suspended') continue;
        if (skill.name.toLowerCase().trim() === q.toLowerCase().trim()) continue;
        const candidates = [
          skill.name,
          ...(skill.trigger_phrases || []),
        ];
        for (const cand of candidates) {
          if (cand.toLowerCase().trim() === q.toLowerCase().trim()) continue;
          const cNorm = cand.toLowerCase().replace(/[^a-z0-9\s]/g, '');
          const cTokens = new Set(cNorm.split(/\s+/).filter(Boolean));
          if (!cTokens.size) continue;
          let overlap = 0;
          for (const t of qTokens) { if (cTokens.has(t)) overlap++; }
          const score = overlap / cTokens.size;
          if (score >= 0.60 && (!best || score > best.score)) {
            best = { name: skill.name, id: skill.id, score };
          }
        }
      }
      setSkillHint(best ? { name: best.name, id: best.id } : null);
    },
    [skills, isLoading, isAgentActive]
  );

  // Debounce skill hint to avoid jitter while typing
  useEffect(() => {
    const t = setTimeout(() => computeSkillHint(query), 300);
    return () => clearTimeout(t);
  }, [query, computeSkillHint]);

  // Clear hint when loading starts or query clears or agent is active
  useEffect(() => {
    if (isLoading || isAgentActive || !query.trim()) setSkillHint(null);
  }, [isLoading, isAgentActive, query]);
  // ── End skill hint ─────────────────────────────────────────────────

  const {
    isListening,
    isSpeaking,
    isTranscribing,
    audioLevel,
    voiceError,
    clearVoiceError,
    devices,
    selectedDeviceId,
    selectDevice,
    toggleListening,
    stopListening,
  } = useVoiceInput({
    enabled: voiceEnabled && !isLoading && !isInputDisabled && !teachMode.isTeaching && !teachMode.isCompilingDraft,
    wakeWordEnabled: wakeWordEnabled && !isLoading && !isInputDisabled && !teachMode.isTeaching && !teachMode.isCompilingDraft,
    autoSubmit: autoSubmitVoice,
    onTranscript: (spokenText) => {
      if (!isInputDisabled) setQuery(spokenText);
    },
    onSubmit: (finalText) => {
      if (!isInputDisabled && finalText.trim()) {
        onSubmit(finalText, true);
      }
    },
  });

  // Interrupt TTS when user speaks
  useEffect(() => {
    if (isListening) {
      onInterruptSpeech?.();
    }
  }, [isListening, onInterruptSpeech]);

  // Close mic dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (micMenuRef.current && !micMenuRef.current.contains(e.target as Node)) {
        setIsMicMenuOpen(false);
      }
    };
    if (isMicMenuOpen) {
      window.addEventListener('mousedown', handleClickOutside);
    }
    return () => window.removeEventListener('mousedown', handleClickOutside);
  }, [isMicMenuOpen]);

  // Close profile dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setIsProfileMenuOpen(false);
      }
    };
    if (isProfileMenuOpen) {
      window.addEventListener('mousedown', handleClickOutside);
    }
    return () => window.removeEventListener('mousedown', handleClickOutside);
  }, [isProfileMenuOpen]);

  const focus = useCallback(() => {
    if (!isInputDisabled) {
      inputRef.current?.focus();
    }
  }, [isInputDisabled]);

  useEffect(() => { focus(); }, [focus]);

  useEffect(() => {
    const cleanup = window.electronAPI?.onWindowShow(() => {
      setTimeout(focus, 60);
    });
    return cleanup;
  }, [focus]);

  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if (isInputDisabled) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'm') {
        e.preventDefault();
        toggleListening();
        return;
      }
      if (
        e.metaKey || e.ctrlKey || e.altKey ||
        e.key === 'Escape' || e.key === 'Tab' ||
        e.key === 'ArrowUp' || e.key === 'ArrowDown' ||
        e.key === 'Enter' || e.key === 'Shift' ||
        e.key.startsWith('F') ||
        document.activeElement === inputRef.current
      ) return;
      // Don't steal focus if the user is already typing in another interactive element
      const active = document.activeElement;
      if (
        active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        (active instanceof HTMLElement && active.isContentEditable)
      ) return;
      if (e.key.length === 1) inputRef.current?.focus();
    };
    window.addEventListener('keydown', handleGlobalKey);
    return () => window.removeEventListener('keydown', handleGlobalKey);
  }, []);

  const getPlaceholder = () => {
    if (isLoading) return 'NEXUS is working on it…';
    if (isTranscribing) return 'Processing your voice…';
    if (isListening) return isSpeaking ? 'Transcribing…' : 'Listening… speak naturally';
    switch (mode) {
      case 'all':   return 'Search, ask AI, or say "Hey Nexus"…';
      case 'apps':  return 'Search applications…';
      case 'files': return 'Search files and folders…';
      case 'ai':    return 'Ask NEXUS anything…';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (isLoading || isInputDisabled) {
      e.preventDefault();
      return;
    }
    if (e.key === 'ArrowDown') {
      if (onArrowDown?.()) {
        e.preventDefault();
        e.stopPropagation();
        requestAnimationFrame(() => {
          if (inputRef.current) {
            const len = inputRef.current.value.length;
            inputRef.current.setSelectionRange(len, len);
          }
        });
        return;
      }
    } else if (e.key === 'ArrowUp') {
      if (onArrowUp?.()) {
        e.preventDefault();
        e.stopPropagation();
        requestAnimationFrame(() => {
          if (inputRef.current) {
            const len = inputRef.current.value.length;
            inputRef.current.setSelectionRange(len, len);
          }
        });
        return;
      }
    } else if (e.key === 'Escape') {
      if (isListening) {
        stopListening();
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (onEscape?.()) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (isListening) stopListening();
      onSubmit(query, false);
    }
  };

  const Divider = () => (
    <div className="w-px h-4 flex-shrink-0" style={{ background: 'rgba(255,255,255,0.08)' }} />
  );

  return (
    <div
      className={`relative flex items-center gap-2 transition-all duration-200 ${
        isListening
          ? 'bg-sky-950/25 shadow-[0_0_30px_rgba(56,189,248,0.12)]'
          : isFocused
          ? 'bg-white/[0.015]'
          : ''
      }`}
      style={{ height: 52, padding: '0 12px 0 14px' }}
    >
      {/* Subtle top edge accent glow when focused or listening */}
      {(isFocused || isListening) && (
        <div
          className="absolute top-0 left-6 right-6 h-[1px] transition-all duration-300 pointer-events-none rounded-full"
          style={{
            background: isListening
              ? 'linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.75), rgba(99, 102, 241, 0.75), transparent)'
              : 'linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.45), transparent)',
            boxShadow: isListening ? `0 0 ${10 + audioLevel * 18}px rgba(56, 189, 248, 0.65)` : 'none',
          }}
        />
      )}

      {/* Animated top-bar loading indicator */}
      {isLoading && (
        <div className="absolute bottom-0 left-0 right-0 h-[1.5px] overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
          <div
            className="h-full"
            style={{
              width: '30%',
              background: 'linear-gradient(90deg, transparent, rgba(110,231,247,0.8), transparent)',
              animation: 'slide 1.3s ease-in-out infinite',
            }}
          />
        </div>
      )}

      {/* Left brand / state icon with Authentic Nexus 3D Animated Ribbon */}
      <div className="flex items-center justify-center w-7 h-7 flex-shrink-0">
        {isListening ? (
          <Mic className="w-5 h-5 text-cyan-400 animate-pulse flex-shrink-0 drop-shadow-[0_0_6px_rgba(56,189,248,0.8)]" strokeWidth={2.2} />
        ) : (
          <NexusLogoMedia
            type="video"
            className="w-7 h-7 group cursor-pointer"
            mediaClassName="transition-transform duration-200 ease-out group-hover:scale-105 active:scale-95"
            title={isLoading ? "NEXUS Thinking..." : isTranscribing ? "Transcribing..." : undefined}
          />
        )}
      </div>

      {/* Active Target Dropdown Selector (hide on dedicated management pages) */}
      {!isInputDisabled && <TargetSelector hideIfGeneral={isAgentActive} onTargetChange={onTargetChange} />}

      {/* Voice Error Badge */}
      {voiceError && !isListening && (
        <div
          title={`Audio/STT Warning: ${voiceError}\nClick to dismiss`}
          onClick={clearVoiceError}
          className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium flex-shrink-0 cursor-pointer transition-all"
          style={{
            background: 'rgba(239,68,68,0.14)',
            color: 'rgba(252,165,165,0.9)',
            border: '1px solid rgba(239,68,68,0.28)',
          }}
        >
          <AlertCircle className="w-2.5 h-2.5 flex-shrink-0" />
          <span className="max-w-[100px] truncate">{voiceError}</span>
        </div>
      )}

      {/* Input field or Disabled Breadcrumb Badge */}
      {isInputDisabled ? (
        <div className="flex-1 flex items-center gap-2 select-none min-w-0">
          <span className="text-[12px] font-medium text-white/40 tracking-wide truncate">
            {disabledReason || 'Management Page'}
          </span>
        </div>
      ) : (
        <input
          ref={inputRef}
          type="text"
          disabled={isLoading}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            onRawInputChange?.(e.target.value);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={getPlaceholder()}
          className={`flex-1 bg-transparent border-none outline-none text-[14.5px] font-normal transition-all ${
            isLoading
              ? 'opacity-50 cursor-not-allowed select-none'
              : isListening
              ? 'text-cyan-100 placeholder-cyan-300/40'
              : 'placeholder-white/25'
          }`}
          style={{
            color: isLoading ? 'rgba(255,255,255,0.45)' : isListening ? '#e0f2fe' : 'rgba(255,255,255,0.90)',
            caretColor: isLoading ? 'transparent' : isListening ? '#38bdf8' : '#38bdf8',
            letterSpacing: '-0.01em',
          }}
          autoComplete="off"
          spellCheck="false"
          autoFocus
        />
      )}

      {/* Real-time moving waveform visualizer */}
      {(isListening || isTranscribing) && (
        <VoiceWaveform
          isListening={isListening}
          isSpeaking={isSpeaking}
          isTranscribing={isTranscribing}
          audioLevel={audioLevel}
          onStop={stopListening}
        />
      )}

      {/* Matched Skill Pill — placed cleanly on the right so input never jumps or duplicates */}
      {skillHint && !isInputDisabled && !isAgentActive && !isLoading && !isListening && !isTranscribing && query.trim().length >= 3 && (
        <button
          type="button"
          onClick={() => {
            setQuery(skillHint.name);
            onSubmit(skillHint.name, false);
          }}
          title={`Run matched skill: ${skillHint.name} (Enter)`}
          className="flex items-center gap-1.5 flex-shrink-0 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all duration-200 group bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/25 hover:border-indigo-500/45 text-indigo-300 shadow-sm"
        >
          <Zap className="w-3 h-3 text-indigo-400 flex-shrink-0" strokeWidth={2.2} />
          <span className="max-w-[130px] truncate">{skillHint.name}</span>
          <span className="text-[10px] text-indigo-400/60 font-mono">↵</span>
        </button>
      )}

      {/* Right actions — icon-only buttons */}
      <div className="flex items-center gap-1 flex-shrink-0">

        {/* Return hint — only show when query has text, not loading/listening, and no active agent task */}
        {!isInputDisabled && !isLoading && !isListening && !isTranscribing && query.trim().length > 0 && !isAgentActive && (
          <kbd
            className="flex items-center gap-0.5 px-1.5 h-5 rounded-md text-[10px] font-medium select-none flex-shrink-0"
            style={{
              color: 'rgba(255,255,255,0.28)',
              border: '1px solid rgba(255,255,255,0.09)',
              background: 'rgba(255,255,255,0.04)',
            }}
          >
            ↵
          </kbd>
        )}

        {/* Clear button */}
        {!isInputDisabled && !isLoading && !isListening && !isTranscribing && query.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="icon-btn"
            title="Clear"
          >
            <X className="w-3.5 h-3.5" strokeWidth={2.2} />
          </button>
        )}

        {!isInputDisabled && <Divider />}

        {/* Voice input mic button + device selector (hidden on dedicated management pages) */}
        {voiceEnabled && !isInputDisabled && (
          <div className="relative flex items-center" ref={micMenuRef}>
            <div
              className={`flex items-center rounded-lg overflow-hidden ${
                isListening
                  ? 'ring-1 ring-cyan-400/40'
                  : ''
              }`}
              style={{
                background: isListening ? 'rgba(56,189,248,0.12)' : 'transparent',
              }}
            >
              {/* Mic toggle button */}
              <button
                type="button"
                disabled={isLoading || isInputDisabled}
                onClick={(isLoading || isInputDisabled) ? undefined : toggleListening}
                title={
                  isInputDisabled
                    ? (disabledReason || 'Voice input disabled on this page')
                    : isLoading
                    ? 'NEXUS is busy'
                    : isListening
                    ? 'Stop listening (Ctrl+M)'
                    : wakeWordEnabled
                    ? 'Click or say "Hey Nexus" (Ctrl+M)'
                    : 'Click to start voice input (Ctrl+M)'
                }
                className={`icon-btn ${
                  (isLoading || isInputDisabled)
                    ? 'opacity-30 cursor-not-allowed pointer-events-none'
                    : isListening
                    ? 'active-accent'
                    : ''
                }`}
                style={{ borderRadius: '6px 0 0 6px', width: 26, height: 26 }}
              >
                <Mic
                  className="w-3.5 h-3.5"
                  strokeWidth={isListening ? 2.2 : 1.8}
                  style={{ color: isListening ? '#38bdf8' : 'inherit' }}
                />
              </button>

              {/* Mic device selector dropdown arrow */}
              <button
                type="button"
                disabled={isLoading || isInputDisabled}
                onClick={(isLoading || isInputDisabled) ? undefined : () => setIsMicMenuOpen(prev => !prev)}
                title={isInputDisabled ? (disabledReason || 'Voice input disabled on this page') : 'Select microphone'}
                className={`flex items-center justify-center h-[26px] w-[16px] transition-all ${
                  (isLoading || isInputDisabled)
                    ? 'opacity-30 cursor-not-allowed pointer-events-none text-neutral-500'
                    : isListening
                    ? 'text-cyan-300/70'
                    : isMicMenuOpen
                    ? 'text-white/60'
                    : 'text-white/20 hover:text-white/50'
                }`}
                style={{ borderLeft: '1px solid rgba(255,255,255,0.07)', borderRadius: '0 6px 6px 0' }}
              >
                <ChevronDown
                  className={`w-2.5 h-2.5 transition-transform duration-150 ${isMicMenuOpen ? 'rotate-180' : ''}`}
                />
              </button>
            </div>

            {/* Mic device picker dropdown */}
            {isMicMenuOpen && (
              <div
                className="absolute right-0 top-full mt-2 w-60 rounded-xl overflow-hidden z-50"
                style={{
                  background: 'rgba(13,14,20,0.97)',
                  backdropFilter: 'blur(40px)',
                  border: '1px solid rgba(255,255,255,0.10)',
                  boxShadow: '0 16px 40px rgba(0,0,0,0.6), 0 0 0 0.5px rgba(255,255,255,0.05)',
                  animation: 'fadeSlideDown 0.14s ease-out forwards',
                }}
              >
                <div
                  className="flex items-center gap-1.5 px-3 py-2.5"
                  style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}
                >
                  <Volume2 className="w-3 h-3 text-white/30" strokeWidth={2} />
                  <span className="text-[10px] font-semibold text-white/35 uppercase tracking-wider">
                    Audio Input ({devices.length})
                  </span>
                </div>
                <div className="max-h-44 overflow-y-auto p-1">
                  {devices.length === 0 ? (
                    <div className="px-2.5 py-2 text-[11px] text-white/35">Default Microphone</div>
                  ) : (
                    devices.map((d, idx) => {
                      const isSel = d.deviceId === selectedDeviceId || (!selectedDeviceId && idx === 0);
                      return (
                        <button
                          key={d.deviceId || idx}
                          type="button"
                          onClick={() => { selectDevice(d.deviceId); setIsMicMenuOpen(false); }}
                          className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left text-[11px] transition-colors"
                          style={{
                            background: isSel ? 'rgba(56,189,248,0.12)' : 'transparent',
                            color: isSel ? '#6ee7f7' : 'rgba(255,255,255,0.55)',
                          }}
                          onMouseEnter={e => !isSel && (e.currentTarget.style.background = 'rgba(255,255,255,0.06)')}
                          onMouseLeave={e => !isSel && (e.currentTarget.style.background = 'transparent')}
                        >
                          <span className="truncate pr-2">{d.label || `Microphone ${idx + 1}`}</span>
                          {isSel && <Check className="w-3 h-3 text-cyan-400 flex-shrink-0" />}
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Teach NEXUS Skill Learning button (Authenticated non-guest only) */}
        {!isGuest && user && (
          <button
            type="button"
            onClick={() => onToggleSkills?.(teachMode.isTeaching ? 'teach' : 'library')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
              teachMode.isTeaching
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                : isSkillsOpen
                ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
                : 'text-indigo-300/80 hover:text-indigo-200 hover:bg-indigo-500/10'
            }`}
            title={teachMode.isTeaching ? 'View live recording session' : 'Teach NEXUS: Demonstrate a reusable workflow'}
          >
            {teachMode.isTeaching ? (
              <>
                <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                <span className="text-[11px] font-semibold text-rose-300">Recording</span>
              </>
            ) : (
              <>
                <GraduationCap className="w-3.5 h-3.5 text-indigo-400" strokeWidth={1.8} />
                <span className="text-[11px] hidden sm:inline">Teach</span>
              </>
            )}
          </button>
        )}

        {/* History button */}
        {onToggleHistory && (
          <button
            type="button"
            onClick={onToggleHistory}
            className={`icon-btn ${isHistoryOpen ? 'active-accent' : ''}`}
            title="History"
          >
            <History className="w-3.5 h-3.5" strokeWidth={1.8} />
          </button>
        )}

        {/* Profile & Settings Menu */}
        <div className="relative" ref={profileMenuRef}>
          {user ? (
            /* Logged in: Profile Avatar Button */
            <button
              type="button"
              onClick={() => setIsProfileMenuOpen(prev => !prev)}
              className={`relative flex items-center justify-center p-0.5 rounded-full transition-all duration-150 focus:outline-none ${
                isProfileMenuOpen || isSettingsOpen
                  ? 'ring-1.5 ring-sky-400'
                  : 'hover:ring-1.5 hover:ring-white/30'
              }`}
              title={`${user.displayName || user.email || 'Profile'} - Settings & Account`}
            >
              <UserAvatar
                src={user.photoURL || dbUser?.profile_image_url}
                name={dbUser?.display_name || user.displayName}
                email={user.email}
                size={22}
              />
              {/* Online status dot */}
              <span className="absolute -bottom-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-emerald-400 ring-2 ring-[#0d0e12]" />
            </button>
          ) : (
            /* Logged out: Log In Button with dropdown indicator */
            <button
              type="button"
              onClick={() => setIsProfileMenuOpen(prev => !prev)}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-normal transition-all duration-150 border ${
                isProfileMenuOpen || isSettingsOpen
                  ? 'bg-white/10 text-white border-white/20'
                  : 'bg-white/[0.03] text-white/70 border-white/[0.07] hover:bg-white/[0.07] hover:text-white'
              }`}
              title="Account & Settings"
            >
              <User className="w-3.5 h-3.5 text-sky-400" />
              <span>Log In</span>
              <ChevronDown
                className={`w-3 h-3 text-white/35 transition-transform duration-150 ${
                  isProfileMenuOpen ? 'rotate-180' : ''
                }`}
              />
            </button>
          )}

          {/* Profile / Settings Dropdown */}
          {isProfileMenuOpen && (
            <div
              className="absolute right-0 top-full mt-2 w-64 rounded-xl overflow-hidden z-50 p-1.5"
              style={{
                background: 'rgba(16,17,22,0.98)',
                backdropFilter: 'blur(30px)',
                border: '1px solid rgba(255,255,255,0.08)',
                boxShadow: '0 12px 32px rgba(0,0,0,0.5)',
                animation: 'fadeSlideDown 0.12s ease-out forwards',
              }}
            >
              {user ? (
                /* Logged In Dropdown Content */
                <>
                  {/* User Profile Header */}
                  <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.05]">
                    <UserAvatar
                      src={user.photoURL || dbUser?.profile_image_url}
                      name={dbUser?.display_name || user.displayName}
                      email={user.email}
                      size={32}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-medium text-white truncate">
                          {dbUser?.display_name || user.displayName || 'Nexus User'}
                        </span>
                        <span className="text-[9px] px-1 py-0.2 rounded bg-sky-500/10 text-sky-400 font-mono border border-sky-500/20">
                          PRO
                        </span>
                      </div>
                      <p className="text-[10.5px] text-white/40 truncate mt-0.5 font-mono">
                        {user.email || 'Signed in'}
                      </p>
                    </div>
                  </div>

                  {/* Connectors Option */}
                  {onToggleConnectors && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onToggleConnectors();
                      }}
                      className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                        isConnectorsOpen
                          ? 'bg-cyan-500/15 text-cyan-300 font-medium'
                          : 'text-white/80 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Blocks className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" strokeWidth={1.8} />
                        <div className="flex flex-col flex-1 min-w-0">
                          <span className="leading-tight">Connectors</span>
                          <span className="text-[10px] text-white/40 leading-tight">External apps, MCP & tools</span>
                        </div>
                      </div>
                      <ChevronRight className="w-3.5 h-3.5 text-white/30" />
                    </button>
                  )}

                  {!isGuest && (
                    <>
                      {/* Skill Library Option */}
                      <button
                        type="button"
                        onClick={() => {
                          setIsProfileMenuOpen(false);
                          onToggleSkills?.('library');
                        }}
                        className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                          isSkillsOpen
                            ? 'bg-indigo-500/15 text-indigo-300 font-medium'
                            : 'text-white/80 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        <BookOpen className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" strokeWidth={1.8} />
                        <div className="flex flex-col flex-1 min-w-0">
                          <span className="leading-tight">Skill Library</span>
                          <span className="text-[10px] text-white/40 leading-tight">Learned workflows & health</span>
                        </div>
                      </button>

                      <div className="h-[1px] bg-white/10 my-1" />
                    </>
                  )}

                  {/* Schedule Option */}
                  {onToggleSchedule && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onToggleSchedule();
                      }}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                        isScheduleOpen
                          ? 'bg-sky-500/15 text-sky-300 font-medium'
                          : 'text-white/80 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <CalendarClock className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" strokeWidth={1.8} />
                      <div className="flex flex-col flex-1 min-w-0">
                        <span className="leading-tight">Scheduler</span>
                        <span className="text-[10px] text-white/40 leading-tight">Reminders & automated tasks</span>
                      </div>
                    </button>
                  )}

                  {/* Settings Option */}
                  {onToggleSettings && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onToggleSettings();
                      }}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                        isSettingsOpen
                          ? 'bg-cyan-500/15 text-cyan-300 font-medium'
                          : 'text-white/80 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <SettingsIcon className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" strokeWidth={1.8} />
                      <div className="flex flex-col flex-1 min-w-0">
                        <span className="leading-tight">Settings</span>
                        <span className="text-[10px] text-white/40 leading-tight">Preferences & API keys</span>
                      </div>
                    </button>
                  )}

                  <div className="h-[1px] bg-white/10 my-1" />

                  {/* Log Out Option */}
                  <button
                    type="button"
                    onClick={async () => {
                      setIsProfileMenuOpen(false);
                      await logout();
                    }}
                    className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 transition-colors"
                  >
                    <LogOut className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" strokeWidth={1.8} />
                    <span className="font-medium">Sign Out</span>
                  </button>
                </>
              ) : (
                /* Logged Out Dropdown Content */
                <>
                  <div className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-semibold text-white/45 uppercase tracking-wider">
                    <img src={nexusLogo} alt="" className="w-3.5 h-3.5 object-contain drop-shadow-[0_0_4px_rgba(56,189,248,0.6)]" />
                    <span>Nexus Account</span>
                  </div>

                  {/* Log In / Sign Up Option */}
                  <button
                    type="button"
                    onClick={() => {
                      setIsProfileMenuOpen(false);
                      onOpenAuthModal?.();
                    }}
                    className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs text-white/90 hover:bg-white/10 hover:text-white transition-colors"
                  >
                    <LogIn className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" strokeWidth={1.8} />
                    <div className="flex flex-col flex-1 min-w-0">
                      <span className="font-medium text-white">Log In / Sign Up</span>
                      <span className="text-[10px] text-white/40">Sync memory, history & models</span>
                    </div>
                  </button>

                  {/* Connectors Option */}
                  {onToggleConnectors && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onToggleConnectors();
                      }}
                      className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                        isConnectorsOpen
                          ? 'bg-cyan-500/15 text-cyan-300 font-medium'
                          : 'text-white/80 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Blocks className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" strokeWidth={1.8} />
                        <div className="flex flex-col flex-1 min-w-0">
                          <span className="leading-tight">Connectors</span>
                          <span className="text-[10px] text-white/40 leading-tight">External apps, MCP & tools</span>
                        </div>
                      </div>
                      <ChevronRight className="w-3.5 h-3.5 text-white/30" />
                    </button>
                  )}

                  {/* Task Scheduler Option */}
                  {onToggleSchedule && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onToggleSchedule();
                      }}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                        isScheduleOpen
                          ? 'bg-sky-500/15 text-sky-300 font-medium'
                          : 'text-white/80 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <CalendarClock className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" strokeWidth={1.8} />
                      <div className="flex flex-col flex-1 min-w-0">
                        <span className="leading-tight">Scheduler</span>
                        <span className="text-[10px] text-white/40 leading-tight">Reminders & automated tasks</span>
                      </div>
                    </button>
                  )}

                  <div className="h-[1px] bg-white/10 my-1" />

                  {/* Settings Option */}
                  {onToggleSettings && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onToggleSettings();
                      }}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                        isSettingsOpen
                          ? 'bg-cyan-500/15 text-cyan-300 font-medium'
                          : 'text-white/80 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <SettingsIcon className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" strokeWidth={1.8} />
                      <div className="flex flex-col flex-1 min-w-0">
                        <span className="leading-tight">Settings</span>
                        <span className="text-[10px] text-white/40 leading-tight">Preferences & API keys</span>
                      </div>
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
