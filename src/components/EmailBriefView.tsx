import React, { useEffect, useState } from 'react';
import { ArrowLeft, ExternalLink, Inbox, LoaderCircle, Mail } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuth } from '../context/AuthContext';

const BACKEND_URL = 'http://127.0.0.1:8000';
const GMAIL_INBOX_URL = 'https://mail.google.com/mail/u/0/#inbox';

interface EmailBriefRun {
  id: string;
  scheduled_for: string;
  status: string;
  result: string | null;
  error: string | null;
}

interface EmailBriefViewProps {
  taskId: string;
  runId: string;
  onClose: () => void;
}

export const EmailBriefView: React.FC<EmailBriefViewProps> = ({ taskId, runId, onClose }) => {
  const { idToken } = useAuth();
  const [run, setRun] = useState<EmailBriefRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCached, setIsCached] = useState(false);

  useEffect(() => {
    if (!idToken) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setIsCached(false);

    fetch(`${BACKEND_URL}/api/scheduled-tasks/${encodeURIComponent(taskId)}/runs?limit=100`, {
      headers: { Authorization: `Bearer ${idToken}` },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Could not load this email brief (${response.status}).`);
        return response.json() as Promise<EmailBriefRun[]>;
      })
      .then((runs) => {
        if (cancelled) return;
        const match = runs.find((item) => item.id === runId);
        if (!match) throw new Error('This scheduled email brief is no longer available.');
        setRun(match);
        setIsCached(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const errMsg = err instanceof Error ? err.message : 'Could not load this email brief.';
          setError(errMsg);
          // Try to load from browser cache as fallback
          const cachedRun = sessionStorage.getItem(`email_brief_${runId}`);
          if (cachedRun) {
            try {
              setRun(JSON.parse(cachedRun));
              setIsCached(true);
              setError(null);
            } catch (parseErr) {
              logger.warn('Failed to parse cached email brief');
            }
          }
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [idToken, taskId, runId]);

  // Cache successful runs
  useEffect(() => {
    if (run && !isCached) {
      sessionStorage.setItem(`email_brief_${runId}`, JSON.stringify(run));
    }
  }, [run, runId, isCached]);

  const openInbox = () => {
    if (window.electronAPI?.openExternal) window.electronAPI.openExternal(GMAIL_INBOX_URL);
    else window.open(GMAIL_INBOX_URL, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="w-[700px] max-w-[700px] min-w-[700px] select-none p-2 mx-auto">
      <section className="w-full max-w-[684px] mx-auto rounded-[20px] glass-panel overflow-hidden text-white/90">
        <header className="flex items-center justify-between gap-3 px-5 py-3 border-b border-white/[0.08]">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-emerald-500/10 border border-emerald-400/20 text-emerald-300">
              <Mail className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h1 className="text-sm font-semibold text-white">Email Brief</h1>
              <p className="text-[11px] text-white/45 truncate">
                {run ? new Date(run.scheduled_for).toLocaleString() : 'Scheduled inbox summary'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs text-white/60 hover:text-white hover:bg-white/[0.07]"
            title="Back to Spotlight"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back
          </button>
        </header>

        <div className="h-[410px] overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="h-full flex items-center justify-center gap-2 text-sm text-white/50">
              <LoaderCircle className="w-4 h-4 animate-spin" /> Loading email brief…
            </div>
          ) : error ? (
            <div className="rounded-xl border border-rose-400/20 bg-rose-500/[0.07] p-4 text-sm text-rose-200">{error}</div>
          ) : run?.error ? (
            <div className="rounded-xl border border-rose-400/20 bg-rose-500/[0.07] p-4 text-sm text-rose-200">{run.error}</div>
          ) : run?.result ? (
            <article className="prose prose-invert prose-sm max-w-none prose-headings:text-white prose-p:text-white/75 prose-li:text-white/75 prose-strong:text-white prose-a:text-sky-300">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{run.result}</ReactMarkdown>
            </article>
          ) : (
            <div className="text-sm text-white/55">No brief was recorded for this run.</div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 px-5 py-3 border-t border-white/[0.08]">
          <span className="text-[11px] text-white/40">
            {isCached ? '📦 Cached summary of received mail' : 'Read-only summary of received mail'}
          </span>
          <button
            type="button"
            onClick={openInbox}
            className="h-9 px-3 rounded-lg flex items-center gap-2 bg-sky-500/15 border border-sky-400/25 text-sky-200 hover:bg-sky-500/25 text-xs font-semibold"
          >
            <Inbox className="w-3.5 h-3.5" /> Open Gmail inbox <ExternalLink className="w-3 h-3 opacity-70" />
          </button>
        </footer>
      </section>
    </div>
  );
};

export default EmailBriefView;