import React, { useState, useEffect, useRef } from "react";
import {
  GraduationCap,
  Globe,
  Monitor,
  Search,
  Trash2,
  Play,
  RefreshCw,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  X,
  Plus,
  Check,
  ShieldCheck,
  Layers,
  Square,
  Pause,
  MousePointer2,
  Keyboard,
  Navigation,
  ToggleRight,
  Eye,
  Sparkles,
  Radio,
} from "lucide-react";
import { useSkills, SkillData } from "../hooks/useSkills";
import { SkillParamModal, SkillParam } from "./SkillParamModal";
import nexusLogo from "../assets/nexus-logo.png";

interface SkillsPanelProps {
  onClose: () => void;
  onRunPrompt: (prompt: string) => void;
  initialTab?: "library" | "teach";
  currentQuery?: string;
  onOpenReviewModal: () => void;
}

type TabType = "library" | "teach";

const formatTimer = (sec: number) => {
  const mins = Math.floor(sec / 60);
  const remaining = sec % 60;
  return `${mins.toString().padStart(2, "0")}:${remaining.toString().padStart(2, "0")}`;
};

/** Classify a raw action string and return icon + formatted label */
const classifyAction = (action: string): { icon: React.ReactNode; label: string; sub?: string } => {
  const a = action.toLowerCase();
  if (a.startsWith("click") || a.includes("clicked")) {
    const target = action.replace(/^click(ed)?\s+on\s+/i, "").replace(/^click(ed)?\s+/i, "");
    return { icon: <MousePointer2 className="w-3 h-3" />, label: "Click", sub: target || action };
  }
  if (a.startsWith("type") || a.includes("typed") || a.includes("input")) {
    const text = action.replace(/^type(d)?\s+/i, "").replace(/^input\s+/i, "");
    return { icon: <Keyboard className="w-3 h-3" />, label: "Type", sub: text.length > 40 ? text.slice(0, 40) + "…" : text };
  }
  if (a.includes("navigate") || a.includes("goto") || a.includes("url") || a.includes("open")) {
    const url = action.replace(/^navigate\s+to\s+/i, "").replace(/^goto\s+/i, "").replace(/^open\s+/i, "");
    return { icon: <Navigation className="w-3 h-3" />, label: "Navigate", sub: url.length > 45 ? url.slice(0, 45) + "…" : url };
  }
  if (a.includes("select") || a.includes("choose") || a.includes("dropdown")) {
    return { icon: <ToggleRight className="w-3 h-3" />, label: "Select", sub: action.replace(/^select\s+/i, "") };
  }
  if (a.includes("scroll") || a.includes("key") || a.includes("press")) {
    return { icon: <Keyboard className="w-3 h-3" />, label: "Key", sub: action };
  }
  return { icon: <Eye className="w-3 h-3" />, label: "Action", sub: action.length > 50 ? action.slice(0, 50) + "…" : action };
};

