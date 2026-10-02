import React, { useState, useRef, useEffect } from "react";
import {
  Sparkles,
  X,
  ChevronRight,
  AlertCircle,
  Zap,
  Variable,
  Calendar,
  Mail,
  Hash,
  FileText,
  Type,
} from "lucide-react";

export interface SkillParam {
  name: string;
  type: "string" | "email" | "date" | "number" | "filepath";
  description: string;
  required: boolean;
  default_value?: string | null;
}

interface SkillParamModalProps {
  skillName: string;
  skillVersion?: number;
  matchConfidence?: number;
  matchType?: "exact_trigger" | "semantic_similarity" | "ai_intent";
  missingParams: SkillParam[];
  resolvedParams?: Record<string, string>;
  onConfirm: (params: Record<string, string>) => void;
  onDismiss: () => void;
}

const TYPE_ICONS: Record<string, React.ReactNode> = {
  email: <Mail className="w-3 h-3" />,
  date: <Calendar className="w-3 h-3" />,
  number: <Hash className="w-3 h-3" />,
  filepath: <FileText className="w-3 h-3" />,
  string: <Type className="w-3 h-3" />,
};

const TYPE_LABELS: Record<string, string> = {
  email: "Email",
  date: "Date",
  number: "Number",
  filepath: "File Path",
  string: "Text",
};

const TYPE_PLACEHOLDERS: Record<string, string> = {
  email: "e.g. user@example.com",
  date: "e.g. March 2026 or 2026-03-28",
  number: "e.g. 42",
  filepath: "e.g. C:\\Users\\you\\Documents\\report.xlsx",
  string: "",
};

const CONFIDENCE_LABELS: Record<string, { label: string; color: string }> = {
  exact_trigger: { label: "Exact Match", color: "#34d399" },
  semantic_similarity: { label: "Semantic Match", color: "#38bdf8" },
  ai_intent: { label: "AI Match", color: "#a78bfa" },
};

