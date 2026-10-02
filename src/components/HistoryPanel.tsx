import React, { useState, useMemo } from 'react';
import {
  Search,
  Trash2,
  Copy,
  Check,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  X,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  CornerDownLeft,
  User,
  Bot,
  Layers,
  Shield,
} from 'lucide-react';
import { HistoryItem } from '../types/nexus';
import { classifyQuerySafety } from '../services/safetyFilter';
import nexusLogo from '../assets/nexus-logo.png';

interface HistoryPanelProps {
  items: HistoryItem[];
  onRerunPrompt: (prompt: string) => void;
  onInsertPrompt: (prompt: string) => void;
  onClearAll: () => void;
  onDeleteItem: (id: string) => void;
  onClose: () => void;
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  items,
  onRerunPrompt,
  onInsertPrompt,
  onClearAll,
  onDeleteItem,
  onClose,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Safe filtering: Exclude NSFW, sexually explicit, and sensitive records from the History Panel display
  const safeItems = useMemo(() => {
    return items.filter((item) => {
      // 1. Explicitly flagged sensitive or recommendation ineligible
      if (item.is_sensitive === true || item.recommendation_eligible === false) {
        return false;
      }
      // 2. Classify prompt for legacy or unclassified history entries
      const safetyPrompt = classifyQuerySafety(item.prompt || '');
      if (safetyPrompt.is_sensitive || !safetyPrompt.recommendation_eligible) {
        return false;
      }
      // 3. Classify response content to prevent explicit textual output leakage
      if (item.finalResponse) {
        const safetyResponse = classifyQuerySafety(item.finalResponse);
        if (safetyResponse.is_sensitive && !safetyResponse.recommendation_eligible) {
          return false;
        }
      }
      return true;
    });
  }, [items]);

  const sensitiveCount = items.length - safeItems.length;

