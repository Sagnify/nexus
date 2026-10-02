import React, { useEffect, useState } from "react";
import {
  Terminal,
  Check,
  Activity,
  ShieldCheck,
  Zap,
  AlertTriangle,
  Copy,
  CheckCheck,
  RotateCcw,
  X,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { NexusLogoMedia } from "./NexusLogoMedia";

interface SkillCompilingLoaderProps {
  prompt?: string;
  eventsCount?: number;
  environment?: string;
  error?: { message: string; error?: string; traceback?: string } | null;
  onRetry?: () => void;
  onCancel?: () => void;
  /** Max seconds to wait before showing a timeout error. Default: 15 */
  timeoutMs?: number;
}

const COMPILATION_STAGES = [
  { id: "telemetry", label: "Ingesting telemetry trace & DOM selectors", sub: "Mapping multi-attribute fallback bundles" },
  { id: "noise", label: "Purging noise & background app events", sub: "Filtering jitter, accidental clicks, and passive tabs" },
  { id: "parameters", label: "Synthesizing dynamic parameter templates", sub: "Extracting dynamic tokens into {{param}} templates via model pool" },
  { id: "contract", label: "Validating execution contracts & preconditions", sub: "Formulating idempotent pre/post-conditions" },
];

export const SkillCompilingLoader: React.FC<SkillCompilingLoaderProps> = ({
  prompt = "",
  eventsCount = 0,
  environment = "browser",
  error = null,
  onRetry,
  onCancel,
  timeoutMs = 15000,
}) => {
  const [activeStageIndex, setActiveStageIndex] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [copied, setCopied] = useState(false);
  const [showTraceback, setShowTraceback] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [isAutoRecovering, setIsAutoRecovering] = useState(false);

  // Dynamic progression timer
  useEffect(() => {
    if (error) return; // Freeze timer if errored
    const start = Date.now();
    const timer = setInterval(() => {
      const diff = Date.now() - start;
      setElapsedMs(diff);
      if (diff > 4500) setActiveStageIndex(3);
      else if (diff > 2500) setActiveStageIndex(2);
      else if (diff > 800) setActiveStageIndex(1);
      else setActiveStageIndex(0);
    }, 150);

    return () => clearInterval(timer);
  }, [error]);

  // UI-level timeout guard — auto-trigger recovery instead of showing a dead error
  useEffect(() => {
    if (error || timedOut) return;
    const id = setTimeout(() => {
      setTimedOut(true);
      if (onRetry) {
        // Auto-invoke deterministic recovery silently — no user action needed
        setIsAutoRecovering(true);
        onRetry();
      }
    }, timeoutMs);
    return () => clearTimeout(id);
  }, [error, timedOut, timeoutMs, onRetry]);

  // Synthesise a timeout error object — only shown if auto-recovery also fails (parent sets error prop)
  const displayError = error ?? (timedOut && !isAutoRecovering ? {
    message: "Compilation timed out — the AI model pool did not respond in time.",
    error: `No response after ${Math.round(timeoutMs / 1000)}s. Use 'Retry' to attempt deterministic recovery.`,
    traceback: "",
  } : null);

  const elapsedSec = (elapsedMs / 1000).toFixed(1);

  const handleCopyError = () => {
    if (!displayError) return;
    const errorPayload = [
      "=== NEXUS SKILL COMPILATION ERROR ===",
      `Timestamp: ${new Date().toISOString()}`,
      `Workflow Intent: ${prompt || "Demonstrated Workflow"}`,
      `Target Environment: ${environment}`,
      `Captured Events: ${eventsCount}`,
      `Message: ${displayError?.message || "Compilation failed"}`,
      `Error Detail: ${displayError?.error || "N/A"}`,
      displayError?.traceback ? `\n--- Traceback ---\n${displayError.traceback}` : "",
      "=====================================",
    ].filter(Boolean).join("\n");

    navigator.clipboard.writeText(errorPayload);
    setCopied(true);
    setTimeout(() => setCopied(false), 2200);
  };

  // ── ERROR STATE UI ──────────────────────────────────────────────────────────
  if (displayError) {
    return (
      <div
        className="relative overflow-hidden rounded-xl p-6 sm:p-7 text-left w-full select-none"
        style={{
          minHeight: "360px",
          background: "rgba(14, 11, 14, 0.96)",
          backdropFilter: "blur(28px) saturate(180%)",
          WebkitBackdropFilter: "blur(28px) saturate(180%)",
          border: "1px solid rgba(239, 68, 68, 0.25)",
          boxShadow: "0 1px 0 0 rgba(239, 68, 68, 0.15) inset, 0 24px 60px -12px rgba(0, 0, 0, 0.9)",
        }}
      >
        {/* Subtle background red glow */}
        <div
          className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 w-96 h-48 rounded-full"
          style={{
            background: "radial-gradient(ellipse at center, rgba(239, 68, 68, 0.15) 0%, transparent 70%)",
            filter: "blur(32px)",
          }}
        />

        {/* Top Header Row */}
        <div className="relative flex items-center justify-between gap-4 pb-4 border-b border-red-500/15">
          <div className="flex items-center gap-3">
            <div className="relative flex items-center justify-center w-10 h-10 rounded-lg bg-red-500/10 border border-red-500/30 shadow-[0_0_15px_rgba(239,68,68,0.2)] flex-shrink-0">
              <AlertTriangle className="w-5 h-5 text-red-400" />
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-[13.5px] font-semibold text-white tracking-tight">
                  {timedOut && !error ? "Compilation Timed Out" : "Compilation Halted"}
                </h3>
                <span className="px-1.5 py-0.5 rounded text-[9.5px] font-mono font-semibold bg-red-500/15 text-red-400 border border-red-500/30">
                  {timedOut && !error ? "TIMEOUT" : "FAILED"}
                </span>
              </div>
              <p className="text-[11px] text-white/50 mt-0.5 truncate max-w-[420px]">
                {prompt || "Demonstrated workflow synthesis"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopyError}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.1] hover:border-white/20 text-[11px] font-medium text-white transition-all shadow-sm active:scale-95"
              title="Copy error and stacktrace to clipboard"
            >
              {copied ? (
                <>
                  <CheckCheck className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-300 font-mono text-[10.5px]">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-white/60" />
                  <span>Copy Error</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Error Detail Box */}
        <div className="relative my-4 space-y-3">
          <div className="p-3.5 rounded-lg bg-red-950/20 border border-red-500/20 text-left">
            <div className="flex items-start gap-2.5">
              <div className="w-1.5 h-1.5 rounded-full bg-red-400 mt-1.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold text-red-200">
                  {displayError.message || "An unexpected error occurred during workflow compilation."}
                </div>
                {displayError.error && displayError.error !== displayError.message && (
                  <p className="text-[11px] font-mono text-red-300/70 mt-1 break-words">
                    {displayError.error}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Collapsible Full Traceback / Console Details */}
          {displayError.traceback && (
            <div className="rounded-lg bg-black/60 border border-white/[0.06] overflow-hidden">
              <button
                type="button"
                onClick={() => setShowTraceback(!showTraceback)}
                className="w-full flex items-center justify-between px-3.5 py-2 text-[11px] font-mono text-white/50 hover:text-white/80 hover:bg-white/[0.02] transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Terminal className="w-3 h-3 text-white/40" />
                  <span>Full Diagnostics & Traceback</span>
                </div>
                {showTraceback ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>

              {showTraceback && (
                <pre className="p-3 text-[10px] font-mono text-red-200/80 overflow-x-auto max-h-48 border-t border-white/[0.04] bg-black/80 select-text leading-relaxed">
                  {displayError.traceback}
                </pre>
              )}
            </div>
          )}
        </div>

        {/* Action Buttons Row */}
        <div className="relative pt-3 border-t border-white/[0.06] flex items-center justify-between gap-3">
          <span className="text-[10.5px] font-mono text-white/40">
            {eventsCount} interaction event{eventsCount !== 1 ? "s" : ""} recorded in {environment}
          </span>

          <div className="flex items-center gap-2">
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                className="px-3.5 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] text-white/70 hover:text-white text-[11.5px] font-medium transition-all"
              >
                Discard & Exit
              </button>
            )}

            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-[11.5px] font-semibold transition-all shadow-[0_0_15px_rgba(16,185,129,0.3)] active:scale-95"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Retry Compilation</span>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── AUTO-RECOVERING STATE ───────────────────────────────────────────────────
  // Shown after timeout fires and onRetry() is auto-called. The spinner keeps
  // running while the deterministic recovery backend call is in-flight.
  if (isAutoRecovering && !error) {
    return (
      <div
        className="relative overflow-hidden rounded-xl p-6 sm:p-7 text-left w-full select-none"
        style={{
          minHeight: "360px",
          background: "rgba(10, 11, 15, 0.94)",
          backdropFilter: "blur(28px) saturate(180%)",
          WebkitBackdropFilter: "blur(28px) saturate(180%)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          boxShadow: "0 1px 0 0 rgba(255, 255, 255, 0.06) inset, 0 24px 60px -12px rgba(0, 0, 0, 0.85)",
        }}
      >
        <div
          className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 w-96 h-48 rounded-full"
          style={{
            background: "radial-gradient(ellipse at center, rgba(245, 158, 11, 0.10) 0%, transparent 70%)",
            filter: "blur(32px)",
          }}
        />
        <div className="relative flex items-center gap-3 pb-5 border-b border-white/[0.06]">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-lg bg-amber-500/[0.07] border border-amber-500/25 flex-shrink-0">
            <div className="absolute inset-0 rounded-lg border border-amber-500/30 border-t-amber-400 animate-spin" style={{ animationDuration: "1.2s" }} />
            <ShieldCheck className="w-4 h-4 text-amber-400 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[13px] font-semibold text-white tracking-tight">Auto-Recovery In Progress</h3>
              <span className="px-1.5 py-0.5 rounded text-[9.5px] font-mono font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                RECOVERING
              </span>
            </div>
            <p className="text-[11px] text-white/45 mt-0.5">
              AI model pool timed out — switching to instant deterministic compiler…
            </p>
          </div>
        </div>
        <div className="relative py-8 flex flex-col items-center justify-center gap-4">
          <div className="flex items-center gap-3">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          <p className="text-[11.5px] text-white/50 text-center">
            Compiling your {eventsCount} recorded actions into a skill using the deterministic engine…
          </p>
        </div>
        <div className="relative pt-3 border-t border-white/[0.06] flex items-center justify-between text-[10.5px] font-mono text-white/40">
          <div className="flex items-center gap-2">
            <Terminal className="w-3.5 h-3.5 text-white/30" />
            <span>Bypassing model pool — deterministic heuristic synthesis active…</span>
          </div>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="px-3 py-1 rounded-lg bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] text-white/50 hover:text-white text-[11px] transition-all"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── ACTIVE COMPILATION UI ───────────────────────────────────────────────────
  return (
    <div
      className="relative overflow-hidden rounded-xl p-6 sm:p-7 text-left w-full select-none"
      style={{
        minHeight: "360px",
        background: "rgba(10, 11, 15, 0.94)",
        backdropFilter: "blur(28px) saturate(180%)",
        WebkitBackdropFilter: "blur(28px) saturate(180%)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        boxShadow: "0 1px 0 0 rgba(255, 255, 255, 0.06) inset, 0 24px 60px -12px rgba(0, 0, 0, 0.85)",
      }}
    >
      {/* Subtle background ambient glow */}
      <div
        className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 w-96 h-48 rounded-full"
        style={{
          background: "radial-gradient(ellipse at center, rgba(16, 185, 129, 0.12) 0%, transparent 70%)",
          filter: "blur(32px)",
        }}
      />

      {/* Top Header Row */}
      <div className="relative flex items-center justify-between gap-4 pb-5 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          {/* Executive Obsidian Aperture with Live Nexus Loader Video & Skeleton */}
          <NexusLogoMedia
            type="video"
            className="w-11 h-11 rounded-xl bg-black/60 border border-white/10 shadow-[0_0_20px_rgba(56,189,248,0.25)] flex-shrink-0"
            skeletonClassName="rounded-xl"
          />

          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[13px] font-semibold text-white tracking-tight">Compiling Skill Specification</h3>
              <span className="px-1.5 py-0.5 rounded text-[9.5px] font-mono font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                ACTIVE
              </span>
            </div>
            <p className="text-[11px] text-white/45 mt-0.5 truncate max-w-[420px]">
              {prompt || "Synthesizing demonstrated workflow into deterministic schema"}
            </p>
          </div>
        </div>

        {/* Live Telemetry Chips & Cancel */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/[0.03] border border-white/[0.07] text-[10.5px] text-white/60 font-mono">
            <Activity className="w-3 h-3 text-emerald-400" />
            <span>{elapsedSec}s</span>
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/[0.03] border border-white/[0.07] text-[10.5px] text-white/60 font-mono">
            <Zap className="w-3 h-3 text-emerald-400" />
            <span>Model Pool</span>
          </div>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="p-1 rounded-md text-white/30 hover:text-white/80 hover:bg-white/[0.05] transition-colors ml-1"
              title="Cancel compilation"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Compiler Multi-Stage Progress Pipeline */}
      <div className="relative py-4 space-y-2.5">
        {COMPILATION_STAGES.map((stage, idx) => {
          const isDone = idx < activeStageIndex;
          const isCurrent = idx === activeStageIndex;

          return (
            <div
              key={stage.id}
              className={`flex items-start gap-3 p-2.5 rounded-lg border transition-all duration-200 ${
                isCurrent
                  ? "bg-emerald-500/[0.04] border-emerald-500/25 shadow-[0_0_12px_rgba(16,185,129,0.06)]"
                  : isDone
                  ? "bg-white/[0.015] border-white/[0.04] opacity-80"
                  : "bg-transparent border-transparent opacity-35"
              }`}
            >
              {/* Stage Status Icon */}
              <div className="mt-0.5 flex-shrink-0">
                {isDone ? (
                  <div className="flex items-center justify-center w-4 h-4 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-400">
                    <Check className="w-2.5 h-2.5 stroke-[3]" />
                  </div>
                ) : isCurrent ? (
                  <div className="relative flex items-center justify-center w-4 h-4 rounded-full bg-emerald-500/20 border border-emerald-500/50">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                  </div>
                ) : (
                  <div className="w-4 h-4 rounded-full border border-white/20 bg-white/[0.02]" />
                )}
              </div>

              {/* Stage Description */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`text-[11.5px] font-medium tracking-tight ${
                      isCurrent ? "text-emerald-300" : isDone ? "text-white/80" : "text-white/40"
                    }`}
                  >
                    {stage.label}
                  </span>
                  {isCurrent && (
                    <span className="text-[10px] font-mono text-emerald-400/80 animate-pulse">processing...</span>
                  )}
                  {isDone && (
                    <span className="text-[10px] font-mono text-white/35">verified</span>
                  )}
                </div>
                <p className="text-[10.5px] text-white/40 mt-0.5 truncate">{stage.sub}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Bottom Live Synthesis Log Stream */}
      <div className="relative pt-3 border-t border-white/[0.06] flex items-center justify-between text-[10.5px] font-mono text-white/40">
        <div className="flex items-center gap-2 truncate">
          <Terminal className="w-3.5 h-3.5 text-white/30 flex-shrink-0" />
          <span className="truncate">
            {activeStageIndex === 0 && `Analyzing ${eventsCount || 1} captured interaction events…`}
            {activeStageIndex === 1 && `Isolating target application context (${environment})…`}
            {activeStageIndex === 2 && `Synthesizing dynamic parameter definitions…`}
            {activeStageIndex >= 3 && `Finalizing deterministic contract for review…`}
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0 text-white/30">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400/60" />
          <span>Synthesizing Schema</span>
        </div>
      </div>
    </div>
  );
};