export const SkillParamModal: React.FC<SkillParamModalProps> = ({
  skillName,
  skillVersion = 1,
  matchConfidence,
  matchType,
  missingParams,
  resolvedParams = {},
  onConfirm,
  onDismiss,
}) => {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const p of missingParams) {
      // Required values from a demonstration are examples, not safe replay defaults.
      init[p.name] = !p.required ? p.default_value || "" : "";
    }
    return init;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [focused, setFocused] = useState<string | null>(null);
  const firstInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setTimeout(() => firstInputRef.current?.focus(), 80);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    for (const p of missingParams) {
      const val = (values[p.name] || "").trim();
      if (p.required && !val) {
        errs[p.name] = "This field is required.";
      } else if (p.type === "email" && val && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
        errs[p.name] = "Please enter a valid email address.";
      } else if (p.type === "number" && val && isNaN(Number(val))) {
        errs[p.name] = "Please enter a valid number.";
      }
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleConfirm = () => {
    if (!validate()) return;
    const allParams = { ...resolvedParams };
    for (const p of missingParams) {
      const val = (values[p.name] || "").trim();
      if (val) allParams[p.name] = val;
    }
    onConfirm(allParams);
  };

  const confidenceInfo = matchType ? CONFIDENCE_LABELS[matchType] : null;
  const confidencePct = matchConfidence != null ? Math.round(matchConfidence * 100) : null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{
        background: "rgba(0,0,0,0.65)",
        backdropFilter: "blur(8px)",
        animation: "spModalFadeIn 0.15s ease-out",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onDismiss(); }}
    >
      <div
        className="relative w-full max-w-md mx-4 rounded-2xl overflow-hidden"
        style={{
          background: "linear-gradient(145deg, rgba(14,15,22,0.98) 0%, rgba(18,20,32,0.97) 100%)",
          border: "1px solid rgba(99,102,241,0.25)",
          boxShadow:
            "0 32px 80px rgba(0,0,0,0.7), 0 0 0 0.5px rgba(255,255,255,0.05), inset 0 1px 0 rgba(255,255,255,0.06)",
          animation: "spModalSlideUp 0.2s cubic-bezier(0.34,1.56,0.64,1)",
        }}
      >
        {/* Top gradient accent bar */}
        <div
          className="absolute top-0 left-0 right-0 h-[1px]"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(99,102,241,0.8), rgba(139,92,246,0.8), transparent)",
          }}
        />

        {/* Glow orb */}
        <div
          className="absolute -top-16 left-1/2 -translate-x-1/2 w-32 h-32 rounded-full pointer-events-none"
          style={{
            background: "radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%)",
          }}
        />

        {/* Header */}
        <div className="flex items-start justify-between px-5 pt-5 pb-4">
          <div className="flex items-start gap-3">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5"
              style={{
                background: "linear-gradient(135deg, rgba(99,102,241,0.25), rgba(139,92,246,0.15))",
                border: "1px solid rgba(99,102,241,0.35)",
                boxShadow: "0 4px 12px rgba(99,102,241,0.2)",
              }}
            >
              <Zap className="w-4 h-4 text-indigo-400" strokeWidth={2} />
            </div>

            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-[13.5px] font-semibold text-white leading-tight">{skillName}</h2>
                <span
                  className="text-[9px] font-mono px-1.5 py-0.5 rounded border"
                  style={{
                    color: "rgba(165,180,252,0.8)",
                    borderColor: "rgba(99,102,241,0.3)",
                    background: "rgba(99,102,241,0.1)",
                  }}
                >
                  v{skillVersion}
                </span>
              </div>

              <div className="flex items-center gap-2 mt-1 flex-wrap">
                <span className="text-[11px] text-white/40">
                  {missingParams.length === 1
                    ? "1 value needed"
                    : `${missingParams.length} values needed`}
                </span>
                {confidenceInfo && confidencePct != null && (
                  <span
                    className="flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full"
                    style={{
                      color: confidenceInfo.color,
                      background: `${confidenceInfo.color}18`,
                      border: `1px solid ${confidenceInfo.color}30`,
                    }}
                  >
                    <Sparkles className="w-2.5 h-2.5" />
                    {confidenceInfo.label} {confidencePct}%
                  </span>
                )}
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={onDismiss}
            className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 transition-all"
            style={{ color: "rgba(255,255,255,0.3)" }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "white"; e.currentTarget.style.background = "rgba(255,255,255,0.1)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.3)"; e.currentTarget.style.background = "transparent"; }}
            title="Dismiss (Esc)"
          >
            <X className="w-3.5 h-3.5" strokeWidth={2} />
          </button>
        </div>

        {/* Resolved params banner */}
        {Object.keys(resolvedParams).length > 0 && (
          <div
            className="mx-5 mb-3 px-3 py-2.5 rounded-xl"
            style={{
              background: "rgba(52,211,153,0.06)",
              border: "1px solid rgba(52,211,153,0.18)",
            }}
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: "rgba(110,231,183,0.7)" }}>
              Auto-detected from prompt
            </p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(resolvedParams).map(([k, v]) => (
                <span
                  key={k}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-lg"
                  style={{
                    background: "rgba(52,211,153,0.10)",
                    color: "rgba(110,231,183,0.9)",
                    border: "1px solid rgba(52,211,153,0.22)",
                  }}
                >
                  <Variable className="w-2.5 h-2.5 flex-shrink-0" />
                  <span className="font-mono">{k}</span>
                  <span style={{ color: "rgba(255,255,255,0.25)", margin: "0 2px" }}>=</span>
                  <span className="max-w-[110px] truncate font-medium">{v}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Inputs */}
        <div className="px-5 pb-2 space-y-4">
          {missingParams.map((param, idx) => {
            const isFocused = focused === param.name;
            const hasError = !!errors[param.name];
            const typeIcon = TYPE_ICONS[param.type] || TYPE_ICONS.string;
            const typeLabel = TYPE_LABELS[param.type] || "Text";
            const placeholder = TYPE_PLACEHOLDERS[param.type] || `Enter ${param.name.replace(/_/g, " ")}…`;

            return (
              <div key={param.name}>
                <div className="flex items-center gap-2 mb-1.5">
                  <label
                    htmlFor={`skill-param-${param.name}`}
                    className="text-[12px] font-medium flex items-center gap-1.5"
                    style={{ color: "rgba(255,255,255,0.75)" }}
                  >
                    <span style={{ color: "rgba(255,255,255,0.4)" }}>{typeIcon}</span>
                    {param.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  </label>
                  {param.required && (
                    <span className="text-[9px] font-mono" style={{ color: "rgba(248,113,113,0.7)" }}>required</span>
                  )}
                  <span
                    className="ml-auto text-[10px] px-1.5 py-0.5 rounded font-mono"
                    style={{ color: "rgba(148,163,184,0.4)", background: "rgba(255,255,255,0.04)" }}
                  >
                    {typeLabel}
                  </span>
                </div>

                {param.description && (
                  <p className="text-[11px] mb-1.5 leading-snug" style={{ color: "rgba(255,255,255,0.35)" }}>
                    {param.description}
                  </p>
                )}

                <div
                  className="relative rounded-xl transition-all duration-200"
                  style={{
                    border: hasError
                      ? "1px solid rgba(248,113,113,0.5)"
                      : isFocused
                      ? "1px solid rgba(99,102,241,0.55)"
                      : "1px solid rgba(255,255,255,0.09)",
                    background: isFocused ? "rgba(99,102,241,0.06)" : "rgba(255,255,255,0.03)",
                    boxShadow: isFocused ? "0 0 0 3px rgba(99,102,241,0.12)" : "none",
                  }}
                >
                  <input
                    id={`skill-param-${param.name}`}
                    ref={idx === 0 ? firstInputRef : undefined}
                    type={param.type === "number" ? "number" : param.type === "email" ? "email" : "text"}
                    value={values[param.name] || ""}
                    placeholder={placeholder}
                    onChange={(e) => {
                      setValues((prev) => ({ ...prev, [param.name]: e.target.value }));
                      if (errors[param.name]) setErrors((prev) => ({ ...prev, [param.name]: "" }));
                    }}
                    onFocus={() => setFocused(param.name)}
                    onBlur={() => setFocused(null)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && idx === missingParams.length - 1) handleConfirm();
                    }}
                    className="w-full bg-transparent border-none outline-none px-3 py-2.5 text-[13px]"
                    style={{
                      color: "rgba(255,255,255,0.9)",
                      caretColor: "#818cf8",
                      letterSpacing: "-0.01em",
                    }}
                    autoComplete={param.type === "email" ? "email" : "off"}
                  />
                </div>

                {hasError && (
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <AlertCircle className="w-3 h-3 flex-shrink-0" style={{ color: "#f87171" }} />
                    <span className="text-[11px]" style={{ color: "#f87171" }}>{errors[param.name]}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-2.5 px-5 py-4 mt-2"
          style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
        >
          <button
            type="button"
            onClick={onDismiss}
            className="flex-1 py-2 rounded-xl text-[12px] font-medium transition-all duration-150"
            style={{
              background: "rgba(255,255,255,0.04)",
              color: "rgba(255,255,255,0.4)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "rgba(255,255,255,0.08)";
              e.currentTarget.style.color = "rgba(255,255,255,0.7)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "rgba(255,255,255,0.04)";
              e.currentTarget.style.color = "rgba(255,255,255,0.4)";
            }}
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleConfirm}
            className="flex-[2] flex items-center justify-center gap-2 py-2 rounded-xl text-[12.5px] font-semibold transition-all duration-150"
            style={{
              background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
              color: "white",
              border: "1px solid rgba(139,92,246,0.4)",
              boxShadow: "0 4px 16px rgba(99,102,241,0.3)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = "0 6px 20px rgba(99,102,241,0.45)";
              (e.currentTarget as HTMLElement).style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = "0 4px 16px rgba(99,102,241,0.3)";
              (e.currentTarget as HTMLElement).style.transform = "translateY(0)";
            }}
          >
            <Zap className="w-3.5 h-3.5" strokeWidth={2.5} />
            Run Skill
            <ChevronRight className="w-3.5 h-3.5 opacity-70" strokeWidth={2.5} />
          </button>
        </div>
      </div>

      <style>{`
        @keyframes spModalFadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes spModalSlideUp {
          from { opacity: 0; transform: translateY(20px) scale(0.96) }
          to   { opacity: 1; transform: translateY(0) scale(1) }
        }
      `}</style>
    </div>
  );
};
