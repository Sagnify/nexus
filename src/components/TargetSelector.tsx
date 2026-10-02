import React, { useState, useEffect, useRef } from 'react';
import { ChevronDown, Check, RefreshCw, X, AppWindow } from 'lucide-react';

export interface Target {
  id: string;
  application: string;
  window_title: string;
  process_name: string;
  window_id?: string;
  target_type: 'auto' | 'antigravity' | 'word' | 'excel' | 'browser' | 'explorer' | 'paint' | 'generic';
  icon?: string;
  icon_data?: string;
  exe_path?: string;
}

export interface TargetContextDetails {
  target_id: string;
  application: string;
  window_title: string;
  target_type: string;
  timestamp: string;
  details: Record<string, any>;
}

interface TargetSelectorProps {
  onTargetChange?: (target: Target, context?: TargetContextDetails) => void;
  hideIfGeneral?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Real Application SVG Icons (Pixel-perfect authentic brand icons)
// ─────────────────────────────────────────────────────────────────────────────

const ChromeIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <circle cx="24" cy="24" r="20" fill="#ECEFF1" />
    <path d="M44 24c0-1.8-.2-3.5-.7-5.1H24v10.2h11.4c-.6 3.1-2.4 5.7-5.1 7.4l8.2 6.4C43.2 38.6 44 31.7 44 24z" fill="#4285F4" />
    <path d="M24 44c5.4 0 9.9-1.8 13.3-4.9l-8.2-6.4c-1.8 1.2-4.1 2-6.6 2-5.1 0-9.4-3.4-10.9-8.1L3.1 33C6.6 39.8 14.6 44 24 44z" fill="#34A853" />
    <path d="M13.1 26.6c-.4-1.2-.6-2.5-.6-3.8s.2-2.6.6-3.8L4.6 12.8C2.9 16.2 2 20 2 24s.9 7.8 2.6 11.2l8.5-6.6z" fill="#FBBC05" />
    <path d="M24 10.4c3 0 5.6 1 7.7 3l5.8-5.8C33.9 4.3 29.4 2.4 24 2.4 14.6 2.4 6.6 6.6 3.1 13.4l8.5 6.6c1.5-4.7 5.8-8.1 10.9-8.1z" fill="#EA4335" />
    <circle cx="24" cy="24" r="9.5" fill="#FFFFFF" />
    <circle cx="24" cy="24" r="7.5" fill="#1A73E8" />
  </svg>
);

const EdgeIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <defs>
      <linearGradient id="edge_b" x1="24" y1="2" x2="46" y2="44" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#0C82D7" />
        <stop offset="100%" stopColor="#0B4B9C" />
      </linearGradient>
      <linearGradient id="edge_g" x1="2" y1="24" x2="38" y2="46" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#00C896" />
        <stop offset="100%" stopColor="#0C82D7" />
      </linearGradient>
    </defs>
    <path d="M44 24c0 11-9 20-20 20-8 0-15-4.7-18.2-11.5 2.5 1.5 5.5 2.5 8.7 2.5 9.4 0 17-7.6 17-17 0-2.4-.5-4.7-1.4-6.8C37.3 12.3 44 17.5 44 24z" fill="url(#edge_g)" />
    <path d="M24 4C13 4 4 13 4 24c0 2.2.4 4.3 1 6.3 1.5-4.8 5.8-8.3 11-8.3 6.6 0 12 5.4 12 12 0 1.2-.2 2.3-.5 3.4 9.1-1.3 16-9.1 16-18.4C43.5 10.2 34.8 4 24 4z" fill="url(#edge_b)" />
    <circle cx="24" cy="24" r="5" fill="#00E5A3" />
  </svg>
);

const WordIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <rect x="6" y="8" width="30" height="32" rx="4" fill="#185ABD" />
    <rect x="14" y="4" width="28" height="32" rx="4" fill="#2B7CD3" opacity="0.9" />
    <rect x="4" y="10" width="28" height="28" rx="4" fill="#103F91" />
    <path d="M11 18l2.6 12h2.8l2.1-8.2 2.1 8.2h2.8l2.6-12h-2.9l-1.4 8.2-2.1-8.2h-2.2l-2.1 8.2-1.4-8.2H11z" fill="#FFFFFF" />
  </svg>
);

const ExcelIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <rect x="6" y="8" width="30" height="32" rx="4" fill="#107C41" />
    <rect x="14" y="4" width="28" height="32" rx="4" fill="#21A366" opacity="0.9" />
    <rect x="4" y="10" width="28" height="28" rx="4" fill="#0E5C2F" />
    <path d="M12 18l3.6 5.8-3.7 6.2h3.2l2.1-4 2.1 4h3.2l-3.7-6.2 3.6-5.8h-3.1l-2.1 3.9-2.1-3.9H12z" fill="#FFFFFF" />
  </svg>
);

const ExplorerIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <path d="M4 12c0-2.2 1.8-4 4-4h11l4 5h17c2.2 0 4 1.8 4 4v3H4v-8z" fill="#F9A825" />
    <rect x="8" y="15" width="32" height="12" rx="2" fill="#42A5F5" opacity="0.8" />
    <rect x="4" y="18" width="40" height="22" rx="4" fill="#FBC02D" />
    <rect x="4" y="24" width="40" height="16" rx="4" fill="#FDD835" />
  </svg>
);

const PaintIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <path d="M24 4C13 4 4 13 4 24c0 10.5 8.5 19 19 19 2.2 0 4-1.8 4-4 0-1-.4-2-.4-3 0-2.2 1.8-4 4-4h4.4c6.6 0 12-5.4 12-12C47 11.2 36.7 4 24 4z" fill="#E0A96D" />
    <circle cx="14" cy="18" r="3.5" fill="#E53935" />
    <circle cx="24" cy="12" r="3.5" fill="#FB8C00" />
    <circle cx="34" cy="18" r="3.5" fill="#FDD835" />
    <circle cx="38" cy="28" r="3.5" fill="#43A047" />
    <circle cx="16" cy="28" r="3.5" fill="#1E88E5" />
    <circle cx="28" cy="37" r="2.5" fill="#8E24AA" />
  </svg>
);

const VSCodeIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <path d="M35.5 3.5l8 4.2v32.6l-8 4.2L16 31.8 7.5 38.5 4 35.8 11.2 24 4 12.2l3.5-2.7L16 16.2 35.5 3.5z" fill="#007ACC" />
    <path d="M35.5 3.5L16 16.2v15.6L35.5 44.5 43.5 40V8L35.5 3.5z" fill="#1F9CF0" />
    <path d="M35.5 3.5v41L16 31.8V16.2L35.5 3.5z" fill="#0066B8" opacity="0.4" />
    <path d="M4 12.2l7.2 11.8L4 35.8l3.5 2.7 8.5-6.7V16.2L7.5 9.5 4 12.2z" fill="#0066B8" />
  </svg>
);

const TerminalIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <rect x="4" y="6" width="40" height="36" rx="6" fill="#18181B" stroke="#3F3F46" strokeWidth="2" />
    <path d="M12 16l8 8-8 8" stroke="#38BDF8" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="24" y1="32" x2="34" y2="32" stroke="#4ADE80" strokeWidth="3.5" strokeLinecap="round" />
  </svg>
);

const AntigravityIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 24 24" fill="none">
    <defs>
      <linearGradient id="anti_pill_grad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#C084FC" />
        <stop offset="50%" stopColor="#818CF8" />
        <stop offset="100%" stopColor="#38BDF8" />
      </linearGradient>
    </defs>
    <path d="M12 2L14.8 9.2L22 12L14.8 14.8L12 22L9.2 14.8L2 12L9.2 9.2L12 2Z" fill="url(#anti_pill_grad)" />
    <circle cx="12" cy="12" r="2.5" fill="#FFFFFF" opacity="0.9" />
  </svg>
);

const GenericAppIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 48 48" fill="none">
    <rect x="4" y="8" width="40" height="32" rx="5" fill="#1F2937" stroke="#374151" strokeWidth="2" />
    <rect x="4" y="8" width="40" height="9" rx="5" fill="#2563EB" />
    <circle cx="9" cy="12.5" r="1.8" fill="#EF4444" />
    <circle cx="14" cy="12.5" r="1.8" fill="#F59E0B" />
    <circle cx="19" cy="12.5" r="1.8" fill="#10B981" />
  </svg>
);

const AutoIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={`${className} flex-shrink-0`} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="9" stroke="#38BDF8" strokeWidth="1.8" />
    <path d="M12 3a15.3 15.3 0 0 1 4 9 15.3 15.3 0 0 1-4 9 15.3 15.3 0 0 1-4-9 15.3 15.3 0 0 1 4-9z" stroke="#38BDF8" strokeWidth="1.6" />
    <path d="M3.6 9h16.8M3.6 15h16.8" stroke="#38BDF8" strokeWidth="1.6" />
  </svg>
);

// Helper to choose the best real application icon based on target metadata
const renderAppIcon = (type: string, appName: string = '', procName: string = '', className?: string) => {
  const name = (appName + ' ' + procName).toLowerCase();

  if (type === 'auto' || name.includes('auto') || name.includes('general')) return <AutoIcon className={className} />;
  if (name.includes('chrome')) return <ChromeIcon className={className} />;
  if (name.includes('edge') || name.includes('msedge')) return <EdgeIcon className={className} />;
  if (type === 'word' || name.includes('word') || name.includes('winword')) return <WordIcon className={className} />;
  if (type === 'excel' || name.includes('excel')) return <ExcelIcon className={className} />;
  if (type === 'explorer' || name.includes('explorer') || name.includes('folder')) return <ExplorerIcon className={className} />;
  if (type === 'paint' || name.includes('paint') || name.includes('mspaint')) return <PaintIcon className={className} />;
  if (name.includes('code') || name.includes('vscode')) return <VSCodeIcon className={className} />;
  if (name.includes('terminal') || name.includes('powershell') || name.includes('cmd') || name.includes('bash')) return <TerminalIcon className={className} />;
  if (type === 'antigravity' || name.includes('antigravity')) return <AntigravityIcon className={className} />;
  if (type === 'browser') return <ChromeIcon className={className} />;

  return <GenericAppIcon className={className} />;
};

// AppIcon renders real native computer icon when available (base64 or Electron native), falling back to brand SVG
export const AppIcon: React.FC<{
  target: Target;
  className?: string;
}> = ({ target, className = 'w-3.5 h-3.5' }) => {
  const [resolvedIcon, setResolvedIcon] = useState<string | null>(target.icon_data || null);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    if (target.icon_data) {
      setResolvedIcon(target.icon_data);
      setImgError(false);
      return;
    }

    // Secondary client-side fallback via Electron native app.getFileIcon
    if (target.exe_path && window.electronAPI?.getFileIcon) {
      window.electronAPI
        .getFileIcon(target.exe_path)
        .then((iconUrl) => {
          if (iconUrl) {
            setResolvedIcon(iconUrl);
            setImgError(false);
          }
        })
        .catch(() => {});
    }
  }, [target.icon_data, target.exe_path]);

  if (resolvedIcon && !imgError) {
    return (
      <img
        src={resolvedIcon}
        alt=""
        onError={() => setImgError(true)}
        className={`${className} object-contain flex-shrink-0 drop-shadow-[0_1px_2px_rgba(0,0,0,0.45)]`}
      />
    );
  }

  return renderAppIcon(target.target_type, target.application, target.process_name, className);
};

// ─────────────────────────────────────────────────────────────────────────────
// TargetSelector Pill Component
// ─────────────────────────────────────────────────────────────────────────────

