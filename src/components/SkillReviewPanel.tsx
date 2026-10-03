import React, { useEffect, useState } from "react";
import {
  Sparkles,
  Check,
  X,
  Globe,
  MousePointer2,
  Keyboard,
  Plus,
  Cpu,
  Trash2,
  Variable,
  AlertCircle,
} from "lucide-react";
import { CreateSkillPayload } from "../hooks/useSkills";

interface SkillReviewPanelProps {
  draft: CreateSkillPayload;
  onClose: () => void;
  onSave: (skill: CreateSkillPayload) => void | Promise<void>;
  saveError?: string | null;
  validationIssues?: Array<{
    step_index: number;
    severity: string;
    issue_type: string;
    title: string;
    description: string;
    suggestion?: string;
  }>;
}

const inferTemplateParameters = (parameters: any[], triggers: string[], steps: any[]) => {
  const knownNames = new Set(
    parameters
      .map((parameter) => String(parameter?.name || "").trim())
      .filter(Boolean),
  );
  const templates = JSON.stringify({ triggers, steps });
  const inferred: any[] = [];
  for (const match of templates.matchAll(/\{\{([^}]+)\}\}/g)) {
    const name = match[1].trim();
    if (!name || knownNames.has(name)) continue;
    knownNames.add(name);
    inferred.push({
      name,
      type: "string",
      description: `Value for ${name.replace(/_/g, " ")}`,
      required: true,
      default_value: null,
    });
  }
  return [...parameters, ...inferred];
};