  // Default first item expanded if 3 or fewer items, else collapsed
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    if (safeItems.length > 0) {
      initial.add(safeItems[0].id);
    }
    return initial;
  });

  const toggleExpand = (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const expandAll = () => {
    setExpandedIds(new Set(safeItems.map((it) => it.id)));
  };

  const collapseAll = () => {
    setExpandedIds(new Set());
  };

  const filteredItems = useMemo(() => {
    return safeItems.filter(
      (item) =>
        item.prompt.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (item.finalResponse && item.finalResponse.toLowerCase().includes(searchTerm.toLowerCase())) ||
        (item.error && item.error.toLowerCase().includes(searchTerm.toLowerCase()))
    );
  }, [safeItems, searchTerm]);

  const formatTime = (timestamp: number) => {
    const diffMs = Date.now() - timestamp;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHr = Math.floor(diffMin / 60);

    if (diffSec < 60) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    return new Date(timestamp).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleCopy = (id: string, text: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1800);
  };

  return (
    <div className="flex flex-col text-neutral-200 bg-transparent select-none">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.08]">
        <div className="flex items-center space-x-2.5">
          <div className="w-6 h-6 rounded-md bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center p-0.5 shadow-[0_0_8px_rgba(56,189,248,0.2)]">
            <img src={nexusLogo} alt="Nexus" className="w-4 h-4 object-contain drop-shadow-[0_0_4px_rgba(56,189,248,0.6)]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-white tracking-wide">Command & Response History</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/10 text-neutral-300 font-medium">
                {safeItems.length} {safeItems.length === 1 ? 'entry' : 'entries'}
              </span>
              {sensitiveCount > 0 && (
                <span
                  className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-medium"
                  title={`${sensitiveCount} sensitive ${sensitiveCount === 1 ? 'search' : 'searches'} filtered for privacy`}
                >
                  <Shield className="w-2.5 h-2.5" />
                  <span>{sensitiveCount} filtered</span>
                </span>
              )}
            </div>
            <div className="text-[10px] text-white/40">Review past user prompts and AI responses</div>
          </div>
        </div>
        <div className="flex items-center space-x-1.5">
          {safeItems.length > 1 && (
            <button
              type="button"
              onClick={expandedIds.size === safeItems.length ? collapseAll : expandAll}
              className="text-[10px] text-neutral-400 hover:text-white px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] transition-colors"
            >
              {expandedIds.size === safeItems.length ? 'Collapse All' : 'Expand All'}
            </button>
          )}
          {safeItems.length > 0 && (
            <button
              type="button"
              onClick={onClearAll}
              title="Clear all history"
              className="icon-btn text-neutral-400 hover:text-rose-400 hover:bg-rose-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            title="Close (Esc)"
            className="icon-btn text-neutral-400 hover:text-white"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      {safeItems.length > 2 && (
        <div className="px-5 pt-3 pb-1">
          <div className="relative flex items-center">
            <Search className="w-3.5 h-3.5 absolute left-3 text-neutral-500" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search prompts, responses or keywords..."
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-neutral-500 outline-none focus:border-cyan-500/40 transition-colors"
            />
          </div>
        </div>
      )}

      {/* History List */}
      <div className="overflow-y-auto px-5 py-3 space-y-2.5 max-h-[420px] custom-scrollbar">
        {safeItems.length === 0 ? (
          <div className="py-12 text-center space-y-2">
            <div className="w-10 h-10 rounded-full bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mx-auto text-neutral-500">
              <Clock className="w-5 h-5" />
            </div>
            <div className="text-neutral-300 text-xs font-medium">No Command History Yet</div>
            <p className="text-[11px] text-neutral-500 max-w-xs mx-auto">
              Every voice command, prompt, and action NEXUS executes will appear here for reviewing prompts and AI responses.
            </p>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="py-8 text-center text-neutral-500 text-xs">
            No matching items found for "{searchTerm}"
          </div>
        ) : (
          filteredItems.map((item) => {
            const isExpanded = expandedIds.has(item.id);
            return (
              <div
                key={item.id}
                onClick={() => toggleExpand(item.id)}
                className={`group relative rounded-xl border transition-all cursor-pointer ${
                  isExpanded
                    ? 'bg-white/[0.04] border-cyan-500/30 shadow-lg shadow-black/20'
                    : 'bg-white/[0.02] hover:bg-white/[0.05] border-white/[0.06] hover:border-white/[0.12]'
                }`}
              >
                {/* Header Summary Row */}
                <div className="p-3 pb-2.5 flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      {/* Status badge */}
                      {item.status === 'completed' && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                          <CheckCircle2 className="w-2.5 h-2.5" />
                          <span>Completed</span>
                        </span>
                      )}
                      {item.status === 'running' && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-400/30 animate-pulse">
                          <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                          <span>Running</span>
                        </span>
                      )}
                      {item.status === 'failed' && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30">
                          <XCircle className="w-2.5 h-2.5" />
                          <span>Failed</span>
                        </span>
                      )}
                      {item.status === 'cancelled' && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
                          <AlertCircle className="w-2.5 h-2.5" />
                          <span>Cancelled</span>
                        </span>
                      )}

                      <span className="text-[10px] font-mono text-neutral-400">
                        {formatTime(item.timestamp)}
                      </span>

                      {item.mode && (
                        <span className="uppercase tracking-wider px-1.5 py-0.2 rounded bg-white/5 text-[9px] text-neutral-400 font-mono">
                          {item.mode}
                        </span>
                      )}

                      {typeof item.stepCount === 'number' && item.stepCount > 0 && (
                        <span className="inline-flex items-center gap-1 text-[9px] text-neutral-400 font-mono">
                          <Layers className="w-2.5 h-2.5 text-neutral-500" />
                          <span>{item.stepCount} {item.stepCount === 1 ? 'step' : 'steps'}</span>
                        </span>
                      )}
                    </div>

                    {/* Collapsed prompt preview */}
                    <div className="flex items-center gap-2">
                      <User className="w-3 h-3 text-cyan-400 flex-shrink-0" />
                      <span className="font-medium text-white text-xs tracking-[-0.01em] line-clamp-1 group-hover:text-cyan-200 transition-colors">
                        {item.prompt}
                      </span>
                    </div>
                  </div>

                  {/* Expand / Collapse toggle icon */}
                  <div className="flex items-center gap-1 flex-shrink-0 pt-0.5">
                    <button
                      type="button"
                      onClick={(e) => toggleExpand(item.id, e)}
                      title={isExpanded ? 'Collapse' : 'Expand full prompt and response'}
                      className="p-1 rounded text-neutral-400 hover:text-white hover:bg-white/10 transition-colors"
                    >
                      {isExpanded ? (
                        <ChevronUp className="w-4 h-4 text-cyan-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-neutral-400" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Expanded Inspection View: Prompt + AI Response */}
                {isExpanded && (
                  <div className="px-3 pb-3 pt-1 space-y-3 border-t border-white/[0.06] mt-1 text-xs">
                    {/* User Prompt Box */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-neutral-400 font-mono uppercase tracking-wider">
                        <span className="flex items-center gap-1.5 text-cyan-300">
                          <User className="w-3 h-3" />
                          <span>User Prompt</span>
                        </span>
                        <button
                          type="button"
                          onClick={(e) => handleCopy(`p_${item.id}`, item.prompt, e)}
                          title="Copy prompt"
                          className="flex items-center gap-1 hover:text-white transition-colors p-0.5"
                        >
                          {copiedId === `p_${item.id}` ? (
                            <Check className="w-3 h-3 text-emerald-400" />
                          ) : (
                            <Copy className="w-3 h-3" />
                          )}
                          <span>{copiedId === `p_${item.id}` ? 'Copied' : 'Copy'}</span>
                        </button>
                      </div>
                      <div className="p-2.5 rounded-lg bg-black/30 border border-white/[0.05] text-white/90 text-xs font-normal leading-relaxed select-text whitespace-pre-wrap">
                        {item.prompt}
                      </div>
                    </div>

                    {/* AI Response Box */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-neutral-400 font-mono uppercase tracking-wider">
                        <span className="flex items-center gap-1.5 text-emerald-300">
                          <Bot className="w-3 h-3" />
                          <span>AI Response</span>
                        </span>
                        {item.finalResponse && (
                          <button
                            type="button"
                            onClick={(e) => handleCopy(`r_${item.id}`, item.finalResponse || '', e)}
                            title="Copy AI response"
                            className="flex items-center gap-1 hover:text-white transition-colors p-0.5"
                          >
                            {copiedId === `r_${item.id}` ? (
                              <Check className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                            <span>{copiedId === `r_${item.id}` ? 'Copied' : 'Copy'}</span>
                          </button>
                        )}
                      </div>

                      {item.finalResponse ? (
                        <div className="p-3 rounded-lg bg-emerald-500/[0.04] border border-emerald-500/20 text-emerald-100/90 text-xs leading-relaxed select-text whitespace-pre-wrap max-h-[220px] overflow-y-auto custom-scrollbar">
                          {item.finalResponse}
                        </div>
                      ) : item.error ? (
                        <div className="p-3 rounded-lg bg-rose-500/[0.05] border border-rose-500/20 text-rose-200/90 text-xs leading-relaxed select-text whitespace-pre-wrap">
                          <div className="font-semibold text-rose-300 mb-0.5 flex items-center gap-1">
                            <AlertCircle className="w-3.5 h-3.5" />
                            <span>Execution Error:</span>
                          </div>
                          {item.error}
                        </div>
                      ) : item.status === 'running' ? (
                        <div className="p-3 rounded-lg bg-cyan-500/[0.04] border border-cyan-500/20 text-cyan-200/80 text-xs italic">
                          Task is currently executing...
                        </div>
                      ) : (
                        <div className="p-2.5 rounded-lg bg-black/20 border border-white/[0.04] text-neutral-500 text-xs italic">
                          Action completed without textual response.
                        </div>
                      )}
                    </div>

                    {/* Bottom Action Buttons */}
                    <div className="flex items-center justify-between pt-1 border-t border-white/[0.04]">
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onInsertPrompt(item.prompt);
                          }}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/[0.05] hover:bg-white/[0.1] text-neutral-300 hover:text-white text-[11px] transition-colors"
                          title="Put prompt into search bar for editing"
                        >
                          <CornerDownLeft className="w-3 h-3" />
                          <span>Edit in Search</span>
                        </button>

                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteItem(item.id);
                          }}
                          className="p-1 rounded-md text-neutral-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                          title="Delete this history entry"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      {/* Explicit Re-run Button */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRerunPrompt(item.prompt);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 hover:text-cyan-200 border border-cyan-400/30 font-medium text-[11px] transition-all hover:scale-[1.02] active:scale-[0.98]"
                        title="Re-run this prompt with NEXUS"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Re-run</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
