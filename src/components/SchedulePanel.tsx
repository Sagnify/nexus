import React, { useState } from 'react';
import {
  Play,
  Trash2,
  History,
  X,
  Clock,
  Bell,
  Zap,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Search,
  Info,
  FileText,
  Mail,
  FileSpreadsheet,
  Presentation,
  Sparkles,
} from 'lucide-react';
import {
  useSchedules,
  ScheduledTaskData,
  ScheduledTaskRunData,
  ScheduleDefinition,
} from '../hooks/useSchedules';

interface SchedulePanelProps {
  onClose: () => void;
  onRunPrompt?: (prompt: string) => void;
}

export const SchedulePanel: React.FC<SchedulePanelProps> = ({ onClose, onRunPrompt }) => {
  const {
    tasks,
    loading,
    error,
    togglePause,
    runNow,
    deleteTask,
    fetchRuns,
  } = useSchedules();

  const [activeTab, setActiveTab] = useState<'all' | 'active' | 'paused' | 'reminder' | 'automation'>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTaskForRuns, setSelectedTaskForRuns] = useState<ScheduledTaskData | null>(null);
  const [taskRuns, setTaskRuns] = useState<ScheduledTaskRunData[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ id: string; message: string } | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);

  // Run history drawer
  const handleOpenRuns = async (task: ScheduledTaskData) => {
    setSelectedTaskForRuns(task);
    setLoadingRuns(true);
    try {
      const runs = await fetchRuns(task.id);
      setTaskRuns(runs);
    } catch {
      setTaskRuns([]);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleRunNow = async (taskId: string) => {
    try {
      setActionFeedback({ id: taskId, message: 'Triggered immediate execution' });
      await runNow(taskId);
      setTimeout(() => setActionFeedback(null), 3000);
    } catch (err: any) {
      setActionFeedback({ id: taskId, message: err?.message || 'Execution failed' });
      setTimeout(() => setActionFeedback(null), 3000);
    }
  };

  const handleTogglePause = async (task: ScheduledTaskData) => {
    try {
      await togglePause(task.id, task.enabled);
    } catch (err: any) {
      setActionFeedback({ id: task.id, message: err?.message || 'Failed to update schedule status' });
      setTimeout(() => setActionFeedback(null), 3000);
    }
  };

  const handleDeleteConfirm = async (taskId: string) => {
    try {
      await deleteTask(taskId);
      setDeletingTaskId(null);
      if (selectedTaskForRuns?.id === taskId) {
        setSelectedTaskForRuns(null);
      }
    } catch (err: any) {
      setActionFeedback({ id: taskId, message: err?.message || 'Failed to delete schedule' });
      setTimeout(() => setActionFeedback(null), 3000);
    }
  };

  const filteredTasks = tasks.filter((t) => {
    const matchesSearch =
      t.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.prompt.toLowerCase().includes(searchTerm.toLowerCase());
    if (!matchesSearch) return false;

    if (activeTab === 'reminder') return t.task_type === 'reminder';
    if (activeTab === 'automation') return t.task_type === 'automation';
    if (activeTab === 'active') return t.enabled;
    if (activeTab === 'paused') return !t.enabled;
    return true;
  });

  const formatScheduleFriendly = (def: ScheduleDefinition, type: string) => {
    if (type === 'one_time' || def.frequency === 'once') {
      if (!def.target_time) return 'One-time';
      try {
        const d = new Date(def.target_time);
        return `Once on ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} at ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
      } catch {
        return 'One-time';
      }
    }
    if (def.frequency === 'daily') return `Daily at ${def.time || '09:00'}`;
    if (def.frequency === 'weekdays') return `Weekdays at ${def.time || '08:30'}`;
    if (def.frequency === 'weekly') {
      const days = (def.days || ['monday']).map((d) => d.slice(0, 3).toUpperCase()).join(', ');
      return `Every ${days} at ${def.time || '10:00'}`;
    }
    if (def.frequency === 'monthly') return `Monthly on day ${def.day_of_month || 1} at ${def.time || '09:00'}`;
    return 'Recurring';
  };

  const formatNextRun = (isoStr: string | null) => {
    if (!isoStr) return 'Not scheduled';
    try {
      const dt = new Date(isoStr);
      const now = new Date();
      const diffMs = dt.getTime() - now.getTime();
      const diffMins = Math.round(diffMs / 60000);

      let relative = '';
      if (diffMins < 0) relative = '(Overdue)';
      else if (diffMins < 60) relative = `(in ${diffMins}m)`;
      else if (diffMins < 1440) relative = `(in ${Math.round(diffMins / 60)}h)`;
      else relative = `(in ${Math.round(diffMins / 1440)}d)`;

      const formatted = dt.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
      return `${formatted} ${relative}`;
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="flex flex-col h-[500px] max-h-[500px] text-white/90 relative select-none">
      {/* Sleek unified toolbar: Filter tabs on left, Search & Close on right */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.08] bg-black/25 gap-3">
        {/* Filter Tabs with task counts */}
        <div className="flex items-center gap-1">
          {[
            { id: 'all', label: 'All', count: tasks.length },
            { id: 'active', label: 'Active', count: tasks.filter(t => t.enabled).length },
            { id: 'paused', label: 'Inactive', count: tasks.filter(t => !t.enabled).length },
            { id: 'reminder', label: 'Reminders', count: tasks.filter(t => t.task_type === 'reminder').length },
            { id: 'automation', label: 'Automations', count: tasks.filter(t => t.task_type === 'automation').length },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === tab.id
                  ? 'bg-sky-500/20 text-sky-200 border border-sky-400/30 shadow-sm'
                  : 'text-white/45 hover:text-white/80 hover:bg-white/[0.04]'
              }`}
            >
              <span>{tab.label}</span>
              {tab.count > 0 && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                  activeTab === tab.id ? 'bg-sky-400/25 text-sky-200' : 'bg-white/10 text-white/40'
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Right side: Search filter & Close button */}
        <div className="flex items-center gap-2">
          <div className="relative w-44">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30 pointer-events-none" />
            <input
              type="text"
              placeholder="Filter tasks…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8 pr-2.5 py-1 text-xs rounded-lg bg-white/[0.04] border border-white/[0.08] focus:border-sky-400/40 focus:outline-none text-white/80 placeholder-white/25 transition-all"
            />
          </div>

          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08] transition-colors"
            title="Close (Esc)"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Main Content: Tasks List or Clean Empty State */}
      <div className="flex-1 overflow-y-auto px-5 py-3.5 space-y-2.5">
        {error && (
          <div className="p-2.5 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2 mb-2">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {loading && tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-white/40 text-xs gap-2">
            <Clock className="w-6 h-6 animate-spin text-sky-400" />
            <span>Loading schedules…</span>
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 px-6 text-center select-none">
            <div className="w-12 h-12 rounded-2xl bg-sky-500/10 border border-sky-400/20 flex items-center justify-center text-sky-400 mb-3 shadow-[0_0_20px_rgba(56,189,248,0.12)]">
              <Clock className="w-6 h-6 text-sky-400" strokeWidth={1.8} />
            </div>
            <h3 className="text-sm font-semibold text-white/90 mb-1">
              {tasks.length === 0 ? 'No scheduled tasks yet' : 'No matching tasks found'}
            </h3>
            <p className="text-xs text-white/40 max-w-sm mb-5 leading-relaxed">
              {tasks.length === 0
                ? 'Tasks are scheduled directly via natural language in the Spotlight on the Launcher screen.'
                : 'Try adjusting your search filter or selecting another tab.'}
            </p>

            {tasks.length === 0 && (
              <div className="w-full max-w-sm space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-sky-400/70 block mb-1">
                  Try asking NEXUS in Spotlight:
                </span>
                {[
                  '“Schedule an email to John wishing him happy birthday at 12 AM on October 15.”',
                  '“Schedule a research report on AI agents for tomorrow at 6 PM.”',
                  '“Remind me tomorrow at 9 AM to check deployment.”',
                ].map((example, i) => (
                  <div
                    key={i}
                    className="px-3.5 py-2.5 rounded-xl bg-white/[0.025] hover:bg-white/[0.045] border border-white/[0.06] text-[11.5px] text-white/65 font-mono transition-all text-left"
                  >
                    {example}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          filteredTasks.map((task) => {
            const isReminder = task.task_type === 'reminder';
            const feedback = actionFeedback?.id === task.id ? actionFeedback.message : null;
            const isPendingDelete = deletingTaskId === task.id;

            return (
              <div
                key={task.id}
                className={`group relative rounded-xl border p-3.5 transition-all duration-150 ${
                  task.enabled
                    ? 'bg-white/[0.025] border-white/[0.08] hover:border-white/[0.15] hover:bg-white/[0.04]'
                    : 'bg-white/[0.01] border-white/[0.04] opacity-60'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <div
                      className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 border ${
                        isReminder
                          ? 'bg-sky-500/10 border-sky-400/20 text-sky-400'
                          : 'bg-indigo-500/10 border-indigo-400/20 text-indigo-400'
                      }`}
                    >
                      {isReminder ? <Bell className="w-4 h-4" /> : <Zap className="w-4 h-4" />}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="text-[13.5px] font-semibold text-white truncate max-w-[280px]">
                          {task.name}
                        </span>

                        {/* Status badge: Active vs Inactive */}
                        <span
                          className={`px-2 py-0.5 rounded-full text-[9.5px] font-bold tracking-wider ${
                            task.enabled
                              ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                              : 'bg-white/[0.05] text-white/35 border border-white/10'
                          }`}
                        >
                          {task.enabled ? 'ACTIVE' : 'INACTIVE'}
                        </span>

                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider ${
                            isReminder
                              ? 'bg-sky-500/10 text-sky-300 border border-sky-400/20'
                              : 'bg-violet-500/10 text-violet-300 border border-violet-400/20'
                          }`}
                        >
                          {task.task_type}
                        </span>

                        {task.normalized_intent?.category === 'email' && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-300 border border-amber-400/20">
                            <Mail className="w-2.5 h-2.5" />
                            Email
                          </span>
                        )}
                        {task.normalized_intent?.category === 'research' && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-400/20">
                            <Sparkles className="w-2.5 h-2.5" />
                            Research
                          </span>
                        )}
                        {task.normalized_intent?.category === 'research_doc' && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-300 border border-blue-400/20">
                            <FileText className="w-2.5 h-2.5" />
                            Word Doc
                          </span>
                        )}
                        {task.normalized_intent?.category === 'spreadsheet' && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-400/20">
                            <FileSpreadsheet className="w-2.5 h-2.5" />
                            Excel Report
                          </span>
                        )}
                        {task.normalized_intent?.category === 'presentation' && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-500/10 text-orange-300 border border-orange-400/20">
                            <Presentation className="w-2.5 h-2.5" />
                            Slide Deck
                          </span>
                        )}

                        <span className="px-2 py-0.5 rounded-full text-[10.5px] font-mono bg-white/[0.04] text-white/50 border border-white/[0.06]">
                          {formatScheduleFriendly(task.schedule_definition, task.schedule_type)}
                        </span>

                        {task.last_run_status === 'blocked' && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
                            <AlertTriangle className="w-2.5 h-2.5" />
                            Connector Blocked
                          </span>
                        )}

                        {task.consecutive_failures > 0 && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-rose-500/15 text-rose-300 border border-rose-500/30">
                            <AlertTriangle className="w-2.5 h-2.5" />
                            {task.consecutive_failures} failures
                          </span>
                        )}
                      </div>

                      <p
                        onClick={() => onRunPrompt && task.task_type === 'automation' && onRunPrompt(task.prompt)}
                        className={`text-[12px] text-white/60 line-clamp-1 mb-2 font-mono bg-black/20 px-2 py-1 rounded border border-white/[0.03] ${
                          onRunPrompt && task.task_type === 'automation' ? 'cursor-pointer hover:text-white/80' : ''
                        }`}
                        title={onRunPrompt && task.task_type === 'automation' ? 'Click to run in Spotlight' : undefined}
                      >
                        {task.prompt}
                      </p>

                      <div className="flex items-center gap-4 text-[11px] text-white/40">
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3 text-white/30" />
                          <span>Next: {formatNextRun(task.next_run_at)}</span>
                        </div>
                        <span>Runs: {task.total_runs || 0}</span>
                        {task.timezone && <span>TZ: {task.timezone}</span>}
                      </div>
                    </div>
                  </div>

                  {/* Actions Column: Slider Toggle, Run Now, Runs History, Delete */}
                  <div className="flex items-center gap-2.5 flex-shrink-0 pt-0.5">
                    {/* Activate / Deactivate Slider Toggle [ ON ] / [ OFF ] */}
                    <button
                      type="button"
                      onClick={() => handleTogglePause(task)}
                      title={task.enabled ? 'Click to deactivate schedule (pauses future runs)' : 'Click to activate schedule'}
                      className={`relative inline-flex items-center h-6 w-14 rounded-full transition-all duration-200 select-none p-0.5 border cursor-pointer ${
                        task.enabled
                          ? 'bg-emerald-500/25 border-emerald-400/50 shadow-[0_0_12px_rgba(16,185,129,0.25)]'
                          : 'bg-white/[0.07] border-white/15'
                      }`}
                    >
                      <span
                        className={`absolute text-[9px] font-bold tracking-wider transition-all duration-200 ${
                          task.enabled
                            ? 'left-2 text-emerald-300'
                            : 'right-2 text-white/40'
                        }`}
                      >
                        {task.enabled ? 'ON' : 'OFF'}
                      </span>
                      <span
                        className={`inline-block w-4 h-4 rounded-full transform transition-transform duration-200 shadow-md ${
                          task.enabled
                            ? 'translate-x-[32px] bg-emerald-400'
                            : 'translate-x-0.5 bg-white/40'
                        }`}
                      />
                    </button>

                    {/* Run Now button */}
                    <button
                      type="button"
                      onClick={() => handleRunNow(task.id)}
                      className="p-1.5 rounded-lg text-white/50 hover:text-emerald-300 hover:bg-emerald-500/15 transition-colors border border-transparent hover:border-emerald-500/25"
                      title="Run immediately"
                    >
                      <Play className="w-3.5 h-3.5 fill-current" />
                    </button>

                    {/* Execution Runs Drawer */}
                    <button
                      type="button"
                      onClick={() => handleOpenRuns(task)}
                      className="p-1.5 rounded-lg text-white/50 hover:text-sky-300 hover:bg-sky-500/15 transition-colors border border-transparent hover:border-sky-500/25"
                      title="View execution runs"
                    >
                      <History className="w-3.5 h-3.5" />
                    </button>

                    {/* Delete button */}
                    <button
                      type="button"
                      onClick={() => setDeletingTaskId(task.id)}
                      className="p-1.5 rounded-lg text-white/35 hover:text-rose-400 hover:bg-rose-500/15 transition-colors border border-transparent hover:border-rose-500/25"
                      title="Delete scheduled task"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Destructive Delete Confirmation Banner */}
                {isPendingDelete && (
                  <div className="mt-3 p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-between gap-3 animate-in fade-in duration-150">
                    <div className="flex items-center gap-2 text-xs text-rose-200">
                      <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
                      <div>
                        <p className="font-semibold text-rose-200">Delete this scheduled task?</p>
                        <p className="text-[11px] text-rose-300/70">Future scheduled runs will be cancelled and removed.</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button
                        type="button"
                        onClick={() => setDeletingTaskId(null)}
                        className="px-2.5 py-1 rounded-lg text-xs font-medium bg-white/[0.08] hover:bg-white/[0.14] text-white/80 transition-all border border-white/10"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteConfirm(task.id)}
                        className="px-3 py-1 rounded-lg text-xs font-medium bg-rose-600 hover:bg-rose-500 text-white shadow-sm transition-all"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}

                {/* Instant Feedback Banner */}
                {feedback && (
                  <div className="mt-2 text-[11px] text-emerald-300 bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1 rounded-md flex items-center gap-1.5">
                    <CheckCircle2 className="w-3 h-3 flex-shrink-0" />
                    <span>{feedback}</span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Execution Runs Drawer */}
      {selectedTaskForRuns && (
        <div className="absolute inset-0 bg-black/85 backdrop-blur-md z-30 flex flex-col p-5 overflow-hidden animate-in fade-in duration-150">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/[0.08]">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-sky-400" />
              <div>
                <h3 className="text-sm font-semibold text-white">
                  Execution Runs: {selectedTaskForRuns.name}
                </h3>
                <p className="text-[11px] text-white/40">{selectedTaskForRuns.prompt}</p>
              </div>
            </div>
            <button
              onClick={() => setSelectedTaskForRuns(null)}
              className="w-6 h-6 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08]"
              title="Close drawer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {loadingRuns ? (
              <div className="flex items-center justify-center h-40 text-xs text-white/40">
                Loading execution runs…
              </div>
            ) : taskRuns.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-xs text-white/40">
                <span>No recorded execution runs yet for this task.</span>
              </div>
            ) : (
              taskRuns.map((run) => {
                const isSuccess = run.status === 'completed';
                const isFailed = run.status === 'failed';
                const isSkipped = run.status === 'skipped';
                const isBlocked = run.status === 'blocked';

                return (
                  <div
                    key={run.id}
                    className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06] text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        {isSuccess && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                        {isFailed && <XCircle className="w-3.5 h-3.5 text-rose-400" />}
                        {isSkipped && <Info className="w-3.5 h-3.5 text-amber-400" />}
                        {isBlocked && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
                        <span className="font-semibold capitalize text-white/90">{run.status}</span>
                      </div>
                      <span className="text-[11px] text-white/40">
                        {new Date(run.scheduled_for).toLocaleString()}
                      </span>
                    </div>

                    {run.result && (
                      <div className="text-[11.5px] text-white/70 bg-black/30 p-2 rounded border border-white/[0.04]">
                        {run.result}
                      </div>
                    )}

                    {run.error && (
                      <div className="text-[11.5px] text-rose-300 bg-rose-950/20 p-2 rounded border border-rose-500/20">
                        {run.error}
                      </div>
                    )}

                    {run.artifacts && run.artifacts.length > 0 && (
                      <div className="pt-1.5 space-y-1">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40 block">
                          Generated Artifacts ({run.artifacts.length}):
                        </span>
                        <div className="space-y-1">
                          {run.artifacts.map((art, idx) => (
                            <div
                              key={idx}
                              className="flex items-center justify-between px-2.5 py-1.5 rounded bg-sky-950/20 border border-sky-400/20 text-[11px] text-sky-200"
                            >
                              <div className="flex items-center gap-1.5 truncate">
                                <FileText className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" />
                                <span className="truncate font-medium">{art.name}</span>
                                <span className="text-[10px] text-sky-400/60 font-mono">
                                  ({Math.round(art.size_bytes / 1024)} KB)
                                </span>
                              </div>
                              <span className="text-[9.5px] font-mono text-white/40">
                                {art.mime_type.split('/').pop()}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
};
