import React, { useState } from 'react';
import {
  Pause,
  Play,
  ChevronDown,
  ChevronUp,
  Check,
  Loader2,
  X,
  AlertCircle,
  HelpCircle,
  FolderOpen,
  Folder,
  FileSpreadsheet,
  FileText,
  Presentation,
  Monitor,
  Download,
} from 'lucide-react';

import { PlanStep, PermissionRequest, UserInputRequest, IssueItem } from '../types/nexus';
import { NexusLogoMedia } from './NexusLogoMedia';

export interface AutomationPillProps {
  isRunning: boolean;
  isPaused?: boolean;
  statusText?: string;
  plan: PlanStep[];
  issues?: IssueItem[];
  onPause: () => void;
  onResume: () => void;
  onCancel?: () => void;
  onReset?: () => void;
  onOpenFullView?: () => void;
  finalResponse?: string | null;
  error?: string | null;
  pendingPermission?: PermissionRequest | null;
  onApprovePermission?: () => void;
  onRejectPermission?: () => void;
  userInputRequest?: UserInputRequest | null;
  onSubmitUserInput?: (val: string) => void;
  onAutoDismiss?: () => void;
}

// OS-level hardware and system automation — these require the floating pill window
export const HARDWARE_TOOLS = new Set([
  'inspect_screen', 'press_hotkey', 'type_text', 'press_key',
  'click_mouse', 'activate_window', 'dismiss_overlay',
  'play_music', 'media_control', 'run_command',
  'read_file', 'write_file', 'delete_file', 'list_directory', 'search_files',
  'docx_create', 'docx_open', 'docx_add_title', 'docx_add_heading',
  'docx_add_paragraph', 'docx_add_bullet', 'docx_add_numbered',
  'docx_add_table', 'docx_add_page_break', 'docx_add_image',
  'docx_save', 'docx_read', 'docx_verify', 'word_format_active',
  'spreadsheet_create', 'spreadsheet_open', 'spreadsheet_list_sheets',
  'spreadsheet_create_sheet', 'spreadsheet_rename_sheet', 'spreadsheet_read_cell',
  'spreadsheet_read_range', 'spreadsheet_read_sheet', 'spreadsheet_write_cell',
  'spreadsheet_write_range', 'spreadsheet_add_formula', 'spreadsheet_format_range',
  'spreadsheet_create_table', 'spreadsheet_create_chart', 'spreadsheet_save',
  'spreadsheet_read', 'spreadsheet_verify', 'excel_format_active',
  'presentation_create', 'presentation_save', 'presentation_read', 'presentation_verify',
]);

// Browser automation — runs inside a browser tab, no pill needed
export const BROWSER_TOOLS = new Set([
  'browser_get_tabs', 'browser_switch_tab', 'browser_navigate',
  'browser_inspect', 'browser_click', 'browser_type',
  'browser_select', 'browser_press', 'browser_wait',
  'browser_dismiss_popup', 'browser_execute_js',
]);

export const AUTOMATION_TOOLS = new Set([...HARDWARE_TOOLS, ...BROWSER_TOOLS]);