export const TargetSelector: React.FC<TargetSelectorProps> = ({ onTargetChange, hideIfGeneral = false }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [targets, setTargets] = useState<Target[]>([]);
  const [activeTargetId, setActiveTargetId] = useState<string>('auto');
  const [activeTarget, setActiveTarget] = useState<Target>({
    id: 'auto',
    application: 'Auto / General',
    window_title: 'General Search & AI Assistant Mode',
    process_name: 'none',
    target_type: 'auto',
    icon: 'globe',
  });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchTargets = async () => {
    setIsRefreshing(true);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/nexus/targets');
      if (res.ok) {
        const data = await res.json();
        if (data.targets && Array.isArray(data.targets)) {
          setTargets(data.targets);
        }
        if (data.active_target_id) {
          setActiveTargetId(data.active_target_id);
        }
        if (data.active_target) {
          setActiveTarget(data.active_target);
        }
      }
    } catch (e) {
      console.debug('Target fetch error:', e);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchTargets();
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      window.addEventListener('mousedown', handleClickOutside);
    }
    return () => window.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleSelectTarget = async (t: Target) => {
    setActiveTarget(t);
    setActiveTargetId(t.id);
    setIsOpen(false);

    try {
      const res = await fetch('http://127.0.0.1:8000/api/nexus/target/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: t.id }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.target) setActiveTarget(data.target);
        onTargetChange?.(data.target || t, data.context);
      }
    } catch (e) {
      console.error('Target select error:', e);
    }
  };

  const isGeneralMode = activeTarget.target_type === 'auto' || activeTarget.id === 'auto';

  if (hideIfGeneral && isGeneralMode) {
    return null;
  }

  return (
    <div className="relative flex items-center" ref={containerRef}>
      {/* Pill Button: Dotted placeholder in General Mode, Solid app pill when an app is selected */}
      <button
        onClick={() => {
          if (!isOpen) fetchTargets();
          setIsOpen(!isOpen);
        }}
        className={`group flex items-center gap-1.5 h-6 rounded-md text-xs font-normal transition-all select-none whitespace-nowrap flex-shrink-0 ${
          isGeneralMode
            ? isOpen
              ? 'px-2 border border-dashed border-white/20 bg-white/[0.05] text-white/75 opacity-90'
              : 'px-2 border border-dashed border-white/[0.08] hover:border-white/20 bg-white/[0.015] hover:bg-white/[0.04] text-white/35 hover:text-white/65 opacity-60 hover:opacity-90'
            : isOpen
              ? 'pl-1.5 pr-2 border border-sky-400/40 bg-white/10 text-white'
              : 'pl-1.5 pr-2 border border-white/10 hover:border-white/20 bg-white/[0.04] hover:bg-white/[0.08] text-white'
        }`}
        title={
          isGeneralMode
            ? 'General Mode (No specific application locked)\nClick to attach NEXUS to an open application'
            : `Active Target: ${activeTarget.application} (${activeTarget.window_title})\nClick to switch or clear target`
        }
      >
        {isGeneralMode ? (
          <>
            <AppWindow className="w-3 h-3 text-white/35 group-hover:text-white/60 transition-colors" />
            <span className="text-[11px] font-normal tracking-tight text-white/45 group-hover:text-white/75 transition-colors">
              Active app
            </span>
            <ChevronDown
              className={`w-2.5 h-2.5 text-white/30 group-hover:text-white/60 transition-transform duration-200 ${
                isOpen ? 'rotate-180 text-cyan-400/80' : ''
              }`}
            />
          </>
        ) : (
          <>
            {/* Real computer app icon in soft squircle badge */}
            <div className="flex items-center justify-center w-5.5 h-5.5 rounded-full bg-gradient-to-b from-white/[0.15] to-black/40 border border-white/15 p-0.5 shadow-sm group-hover:scale-105 transition-transform flex-shrink-0">
              <AppIcon target={activeTarget} className="w-3.5 h-3.5" />
            </div>
            <span className="max-w-[135px] truncate text-[11.5px] font-semibold tracking-tight text-neutral-100 group-hover:text-white drop-shadow-sm">
              {activeTarget.application}
            </span>
            {/* Quick Deselect / Reset to General Mode button */}
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                handleSelectTarget({
                  id: 'auto',
                  application: 'Auto / General',
                  window_title: 'General Search & AI Assistant Mode',
                  process_name: 'none',
                  target_type: 'auto',
                  icon: 'globe',
                });
              }}
              className="w-4 h-4 rounded-full flex items-center justify-center bg-white/[0.08] hover:bg-red-500/30 text-neutral-400 hover:text-red-300 transition-all cursor-pointer flex-shrink-0 ml-0.5"
              title="Reset to General mode"
            >
              <X className="w-2.5 h-2.5" />
            </span>
            <ChevronDown
              className={`w-3 h-3 text-neutral-400 group-hover:text-neutral-200 transition-transform duration-200 ${
                isOpen ? 'rotate-180 text-cyan-400' : ''
              }`}
            />
          </>
        )}
      </button>

      {/* Target Dropdown Menu */}
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-80 rounded-xl bg-[#101116] border border-white/[0.08] shadow-2xl z-50 overflow-hidden animate-fadeIn">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.06] bg-white/[0.015]">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
              <span className="text-[10px] font-semibold text-white/40 uppercase tracking-wider font-mono">Target Application</span>
            </div>
            <button
              onClick={fetchTargets}
              disabled={isRefreshing}
              className="p-1 rounded text-white/35 hover:text-white hover:bg-white/[0.06] transition-colors"
              title="Refresh available windows"
            >
              <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {/* List of Applications */}
          <div className="max-h-72 overflow-y-auto py-1 scrollbar-thin scrollbar-thumb-white/10">
            {targets.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-white/40">Discovering open applications…</div>
            ) : (
              <>
                {/* General Mode Option (always on top) */}
                {(() => {
                  const autoTarget = targets.find((t) => t.id === 'auto') || {
                    id: 'auto',
                    application: 'Auto / General',
                    window_title: 'General Search & AI Assistant Mode',
                    process_name: 'none',
                    target_type: 'auto' as const,
                    icon: 'globe',
                  };
                  const isSelected = activeTargetId === 'auto';
                  return (
                    <button
                      key="auto"
                      onClick={() => handleSelectTarget(autoTarget)}
                      className={`w-[calc(100%-10px)] mx-1.25 mb-1 flex items-center justify-between p-2 rounded-lg text-left text-xs transition-colors group ${
                        isSelected
                          ? 'bg-white/[0.07] border border-white/[0.09] text-white font-medium'
                          : 'hover:bg-white/[0.035] text-white/75 hover:text-white border border-transparent'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0 pr-2">
                        <div className="flex items-center justify-center w-6 h-6 flex-shrink-0 rounded-md bg-white/[0.04] border border-white/[0.06] text-sky-400">
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="8" strokeDasharray="3 2" />
                            <circle cx="12" cy="12" r="2.5" fill="currentColor" />
                          </svg>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium text-white/90 group-hover:text-white">General Mode</span>
                            <span className="px-1 py-0.2 rounded text-[9px] font-mono text-white/35 bg-white/[0.03] border border-white/[0.06]">Default</span>
                          </div>
                          <div className="text-[10px] text-white/35 truncate leading-snug">Search & AI assistant (no app locked)</div>
                        </div>
                      </div>
                      {isSelected && (
                        <div className="w-4 h-4 rounded-full bg-sky-400/15 border border-sky-400/30 flex items-center justify-center flex-shrink-0">
                          <Check className="w-2.5 h-2.5 text-sky-400" />
                        </div>
                      )}
                    </button>
                  );
                })()}

                {/* Section Divider for Open Applications */}
                {targets.filter((t) => t.id !== 'auto').length > 0 && (
                  <div className="px-3.5 pt-2.5 pb-1 border-t border-white/[0.06] mt-1 flex items-center justify-between">
                    <span className="text-[9px] font-semibold text-neutral-400 uppercase tracking-wider">
                      Open Applications
                    </span>
                    <span className="text-[9px] font-medium text-neutral-500">
                      {targets.filter((t) => t.id !== 'auto').length} windows
                    </span>
                  </div>
                )}

                {/* Native Running Applications */}
                {targets
                  .filter((t) => t.id !== 'auto')
                  .map((t) => {
                    const isSelected = t.id === activeTargetId;
                    return (
                      <button
                        key={t.id}
                        onClick={() => handleSelectTarget(t)}
                        className={`w-[calc(100%-10px)] mx-1.25 my-0.5 flex items-center justify-between p-2 rounded-lg text-left text-xs transition-colors group ${
                          isSelected
                            ? 'bg-white/[0.07] border border-white/[0.09] text-white font-medium'
                            : 'hover:bg-white/[0.035] text-white/75 hover:text-white border border-transparent'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 pr-2">
                          <div className="flex items-center justify-center w-6 h-6 flex-shrink-0 rounded-md bg-white/[0.04] border border-white/[0.06] p-0.5">
                            <AppIcon target={t} className="w-4 h-4" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="font-medium truncate leading-snug text-white/90 group-hover:text-white">{t.application}</div>
                            <div className="text-[10px] text-white/35 truncate leading-snug">{t.window_title}</div>
                          </div>
                        </div>
                        {isSelected && (
                          <div className="w-4 h-4 rounded-full bg-sky-400/15 border border-sky-400/30 flex items-center justify-center flex-shrink-0">
                            <Check className="w-2.5 h-2.5 text-sky-400" />
                          </div>
                        )}
                      </button>
                    );
                  })}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
