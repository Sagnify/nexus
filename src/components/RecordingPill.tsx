import React, { useRef, useEffect, useCallback } from 'react';
import {
  Globe,
  Monitor,
  Layers,
  Pause,
  Play,
  Trash2,
  Check,
  MousePointer2,
  Keyboard,
  Navigation,
  ToggleRight,
  Eye,
  ChevronDown,
} from 'lucide-react';
import nexusLogo from '../assets/nexus-logo.png';

interface RecordingPillProps {
  isTeaching: boolean;
  environment: string;
  prompt: string;
  timerSeconds: number;
  eventsCount: number;
  recentActions: string[];
  isPaused?: boolean;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onFinish: () => void;
  onDiscard: () => void;
}

const formatTimer = (sec: number) => {
  const mins = Math.floor(sec / 60);
  const remaining = sec % 60;
  return `${mins.toString().padStart(2, '0')}:${remaining.toString().padStart(2, '0')}`;
};

/** Classify a raw action string and return icon + formatted label */
const classifyAction = (action: string): { icon: React.ReactNode; label: string; sub?: string } => {
  const a = action.toLowerCase();

  if (a.startsWith('click') || a.includes('clicked')) {
    const target = action.replace(/^click(ed)?\s+on\s+/i, '').replace(/^click(ed)?\s+/i, '');
    return {
      icon: <MousePointer2 className="w-3 h-3" />,
      label: 'Click',
      sub: target || action,
    };
  }
  if (a.startsWith('type') || a.includes('typed') || a.includes('input')) {
    const text = action.replace(/^type(d)?\s+/i, '').replace(/^input\s+/i, '');
    return {
      icon: <Keyboard className="w-3 h-3" />,
      label: 'Type',
      sub: text.length > 40 ? text.slice(0, 40) + '…' : text,
    };
  }
  if (a.includes('navigate') || a.includes('goto') || a.includes('url') || a.includes('open')) {
    const url = action.replace(/^navigate\s+to\s+/i, '').replace(/^goto\s+/i, '').replace(/^open\s+/i, '');
    return {
      icon: <Navigation className="w-3 h-3" />,
      label: 'Navigate',
      sub: url.length > 45 ? url.slice(0, 45) + '…' : url,
    };
  }
  if (a.includes('select') || a.includes('choose') || a.includes('dropdown')) {
    return {
      icon: <ToggleRight className="w-3 h-3" />,
      label: 'Select',
      sub: action.replace(/^select\s+/i, ''),
    };
  }
  if (a.includes('scroll') || a.includes('key') || a.includes('press')) {
    return {
      icon: <Keyboard className="w-3 h-3" />,
      label: 'Key',
      sub: action,
    };
  }
  return {
    icon: <Eye className="w-3 h-3" />,
    label: 'Action',
    sub: action.length > 50 ? action.slice(0, 50) + '…' : action,
  };
};