export const renderChoiceChip = (opt: string) => {
  const l = opt.toLowerCase();
  if (l.includes('browse') || l.includes('explorer') || l.includes('select')) {
    return (
      <span className="flex items-center gap-1.5 font-semibold text-sky-300">
        <FolderOpen className="w-3.5 h-3.5 text-sky-400" />
        <span>{opt}</span>
      </span>
    );
  }
  if (l.endsWith('.pptx') || l.endsWith('.ppt') || l.includes('presentation') || l.includes('powerpoint') || l.includes('slides')) {
    return (
      <span className="flex items-center gap-1.5 text-orange-400">
        <Presentation className="w-3.5 h-3.5 text-orange-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  if (l === 'desktop' || l.startsWith('desktop')) {
    return (
      <span className="flex items-center gap-1.5 text-cyan-300">
        <Monitor className="w-3.5 h-3.5 text-cyan-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  if (l === 'documents' || l.startsWith('documents')) {
    return (
      <span className="flex items-center gap-1.5 text-blue-300">
        <FileText className="w-3.5 h-3.5 text-blue-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  if (l === 'downloads' || l.startsWith('downloads')) {
    return (
      <span className="flex items-center gap-1.5 text-purple-300">
        <Download className="w-3.5 h-3.5 text-purple-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  if (l.endsWith('.xlsx') || l.endsWith('.xls') || l.includes('sheet') || l.includes('excel')) {
    return (
      <span className="flex items-center gap-1.5 text-emerald-300">
        <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  if (l.endsWith('.docx') || l.endsWith('.doc') || l.includes('word') || l.includes('document')) {
    return (
      <span className="flex items-center gap-1.5 text-blue-300">
        <FileText className="w-3.5 h-3.5 text-blue-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  if (opt.includes('/') || opt.includes('\\')) {
    return (
      <span className="flex items-center gap-1.5 text-amber-300">
        <Folder className="w-3.5 h-3.5 text-amber-400" />
        <span className="truncate max-w-[200px]">{opt}</span>
      </span>
    );
  }
  return <span>{opt}</span>;
};


export const AutomationPill: React.FC<AutomationPillProps> = ({
  isRunning,
  isPaused = false,
  statusText,
  plan = [],
  issues = [],
  onPause,
  onResume,
  onCancel,
  onReset,
  finalResponse,
  error,
  pendingPermission,
  onApprovePermission,
  onRejectPermission,
  userInputRequest,
  onSubmitUserInput,
  onAutoDismiss,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showErrorDrawer, setShowErrorDrawer] = useState(false);
  const [customInputText, setCustomInputText] = useState('');

  // Accumulate and deduplicate all issues across runtime, steps, and errors
  const allIssues: IssueItem[] = React.useMemo(() => {
    const list: IssueItem[] = [];
    const seen = new Set<string>();

    const add = (item: IssueItem) => {
      const key = (item.message || '').trim().toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      list.push(item);
    };

    if (issues && issues.length > 0) {
      issues.forEach(add);
    }
    if (error) {
      add({
        type: 'error',
        message: error,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      });
    }
    plan.forEach((s, idx) => {
      if (s.error) {
        add({
          type: 'step_error',
          step: idx + 1,
          message: `${s.title}: ${s.error}`,
        });
      } else if (s.status === 'failed' && s.result) {
        add({
          type: 'step_failed',
          step: idx + 1,
          message: `${s.title}: ${s.result}`,
        });
      }
    });

    return list;
  }, [issues, error, plan]);

  const hasIssues = allIssues.length > 0;
  const isCompleted = !isRunning && !isPaused && (finalResponse !== null || (plan.length > 0 && plan.every(s => s.status === 'completed')));
  const isFailed = !isRunning && !isPaused && (error !== null || plan.some(s => s.status === 'failed'));

  // Auto-collapse expanded details when task completes
  React.useEffect(() => {
    if (isCompleted) {
      setIsExpanded(false);
      setShowErrorDrawer(false);
    }
  }, [isCompleted]);

  // Auto-dismiss pill after showing success message for 4.0 seconds
  React.useEffect(() => {
    if (!isCompleted) return;
    const timer = setTimeout(() => {
      onAutoDismiss?.();
    }, 4000);
    return () => clearTimeout(timer);
  }, [isCompleted, onAutoDismiss]);

  const currentStep =
    plan.find(s => s.status === 'running') ||
    plan.find(s => s.status === 'pending') ||
    plan[plan.length - 1];

  const totalSteps = plan.length;
  const completedCount = plan.filter(s => s.status === 'completed').length;
  const currentIdx = currentStep ? plan.findIndex(s => s.id === currentStep.id) : 0;
  const progress = isCompleted ? 100 : totalSteps > 0 ? (completedCount / totalSteps) * 100 : 0;

  // Status string
  const statusLabel = userInputRequest
    ? 'Input Needed'
    : pendingPermission
    ? 'Requires approval'
    : isPaused
    ? 'Paused'
    : isRunning
    ? 'Automating'
    : isFailed
    ? 'Failed'
    : isCompleted
    ? 'Completed'
    : 'Pending';

  const statusClass = isPaused
    ? 'paused'
    : isFailed
    ? 'failed'
    : isCompleted
    ? 'completed'
    : '';

  // Step description
  const isGenericStatus = !statusText || !statusText.trim() || statusText === 'Automating' || statusText === 'Executing...' || /^Executing \d+ step\(s\)\.\.\.$/.test(statusText.trim());
  const liveAction = !isGenericStatus ? statusText : null;
  const activeStepDesc = currentStep?.description && (
    currentStep.description.toLowerCase().includes('screenshot') ||
    currentStep.description.toLowerCase().includes('validat') ||
    currentStep.description.toLowerCase().includes('vlm')
  ) ? currentStep.description : null;

  const stepLabel = userInputRequest
    ? userInputRequest.prompt
    : pendingPermission
    ? `Approval needed — ${currentStep?.title || 'system action'}`
    : liveAction
    ? liveAction
    : isRunning
    ? activeStepDesc || currentStep?.title || 'Executing action...'
    : isPaused
    ? currentStep?.title || 'Paused'
    : isFailed
    ? error || 'Encountered an issue'
    : isCompleted
    ? 'Task completed successfully'
    : totalSteps > 0
    ? `${completedCount} of ${totalSteps} steps completed`
    : 'System Automation';


  return (
    <div className="nexus-pill-root">
      <div className="nexus-widget">
        {/* ── Main Banner ── */}
        <div className={`nexus-banner ${isPaused ? 'paused' : ''}`}>
          {/* NEXUS Logo with Live Video Loader during execution with Skeleton */}
          <NexusLogoMedia
            type={isRunning && !isPaused ? "video" : "image"}
            className="nexus-logo"
            mediaClassName={isRunning && !isPaused ? "" : "nexus-logo-img"}
            title={isRunning && !isPaused ? "NEXUS Agent Running..." : "NEXUS Automation"}
          />

          {/* Content: Header, Step Label, Hairline Progress */}
          <div className="nexus-content" title={stepLabel}>
            <div className="nexus-header">
              <span className={`nexus-status ${statusClass}`}>
                {statusLabel}
              </span>
              <div className={`nexus-dot ${statusClass}`} />
            </div>

            <div className="nexus-step">
              {stepLabel}
            </div>

            <div className="nexus-progress-track">
              <div
                className={`nexus-progress-fill ${isRunning && progress === 0 ? 'indeterminate' : ''}`}
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          {/* Step Count */}
          {totalSteps > 0 && (
            <div className="nexus-step-count">
              {completedCount}/{totalSteps}
            </div>
          )}

          {/* Actions */}
          <div className="nexus-actions">
            {hasIssues && (
              <button
                type="button"
                onClick={() => setShowErrorDrawer(!showErrorDrawer)}
                className="nexus-btn nexus-btn-error"
                title="View Issues"
              >
                <AlertCircle className="w-2.5 h-2.5 shrink-0" strokeWidth={2.5} />
                <span>Issues ({allIssues.length})</span>
              </button>
            )}

            {pendingPermission ? (
              <>
                {onApprovePermission && (
                  <button
                    type="button"
                    onClick={onApprovePermission}
                    className="nexus-btn"
                    title="Approve Action"
                    style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', borderColor: 'rgba(52, 211, 153, 0.35)', fontWeight: 600 }}
                  >
                    Approve
                  </button>
                )}
                {onRejectPermission && (
                  <button
                    type="button"
                    onClick={onRejectPermission}
                    className="nexus-btn"
                    title="Deny Action"
                    style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#fca5a5', borderColor: 'rgba(239, 68, 68, 0.35)', fontWeight: 600 }}
                  >
                    Deny
                  </button>
                )}
              </>
            ) : (
              <button
                type="button"
                onClick={isPaused ? onResume : onPause}
                className="nexus-btn"
                title={isPaused ? 'Resume Automation' : 'Pause Automation'}
              >
                {isPaused ? (
                  <Play className="w-2.5 h-2.5 fill-current" strokeWidth={2.5} />
                ) : (
                  <Pause className="w-2.5 h-2.5" strokeWidth={2.5} />
                )}
              </button>
            )}

            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="nexus-btn"
              title="Toggle Steps List"
            >
              {isExpanded ? (
                <ChevronUp className="w-2.5 h-2.5" strokeWidth={2.5} />
              ) : (
                <ChevronDown className="w-2.5 h-2.5" strokeWidth={2.5} />
              )}
            </button>

            <button
              type="button"
              onClick={isRunning ? onCancel : onReset}
              className="nexus-btn"
              title="Dismiss / Quit Pill"
            >
              <X className="w-2.5 h-2.5" strokeWidth={2.5} />
            </button>
          </div>

          {/* Hover Tooltip */}
          <div className="nexus-step-tooltip">
            {stepLabel}
          </div>
        </div>

        {/* ── Input Drawer ── */}
        {userInputRequest && (
          <div className="nexus-input-drawer">
            <div className="nexus-input-header">
              <HelpCircle className="w-3 h-3 text-sky-400 shrink-0" strokeWidth={2.5} />
              <span style={{ flex: 1 }}>{userInputRequest.prompt}</span>
            </div>

            {userInputRequest.options && userInputRequest.options.length > 0 && (
              <div className="nexus-input-options">
                {userInputRequest.options.map((opt, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={async () => {
                      if (opt.toLowerCase().includes('file explorer') || opt.toLowerCase().includes('browse')) {
                        if (window.electronAPI?.selectSavePath) {
                          try {
                            const match = userInputRequest?.prompt?.match(/\(([^)]+\.pptx|[^)]+\.xlsx|[^)]+\.docx)\)/i);
                            const def = match ? match[1] : 'presentation.pptx';
                            const selected = await window.electronAPI.selectSavePath(def);
                            if (selected) {
                              onSubmitUserInput?.(selected);
                              return;
                            }
                          } catch (err) {
                            console.warn('Native save dialog error:', err);
                          }
                        }
                      }
                      onSubmitUserInput?.(opt);
                    }}
                    className="nexus-choice-chip"
                  >
                    {renderChoiceChip(opt)}
                  </button>
                ))}
              </div>
            )}


            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (customInputText.trim()) {
                  onSubmitUserInput?.(customInputText.trim());
                  setCustomInputText('');
                }
              }}
              className="nexus-input-form"
            >
              <input
                type="text"
                value={customInputText}
                onChange={e => setCustomInputText(e.target.value)}
                placeholder={userInputRequest.placeholder || 'Type custom response...'}
                className="nexus-input-field"
                autoFocus
              />
              <button type="submit" className="nexus-input-submit">
                Submit
              </button>
            </form>
          </div>
        )}

        {/* ── Error / Issues Drawer ── */}
        {showErrorDrawer && hasIssues && (
          <div className="nexus-error-drawer">
            <div className="nexus-error-header">
              <span className="nexus-error-title">
                Runtime Issues & Notices ({allIssues.length})
              </span>
              <button
                type="button"
                onClick={() => setShowErrorDrawer(false)}
                className="text-red-400 hover:text-red-300 text-[10px] px-1"
                title="Close"
              >
                <X className="w-3 h-3" strokeWidth={2} />
              </button>
            </div>
            <div className="nexus-error-list">
              {allIssues.map((iss, i) => (
                <div key={iss.id || i} className="nexus-issue-card">
                  <div className="nexus-issue-meta">
                    <span className="nexus-issue-badge">
                      {iss.type || 'NOTICE'}
                      {iss.step ? ` • STEP ${iss.step}` : ''}
                    </span>
                    {iss.timestamp && (
                      <span className="nexus-issue-time">{iss.timestamp}</span>
                    )}
                  </div>
                  <div className="nexus-issue-text">
                    {iss.message}
                    {iss.count && iss.count > 1 && (
                      <span style={{ opacity: 0.65 }}> (x{iss.count})</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Steps Drawer ── */}
        {isExpanded && (
          <div className="nexus-steps-drawer">
            <div className="flex items-center justify-between mb-2 pb-1" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'rgba(255,255,255,0.3)', letterSpacing: '0.08em' }}>
                Steps
              </span>
              <span className="text-[10px] tabular-nums font-mono" style={{ color: 'rgba(255,255,255,0.3)' }}>
                {currentIdx + 1} / {totalSteps}
              </span>
            </div>

            {plan.length === 0 ? (
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', padding: '4px 6px' }}>
                No steps available
              </div>
            ) : (
              plan.map((s, idx) => {
                const status = s.status || 'pending';
                const title = s.title || s.description || `Step ${idx + 1}`;
                return (
                  <div key={s.id || idx} className={`nexus-step-item ${status}`}>
                    <span style={{ flexShrink: 0, display: 'inline-flex', alignItems: 'center', marginTop: 1 }}>
                      {status === 'completed' ? (
                        <Check className="w-2.5 h-2.5 text-emerald-400" strokeWidth={3} />
                      ) : status === 'running' ? (
                        <Loader2 className="w-2.5 h-2.5 text-blue-400 animate-spin" strokeWidth={2.5} />
                      ) : status === 'failed' ? (
                        <X className="w-2.5 h-2.5 text-red-400" strokeWidth={3} />
                      ) : (
                        <span style={{ width: 10, height: 10, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', opacity: 0.35 }}>
                          •
                        </span>
                      )}
                    </span>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={title}>
                      {title}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
};
export default AutomationPill;