export const SkillsPanel: React.FC<SkillsPanelProps> = ({
  onClose,
  onRunPrompt,
  initialTab = "library",
  currentQuery = "",
  onOpenReviewModal,
}) => {
  const {
    skills,
    loading,
    refreshing,
    error: skillsLoadError,
    fetchSkills,
    rollbackVersion,
    setHealthStatus,
    deleteSkill,
    teachMode,
  } = useSkills();

  const [activeTab, setActiveTab] = useState<TabType>(initialTab);
  const [selectedSkill, setSelectedSkill] = useState<SkillData | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [teachInput, setTeachInput] = useState<string>(currentQuery);
  const [teachEnv, setTeachEnv] = useState<"browser" | "desktop">("browser");
  const [teachError, setTeachError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmRollbackVer, setConfirmRollbackVer] = useState<{ skillId: string; version: number } | null>(null);
  const [panelError, setPanelError] = useState<string | null>(null);
  const [paramModalConfig, setParamModalConfig] = useState<{
    skill: SkillData;
    trigger: string;
    missingParams: SkillParam[];
  } | null>(null);
  const stepsEndRef = useRef<HTMLDivElement>(null);

  const handleTriggerClick = (skill: SkillData, trigger: string) => {
    const mustacheMatches = Array.from(trigger.matchAll(/\{\{([^}]+)\}\}/g)).map((m) => m[1].trim());
    const savedSteps = skill.versions?.[0]?.steps || [];
    const stepTemplateMatches = Array.from(
      JSON.stringify(savedSteps).matchAll(/\{\{([^}]+)\}\}/g),
    ).map((m) => m[1].trim());
    const referencedParams = new Set([...mustacheMatches, ...stepTemplateMatches]);
    const schemaParams: SkillParam[] = (skill.parameters_schema || []).map((p: any) => ({
      name: p.name || p.parameter_name || "param",
      type: (p.type || "string") as SkillParam["type"],
      description: p.description || "",
      required: p.required !== false,
      default_value: p.default_value ?? p.default ?? null,
    }));

    const paramMap = new Map<string, SkillParam>();
    for (const sp of schemaParams) {
      paramMap.set(sp.name, sp);
    }
    for (const m of mustacheMatches) {
      if (!paramMap.has(m)) {
        const isEmail = m.toLowerCase().includes("email");
        const isDate = m.toLowerCase().includes("date") || m.toLowerCase().includes("time");
        const isNum = m.toLowerCase().includes("num") || m.toLowerCase().includes("count");
        const isFile = m.toLowerCase().includes("file") || m.toLowerCase().includes("path");
        paramMap.set(m, {
          name: m,
          type: (isEmail ? "email" : isDate ? "date" : isNum ? "number" : isFile ? "filepath" : "string") as SkillParam["type"],
          description: `Value for ${m}`,
          required: true,
        });
      }
    }

    const relevantParams = referencedParams.size > 0
      ? Array.from(paramMap.values()).filter((param) => referencedParams.has(param.name))
      : Array.from(paramMap.values());
    const missing = relevantParams.filter((param) => param.required || !param.default_value);
    if (missing.length > 0) {
      setParamModalConfig({ skill, trigger, missingParams: missing });
    } else {
      onRunPrompt(trigger);
      onClose();
    }
  };

  // If teaching is active, switch to teach tab automatically
  useEffect(() => {
    if (teachMode.isTeaching) {
      setActiveTab("teach");
    }
  }, [teachMode.isTeaching]);

  // Auto-scroll steps
  useEffect(() => {
    if (stepsEndRef.current && teachMode.isTeaching) {
      stepsEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [teachMode.recentActions, teachMode.isTeaching]);

  // Handle Esc key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (confirmDeleteId) {
          setConfirmDeleteId(null);
          return;
        }
        if (confirmRollbackVer) {
          setConfirmRollbackVer(null);
          return;
        }
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, confirmDeleteId, confirmRollbackVer]);

  const filteredSkills = skills.filter((s) => {
    if (filter !== "all") {
      if (filter === "suspended" && s.health_status !== "suspended") return false;
      if (filter === "browser" && s.environment !== "browser") return false;
      if (filter === "desktop" && s.environment !== "desktop") return false;
    }
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      const matchName = s.name.toLowerCase().includes(q);
      const matchTrig = s.trigger_phrases?.some((t) => t.toLowerCase().includes(q));
      if (!matchName && !matchTrig) return false;
    }
    return true;
  });

  const handleStartDemonstration = async () => {
    if (!teachInput.trim()) {
      setTeachError("Please describe what workflow you want NEXUS to learn.");
      return;
    }
    setTeachError(null);
    const input = teachInput.trim();
    const env = teachEnv;
    setActionLoading(true);
    try {
      await teachMode.startTeach(input, env);
      onClose();
    } catch (err: any) {
      setTeachError(err.message || "Could not start recording. Check that the browser extension is connected.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleFinishDemonstration = async () => {
    const compiled = await teachMode.stopTeach();
    if (compiled) {
      onOpenReviewModal();
    }
  };

  const executeRollback = async (skillId: string, version: number) => {
    setActionLoading(true);
    setPanelError(null);
    try {
      const updated = await rollbackVersion(skillId, version);
      setSelectedSkill(updated);
      setConfirmRollbackVer(null);
    } catch (err: any) {
      setPanelError(err.message || "Failed to rollback version");
    } finally {
      setActionLoading(false);
    }
  };

  const handleReactivate = async (skillId: string) => {
    setActionLoading(true);
    setPanelError(null);
    try {
      const updated = await setHealthStatus(skillId, "healthy");
      setSelectedSkill(updated);
    } catch (err: any) {
      setPanelError(err.message || "Failed to reactivate");
    } finally {
      setActionLoading(false);
    }
  };

  const executeDelete = async (skillId: string) => {
    setDeletingId(skillId);
    setPanelError(null);
    try {
      await deleteSkill(skillId);
      if (selectedSkill?.id === skillId) setSelectedSkill(null);
      setConfirmDeleteId(null);
    } catch (err: any) {
      setPanelError(err.message || "Failed to delete skill");
    } finally {
      setDeletingId(null);
    }
  };

  const samplePrompts = [
    "Download monthly invoice from Stripe",
    "Export Google Analytics weekly report",
    "Open AWS console and check EC2 instances",
  ];

  // Theme derived from selected environment
  const envTheme = teachEnv === "browser"
    ? {
        accent: "#38bdf8",
        accentDim: "rgba(56,189,248,0.10)",
        accentBorder: "rgba(56,189,248,0.30)",
        recDot: "#f87171",
        recText: "#fca5a5",
        recBg: "rgba(248,113,113,0.12)",
        recBorder: "rgba(248,113,113,0.30)",
        stepBg: "rgba(56,189,248,0.08)",
        stepBorder: "rgba(56,189,248,0.22)",
        iconColor: "text-sky-400",
        envIcon: <Globe className="w-4 h-4 text-sky-400" />,
        envLabel: "Web Browser",
        envSub: "Chrome extension captures clicks, typing, navigation",
      }
    : {
        accent: "#a855f7",
        accentDim: "rgba(168,85,247,0.10)",
        accentBorder: "rgba(168,85,247,0.30)",
        recDot: "#f87171",
        recText: "#fca5a5",
        recBg: "rgba(248,113,113,0.12)",
        recBorder: "rgba(248,113,113,0.30)",
        stepBg: "rgba(168,85,247,0.08)",
        stepBorder: "rgba(168,85,247,0.22)",
        iconColor: "text-purple-400",
        envIcon: <Monitor className="w-4 h-4 text-purple-400" />,
        envLabel: "Desktop App",
        envSub: "Win32 window focus + native mouse/keyboard capture",
      };

  return (
    <div className="flex flex-col bg-[#101116]/95 text-white/90 select-none animate-in fade-in duration-150">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-2.5">
          <div className="w-6 h-6 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center p-0.5 shadow-[0_0_8px_rgba(168,85,247,0.25)]">
            <img src={nexusLogo} alt="Nexus" className="w-4 h-4 object-contain drop-shadow-[0_0_5px_rgba(168,85,247,0.7)]" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-white tracking-tight">Skills & Teach Studio</span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/[0.05] text-white/50 border border-white/[0.07]">
              {skills.length} {skills.length === 1 ? "skill" : "skills"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => void fetchSkills(true)}
            type="button"
            title="Reload skills"
            aria-label="Reload skills"
            disabled={loading || refreshing}
            className="w-6 h-6 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08] disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} strokeWidth={1.8} />
          </button>
          <button
            onClick={onClose}
            type="button"
            title="Close (Esc)"
            aria-label="Close Skills & Teach Studio"
            className="w-6 h-6 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08] transition-colors"
          >
            <X className="w-3.5 h-3.5" strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="px-5 pt-3 pb-2 border-b border-white/[0.05]">
        <div className="flex items-center p-0.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-xs">
          <button
            type="button"
            onClick={() => setActiveTab("library")}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium text-[11.5px] transition-all duration-150 ${
              activeTab === "library"
                ? "bg-white/[0.12] text-white shadow-sm border border-white/[0.10]"
                : "text-white/45 hover:text-white/80 hover:bg-white/[0.03]"
            }`}
          >
            <Layers className={`w-3.5 h-3.5 ${activeTab === "library" ? "text-indigo-400" : "text-white/40"}`} strokeWidth={1.8} />
            <span>Learned Skills ({skills.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("teach")}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium text-[11.5px] transition-all duration-150 ${
              activeTab === "teach"
                ? "bg-white/[0.12] text-white shadow-sm border border-white/[0.10]"
                : "text-white/45 hover:text-white/80 hover:bg-white/[0.03]"
            }`}
          >
            {teachMode.isTeaching ? (
              <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
            ) : (
              <GraduationCap className={`w-3.5 h-3.5 ${activeTab === "teach" ? "text-rose-400" : "text-white/40"}`} strokeWidth={1.8} />
            )}
            <span>
              {teachMode.isTeaching
                ? `${teachMode.isPaused ? "Paused" : "Recording"} (${formatTimer(teachMode.teachTimer)})`
                : "Teach New Skill"}
            </span>
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="overflow-y-auto px-5 py-4 space-y-3.5 text-xs max-h-[420px] custom-scrollbar">

        {/* ── TAB 1: LIBRARY ── */}
        {activeTab === "library" && (
          <div className="space-y-3">
            {/* Search + Filter */}
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-white/40" />
                <input
                  type="text"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Search skills by name or trigger phrase…"
                  className="w-full pl-8 pr-3 py-1.5 bg-white/[0.03] border border-white/[0.08] rounded-lg text-xs text-white placeholder:text-white/30 focus:outline-none focus:border-indigo-500/70"
                />
              </div>
              <div className="flex items-center gap-1 bg-white/[0.02] p-0.5 rounded-lg border border-white/[0.06] text-[11px]">
                {["all", "browser", "desktop", "suspended"].map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setFilter(cat)}
                    className={`px-2 py-1 rounded capitalize transition-colors ${
                      filter === cat ? "bg-white/[0.10] text-white font-medium" : "text-white/40 hover:text-white/70"
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            {panelError && (
              <div className="flex items-center justify-between p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs animate-in fade-in">
                <div className="flex items-center gap-2 min-w-0">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-rose-400" />
                  <span className="truncate">{panelError}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setPanelError(null)}
                  className="text-rose-400 hover:text-rose-200 p-0.5 ml-2 shrink-0"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            )}

            {skillsLoadError && (
              <div className="flex items-center justify-between gap-3 p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs" role="alert">
                <span>Could not load skills: {skillsLoadError}</span>
                <button
                  type="button"
                  onClick={() => void fetchSkills()}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-rose-400/25 hover:bg-rose-500/10 shrink-0"
                >
                  <RotateCcw className="w-3 h-3" />
                  Retry
                </button>
              </div>
            )}

            {loading && (
              <div className="py-8 text-center text-white/40 flex items-center justify-center gap-2">
                <span className="w-3.5 h-3.5 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                <span>Loading skills…</span>
              </div>
            )}

            {!loading && !skillsLoadError && filteredSkills.length === 0 && (
              <div className="py-8 text-center space-y-2.5 p-6 rounded-xl bg-white/[0.02] border border-white/[0.05]">
                <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 mx-auto flex items-center justify-center">
                  <GraduationCap className="w-5 h-5" />
                </div>
                <div className="text-sm font-semibold text-white/90">No automation skills found</div>
                <p className="text-xs text-white/40 max-w-sm mx-auto">
                  {searchTerm
                    ? "No skills matched your search query."
                    : "Teach NEXUS any workflow once by demonstration, and it will automate it on command."}
                </p>
                <button
                  type="button"
                  onClick={() => setActiveTab("teach")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-sm shadow-indigo-600/30"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Teach NEXUS a Workflow</span>
                </button>
              </div>
            )}

            {!loading && filteredSkills.length > 0 && (
              <div className="space-y-2">
                {filteredSkills.map((s) => {
                  const trigger = s.trigger_phrases?.[0] || s.name;
                  const isSelected = selectedSkill?.id === s.id;
                  const isBrowser = s.environment === "browser";
                  const isConfirmingDelete = confirmDeleteId === s.id;
                  const isDeleting = deletingId === s.id;
                  return (
                    <div
                      key={s.id}
                      className={`p-3 rounded-xl border transition-all ${
                        isSelected
                          ? "bg-white/[0.06] border-indigo-500/50 shadow-sm"
                          : "bg-white/[0.02] border-white/[0.06] hover:border-white/[0.12]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-2.5 min-w-0 flex-1">
                          <div
                            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                            style={{
                              background: isBrowser ? "rgba(56,189,248,0.08)" : "rgba(168,85,247,0.08)",
                              border: isBrowser ? "1px solid rgba(56,189,248,0.20)" : "1px solid rgba(168,85,247,0.20)",
                            }}
                          >
                            {isBrowser
                              ? <Globe className="w-3.5 h-3.5 text-sky-400" />
                              : <Monitor className="w-3.5 h-3.5 text-purple-400" />}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-white text-xs truncate">{s.name}</span>
                              {s.save_pending && (
                                <span className="inline-flex items-center gap-1 text-[9px] text-sky-300">
                                  <span className="w-2.5 h-2.5 rounded-full border border-sky-300/30 border-t-sky-300 animate-spin" />
                                  Saving
                                </span>
                              )}
                              <span className="text-[10px] font-mono text-white/40">v{s.current_version}</span>
                              {/* Environment pill */}
                              <span
                                className="text-[9px] px-1.5 py-0.5 rounded-full font-medium"
                                style={{
                                  background: isBrowser ? "rgba(56,189,248,0.10)" : "rgba(168,85,247,0.10)",
                                  border: isBrowser ? "1px solid rgba(56,189,248,0.25)" : "1px solid rgba(168,85,247,0.25)",
                                  color: isBrowser ? "#7dd3fc" : "#d8b4fe",
                                }}
                              >
                                {isBrowser ? "Browser" : "Desktop"}
                              </span>
                              {s.health_status === "healthy" && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                                  <CheckCircle2 className="w-2.5 h-2.5" /> Healthy
                                </span>
                              )}
                              {s.health_status === "degraded" && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium">
                                  <AlertTriangle className="w-2.5 h-2.5" /> Degraded
                                </span>
                              )}
                              {s.health_status === "suspended" && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] bg-rose-500/10 text-rose-400 border border-rose-500/20 font-medium">
                                  <XCircle className="w-2.5 h-2.5" /> Suspended
                                </span>
                              )}
                            </div>
                            {s.description && (
                              <p className="text-[11px] text-white/50 mt-0.5 line-clamp-1">{s.description}</p>
                            )}
                            <div className="flex items-center gap-2 mt-2 flex-wrap">
                              <span className="text-[10px] text-white/40">Trigger:</span>
                              <button
                                type="button"
                                onClick={() => handleTriggerClick(s, trigger)}
                                disabled={s.save_pending}
                                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 border border-sky-500/30 text-[10.5px] transition-colors"
                                title={s.save_pending ? "Skill is still saving" : "Click to run this skill now"}
                              >
                                <Sparkles className="w-2.5 h-2.5 text-sky-400 shrink-0" />
                                <span>"{trigger}"</span>
                                <Play className="w-2.5 h-2.5 ml-0.5 fill-sky-400 text-sky-400" />
                              </button>
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0">
                          {s.health_status === "suspended" && (
                            <button
                              type="button"
                              onClick={() => handleReactivate(s.id)}
                              className="px-2 py-1 rounded text-[10.5px] font-medium bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 border border-emerald-500/30 transition-colors"
                            >
                              Reactivate
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setSelectedSkill(isSelected ? null : s)}
                            className="px-2 py-1 rounded text-[10.5px] text-white/50 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] transition-colors"
                          >
                            {isSelected ? "Hide" : "Versions"}
                          </button>
                          {isConfirmingDelete ? (
                            <div className="flex items-center gap-1 animate-in fade-in zoom-in-95 duration-150">
                              <button
                                type="button"
                                disabled={isDeleting}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  executeDelete(s.id);
                                }}
                                className="px-2 py-1 rounded text-[10.5px] font-medium bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 transition-all flex items-center gap-1 shadow-sm"
                                title="Confirm permanent deletion"
                              >
                                {isDeleting ? (
                                  <>
                                    <span className="w-2.5 h-2.5 border-2 border-rose-400 border-t-transparent rounded-full animate-spin" />
                                    <span>Deleting…</span>
                                  </>
                                ) : (
                                  <>
                                    <Trash2 className="w-3 h-3 text-rose-400" />
                                    <span>Delete?</span>
                                  </>
                                )}
                              </button>
                              <button
                                type="button"
                                disabled={isDeleting}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setConfirmDeleteId(null);
                                }}
                                className="p-1 rounded text-white/40 hover:text-white/80 hover:bg-white/[0.06] transition-colors"
                                title="Cancel"
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setConfirmDeleteId(s.id);
                              }}
                              className="p-1.5 rounded text-white/40 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                              title="Delete skill"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>

                      {isSelected && (
                        <div className="mt-3 pt-3 border-t border-white/[0.06] space-y-2 animate-in fade-in duration-150">
                          <div className="flex items-center justify-between text-[11px] text-white/50">
                            <span className="font-semibold text-white/80">Version History & Rollbacks</span>
                            <span>Successes: {s.success_count} · Failures: {s.failure_count}</span>
                          </div>
                          <div className="space-y-1.5">
                            {s.versions && s.versions.length > 0 ? (
                              s.versions.map((v) => (
                                <div
                                  key={v.id}
                                  className="flex items-center justify-between p-2 rounded-lg bg-white/[0.02] border border-white/[0.04] text-[11px]"
                                >
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono font-medium text-white/80">v{v.version_number}</span>
                                    <span className="text-white/40">
                                      ({v.steps?.length || 0} steps) {v.change_summary || "Demonstrated workflow"}
                                    </span>
                                  </div>
                                  {v.version_number !== s.current_version ? (
                                    confirmRollbackVer?.skillId === s.id && confirmRollbackVer?.version === v.version_number ? (
                                      <div className="flex items-center gap-1 animate-in fade-in duration-150">
                                        <button
                                          type="button"
                                          disabled={actionLoading}
                                          onClick={() => executeRollback(s.id, v.version_number)}
                                          className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/25 text-amber-300 border border-amber-500/40 hover:bg-amber-500/35 transition-colors"
                                        >
                                          Confirm v{v.version_number}?
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => setConfirmRollbackVer(null)}
                                          className="p-0.5 text-white/40 hover:text-white"
                                        >
                                          <X className="w-2.5 h-2.5" />
                                        </button>
                                      </div>
                                    ) : (
                                      <button
                                        type="button"
                                        disabled={actionLoading}
                                        onClick={() => setConfirmRollbackVer({ skillId: s.id, version: v.version_number })}
                                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white/[0.06] hover:bg-white/[0.12] text-white/70 hover:text-white transition-colors"
                                      >
                                        <RotateCcw className="w-2.5 h-2.5" />
                                        <span>Restore</span>
                                      </button>
                                    )
                                  ) : (
                                    <span className="text-[10px] text-emerald-400 font-medium">Active</span>
                                  )}
                                </div>
                              ))
                            ) : (
                              <div className="text-[11px] text-white/40 italic p-1">No prior versions recorded.</div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ── TAB 2: TEACH STUDIO ── */}
        {activeTab === "teach" && (
          <div className="space-y-3">

            {/* ── ACTIVE RECORDING STATE ── */}
            {teachMode.isTeaching ? (
              <div className="space-y-3">
                {/* Recording Header Pill */}
                <div
                  className="rounded-2xl overflow-hidden"
                  style={{
                    background: "rgba(8,10,20,0.95)",
                    border: `1px solid ${teachMode.isPaused ? "rgba(255,255,255,0.12)" : envTheme.recBorder}`,
                    boxShadow: teachMode.isPaused
                      ? "none"
                      : `0 0 24px ${envTheme.accentDim}, 0 8px 24px rgba(0,0,0,0.5)`,
                  }}
                >
                  {/* Top bar */}
                  <div
                    className="flex items-center gap-2.5 px-3 py-2.5"
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
                  >
                    {/* REC badge */}
                    <div
                      className="flex items-center gap-1.5 px-2 py-1 rounded-lg shrink-0 font-mono text-[11px] font-bold tracking-wider"
                      style={{
                        background: teachMode.isPaused ? "rgba(255,255,255,0.05)" : envTheme.recBg,
                        border: `1px solid ${teachMode.isPaused ? "rgba(255,255,255,0.10)" : envTheme.recBorder}`,
                        color: teachMode.isPaused ? "rgba(255,255,255,0.40)" : envTheme.recText,
                      }}
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{
                          background: teachMode.isPaused ? "rgba(255,255,255,0.25)" : "#f87171",
                          animation: teachMode.isPaused ? "none" : "pulse 1.4s ease-in-out infinite",
                        }}
                      />
                      {teachMode.isPaused ? "PAUSED" : "REC"} {formatTimer(teachMode.teachTimer)}
                    </div>

                    {/* Env chip */}
                    <div
                      className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10.5px] font-medium shrink-0"
                      style={{
                        background: envTheme.accentDim,
                        border: `1px solid ${envTheme.accentBorder}`,
                        color: envTheme.accent,
                      }}
                    >
                      {teachMode.teachEnvironment === "browser"
                        ? <Globe className="w-3 h-3" />
                        : <Monitor className="w-3 h-3" />}
                      <span>{teachMode.teachEnvironment === "browser" ? "Browser" : "Desktop"}</span>
                    </div>

                    {/* Prompt */}
                    <span className="text-xs font-semibold truncate flex-1 min-w-0" style={{ color: "rgba(255,255,255,0.85)" }}>
                      {teachMode.teachPrompt || "Recording workflow…"}
                    </span>

                    {/* Steps count */}
                    {teachMode.eventsCount > 0 && (
                      <span
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded-md shrink-0"
                        style={{
                          background: "rgba(255,255,255,0.06)",
                          border: "1px solid rgba(255,255,255,0.10)",
                          color: "rgba(255,255,255,0.50)",
                        }}
                      >
                        {teachMode.eventsCount} step{teachMode.eventsCount !== 1 ? "s" : ""}
                      </span>
                    )}
                  </div>

                  {/* Controls row */}
                  <div className="flex items-center gap-2 px-3 py-2.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                    {/* Pause / Resume */}
                    {teachMode.isPaused ? (
                      <button
                        type="button"
                        onClick={teachMode.resumeTeach}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all active:scale-95"
                        style={{
                          background: envTheme.accentDim,
                          border: `1px solid ${envTheme.accentBorder}`,
                          color: envTheme.accent,
                        }}
                      >
                        <Play className="w-3.5 h-3.5 fill-current" />
                        <span>Resume Recording</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={teachMode.pauseTeach}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-95"
                        style={{
                          background: "rgba(255,255,255,0.04)",
                          border: "1px solid rgba(255,255,255,0.10)",
                          color: "rgba(255,255,255,0.60)",
                        }}
                      >
                        <Pause className="w-3.5 h-3.5 fill-current" />
                        <span>Pause</span>
                      </button>
                    )}

                    <div className="flex-1" />

                    {/* Discard */}
                    <button
                      type="button"
                      onClick={teachMode.discardTeach}
                      className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all hover:bg-rose-500/10 hover:text-rose-300 active:scale-95"
                      style={{ color: "rgba(255,255,255,0.40)" }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Discard</span>
                    </button>

                    {/* Finish */}
                    <button
                      type="button"
                      onClick={handleFinishDemonstration}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all active:scale-95 text-white"
                      style={{
                        background: "linear-gradient(135deg, #059669 0%, #047857 100%)",
                        boxShadow: "0 2px 12px rgba(5,150,105,0.35)",
                      }}
                    >
                      <Square className="w-3 h-3 fill-white" />
                      <span>Finish & Review</span>
                      <Check className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {/* Live step status */}
                  <div
                    className="flex items-center gap-2 px-3 py-1.5 text-[10.5px]"
                    style={{ background: "rgba(0,0,0,0.25)" }}
                  >
                    {teachMode.isPaused ? (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-white/30 shrink-0" />
                        <span style={{ color: "rgba(255,255,255,0.38)" }}>
                          Paused — {teachMode.eventsCount} step{teachMode.eventsCount !== 1 ? "s" : ""} captured so far
                        </span>
                      </>
                    ) : teachMode.eventsCount === 0 ? (
                      <>
                        <Radio className="w-3 h-3 shrink-0 animate-pulse" style={{ color: envTheme.accent }} />
                        <span style={{ color: "rgba(255,255,255,0.42)" }}>
                          {teachMode.teachEnvironment === "browser"
                            ? "Listening in Chrome — interact with any page to start recording"
                            : "Listening for desktop interactions — switch to your app"}
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                        <span className="text-emerald-300">
                          {teachMode.eventsCount} step{teachMode.eventsCount !== 1 ? "s" : ""} captured
                        </span>
                        {teachMode.recentActions.length > 0 && (
                          <span className="text-white/30 truncate">
                            · {teachMode.recentActions[teachMode.recentActions.length - 1]}
                          </span>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* ── RECORDING STEPS FEED ── */}
                <div
                  className="rounded-xl overflow-hidden"
                  style={{
                    background: "rgba(0,0,0,0.30)",
                    border: "1px solid rgba(255,255,255,0.06)",
                  }}
                >
                  <div
                    className="flex items-center justify-between px-3 py-2"
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "rgba(255,255,255,0.40)" }}>
                        Recording Steps
                      </span>
                      {teachMode.eventsCount > 0 && (
                        <span
                          className="text-[9px] font-mono px-1.5 py-0.5 rounded-full"
                          style={{
                            background: envTheme.stepBg,
                            border: `1px solid ${envTheme.stepBorder}`,
                            color: envTheme.accent,
                          }}
                        >
                          {teachMode.eventsCount}
                        </span>
                      )}
                    </div>
                    {!teachMode.isPaused && teachMode.eventsCount === 0 && (
                      <span className="flex items-center gap-1 text-[9.5px]" style={{ color: "rgba(255,255,255,0.28)" }}>
                        <Sparkles className="w-2.5 h-2.5" />
                        Live capture active
                      </span>
                    )}
                  </div>

                  <div className="px-2 py-2" style={{ maxHeight: "160px", overflowY: "auto" }}>
                    {teachMode.recentActions.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-5 gap-2 text-center">
                        <div
                          className="w-8 h-8 rounded-xl flex items-center justify-center"
                          style={{ background: envTheme.accentDim, border: `1px solid ${envTheme.accentBorder}` }}
                        >
                          {teachMode.teachEnvironment === "browser"
                            ? <Globe className="w-4 h-4" style={{ color: envTheme.accent }} />
                            : <Monitor className="w-4 h-4" style={{ color: envTheme.accent }} />}
                        </div>
                        <p className="text-[10.5px]" style={{ color: "rgba(255,255,255,0.35)" }}>
                          {teachMode.teachEnvironment === "browser"
                            ? "Switch to Chrome and interact — clicks, typing, and navigation will appear here"
                            : "Switch to your desktop app — clicks and keystrokes will appear here"}
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-0.5">
                        {teachMode.recentActions.map((action, i) => {
                          const { icon, label, sub } = classifyAction(action);
                          const isLatest = i === teachMode.recentActions.length - 1;
                          return (
                            <div
                              key={i}
                              className="flex items-start gap-2.5 px-2 py-1.5 rounded-lg transition-all"
                              style={{
                                background: isLatest ? envTheme.stepBg : "transparent",
                                border: `1px solid ${isLatest ? envTheme.stepBorder : "transparent"}`,
                              }}
                            >
                              {/* Step number */}
                              <span
                                className="text-[9px] font-mono shrink-0 mt-0.5 w-4 text-center"
                                style={{ color: "rgba(255,255,255,0.25)" }}
                              >
                                {i + 1}
                              </span>
                              {/* Timeline dot */}
                              <span
                                className="w-1.5 h-1.5 rounded-full shrink-0 mt-1"
                                style={{ background: isLatest ? envTheme.accent : "rgba(255,255,255,0.20)" }}
                              />
                              {/* Icon */}
                              <span
                                className="shrink-0 mt-0.5"
                                style={{ color: isLatest ? envTheme.accent : "rgba(255,255,255,0.38)" }}
                              >
                                {icon}
                              </span>
                              {/* Text */}
                              <div className="min-w-0 flex-1">
                                <div className="flex items-baseline gap-1.5">
                                  <span
                                    className="text-[10.5px] font-semibold shrink-0"
                                    style={{ color: isLatest ? envTheme.accent : "rgba(255,255,255,0.60)" }}
                                  >
                                    {label}
                                  </span>
                                  {sub && (
                                    <span
                                      className="text-[10px] truncate"
                                      style={{ color: isLatest ? "rgba(255,255,255,0.70)" : "rgba(255,255,255,0.35)" }}
                                    >
                                      {sub}
                                    </span>
                                  )}
                                </div>
                              </div>
                              {isLatest && (
                                <span
                                  className="text-[8px] font-bold uppercase tracking-wider shrink-0 px-1 py-0.5 rounded"
                                  style={{
                                    background: envTheme.stepBg,
                                    color: envTheme.accent,
                                    border: `1px solid ${envTheme.stepBorder}`,
                                  }}
                                >
                                  new
                                </span>
                              )}
                            </div>
                          );
                        })}
                        <div ref={stepsEndRef} />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              /* ── IDLE TEACH STUDIO FORM ── */
              <div className="space-y-3.5">
                {teachError && (
                  <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
                    {teachError}
                  </div>
                )}

                {/* Workflow Prompt Input */}
                <div className="space-y-2 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                  <label className="text-[11px] font-semibold text-white/60 uppercase tracking-wider block">
                    What workflow should NEXUS learn?
                  </label>
                  <input
                    type="text"
                    value={teachInput}
                    onChange={(e) => { setTeachInput(e.target.value); if (teachError) setTeachError(null); }}
                    placeholder="e.g. Download monthly invoice from Stripe"
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/[0.08] rounded-lg text-xs text-white placeholder:text-white/30 focus:outline-none focus:border-indigo-500"
                    onKeyDown={(e) => { if (e.key === "Enter") handleStartDemonstration(); }}
                  />
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {samplePrompts.map((s, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => setTeachInput(s)}
                        className="px-2 py-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] text-[10px] text-white/40 hover:text-white/80 transition-colors"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Environment Selection */}
                <div>
                  <p className="text-[11px] font-semibold text-white/50 uppercase tracking-wider mb-2">
                    Recording Environment
                  </p>
                  <div className="grid grid-cols-2 gap-2.5">
                    {/* Browser */}
                    <button
                      type="button"
                      onClick={() => setTeachEnv("browser")}
                      className="relative p-3.5 rounded-xl border text-left flex flex-col gap-2 transition-all group"
                      style={{
                        background: teachEnv === "browser" ? "rgba(56,189,248,0.07)" : "rgba(255,255,255,0.02)",
                        border: teachEnv === "browser" ? "1px solid rgba(56,189,248,0.40)" : "1px solid rgba(255,255,255,0.07)",
                        boxShadow: teachEnv === "browser" ? "0 0 16px rgba(56,189,248,0.08)" : "none",
                      }}
                    >
                      {teachEnv === "browser" && (
                        <span
                          className="absolute top-2.5 right-2.5 w-4 h-4 rounded-full flex items-center justify-center"
                          style={{ background: "rgba(56,189,248,0.20)", border: "1px solid rgba(56,189,248,0.40)" }}
                        >
                          <Check className="w-2.5 h-2.5 text-sky-400" />
                        </span>
                      )}
                      <div className="flex items-center gap-2">
                        <div
                          className="w-7 h-7 rounded-lg flex items-center justify-center"
                          style={{
                            background: "rgba(56,189,248,0.10)",
                            border: "1px solid rgba(56,189,248,0.22)",
                          }}
                        >
                          <Globe className="w-4 h-4 text-sky-400" />
                        </div>
                        <div>
                          <div className="text-[11.5px] font-bold text-white">Web Browser</div>
                          <div className="text-[9.5px] text-emerald-400/80 font-medium">Extension Active</div>
                        </div>
                      </div>
                      <p className="text-[10px] text-white/40 leading-relaxed">
                        Records clicks, typing, navigation in Chrome with semantic selectors.
                      </p>
                      {/* Browser pill preview */}
                      <div
                        className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[9.5px] font-mono self-start"
                        style={{
                          background: "rgba(56,189,248,0.08)",
                          border: "1px solid rgba(56,189,248,0.20)",
                          color: "#7dd3fc",
                        }}
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-red-400" style={{ animation: "pulse 1.4s ease-in-out infinite" }} />
                        <Globe className="w-2.5 h-2.5" />
                        REC Browser
                      </div>
                    </button>

                    {/* Desktop */}
                    <button
                      type="button"
                      onClick={() => setTeachEnv("desktop")}
                      className="relative p-3.5 rounded-xl border text-left flex flex-col gap-2 transition-all"
                      style={{
                        background: teachEnv === "desktop" ? "rgba(168,85,247,0.07)" : "rgba(255,255,255,0.02)",
                        border: teachEnv === "desktop" ? "1px solid rgba(168,85,247,0.40)" : "1px solid rgba(255,255,255,0.07)",
                        boxShadow: teachEnv === "desktop" ? "0 0 16px rgba(168,85,247,0.08)" : "none",
                      }}
                    >
                      {teachEnv === "desktop" && (
                        <span
                          className="absolute top-2.5 right-2.5 w-4 h-4 rounded-full flex items-center justify-center"
                          style={{ background: "rgba(168,85,247,0.20)", border: "1px solid rgba(168,85,247,0.40)" }}
                        >
                          <Check className="w-2.5 h-2.5 text-purple-400" />
                        </span>
                      )}
                      <div className="flex items-center gap-2">
                        <div
                          className="w-7 h-7 rounded-lg flex items-center justify-center"
                          style={{
                            background: "rgba(168,85,247,0.10)",
                            border: "1px solid rgba(168,85,247,0.22)",
                          }}
                        >
                          <Monitor className="w-4 h-4 text-purple-400" />
                        </div>
                        <div>
                          <div className="text-[11.5px] font-bold text-white">Desktop App</div>
                          <div className="text-[9.5px] text-white/40 font-medium">Win32 Capture</div>
                        </div>
                      </div>
                      <p className="text-[10px] text-white/40 leading-relaxed">
                        Records native interactions in Windows apps, Excel, Word, and more.
                      </p>
                      {/* Desktop pill preview */}
                      <div
                        className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[9.5px] font-mono self-start"
                        style={{
                          background: "rgba(168,85,247,0.08)",
                          border: "1px solid rgba(168,85,247,0.20)",
                          color: "#d8b4fe",
                        }}
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-red-400" style={{ animation: "pulse 1.4s ease-in-out infinite" }} />
                        <Monitor className="w-2.5 h-2.5" />
                        REC Desktop
                      </div>
                    </button>
                  </div>
                </div>

                {/* Privacy callout */}
                <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] flex items-start gap-2.5 text-[11px] text-white/50">
                  <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-medium text-white/80">Credential Masking: </span>
                    Passwords and OTP fields are automatically redacted. You review the compiled recipe before saving.
                  </div>
                </div>

                {/* Start button */}
                <div className="flex justify-end pt-1">
                  <button
                    type="button"
                    onClick={handleStartDemonstration}
                    disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white shadow-lg active:scale-95 transition-all"
                    style={{
                      background: teachEnv === "browser"
                        ? "linear-gradient(135deg, #f87171 0%, #38bdf8 100%)"
                        : "linear-gradient(135deg, #f87171 0%, #a855f7 100%)",
                      boxShadow: teachEnv === "browser"
                        ? "0 4px 16px rgba(56,189,248,0.25), 0 2px 8px rgba(248,113,113,0.20)"
                        : "0 4px 16px rgba(168,85,247,0.25), 0 2px 8px rgba(248,113,113,0.20)",
                    }}
                  >
                    {actionLoading
                      ? <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                      : <span className="w-2 h-2 rounded-full bg-white animate-ping" />}
                    <span>{actionLoading ? "Connecting to browser…" : "Start Recording"}</span>
                    {teachEnv === "browser" ? <Globe className="w-3.5 h-3.5" /> : <Monitor className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Parameter input modal when running parameterized skill */}
      {paramModalConfig && (
        <SkillParamModal
          skillName={paramModalConfig.skill.name}
          skillVersion={paramModalConfig.skill.current_version}
          matchConfidence={1.0}
          matchType="exact_trigger"
          missingParams={paramModalConfig.missingParams}
          onConfirm={(params) => {
            let finalPrompt = paramModalConfig.trigger;
            for (const [k, v] of Object.entries(params)) {
              finalPrompt = finalPrompt.split(`{{${k}}}`).join(v);
            }
            const parameterLines = Object.entries(params)
              .map(([name, value]) => `${name}: ${JSON.stringify(value)}`)
              .join("\n");
            setParamModalConfig(null);
            onRunPrompt(parameterLines ? `${finalPrompt}\n\n${parameterLines}` : finalPrompt);
            onClose();
          }}
          onDismiss={() => setParamModalConfig(null)}
        />
      )}
    </div>
  );
};
