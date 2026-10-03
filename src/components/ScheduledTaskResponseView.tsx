import React, { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowLeft, CheckCircle2, Clock, ExternalLink, FileText, Inbox, RefreshCw, XCircle } from 'lucide-react';
import { ScheduledTaskData, ScheduledTaskRunData, useSchedules } from '../hooks/useSchedules';

interface ScheduledTaskResponseViewProps {
  taskId: string;
  runId?: string;
  onClose: () => void;
}

const formatTimestamp = (value: string | null | undefined) => {
  if (!value) return 'Not available yet';
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
};

const GMAIL_INBOX_URL = 'https://mail.google.com/mail/u/0/#inbox';

const isEmailBriefTask = (task: ScheduledTaskData | null) => {
  if (task?.normalized_intent?.action === 'gmail_brief_messages') return true;
  const text = `${task?.name || ''} ${task?.prompt || ''}`.toLowerCase();
  return /\b(?:email|emails|e-mail|e-mails|mail|inbox|message|messages)\b/.test(text)
    && /\b(?:notify|alert)\b/.test(text)
    && /\b(?:new|recent|received|unread|inbox)\b/.test(text);
};

const CustomLink = ({ href, children }: { href?: string; children?: React.ReactNode }) => {
  if (!href) return <span>{children}</span>;
  
  const isExternal = href.startsWith('http://') || href.startsWith('https://');
  
  return (
    <a
      href={href}
      target={isExternal ? '_blank' : undefined}
      rel={isExternal ? 'noopener noreferrer' : undefined}
      className="text-sky-300 underline hover:text-sky-200 transition-colors break-all"
      title={href}
    >
      {children}
      {isExternal && <ExternalLink className="inline h-3 w-3 ml-1 opacity-60" />}
    </a>
  );
};

const preprocessContent = (content: string): string => {
  return content
    .replace(/\\n/g, '\n')
    .replace(/\\r\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\r/g, '\n');
};

export const ScheduledTaskResponseView: React.FC<ScheduledTaskResponseViewProps> = ({ taskId, runId, onClose }) => {
  const { fetchTask, fetchRuns } = useSchedules();
  const [task, setTask] = useState<ScheduledTaskData | null>(null);
  const [runs, setRuns] = useState<ScheduledTaskRunData[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadResponse = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) setRefreshing(true);
    try {
      const [nextTask, nextRuns] = await Promise.all([fetchTask(taskId), fetchRuns(taskId)]);
      setTask(nextTask);
      setRuns(nextRuns);
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Unable to load this scheduled task response.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchRuns, fetchTask, taskId]);

  useEffect(() => {
    void loadResponse();
    const interval = window.setInterval(() => void loadResponse(), 5000);
    return () => window.clearInterval(interval);
  }, [loadResponse]);

  const run = runs.find((item) => item.id === runId) || runs[0] || null;
  const updatedAt = run?.completed_at || run?.started_at || run?.scheduled_for || task?.last_run_at;
  const isSuccessful = run?.status === 'completed';
  const isWorking = run?.status === 'pending' || run?.status === 'running';
  const isEmailBrief = isEmailBriefTask(task);

  const openGmailInbox = () => {
    if (window.electronAPI?.openExternal) window.electronAPI.openExternal(GMAIL_INBOX_URL);
    else window.open(GMAIL_INBOX_URL, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="flex flex-col h-screen max-h-[90vh] w-[700px] max-w-[700px] select-none mx-auto">
      <section className="glass-panel overflow-hidden rounded-[20px] text-white flex flex-col h-full">
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.08] px-5 py-4 shrink-0">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2 text-sky-300">
              <FileText className="h-4 w-4 shrink-0" />
              <span className="text-xs font-semibold uppercase tracking-wider">Scheduled task response</span>
            </div>
            <h2 className="truncate text-base font-semibold text-white">{task?.name || 'Scheduled task'}</h2>
            <p className="mt-1 line-clamp-2 text-xs text-white/50">{task?.prompt || 'Loading task details...'}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => void loadResponse(true)}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-white/50 hover:bg-white/[0.08] hover:text-white transition-colors"
              title="Refresh response"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-white/65 hover:bg-white/[0.08] hover:text-white transition-colors"
              title="Back to scheduled tasks"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Back
            </button>
          </div>
        </header>

        {!loading && run && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-white/55 px-5 py-3 border-b border-white/[0.08] shrink-0 bg-white/[0.02]">
            <span className="flex items-center gap-1.5">
              {isSuccessful ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
              ) : (
                <XCircle className="h-3.5 w-3.5 text-amber-400 shrink-0" />
              )}
              <span className="capitalize">{isWorking ? 'Updating response' : run.status}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 shrink-0" /> Updated {formatTimestamp(updatedAt)}
            </span>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0">
          {loading ? (
            <div className="py-12 text-center text-sm text-white/45">Loading scheduled response...</div>
          ) : error ? (
            <div className="rounded-lg border border-rose-400/20 bg-rose-500/[0.07] p-3 text-sm text-rose-200">
              {error}
            </div>
          ) : !run ? (
            <div className="py-12 text-center text-sm text-white/45">
              This scheduled task has not produced a response yet.
            </div>
          ) : (
            <>
              {run.error ? (
                <div className="rounded-lg border border-rose-400/20 bg-rose-500/[0.07] p-4 text-sm text-rose-200">
                  {run.error}
                </div>
              ) : run.result ? (
                <article className="prose prose-invert prose-sm max-w-none prose-headings:text-white prose-p:text-white/75 prose-li:text-white/75 prose-strong:text-white prose-code:text-amber-200 prose-code:bg-white/[0.08] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-pre:bg-white/[0.05] prose-pre:border prose-pre:border-white/[0.08] prose-blockquote:border-l-sky-400 prose-blockquote:text-white/60 prose-table:border-collapse prose-td:border prose-td:border-white/[0.08] prose-td:px-3 prose-td:py-2 prose-th:border prose-th:border-white/[0.08] prose-th:px-3 prose-th:py-2 prose-th:bg-white/[0.05] whitespace-pre-wrap">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: CustomLink,
                      img: ({ src, alt }) => (
                        <img
                          src={src}
                          alt={alt}
                          className="max-w-full h-auto rounded-lg border border-white/[0.08] my-2"
                          loading="lazy"
                        />
                      ),
                      table: ({ children }) => (
                        <div className="overflow-x-auto my-4">
                          <table className="border-collapse border border-white/[0.08]">
                            {children}
                          </table>
                        </div>
                      ),
                      p: ({ children }) => (
                        <p className="whitespace-pre-wrap break-words">
                          {children}
                        </p>
                      ),
                    }}
                  >
                    {preprocessContent(run.result)}
                  </ReactMarkdown>
                </article>
              ) : (
                <div className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-4 text-sm text-white/55">
                  The task is still running. This page refreshes automatically.
                </div>
              )}
            </>
          )}
        </div>

        {!loading && run && run.result && isEmailBrief && (
          <div className="border-t border-white/[0.08] px-5 py-4 shrink-0 bg-white/[0.02] flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={openGmailInbox}
              className="flex h-9 items-center gap-2 rounded-lg border border-sky-400/25 bg-sky-500/15 px-3 text-xs font-semibold text-sky-200 hover:bg-sky-500/25 transition-colors active:scale-95"
              title="Open Gmail inbox"
            >
              <Inbox className="h-3.5 w-3.5 shrink-0" />
              <span>Open Gmail inbox</span>
              <ExternalLink className="h-3 w-3 opacity-70 shrink-0" />
            </button>
          </div>
        )}
      </section>
    </div>
  );
};
