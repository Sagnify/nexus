import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Minimize2,
  Table,
  ChevronDown,
  ChevronUp,
  Zap,
  Loader2,
  RefreshCw,
  Eye,
} from 'lucide-react';

interface ExcelCopilotProps {
  hwnd?: string | null;
  workbook?: string | null;
}

interface ExcelContextData {
  workbook_name?: string;
  sheet_name?: string;
  active_cell?: string;
  selection?: string;
  used_range?: string;
  headers?: string[];
  columns?: Array<{ letter: string; name: string; type?: string }>;
  sample_rows?: Array<Record<string, any>>;
  row_count?: number;
  col_count?: number;
  has_tables?: boolean;
}

export const ExcelCopilot: React.FC<ExcelCopilotProps> = ({ hwnd, workbook }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<{
    success: boolean;
    message: string;
    plan?: any[];
    error?: string;
    vlmValidation?: {
      passed: boolean;
      confidence?: number;
      observation?: string;
      source?: string;
    };
    replanApplied?: boolean;
  } | null>(null);
  const [context, setContext] = useState<ExcelContextData | null>(null);
  const [showContextDetails, setShowContextDetails] = useState(false);
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const numericHwnd = hwnd ? parseInt(hwnd, 10) : undefined;
  const currentWorkbookName = workbook || context?.workbook_name || 'Excel Workbook';

  // Fetch real-time deep context from backend
  const fetchContext = useCallback(async () => {
    setIsLoadingContext(true);
    try {
      const params = new URLSearchParams();
      if (hwnd) params.set('hwnd', hwnd);
      if (workbook) params.set('workbook_name', workbook);

      const res = await fetch(`http://127.0.0.1:8000/api/nexus/excel/context?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (data.context) {
          setContext(data.context);
        }
      }
    } catch (err) {
      console.warn('Could not fetch Excel context:', err);
    } finally {
      setIsLoadingContext(false);
    }
  }, [hwnd, workbook]);

  // Initial context load
  useEffect(() => {
    fetchContext();
  }, [fetchContext]);

  useEffect(() => {
    document.body.classList.add('excel-copilot-view');
    return () => {
      document.body.classList.remove('excel-copilot-view');
    };
  }, []);

  // Sync window size with Electron based on collapsed / expanded state
  useEffect(() => {
    if (numericHwnd && window.electronAPI?.resizeExcelCopilot) {
      if (isExpanded) {
        const height = showContextDetails ? 480 : 380;
        window.electronAPI.resizeExcelCopilot(numericHwnd, 460, height);
      } else {
        window.electronAPI.resizeExcelCopilot(numericHwnd, 160, 48);
      }
    }
  }, [isExpanded, showContextDetails, numericHwnd]);

  // Focus input when expanded
  useEffect(() => {
    if (isExpanded) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    }
  }, [isExpanded]);

  const handleExecute = async (queryToRun?: string) => {
    const text = (queryToRun || instruction).trim();
    if (!text || isRunning) return;

    setIsRunning(true);
    setStatusMessage('Analyzing spreadsheet and compiling Excel operation...');
    setLastResult(null);

    try {
      const res = await fetch('http://127.0.0.1:8000/api/nexus/excel/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instruction: text,
          hwnd: numericHwnd,
          workbook_name: workbook || undefined,
        }),
      });

      const data = await res.json();
      if (data.success) {
        setLastResult({
          success: true,
          message: data.message || 'Operation executed and verified in Excel.',
          plan: data.plan,
          vlmValidation: data.vlm_validation,
          replanApplied: data.replan_applied,
        });
        if (data.updated_context) {
          setContext(data.updated_context);
        } else {
          fetchContext();
        }
        setInstruction('');
      } else {
        setLastResult({
          success: false,
          message: data.error || data.message || 'Operation could not be completed.',
          error: data.error,
        });
      }
    } catch (err: any) {
      setLastResult({
        success: false,
        message: err?.message || 'Connection error with NEXUS backend.',
        error: String(err),
      });
    } finally {
      setIsRunning(false);
      setStatusMessage(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleExecute();
    } else if (e.key === 'Escape') {
      setIsExpanded(false);
    }
  };

  // Quick Action Chips
  const quickActions = [
    { label: 'Σ Sum Sales', query: 'Calculate total sales' },
    { label: 'Avg Sales', query: 'Calculate the average sales' },
    { label: 'Sort High → Low', query: 'Sort the table by sales from highest to lowest' },
    { label: 'Highlight > 10k', query: 'Highlight sales greater than 10000' },
    { label: 'Pivot Table', query: 'Create a pivot table showing total sales by region' },
    { label: 'Remove Duplicates', query: 'Remove duplicate rows' },
    { label: 'XLOOKUP Category', query: 'Use XLOOKUP to bring category into column F' },
    { label: 'Split Full Name', query: 'Split the full name into first and last name' },
  ];

  // Collapsed Mode: Small Floating NEXUS badge
  if (!isExpanded) {
    return (
      <div className="w-[160px] h-[48px] p-1 flex items-center justify-center select-none">
        <button
          onClick={() => setIsExpanded(true)}
          className="group relative flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900/95 hover:bg-slate-800 border border-cyan-500/50 hover:border-cyan-400 shadow-[0_0_20px_rgba(6,182,212,0.45)] backdrop-blur-md transition-all duration-200 cursor-pointer active:scale-95"
          title={`NEXUS Floating Copilot - Click to command ${currentWorkbookName}`}
        >
          <div className="relative flex items-center justify-center w-5 h-5 rounded-full bg-cyan-500/20 text-cyan-400">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping absolute" />
            <span className="w-2 h-2 rounded-full bg-cyan-400 relative" />
          </div>
          <span className="text-xs font-semibold text-slate-100 group-hover:text-white tracking-wide">
            NEXUS
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-950/90 text-cyan-300 font-mono font-semibold border border-cyan-500/40">
            Excel
          </span>
        </button>
      </div>
    );
  }

  // Expanded Mode: Floating Command Window
  return (
    <div className="w-full h-full p-2 flex flex-col font-sans select-none animate-in fade-in zoom-in-95 duration-150">
      <div className="flex-1 flex flex-col rounded-2xl bg-slate-950/95 border border-cyan-500/40 shadow-[0_10px_35px_rgba(0,0,0,0.8),0_0_25px_rgba(6,182,212,0.25)] backdrop-blur-xl overflow-hidden text-slate-200">
        
        {/* Header Bar */}
        <div className="flex items-center justify-between px-3.5 py-2.5 bg-gradient-to-r from-slate-900/90 via-slate-900/70 to-slate-950 border-b border-cyan-500/20">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex items-center justify-center w-6 h-6 rounded-lg bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 shadow-[0_0_10px_rgba(6,182,212,0.3)]">
              <Sparkles className="w-3.5 h-3.5" />
            </div>
            <div className="flex flex-col min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold text-white tracking-wide">NEXUS</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-900/50 text-cyan-300 border border-cyan-500/30 font-medium truncate max-w-[140px]">
                  {currentWorkbookName}
                </span>
                {context?.sheet_name && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                    {context.sheet_name}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={fetchContext}
              disabled={isLoadingContext}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-cyan-300 transition-colors"
              title="Refresh spreadsheet context"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoadingContext ? 'animate-spin text-cyan-400' : ''}`} />
            </button>
            <button
              onClick={() => setIsExpanded(false)}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-100 transition-colors"
              title="Minimize to floating icon"
            >
              <Minimize2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Active Range & Selection Status */}
        {context && (
          <div className="flex items-center justify-between px-3.5 py-1.5 bg-slate-900/40 border-b border-slate-800/80 text-[11px] text-slate-400">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-slate-300">
                <Table className="w-3 h-3 text-cyan-400" />
                <span>Used: {context.used_range || 'Empty'}</span>
              </span>
              {context.selection && (
                <span className="text-cyan-400/80 font-mono">
                  Sel: {context.selection}
                </span>
              )}
            </div>
            <button
              onClick={() => setShowContextDetails(!showContextDetails)}
              className="flex items-center gap-0.5 text-cyan-400 hover:text-cyan-300 text-[10px] font-medium"
            >
              <span>{showContextDetails ? 'Hide Structure' : 'Inspect Columns'}</span>
              {showContextDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          </div>
        )}

        {/* Collapsible Context Inspector */}
        {showContextDetails && context && (
          <div className="px-3.5 py-2 bg-slate-900/90 border-b border-slate-800 max-h-36 overflow-y-auto text-xs space-y-1.5">
            <div className="text-[11px] font-semibold text-cyan-300">Detected Columns & Types:</div>
            <div className="flex flex-wrap gap-1">
              {context.columns && context.columns.length > 0 ? (
                context.columns.map((c, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-200"
                  >
                    <span className="font-mono text-cyan-400 font-bold">{c.letter}:</span>
                    <span>{c.name}</span>
                    {c.type && <span className="text-[9px] text-slate-400">({c.type})</span>}
                  </span>
                ))
              ) : (
                <span className="text-slate-500 italic">No column headers detected yet</span>
              )}
            </div>
          </div>
        )}

        {/* Input Bar */}
        <div className="p-3 flex flex-col gap-2">
          <div className="relative flex items-center">
            <input
              ref={inputRef}
              type="text"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning}
              placeholder="What should I do in Excel? (e.g. Calculate total sales...)"
              className="w-full pr-24 pl-3 py-2 rounded-xl bg-slate-900/90 border border-slate-700 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 outline-none text-xs text-white placeholder-slate-500 transition-all"
            />
            <button
              onClick={() => handleExecute()}
              disabled={isRunning || !instruction.trim()}
              className="absolute right-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-cyan-600 to-cyan-500 hover:from-cyan-500 hover:to-cyan-400 disabled:opacity-40 disabled:pointer-events-none text-white text-xs font-semibold flex items-center gap-1.5 shadow-[0_0_10px_rgba(6,182,212,0.3)] transition-all cursor-pointer"
            >
              {isRunning ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Acting...</span>
                </>
              ) : (
                <>
                  <Zap className="w-3.5 h-3.5" />
                  <span>Execute</span>
                </>
              )}
            </button>
          </div>

          {/* Quick Suggestions Chips */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {quickActions.map((action, i) => (
              <button
                key={i}
                onClick={() => {
                  setInstruction(action.query);
                  handleExecute(action.query);
                }}
                disabled={isRunning}
                className="px-2 py-1 rounded-md bg-slate-900/80 hover:bg-cyan-950/60 border border-slate-800 hover:border-cyan-500/40 text-[10px] text-slate-300 hover:text-cyan-300 transition-all cursor-pointer active:scale-95"
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>

        {/* Live Status & Verification Feedback */}
        {(statusMessage || lastResult) && (
          <div className="px-3 pb-3">
            {statusMessage && (
              <div className="flex items-center gap-2 p-2 rounded-lg bg-cyan-950/40 border border-cyan-500/30 text-xs text-cyan-300">
                <Loader2 className="w-4 h-4 animate-spin text-cyan-400 shrink-0" />
                <span className="truncate">{statusMessage}</span>
              </div>
            )}

            {lastResult && (
              <div
                className={`flex items-start gap-2 p-2.5 rounded-xl border text-xs ${
                  lastResult.success
                    ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.15)]'
                    : 'bg-rose-950/40 border-rose-500/40 text-rose-300 shadow-[0_0_15px_rgba(244,63,94,0.15)]'
                }`}
              >
                {lastResult.success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                )}
                <div className="flex flex-col min-w-0">
                  <span className="font-semibold">{lastResult.message}</span>
                  {lastResult.vlmValidation && (
                    <div className="flex items-center gap-1.5 mt-1 text-[10px] text-cyan-300 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/30 w-fit">
                      <Eye className="w-3 h-3 text-cyan-400" />
                      <span>
                        {lastResult.replanApplied ? 'Auto-Corrected & Audited by VLM' : 'Audited by VLM'}
                        {lastResult.vlmValidation.confidence ? ` (${Math.round(lastResult.vlmValidation.confidence * 100)}%)` : ''}
                      </span>
                    </div>
                  )}
                  {lastResult.plan && lastResult.plan.length > 0 && (
                    <span className="text-[10px] text-slate-400 mt-0.5 font-mono">
                      ✓ Tool: {lastResult.plan.map((p) => p.tool).join(', ')} verified in Excel
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
};
