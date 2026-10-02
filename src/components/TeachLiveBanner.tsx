import React from "react";
import { Check, Trash2, Globe, Monitor, Radio } from "lucide-react";

interface TeachLiveBannerProps {
  isTeaching: boolean;
  timerSeconds: number;
  prompt: string;
  environment: string;
  eventsCount: number;
  recentActions: string[];
  onFinish: () => void;
  onDiscard: () => void;
}

export const TeachLiveBanner: React.FC<TeachLiveBannerProps> = ({
  isTeaching,
  timerSeconds,
  prompt,
  environment,
  eventsCount,
  recentActions,
  onFinish,
  onDiscard,
}) => {
  if (!isTeaching) return null;

  const formatTimer = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const remaining = sec % 60;
    return `${mins.toString().padStart(2, "0")}:${remaining.toString().padStart(2, "0")}`;
  };

  const lastAction = recentActions.length > 0 ? recentActions[recentActions.length - 1] : null;

  return (
    <div className="w-full max-w-2xl mx-auto my-2 p-3 bg-slate-900/90 backdrop-blur-md border border-rose-500/40 rounded-xl shadow-xl shadow-rose-950/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-in slide-in-from-top-2 duration-200">
      {/* Left Details */}
      <div className="flex items-center gap-3">
        {/* Blinking REC indicator */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-rose-500/20 border border-rose-500/40 text-rose-300 font-mono text-xs font-semibold shrink-0">
          <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
          <span>REC {formatTimer(timerSeconds)}</span>
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-100 truncate">
              {prompt || "Demonstrating New Workflow"}
            </span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700/50 flex items-center gap-1 shrink-0">
              {environment === "browser" ? <Globe className="w-2.5 h-2.5" /> : <Monitor className="w-2.5 h-2.5" />}
              {environment === "browser" ? "Browser" : "Desktop"}
            </span>
          </div>

          <div className="text-[11px] text-slate-400 flex items-center gap-1.5 mt-0.5 truncate">
            {eventsCount === 0 ? (
              <span className="text-amber-400/90 flex items-center gap-1">
                <Radio className="w-3 h-3 animate-pulse" />
                Perform your steps in Chrome or active app...
              </span>
            ) : (
              <span className="text-emerald-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                {eventsCount} events recorded {lastAction && `• Latest: ${lastAction}`}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
        <button
          type="button"
          onClick={onDiscard}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
          title="Discard demonstration"
        >
          <Trash2 className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Discard</span>
        </button>

        <button
          type="button"
          onClick={onFinish}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-md shadow-emerald-600/30 transition-all active:scale-95"
        >
          <Check className="w-3.5 h-3.5" />
          <span>Finish & Review</span>
        </button>
      </div>
    </div>
  );
};
