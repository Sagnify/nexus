import React from 'react';
import { ShieldAlert, ChevronRight, ArrowRight, Mail, Send, XCircle } from 'lucide-react';
import { PermissionRequest } from '../types/nexus';

interface PermissionCardProps {
  request: PermissionRequest;
  onApprove: () => void;
  onReject: () => void;
}

export const PermissionCard: React.FC<PermissionCardProps> = ({
  request,
  onApprove,
  onReject,
}) => {
  const currentStepObj =
    request.plan?.find((s) => s.id === request.stepId) ||
    request.plan?.[request.currentStep];

  const args = currentStepObj?.args || {};
  const isEmailTool =
    currentStepObj?.tool === 'gmail_send_email' ||
    currentStepObj?.tool === 'send_email' ||
    currentStepObj?.tool === 'email_send' ||
    (Boolean(args.to) && Boolean(args.subject));

  if (isEmailTool) {
    const toEmail = String(args.to || 'recipient@example.com');
    const subject = String(args.subject || 'No Subject');
    const body = String(args.body || '');

    return (
      <div className="p-4 bg-gradient-to-b from-sky-950/40 to-neutral-900/80 border border-sky-500/30 rounded-xl m-3 text-neutral-200 backdrop-blur-md shadow-xl shadow-sky-950/30 animate-in fade-in duration-200">
        <div className="flex items-start space-x-3">
          <div className="w-9 h-9 rounded-lg bg-sky-500/20 border border-sky-500/30 flex items-center justify-center text-sky-400 font-bold shrink-0 mt-0.5">
            <Mail className="w-5 h-5 text-sky-400" />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center space-x-2">
              <h4 className="font-semibold text-sm text-white">Review & Confirm Outgoing Email</h4>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-sky-500/20 text-sky-300 font-mono font-semibold border border-sky-500/30">
                PRIVILEGED ACTION
              </span>
            </div>
            <p className="text-xs text-neutral-400 mt-1">
              NEXUS has composed this email based on your request. Please review the recipient, subject, and content before sending:
            </p>

            <div className="mt-3 p-3.5 rounded-lg bg-black/60 border border-white/10 text-xs space-y-2.5">
              <div className="flex items-center space-x-2 pb-2 border-b border-white/10">
                <span className="text-[11px] font-mono uppercase text-neutral-400 font-semibold w-14 shrink-0">
                  To:
                </span>
                <span className="text-xs font-semibold text-sky-300 font-mono select-text bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20">
                  {toEmail}
                </span>
              </div>

              <div className="flex items-start space-x-2 pb-2 border-b border-white/10">
                <span className="text-[11px] font-mono uppercase text-neutral-400 font-semibold w-14 shrink-0 mt-0.5">
                  Subject:
                </span>
                <span className="text-xs font-medium text-neutral-100 select-text flex-1">
                  {subject}
                </span>
              </div>

              <div className="space-y-1 pt-1">
                <div className="text-[11px] font-mono uppercase text-neutral-400 font-semibold">
                  Message Body:
                </div>
                <div className="p-3 rounded-md bg-neutral-950/70 border border-white/5 text-xs text-neutral-200 select-text font-sans whitespace-pre-wrap leading-relaxed max-h-56 overflow-y-auto">
                  {body || <span className="italic text-neutral-500">No message content</span>}
                </div>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-end space-x-2.5">
              <button
                type="button"
                onClick={onReject}
                className="px-3.5 py-1.5 rounded-lg bg-white/10 hover:bg-red-500/20 hover:text-red-300 hover:border-red-500/30 border border-white/10 text-neutral-300 text-xs font-medium transition-all flex items-center space-x-1.5"
              >
                <XCircle className="w-3.5 h-3.5" />
                <span>Cancel</span>
              </button>
              <button
                type="button"
                onClick={onApprove}
                className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-lg shadow-emerald-950/40 transition-all flex items-center space-x-1.5 cursor-pointer"
              >
                <span>Send Email Immediately</span>
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-amber-500/[0.08] border border-amber-500/30 rounded-xl m-3 text-neutral-200 backdrop-blur-md shadow-lg shadow-amber-950/20">
      <div className="flex items-start space-x-3">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400 font-bold shrink-0 mt-0.5">
          <ShieldAlert className="w-4 h-4 text-amber-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center space-x-2">
            <h4 className="font-semibold text-sm text-white">NEXUS Requires Authorization</h4>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono font-semibold border border-amber-500/30">
              {currentStepObj?.risk_level || 'ELEVATED'}
            </span>
          </div>
          <p className="text-xs text-neutral-400 mt-1">
            This step will execute a system action or modify files. Confirm to proceed:
          </p>

          <div className="mt-3 p-2.5 rounded-lg bg-black/40 border border-white/10 font-mono text-xs text-amber-200/90 break-all space-y-1">
            {request.items && request.items.length > 0 ? (
              request.items.map((item, i) => (
                <div key={i} className="flex items-start space-x-2">
                  <ChevronRight className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                  <span>{item}</span>
                </div>
              ))
            ) : (
              <div>
                {currentStepObj?.title || 'System Execution'}
                {currentStepObj?.args && (
                  <div className="text-[11px] text-neutral-400 mt-1">
                    {JSON.stringify(currentStepObj.args)}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="mt-3.5 flex items-center justify-end space-x-2.5">
            <button
              onClick={onReject}
              className="px-3.5 py-1.5 rounded-lg bg-white/10 hover:bg-red-500/20 hover:text-red-300 hover:border-red-500/30 border border-white/10 text-neutral-300 text-xs font-medium transition-all"
            >
              Reject Action
            </button>
            <button
              onClick={onApprove}
              className="px-4 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium shadow-md shadow-amber-950/40 transition-all flex items-center space-x-1.5"
            >
              <span>Approve & Continue</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