export const RecordingPill: React.FC<RecordingPillProps> = ({
  isTeaching,
  environment,
  prompt,
  timerSeconds,
  eventsCount,
  recentActions,
  isPaused = false,
  isExpanded = false,
  onToggleExpand,
  onPause,
  onResume,
  onFinish,
  onDiscard,
}) => {
  if (!isTeaching) return null;

  const isBrowser = environment === 'browser';
  const isDesktop = environment === 'desktop';
  const pillRef = useRef<HTMLDivElement>(null);
  const stepsEndRef = useRef<HTMLDivElement>(null);

  // Sync pill window height to Electron whenever content changes
  const syncPillHeight = useCallback(() => {
    if (!pillRef.current) return;
    const h = Math.ceil(pillRef.current.getBoundingClientRect().height) + 12; // +12 for p-1.5 padding
    window.electronAPI?.resizePill(Math.max(h, 84));
  }, []);

  useEffect(() => {
    syncPillHeight();
    const el = pillRef.current;
    if (!el) return;
    const ro = new ResizeObserver(syncPillHeight);
    ro.observe(el);
    return () => ro.disconnect();
  }, [syncPillHeight, isExpanded, recentActions.length]);

  // Auto-scroll to latest step
  useEffect(() => {
    if (isExpanded && stepsEndRef.current) {
      stepsEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [recentActions, isExpanded]);

  // Theme accents matching Spotlight glass system
  const theme = isBrowser
    ? {
        accent: '#38bdf8',
        accentDim: 'rgba(56,189,248,0.10)',
        accentBorder: 'rgba(56,189,248,0.25)',
        accentGlow: 'rgba(56,189,248,0.12)',
        recDot: '#ef4444',
        recBg: 'rgba(239,68,68,0.12)',
        recBorder: 'rgba(239,68,68,0.25)',
        recText: '#fca5a5',
        stepDot: 'bg-sky-400',
        stepText: 'text-sky-300',
        iconColor: 'text-sky-400',
        badgeBg: 'rgba(56,189,248,0.08)',
        badgeBorder: 'rgba(56,189,248,0.20)',
        badgeText: '#7dd3fc',
        envLabel: 'Browser',
      }
    : isDesktop
    ? {
        accent: '#a855f7',
        accentDim: 'rgba(168,85,247,0.10)',
        accentBorder: 'rgba(168,85,247,0.25)',
        accentGlow: 'rgba(168,85,247,0.12)',
        recDot: '#ef4444',
        recBg: 'rgba(239,68,68,0.12)',
        recBorder: 'rgba(239,68,68,0.25)',
        recText: '#fca5a5',
        stepDot: 'bg-purple-400',
        stepText: 'text-purple-300',
        iconColor: 'text-purple-400',
        badgeBg: 'rgba(168,85,247,0.08)',
        badgeBorder: 'rgba(168,85,247,0.20)',
        badgeText: '#d8b4fe',
        envLabel: 'Desktop',
      }
    : {
        accent: '#10b981',
        accentDim: 'rgba(16,185,129,0.10)',
        accentBorder: 'rgba(16,185,129,0.25)',
        accentGlow: 'rgba(16,185,129,0.12)',
        recDot: '#ef4444',
        recBg: 'rgba(239,68,68,0.12)',
        recBorder: 'rgba(239,68,68,0.25)',
        recText: '#fca5a5',
        stepDot: 'bg-emerald-400',
        stepText: 'text-emerald-300',
        iconColor: 'text-emerald-400',
        badgeBg: 'rgba(16,185,129,0.08)',
        badgeBorder: 'rgba(16,185,129,0.20)',
        badgeText: '#6ee7b7',
        envLabel: 'Universal OS',
      };

  return (
    <div className="w-full select-none p-1.5 flex justify-center">
      <div
        ref={pillRef}
        className="relative w-full max-w-[580px] rounded-full overflow-hidden transition-all duration-300"
        style={{
          background: 'rgba(13, 15, 20, 0.94)',
          backdropFilter: 'blur(24px) saturate(180%)',
          WebkitBackdropFilter: 'blur(24px) saturate(180%)',
          border: '1px solid rgba(255, 255, 255, 0.10)',
          boxShadow: '0 16px 36px -4px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(0, 0, 0, 0.4)',
        }}
      >
        {/* ── TOP BAR ── */}
        <div
          className="flex items-center gap-2 px-3.5 py-1.5"
          style={{ borderBottom: isExpanded ? '1px solid rgba(255,255,255,0.06)' : 'none' }}
        >
          {/* Authentic NEXUS Ribbon Logo */}
          <div className="flex items-center justify-center shrink-0" title="NEXUS Autonomous Recorder">
            <img
              src={nexusLogo}
              alt="NEXUS"
              className="w-4 h-4 object-contain drop-shadow-[0_0_5px_rgba(56,189,248,0.7)]"
            />
          </div>

          {/* REC badge with pulsing dot */}
          <div
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-full shrink-0 font-mono text-[10.5px] font-medium tracking-wide"
            style={{
              background: isPaused ? 'rgba(245, 158, 11, 0.08)' : 'rgba(255, 255, 255, 0.05)',
              border: `1px solid ${isPaused ? 'rgba(245, 158, 11, 0.25)' : 'rgba(255, 255, 255, 0.08)'}`,
              color: isPaused ? '#fef3c7' : '#e2e8f0',
            }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{
                background: isPaused ? '#f59e0b' : '#f87171',
                animation: isPaused ? 'none' : 'pulse 1.4s cubic-bezier(0.4,0,0.6,1) infinite',
              }}
            />
            {isPaused ? 'PAUSED' : 'REC'} {formatTimer(timerSeconds)}
          </div>

          {/* Environment chip */}
          <div
            className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium shrink-0"
            style={{
              background: 'rgba(255, 255, 255, 0.04)',
              border: '1px solid rgba(255, 255, 255, 0.07)',
              color: '#94a3b8',
            }}
          >
            {isBrowser ? (
              <Globe className="w-3 h-3 text-sky-400" />
            ) : isDesktop ? (
              <Monitor className="w-3 h-3 text-purple-400" />
            ) : (
              <Layers className="w-3 h-3 text-emerald-400" />
            )}
            <span>{theme.envLabel}</span>
          </div>

          {/* Prompt label */}
          <span
            className="text-[12px] font-medium truncate flex-1 min-w-0 text-white tracking-tight"
          >
            {prompt || 'Recording demonstration…'}
          </span>

          {/* Events count badge */}
          {eventsCount > 0 && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono shrink-0"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.08)',
                color: '#94a3b8',
              }}
            >
              {eventsCount} step{eventsCount !== 1 ? 's' : ''}
            </div>
          )}

          {/* Expand toggle */}
          {onToggleExpand && (
            <button
              type="button"
              onClick={onToggleExpand}
              className="flex items-center justify-center w-6 h-6 rounded-md shrink-0 transition-all hover:bg-white/[0.08] active:scale-95"
              style={{
                background: isExpanded ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
                color: isExpanded ? 'rgba(255,255,255,0.85)' : '#94a3b8',
              }}
              title={isExpanded ? 'Collapse steps' : 'Show recorded steps'}
            >
              <ChevronDown
                className="w-3.5 h-3.5 transition-transform duration-200"
                style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
              />
            </button>
          )}

          {/* ── Controls ── */}
          <div className="flex items-center gap-1.5 shrink-0 ml-1">
            {/* Pause / Resume */}
            {isPaused ? (
              <button
                type="button"
                onClick={onResume}
                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all active:scale-95"
                style={{
                  background: 'rgba(245, 158, 11, 0.12)',
                  border: '1px solid rgba(245, 158, 11, 0.30)',
                  color: '#fbbf24',
                }}
                title="Resume recording"
              >
                <Play className="w-3 h-3 fill-current" />
                <span>Resume</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onPause}
                className="flex items-center justify-center w-6 h-6 rounded-md transition-all hover:bg-white/[0.08] active:scale-95 text-slate-400 hover:text-white"
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.07)',
                }}
                title="Pause recording"
              >
                <Pause className="w-3 h-3 fill-current" />
              </button>
            )}

            {/* Discard */}
            <button
              type="button"
              onClick={onDiscard}
              className="flex items-center justify-center w-6 h-6 rounded-md transition-all hover:bg-rose-500/15 hover:text-rose-300 border border-transparent hover:border-rose-500/25 active:scale-95 text-slate-400"
              title="Discard recording"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>

            {/* Finish / Save */}
            <button
              type="button"
              onClick={onFinish}
              className="flex items-center gap-1.5 px-3 py-1 rounded-md text-[11px] font-semibold transition-all active:scale-95 text-white"
              style={{
                background: '#059669',
                border: '1px solid rgba(16, 185, 129, 0.35)',
                boxShadow: '0 1px 3px rgba(0, 0, 0, 0.25)',
              }}
              title="Finish & review skill"
            >
              <Check className="w-3.5 h-3.5 stroke-[2.5]" />
              <span>Finish</span>
            </button>
          </div>
        </div>

        {/* ── EXPANDED: RECORDED STEPS FEED ── */}
        {isExpanded && (
          <div
            className="px-3 py-2"
            style={{ maxHeight: '200px', overflowY: 'auto', willChange: 'transform' }}
          >
            {recentActions.length === 0 ? (
              <div className="flex items-center gap-2 py-3 justify-center">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: theme.accent,
                    animation: 'pulse 1.2s ease-in-out infinite',
                  }}
                />
                <span className="text-[11px]" style={{ color: 'rgba(255,255,255,0.40)' }}>
                  {isBrowser
                    ? 'Waiting for interactions in Chrome…'
                    : 'Waiting for desktop interactions…'}
                </span>
              </div>
            ) : (
              <div className="space-y-1">
                {recentActions.map((action, i) => {
                  const { icon, label, sub } = classifyAction(action);
                  const isLatest = i === recentActions.length - 1;
                  return (
                    <div
                      key={i}
                      className="flex items-start gap-2.5 py-1 px-1.5 rounded-lg transition-all"
                      style={{
                        background: isLatest ? theme.accentDim : 'transparent',
                        border: `1px solid ${isLatest ? theme.accentBorder : 'transparent'}`,
                        willChange: isLatest ? 'background, border-color' : 'auto',
                      }}
                    >
                      {/* Step number */}
                      <span
                        className="text-[9px] font-mono shrink-0 mt-0.5 w-4 text-center"
                        style={{ color: 'rgba(255,255,255,0.28)' }}
                      >
                        {i + 1}
                      </span>

                      {/* Timeline dot */}
                      <div className="flex flex-col items-center shrink-0 mt-1">
                        <span
                          className="w-1.5 h-1.5 rounded-full shrink-0"
                          style={{
                            background: isLatest ? theme.accent : 'rgba(255,255,255,0.25)',
                          }}
                        />
                      </div>

                      {/* Icon + label */}
                      <div
                        className="shrink-0 mt-0.5"
                        style={{ color: isLatest ? theme.accent : 'rgba(255,255,255,0.40)' }}
                      >
                        {icon}
                      </div>

                      {/* Content */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-1.5">
                          <span
                            className="text-[10.5px] font-semibold shrink-0"
                            style={{ color: isLatest ? theme.accent : 'rgba(255,255,255,0.65)' }}
                          >
                            {label}
                          </span>
                          {sub && (
                            <span
                              className="text-[10px] truncate"
                              style={{ color: isLatest ? 'rgba(255,255,255,0.75)' : 'rgba(255,255,255,0.38)' }}
                            >
                              {sub}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Latest badge */}
                      {isLatest && (
                        <span
                          className="text-[8.5px] font-bold uppercase tracking-wider shrink-0 px-1 py-0.5 rounded"
                          style={{
                            background: theme.accentDim,
                            color: theme.accent,
                            border: `1px solid ${theme.accentBorder}`,
                          }}
                        >
                          latest
                        </span>
                      )}
                    </div>
                  );
                })}
                <div ref={stepsEndRef} />
              </div>
            )}
          </div>
        )}

        {/* ── STATUS FOOTER (collapsed) ── */}
        {!isExpanded && (
          <div
            className="px-3 py-1.5 flex items-center gap-2 text-[10.5px]"
            style={{ borderTop: '1px solid rgba(255,255,255,0.05)', background: 'rgba(255,255,255,0.015)' }}
          >
            {isPaused ? (
              <>
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: 'rgba(255,255,255,0.30)' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.40)' }}>
                  Recording paused · {eventsCount} step{eventsCount !== 1 ? 's' : ''} captured
                </span>
              </>
            ) : eventsCount === 0 ? (
              <>
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{
                    background: theme.accent,
                    animation: 'pulse 1.2s ease-in-out infinite',
                  }}
                />
                <span style={{ color: 'rgba(255,255,255,0.42)' }}>
                  {isBrowser
                    ? 'Listening in Chrome · interact with any page'
                    : 'Listening for desktop app interactions…'}
                </span>
              </>
            ) : (
              <>
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: '#34d399' }}
                />
                <span style={{ color: 'rgba(52,211,153,0.90)' }}>
                  {eventsCount} step{eventsCount !== 1 ? 's' : ''} recorded
                </span>
                {recentActions.length > 0 && (
                  <span style={{ color: 'rgba(255,255,255,0.30)' }} className="truncate">
                    · {recentActions[recentActions.length - 1]}
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