export const SkillReviewPanel: React.FC<SkillReviewPanelProps> = ({
  draft,
  onClose,
  onSave,
  saveError,
  validationIssues = [],
}) => {
  const [name, setName] = useState(draft.name || "Custom Automated Skill");
  const [description, setDescription] = useState(draft.description || "");
  const [triggers, setTriggers] = useState<string[]>(draft.trigger_phrases || []);
  const [newTrigger, setNewTrigger] = useState("");
  const [steps, setSteps] = useState<any[]>(draft.steps || []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationList, setValidationList] = useState(validationIssues);

  const parameters = draft.parameters_schema || [];

  useEffect(() => {
    if (saveError) setError(saveError);
  }, [saveError]);

  useEffect(() => {
    setValidationList(validationIssues);
  }, [validationIssues]);

  const handleAutoFixSteps = () => {
    let reordered = [...steps];
    const navIdx = reordered.findIndex((s) => s.action_type === "browser_navigate");
    if (navIdx > 0) {
      const [navStep] = reordered.splice(navIdx, 1);
      reordered.unshift(navStep);
    }
    const pruned: any[] = [];
    for (const step of reordered) {
      if (pruned.length > 0) {
        const prev = pruned[pruned.length - 1];
        if (
          prev.action_type === step.action_type &&
          step.action_type === "browser_click" &&
          (prev.selector_bundle?.cssPath === step.selector_bundle?.cssPath || prev.title === step.title)
        ) {
          continue;
        }
      }
      pruned.push(step);
    }
    setSteps(pruned);
    setValidationList([]);
  };

  const handleAddTrigger = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = newTrigger.trim().toLowerCase().replace(/[^\x00-\x7F]+/g, "");
    if (trimmed && !triggers.includes(trimmed)) {
      setTriggers([...triggers, trimmed]);
      setNewTrigger("");
    }
  };

  const handleRemoveTrigger = (idx: number) => {
    setTriggers(triggers.filter((_, i) => i !== idx));
  };

  const handleDeleteStep = (stepIdx: number) => {
    setSteps(steps.filter((_, i) => i !== stepIdx));
  };

  const handleSave = async (isDraft: boolean = false) => {
    if (!name.trim()) {
      setError("Please provide a name for this skill.");
      return;
    }
    if (steps.length === 0) {
      setError("A skill must have at least one step.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload: CreateSkillPayload = {
        ...draft,
        name: name.trim(),
        description: description.trim(),
        trigger_phrases: triggers,
        parameters_schema: inferTemplateParameters(parameters, triggers, steps),
        steps: steps,
        is_draft: isDraft,
      };
      await onSave(payload);
      setSaving(false);
      onClose();
    } catch (err: any) {
      setError(err?.message || "Failed to save skill. Please try again.");
      setSaving(false);
    }
  };

  const renderParamHighlight = (text: string) => {
    if (!text) return null;
    const parts = text.split(/({{[^}]+}})/g);
    return (
      <span className="font-mono text-xs">
        {parts.map((p, idx) => {
          if (p.startsWith("{{") && p.endsWith("}}")) {
            return (
              <span
                key={idx}
                className="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-amber-500/15 border border-amber-500/30 text-amber-300 font-semibold text-[11px]"
              >
                {p}
              </span>
            );
          }
          return <span key={idx} className="text-white/80">{p}</span>;
        })}
      </span>
    );
  };

  const formatStep = (step: any) => {
    if (step.action_type === "browser_navigate") {
      let hostname = "";
      try {
        if (step.url) {
          const u = new URL(step.url);
          hostname = u.hostname.replace(/^www\./, "");
          const path = u.pathname.length > 1 ? u.pathname.slice(0, 18) : "";
          return {
            title: `Open ${hostname}${path}`,
            badge: hostname,
            icon: <Globe className="w-3.5 h-3.5 text-sky-400" />,
            isType: false,
          };
        }
      } catch (_) {}
      return {
        title: step.title || "Navigate to URL",
        badge: "browser",
        icon: <Globe className="w-3.5 h-3.5 text-sky-400" />,
        isType: false,
      };
    }

    if (step.action_type === "browser_click") {
      const cleanTitle = (step.title || "Click element")
        .replace(/^click(ed)?\s+(on\s+)?/i, "")
        .replace(/<[^>]*>/g, "");
      return {
        title: `Click ${cleanTitle}`,
        badge: "click",
        icon: <MousePointer2 className="w-3.5 h-3.5 text-emerald-400" />,
        isType: false,
      };
    }

    if (step.action_type === "browser_type") {
      return {
        title: "Enter",
        value: step.value_template || step.value || "",
        badge: "input",
        icon: <Keyboard className="w-3.5 h-3.5 text-amber-400" />,
        isType: true,
      };
    }

    return {
      title: step.title || "Execute step",
      badge: step.action_type?.replace("browser_", "") || "action",
      icon: <Cpu className="w-3.5 h-3.5 text-purple-400" />,
      isType: false,
    };
  };

  const targetSites = ((draft.target_sites || draft.metadata?.target_sites || []) as string[]).filter(
    (s) => s && !s.includes("about:blank")
  );

  return (
    <div
      className="w-full h-[min(580px,calc(100vh-32px))] max-h-[min(580px,calc(100vh-32px))] flex flex-col select-none text-white animate-in fade-in duration-200 rounded-2xl overflow-hidden border border-white/10 shadow-[0_24px_70px_rgba(0,0,0,0.95)]"
      style={{
        background: "rgba(13, 14, 20, 0.98)",
        backdropFilter: "blur(32px) saturate(180%)",
        WebkitBackdropFilter: "blur(32px) saturate(180%)",
      }}
    >
      {/* ── HEADER BAR ── */}
      <div className="px-5 py-3.5 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.03] shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-sky-500/10 border border-sky-500/25 flex items-center justify-center text-sky-400 shrink-0">
            <Sparkles className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[13px] font-semibold text-white tracking-tight">
                Review Learned Skill
              </h2>
              <span className="inline-flex items-center gap-1 text-[9.5px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 font-medium">
                <Cpu className="w-2.5 h-2.5" />
                AI Distilled
              </span>
              <span className="text-[9.5px] px-2 py-0.5 rounded-full bg-white/[0.05] text-white/60 border border-white/[0.08] font-mono">
                {steps.length} {steps.length === 1 ? "step" : "steps"}
              </span>
              {targetSites.length > 0 && (
                <span className="text-[9.5px] px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20 font-mono">
                  {targetSites[0]}
                </span>
              )}
            </div>
            <p className="text-[10.5px] text-white/40 mt-0.5">
              Cleaned, parameterized, and ready to automate dynamically across any input
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-white/[0.08] text-white/40 hover:text-white/80 transition-colors"
          title="Close review"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* ── ERROR BANNER ── */}
      {error && (
        <div className="px-5 py-2 bg-rose-500/10 border-b border-rose-500/25 text-rose-300 text-[11px] flex items-center gap-2 shrink-0">
          <AlertCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* ── VALIDATION ISSUES BANNER ── */}
      {validationList.length > 0 && (
        <div className="px-5 py-2 bg-amber-500/10 border-b border-amber-500/25 shrink-0">
          <div className="flex items-center justify-between gap-2 mb-1">
            <div className="flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span className="text-[11px] font-semibold text-amber-300 uppercase tracking-wider">
                Step Suggestions ({validationList.length})
              </span>
            </div>
            <button
              type="button"
              onClick={handleAutoFixSteps}
              className="px-2.5 py-0.5 rounded-md bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 text-[10px] font-semibold transition-all active:scale-95"
            >
              Auto-Fix & Reorder
            </button>
          </div>
          <div className="space-y-1 max-h-[70px] overflow-y-auto pr-1">
            {validationList.map((issue, idx) => {
              const severityColor = {
                error: "text-rose-300 bg-rose-500/10 border-rose-500/20",
                warning: "text-amber-300 bg-amber-500/10 border-amber-500/20",
                info: "text-sky-300 bg-sky-500/10 border-sky-500/20",
              }[issue.severity] || "text-white/60 bg-white/5 border-white/10";
              
              return (
                <div key={idx} className={`p-1.5 rounded-lg border text-[10px] ${severityColor}`}>
                  <span className="font-semibold">Step {issue.step_index + 1}: {issue.title}</span> — {issue.description}
                  {issue.suggestion && (
                    <span className="opacity-75 italic ml-1">💡 {issue.suggestion}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── SCROLLABLE BODY ── */}
      <div className="p-5 space-y-4 flex-1 min-h-0 overflow-y-auto bg-black/20">
        {/* Name and Description Inputs */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-white/40 mb-1.5">
              Skill Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Send Email in Gmail"
              className="w-full bg-black/40 border border-white/[0.12] focus:border-sky-500/60 focus:bg-black/60 rounded-xl px-3.5 py-2 text-[12.5px] font-medium text-white placeholder-white/25 outline-none transition-all shadow-inner"
            />
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-white/40 mb-1.5">
              Description (Optional)
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Composes and sends emails via Gmail"
              className="w-full bg-black/40 border border-white/[0.12] focus:border-sky-500/60 focus:bg-black/60 rounded-xl px-3.5 py-2 text-[12.5px] font-medium text-white placeholder-white/25 outline-none transition-all shadow-inner"
            />
          </div>
        </div>

        {/* Triggers Section */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Trigger Phrases (How to invoke)
            </label>
            <span className="text-[10px] text-white/30">
              User can type or say these naturally
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 p-2 bg-white/[0.02] border border-white/[0.06] rounded-xl min-h-[40px]">
            {triggers.map((trig, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/[0.05] border border-white/[0.08] text-[11px] text-white/85 font-medium"
              >
                <span>{trig}</span>
                <button
                  type="button"
                  onClick={() => handleRemoveTrigger(idx)}
                  className="hover:text-rose-400 text-white/30 transition-colors ml-0.5"
                  title="Remove trigger"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}

            <form onSubmit={handleAddTrigger} className="inline-flex items-center gap-1 flex-1 min-w-[140px]">
              <Plus className="w-3 h-3 text-white/30 ml-1 shrink-0" />
              <input
                type="text"
                value={newTrigger}
                onChange={(e) => setNewTrigger(e.target.value)}
                placeholder="Add trigger phrase…"
                className="w-full bg-transparent text-[11px] text-white/80 placeholder-white/25 px-1 py-0.5 outline-none font-medium"
              />
            </form>
          </div>
        </div>

        {/* Detected Variables Banner */}
        {parameters.length > 0 && (
          <div className="p-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/20">
            <div className="flex items-center gap-1.5 text-[10.5px] font-semibold text-amber-300 uppercase tracking-wider mb-1.5">
              <Variable className="w-3.5 h-3.5 text-amber-400" />
              <span>Dynamic Variables Detected</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {parameters.map((param, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/25 text-[11px]"
                >
                  <span className="font-mono font-semibold text-amber-200">
                    {`{{${param.name}}}`}
                  </span>
                  <span className="text-[9px] uppercase px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 font-mono">
                    {param.type || "string"}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-amber-200/60 mt-2">
              If any of these fields are missing when you ask NEXUS, it will follow up conversationally to ask for them.
            </p>
          </div>
        )}

        {/* Steps Sequence List */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Automation Steps ({steps.length})
            </label>
            <span className="text-[10px] text-white/30">
              Hover step to prune noise
            </span>
          </div>

          <div className="space-y-1.5">
            {steps.map((step, idx) => {
              const info = formatStep(step);
              return (
                <div
                  key={step.step_id || idx}
                  className="group flex items-center justify-between gap-3 p-2.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.08] transition-all"
                >
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <span className="w-5 h-5 rounded-md bg-white/[0.08] text-[10px] font-mono text-white/60 flex items-center justify-center shrink-0">
                      {idx + 1}
                    </span>
                    <div className="shrink-0">{info.icon}</div>
                    <div className="min-w-0 flex-1 text-[12px] truncate">
                      {info.isType ? (
                        <div className="flex items-center gap-1.5 truncate">
                          <span className="text-white/60 font-medium">Enter:</span>
                          <span className="truncate">{renderParamHighlight(info.value)}</span>
                        </div>
                      ) : (
                        <span className="text-white/85 font-medium">{info.title}</span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[9.5px] px-2 py-0.5 rounded-md bg-white/[0.06] text-white/50 border border-white/[0.08] font-mono uppercase">
                      {info.badge}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDeleteStep(idx)}
                      className="opacity-0 group-hover:opacity-100 hover:text-rose-400 hover:bg-rose-500/15 p-1 rounded-md transition-all text-white/30"
                      title="Delete step"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── FOOTER ACTIONS ── */}
      <div className="px-5 py-3 border-t border-white/[0.1] flex items-center justify-between bg-[#0e0f17] shrink-0 sticky bottom-0 z-20">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg text-[11.5px] font-medium text-white/45 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition-all"
        >
          Discard
        </button>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={saving}
            onClick={() => handleSave(true)}
            className="px-3.5 py-1.5 rounded-lg text-[11.5px] font-medium text-white/70 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] transition-all disabled:opacity-50"
          >
            Save as Draft
          </button>

          <button
            type="button"
            disabled={saving}
            onClick={() => handleSave(false)}
            className="px-4 py-1.5 rounded-lg text-[11.5px] font-semibold text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 shadow-[0_2px_14px_rgba(56,189,248,0.35)] border border-sky-400/30 flex items-center gap-1.5 transition-all active:scale-95 disabled:opacity-50"
          >
            <Check className="w-3.5 h-3.5" />
            <span>{saving ? "Saving…" : "Save to My Skills"}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
