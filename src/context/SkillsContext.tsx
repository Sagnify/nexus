import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "./AuthContext";

export interface SkillVersionData {
  id: string;
  skill_id: string;
  version_number: number;
  steps: any[];
  preconditions: any[];
  postconditions: any[];
  change_summary: string | null;
  created_at: string;
}

export interface SkillData {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  category: string;
  environment: string;
  trigger_phrases: string[];
  parameters_schema: any[];
  is_active: boolean;
  is_draft: boolean;
  current_version: number;
  health_status: "healthy" | "degraded" | "suspended";
  consecutive_failures: number;
  success_count: number;
  failure_count: number;
  recovery_count: number;
  last_executed_at: string | null;
  last_failed_at: string | null;
  created_at: string;
  updated_at: string;
  save_pending?: boolean;
  versions?: SkillVersionData[];
}

export interface CreateSkillPayload {
  name: string;
  description?: string;
  category?: string;
  environment?: string;
  trigger_phrases?: string[];
  parameters_schema?: any[];
  steps: any[];
  preconditions?: any[];
  postconditions?: any[];
  target_sites?: string[];
  metadata?: Record<string, any>;
  is_draft?: boolean;
}

export interface SkillsContextType {
  skills: SkillData[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  isGuest: boolean;
  fetchSkills: (force?: boolean) => Promise<void>;
  createSkill: (payload: CreateSkillPayload) => Promise<SkillData>;
  rollbackVersion: (skillId: string, targetVersion: number) => Promise<SkillData>;
  setHealthStatus: (skillId: string, healthStatus: string) => Promise<SkillData>;
  deleteSkill: (skillId: string) => Promise<void>;
  teachMode: {
    isTeaching: boolean;
    teachSessionId: string | null;
    teachTimer: number;
    teachPrompt: string;
    teachEnvironment: string;
    eventsCount: number;
    recentActions: string[];
    extensionConnected: boolean;
    draftSkill: CreateSkillPayload | null;
    isCompilingDraft: boolean;
    isPaused: boolean;
    isExpanded: boolean;
    compilationError: { message: string; error?: string; traceback?: string } | null;
    setDraftSkill: React.Dispatch<React.SetStateAction<CreateSkillPayload | null>>;
    startTeach: (intentPrompt?: string, targetEnv?: string) => Promise<any>;
    stopTeach: () => Promise<CreateSkillPayload | null>;
    discardTeach: () => Promise<void>;
    retryCompilation: () => Promise<CreateSkillPayload | null>;
    clearCompilationError: () => void;
    pauseTeach: () => void;
    resumeTeach: () => void;
    toggleExpanded: () => void;
  };
}

const SkillsContext = createContext<SkillsContextType | null>(null);
const SKILLS_CACHE_TTL_MS = 30_000;

export const SkillsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, dbUser, idToken, isGuest, loading: authLoading } = useAuth();
  const [skills, setSkills] = useState<SkillData[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [hasFetched, setHasFetched] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const skillsCacheRef = useRef<{ userId: string; skills: SkillData[]; fetchedAt: number } | null>(null);
  const pendingSkillSavesRef = useRef<Map<string, SkillData>>(new Map());
  const previousSkillsOwnerRef = useRef<string | null>(dbUser?.id ?? null);

  const [isTeaching, setIsTeaching] = useState<boolean>(false);
  const [teachSessionId, setTeachSessionId] = useState<string | null>(null);
  const [teachTimer, setTeachTimer] = useState<number>(0);
  const [teachPrompt, setTeachPrompt] = useState<string>("");
  const [teachEnvironment, setTeachEnvironment] = useState<string>("browser");
  const [eventsCount, setEventsCount] = useState<number>(0);
  const [recentActions, setRecentActions] = useState<string[]>([]);
  const [extensionConnected, setExtensionConnected] = useState<boolean>(false);
  const [draftSkill, setDraftSkill] = useState<CreateSkillPayload | null>(null);
  const [isCompilingDraft, setIsCompilingDraft] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const [compilationError, setCompilationError] = useState<{ message: string; error?: string; traceback?: string } | null>(null);
  const handledCompletedSessionsRef = useRef<Set<string>>(new Set());
  const isStoppingRef = useRef<boolean>(false);
  const isTeachingRef = useRef<boolean>(isTeaching);
  isTeachingRef.current = isTeaching;

  const isPillWindow = new URLSearchParams(window.location.search).get('view') === 'pill';

  const requestGenerationRef = useRef(0);
  const lastAuthHeaderRef = useRef<{ scope: string; token: string; expiresAt: number }>({ scope: '', token: '', expiresAt: 0 });
  const activeUserId = dbUser?.id ?? null;
  const activeUserIdRef = useRef(activeUserId);
  activeUserIdRef.current = activeUserId;

  const getRequestHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (isGuest) return headers;

    const scope = activeUserId || user?.uid || '';
    const now = Date.now();
    if (
      lastAuthHeaderRef.current.scope === scope &&
      lastAuthHeaderRef.current.token &&
      now < lastAuthHeaderRef.current.expiresAt
    ) {
      headers["Authorization"] = lastAuthHeaderRef.current.token;
      return headers;
    }
    if (user?.getIdToken) {
      try {
        const t = await user.getIdToken();
        if (t) {
          headers["Authorization"] = `Bearer ${t}`;
          lastAuthHeaderRef.current = { scope, token: `Bearer ${t}`, expiresAt: now + 5 * 60 * 1000 };
          return headers;
        }
      } catch (_) {}
    }
    if (idToken) {
      headers["Authorization"] = `Bearer ${idToken}`;
      lastAuthHeaderRef.current = { scope, token: `Bearer ${idToken}`, expiresAt: now + 5 * 60 * 1000 };
    }
    return headers;
  }, [activeUserId, idToken, isGuest, user]);

  const updateSkills = useCallback((nextSkills: SkillData[]) => {
    setSkills(nextSkills);
    if (activeUserId) {
      skillsCacheRef.current = { userId: activeUserId, skills: nextSkills, fetchedAt: Date.now() };
      try {
        localStorage.setItem(`nexus_cached_skills_${activeUserId}`, JSON.stringify(nextSkills));
      } catch {}
    }
  }, [activeUserId]);

  // Any auth transition invalidates in-flight requests and hydrates skills from persistent cache
  useEffect(() => {
    requestGenerationRef.current += 1;
    lastAuthHeaderRef.current = { scope: '', token: '', expiresAt: 0 };
    const ownerChanged = previousSkillsOwnerRef.current !== activeUserId;
    previousSkillsOwnerRef.current = activeUserId;
    if (ownerChanged || isGuest) {
      skillsCacheRef.current = null;
      let cachedSkills: SkillData[] = [];
      if (activeUserId && !isGuest) {
        try {
          const raw = localStorage.getItem(`nexus_cached_skills_${activeUserId}`);
          if (raw) cachedSkills = JSON.parse(raw);
        } catch {}
      }
      setSkills(cachedSkills);
      if (cachedSkills.length > 0 && activeUserId) {
        skillsCacheRef.current = { userId: activeUserId, skills: cachedSkills, fetchedAt: Date.now() };
        setHasFetched(true);
      } else {
        setHasFetched(false);
      }
    } else if (activeUserId && skillsCacheRef.current?.userId === activeUserId) {
      setSkills(skillsCacheRef.current.skills);
      setHasFetched(true);
    }
    setError(null);
    setLoading(false);
    setRefreshing(false);
  }, [activeUserId, authLoading, idToken, isGuest, user?.uid]);

  const fetchSkills = useCallback(async (force = false) => {
    const requestGeneration = ++requestGenerationRef.current;
    if (authLoading) return;
    if (isGuest) {
      setSkills([]);
      setLoading(false);
      setRefreshing(false);
      setHasFetched(true);
      return;
    }
    if (!activeUserId || (!user && !idToken)) {
      setLoading(false);
      setRefreshing(false);
      setHasFetched(true);
      return;
    }

    const cached = skillsCacheRef.current?.userId === activeUserId ? skillsCacheRef.current : null;
    if (cached) {
      setSkills(cached.skills);
      setHasFetched(true);
      if (!force && Date.now() - cached.fetchedAt < SKILLS_CACHE_TTL_MS) {
        setLoading(false);
        setRefreshing(false);
        return;
      }
    }

    setLoading(!cached);
    setRefreshing(Boolean(cached));
    setError(null);
    try {
      const headers = await getRequestHeaders();
      let res = await fetch("http://127.0.0.1:8000/api/skills", { headers });
      
      // If unauthorized, attempt an active token refresh and retry once
      if (res.status === 401 && user?.getIdToken) {
        try {
          const fresh = await user.getIdToken(true);
          if (fresh) {
            headers["Authorization"] = `Bearer ${fresh}`;
            res = await fetch("http://127.0.0.1:8000/api/skills", { headers });
          }
        } catch {}
      }

      if (res.status === 401 || res.status === 403) {
        if (requestGeneration === requestGenerationRef.current) {
          // Do NOT wipe skills if we already have cached skills in state!
          setError(res.status === 401
            ? "Your sign-in could not be verified. Refresh your session and retry."
            : "This account is not allowed to access saved skills.");
          setLoading(false);
          setRefreshing(false);
        }
        setHasFetched(true);
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to fetch skills (${res.status})`);
      }
      const data = await res.json();
      if (requestGeneration !== requestGenerationRef.current) return;
      const returnedSkills: SkillData[] = Array.isArray(data.skills) ? data.skills : [];
      const ownerSkills = returnedSkills.filter((skill: SkillData) => skill.user_id === activeUserId);
      const pendingSkills = Array.from(pendingSkillSavesRef.current.values())
        .filter((skill) => skill.user_id === activeUserId);
      const pendingNames = new Set(pendingSkills.map((skill) => skill.name.trim().toLowerCase()));
      updateSkills([
        ...pendingSkills,
        ...ownerSkills.filter((skill) => !pendingNames.has(skill.name.trim().toLowerCase())),
      ]);
    } catch (err: any) {
      if (requestGeneration !== requestGenerationRef.current) return;
      setError(err.message || "Failed to load skills");
      if (!cached) updateSkills([]);
    } finally {
      if (requestGeneration === requestGenerationRef.current) {
        setLoading(false);
        setRefreshing(false);
        setHasFetched(true);
      }
    }
  }, [activeUserId, isGuest, authLoading, user, idToken, getRequestHeaders, updateSkills]);

  useEffect(() => {
    if (isPillWindow) return;
    fetchSkills();
  }, [fetchSkills, isPillWindow]);

  const teachStartTimeRef = useRef<number>(0);
  useEffect(() => {
    if (!isTeaching || isPaused) return;
    if (teachStartTimeRef.current === 0) teachStartTimeRef.current = Date.now() - teachTimer * 1000;
    const tick = setInterval(() => {
      setTeachTimer(Math.floor((Date.now() - teachStartTimeRef.current) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, [isTeaching, isPaused]);

  useEffect(() => {
    if (isTeaching) teachStartTimeRef.current = Date.now();
    else teachStartTimeRef.current = 0;
  }, [isTeaching]);

  useEffect(() => {
    if (!isTeaching) {
      localStorage.removeItem('nexus_teach_session');
      return;
    }
    if (isPillWindow) return;

    const interval = setInterval(async () => {
      try {
        const headers = await getRequestHeaders();
        const res = await fetch("http://127.0.0.1:8000/api/skills/teach/status", { headers });
        if (res.ok) {
          const data = await res.json();
          if (data.is_active) {
            const count = data.events_count || 0;
            const actions = data.recent_actions || [];
            const extConn = Boolean(data.extension_connected);
            setEventsCount(count);
            setRecentActions(actions);
            setExtensionConnected(extConn);
            if (data.status === 'paused' && !isPaused) setIsPaused(true);
            if (data.status === 'recording' && isPaused) setIsPaused(false);
            const currentTimer = Math.floor((Date.now() - teachStartTimeRef.current) / 1000);
            const stateSync = {
              isTeaching: true,
              teachEnvironment,
              teachPrompt,
              teachTimer: currentTimer,
              eventsCount: count,
              recentActions: actions,
              extensionConnected: extConn,
              isPaused: data.status === 'paused',
              isCompilingDraft: false,
            };
            window.electronAPI?.syncTeachState?.(stateSync);
            localStorage.setItem('nexus_teach_session', JSON.stringify(stateSync));
          } else if (data.status === 'completed') {
            const sid = data.session_id || teachSessionId || 'active';
            if (!isStoppingRef.current && !handledCompletedSessionsRef.current.has(sid)) {
              handledCompletedSessionsRef.current.add(sid);
              await stopTeachRef.current?.();
            }
          } else if (data.status === 'idle') {
            setIsTeaching(false);
            setIsPaused(false);
            setTeachTimer(0);
            setEventsCount(0);
            setRecentActions([]);
            const idleState = {
              isTeaching: false, teachEnvironment, teachPrompt, teachTimer: 0,
              eventsCount: 0, recentActions: [], extensionConnected: false,
              isPaused: false, isCompilingDraft: false,
            };
            window.electronAPI?.syncTeachState?.(idleState);
            localStorage.removeItem('nexus_teach_session');
          }
        }
      } catch (_) {}
    }, 1000);

    return () => clearInterval(interval);
  }, [isTeaching, isPillWindow, teachEnvironment, teachPrompt, isPaused, getRequestHeaders]);

  useEffect(() => {
    if (isPillWindow) return;
    const unsub = window.electronAPI?.onRemoteTeachFinished?.(() => {
      if (!isStoppingRef.current && isTeachingRef.current) {
        setIsCompilingDraft(true);
        stopTeachRef.current?.();
      }
    });
    return () => {
      if (unsub) unsub();
    };
  }, [isPillWindow]);

  useEffect(() => {
    if (!isPillWindow) return;

    const unsub = window.electronAPI?.onTeachStateUpdate?.((d: any) => {
      if (d) {
        setIsTeaching(d.isTeaching ?? false);
        setTeachEnvironment(d.teachEnvironment ?? 'browser');
        setTeachPrompt(d.teachPrompt ?? '');
        setTeachTimer(d.teachTimer ?? 0);
        setEventsCount(d.eventsCount ?? 0);
        setRecentActions(d.recentActions ?? []);
        setExtensionConnected(d.extensionConnected ?? false);
        setIsPaused(d.isPaused ?? false);
        setIsCompilingDraft(d.isCompilingDraft ?? false);
      }
    });

    window.electronAPI?.sendPillAction?.('request-state-sync');

    const existing = localStorage.getItem('nexus_teach_session');
    if (existing) {
      try {
        const d = JSON.parse(existing);
        setIsTeaching(d.isTeaching ?? false);
        setTeachEnvironment(d.teachEnvironment ?? 'browser');
        setTeachPrompt(d.teachPrompt ?? '');
        setTeachTimer(d.teachTimer ?? 0);
        setEventsCount(d.eventsCount ?? 0);
        setRecentActions(d.recentActions ?? []);
        setIsPaused(d.isPaused ?? false);
      } catch (_) {}
    }

    return () => {
      if (unsub) unsub();
    };
  }, [isPillWindow]);

  const createSkill = async (payload: CreateSkillPayload): Promise<SkillData> => {
    const ownerId = activeUserId;
    if (!ownerId || isGuest) throw new Error("Sign in before saving a skill.");

    const pendingId = `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();
    const optimisticSkill: SkillData = {
      id: pendingId,
      user_id: ownerId,
      name: payload.name,
      description: payload.description || null,
      category: payload.category || "general",
      environment: payload.environment || "mixed",
      trigger_phrases: payload.trigger_phrases || [],
      parameters_schema: payload.parameters_schema || [],
      is_active: true,
      is_draft: Boolean(payload.is_draft),
      current_version: 1,
      health_status: "healthy",
      consecutive_failures: 0,
      success_count: 0,
      failure_count: 0,
      recovery_count: 0,
      last_executed_at: null,
      last_failed_at: null,
      created_at: now,
      updated_at: now,
      save_pending: true,
    };
    pendingSkillSavesRef.current.set(pendingId, optimisticSkill);
    updateSkills([optimisticSkill, ...skills.filter((skill) => skill.name.trim().toLowerCase() !== payload.name.trim().toLowerCase())]);
    setError(null);

    try {
      const headers = await getRequestHeaders();
      const res = await fetch("http://127.0.0.1:8000/api/skills", {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to create skill (${res.status}).`);
      }

      const data = await res.json();
      const savedSkill: SkillData = {
        ...data.skill,
        versions: data.versions ?? data.skill.versions,
        save_pending: false,
      };
      pendingSkillSavesRef.current.delete(pendingId);
      if (activeUserIdRef.current === ownerId) {
        const cachedSkills = skillsCacheRef.current?.userId === ownerId ? skillsCacheRef.current.skills : skills;
        updateSkills([
          savedSkill,
          ...cachedSkills.filter((skill) => skill.id !== pendingId && skill.id !== savedSkill.id),
        ]);
        setDraftSkill(null);
      }
      return savedSkill;
    } catch (err: any) {
      pendingSkillSavesRef.current.delete(pendingId);
      if (activeUserIdRef.current === ownerId) {
        const cachedSkills = skillsCacheRef.current?.userId === ownerId ? skillsCacheRef.current.skills : skills;
        updateSkills(cachedSkills.filter((skill) => skill.id !== pendingId));
        setError(err.message || "Failed to save skill.");
      }
      throw err;
    }
  };

  const rollbackVersion = async (skillId: string, targetVersion: number) => {
    const headers = await getRequestHeaders();
    const res = await fetch(`http://127.0.0.1:8000/api/skills/${skillId}/rollback`, {
      method: "POST",
      headers,
      body: JSON.stringify({ target_version_number: targetVersion }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to rollback version");
    }
    const data = await res.json();
    updateSkills(skills.map((s) => (s.id === skillId ? data.skill : s)));
    return data.skill;
  };

  const setHealthStatus = async (skillId: string, healthStatus: string) => {
    const headers = await getRequestHeaders();
    const res = await fetch(`http://127.0.0.1:8000/api/skills/${skillId}/health`, {
      method: "POST",
      headers,
      body: JSON.stringify({ health_status: healthStatus }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to update health status");
    }
    const data = await res.json();
    updateSkills(skills.map((s) => (s.id === skillId ? data.skill : s)));
    return data.skill;
  };

  const deleteSkill = async (skillId: string) => {
    const headers = await getRequestHeaders();
    const res = await fetch(`http://127.0.0.1:8000/api/skills/${skillId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to delete skill");
    }
    updateSkills(skills.filter((s) => s.id !== skillId));
  };

  const startTeach = async (intentPrompt: string = "", targetEnv: string = "browser") => {
    isStoppingRef.current = false;
    setTeachPrompt(intentPrompt);
    setTeachEnvironment(targetEnv);
    setTeachTimer(0);
    setEventsCount(0);
    setRecentActions([]);
    setIsTeaching(false);
    setIsPaused(false);
    setIsExpanded(false);
    setIsCompilingDraft(false);

    try {
      const headers = await getRequestHeaders();
      const res = await fetch("http://127.0.0.1:8000/api/skills/teach/start", {
        method: "POST",
        headers,
        body: JSON.stringify({
          prompt: intentPrompt,
          target_environment: targetEnv,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Failed to start recording (${res.status}).`);
      }

      const extConnected = Boolean(data.extension_connected);
      setTeachSessionId(data.session_id);
      setExtensionConnected(extConnected);
      setIsTeaching(true);

      const initSession = {
        isTeaching: true,
        teachEnvironment: targetEnv,
        teachPrompt: intentPrompt,
        teachTimer: 0,
        eventsCount: 0,
        recentActions: [],
        extensionConnected: extConnected,
        isPaused: false,
        isCompilingDraft: false,
      };
      localStorage.setItem('nexus_teach_session', JSON.stringify(initSession));
      window.electronAPI?.syncTeachState?.(initSession);
      window.electronAPI?.showAutomationPill?.();
      window.electronAPI?.hideWindow?.();
      return data;
    } catch (err: any) {
      setIsTeaching(false);
      setTeachSessionId(null);
      setExtensionConnected(false);
      setError(err.message || "Failed to start teach session");
      throw err;
    }
  };

  const stopTeach = async (): Promise<CreateSkillPayload | null> => {
    if (isStoppingRef.current) return null;
    isStoppingRef.current = true;
    setCompilationError(null);

    setIsTeaching(false);
    setIsPaused(false);
    setIsExpanded(false);
    setIsCompilingDraft(true);
    localStorage.removeItem('nexus_teach_session');

    window.electronAPI?.syncTeachState?.({
      isTeaching: false,
      teachEnvironment,
      teachPrompt,
      teachTimer,
      eventsCount,
      recentActions,
      extensionConnected,
      isPaused: false,
      isCompilingDraft: true,
    });
    if (typeof window !== 'undefined' && window.electronAPI) {
      window.electronAPI.hideAutomationPill?.();
      window.electronAPI.showWindow?.();
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 22000);

      const headers = await getRequestHeaders();
      const res = await fetch("http://127.0.0.1:8000/api/skills/teach/stop", {
        method: "POST",
        headers,
        signal: controller.signal,
        body: JSON.stringify({ session_id: teachSessionId }),
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        const compiled = data.draft;
        setDraftSkill(compiled);
        setTeachSessionId(null);
        setIsCompilingDraft(false);
        isStoppingRef.current = false;
        setCompilationError(null);
        return compiled;
      } else {
        const errData = await res.json().catch(() => ({}));
        const detail = errData.detail;
        const errObj = typeof detail === 'object' && detail !== null ? {
          message: detail.message || "Skill compilation failed",
          error: detail.error || errData.error || "Compilation Error",
          traceback: detail.traceback || errData.traceback || "",
        } : {
          message: typeof detail === 'string' ? detail : "Failed to compile demonstrated skill",
          error: typeof detail === 'string' ? detail : "Failed to compile demonstrated skill",
          traceback: "",
        };
        setCompilationError(errObj);
        setError(errObj.message);
        isStoppingRef.current = false;
      }
    } catch (err: any) {
      console.warn("[Auto-Healer] Primary teach compilation failed or timed out:", err);

      try {
        console.log("[Auto-Healer] Invoking deterministic emergency recovery endpoint...");
        const recController = new AbortController();
        const recTimeout = setTimeout(() => recController.abort(), 8000);
        const recHeaders = await getRequestHeaders();
        const recRes = await fetch("http://127.0.0.1:8000/api/skills/teach/recover", {
          method: "POST",
          headers: recHeaders,
          signal: recController.signal,
        });
        clearTimeout(recTimeout);
        if (recRes.ok) {
          const recData = await recRes.json();
          if (recData.draft) {
            console.log("[Auto-Healer] Deterministic recovery succeeded!", recData.draft);
            setDraftSkill(recData.draft);
            setTeachSessionId(null);
            setIsCompilingDraft(false);
            isStoppingRef.current = false;
            setCompilationError(null);
            return recData.draft;
          }
        }
      } catch (recErr) {
        console.warn("[Auto-Healer] Backend recovery probe failed (network/timeout):", recErr);
      }

      const compileError = {
        message: "NEXUS could not compile a reliable automation from this recording.",
        error: "Backend compilation and selector-aware recovery both failed. Action summaries alone are not safe replay steps; retry or discard this recording.",
        traceback: err?.stack || "",
      };
      setCompilationError(compileError);
      setError(compileError.message);
      isStoppingRef.current = false;
      // Keep the compilation view open with Retry/Discard instead of presenting
      // selector-free action summaries as a runnable saved skill.
      setIsCompilingDraft(true);
      return null;
    }
    return null;
  };

  const stopTeachRef = useRef(stopTeach);
  stopTeachRef.current = stopTeach;

  const retryCompilation = async (): Promise<CreateSkillPayload | null> => {
    setCompilationError(null);
    isStoppingRef.current = false;
    setIsCompilingDraft(true);

    try {
      const recController = new AbortController();
      const recTimeout = setTimeout(() => recController.abort(), 5000);
      const recHeaders = await getRequestHeaders();
      const recRes = await fetch("http://127.0.0.1:8000/api/skills/teach/recover", {
        method: "POST",
        headers: recHeaders,
        signal: recController.signal,
      });
      clearTimeout(recTimeout);
      if (recRes.ok) {
        const recData = await recRes.json();
        if (recData.draft) {
          console.log("[retryCompilation] Deterministic recovery succeeded on retry!", recData.draft);
          setDraftSkill(recData.draft);
          setTeachSessionId(null);
          setIsCompilingDraft(false);
          isStoppingRef.current = false;
          setCompilationError(null);
          try {
            await createSkill({
              name: recData.draft.name || teachPrompt || 'Recovered Workflow',
              description: recData.draft.description || '',
              category: recData.draft.category || 'general',
              environment: recData.draft.environment || teachEnvironment,
              trigger_phrases: recData.draft.trigger_phrases || [],
              parameters_schema: recData.draft.parameters_schema || [],
              steps: recData.draft.steps || [],
              preconditions: recData.draft.preconditions || [],
              postconditions: recData.draft.postconditions || [],
              is_draft: true,
            });
          } catch (saveErr: any) {
            console.warn('[retryCompilation] Auto-save failed (draft still available for manual save):', saveErr.message);
          }
          return recData.draft;
        }
      }
    } catch (recErr) {
      console.warn("[retryCompilation] Recovery endpoint failed, falling back to full stopTeach:", recErr);
    }

    return await stopTeach();
  };

  const clearCompilationError = () => {
    setCompilationError(null);
    setIsCompilingDraft(false);
    isStoppingRef.current = false;
  };

  const discardTeach = async () => {
    isStoppingRef.current = false;
    setCompilationError(null);
    setIsTeaching(false);
    setIsPaused(false);
    setIsExpanded(false);
    setIsCompilingDraft(false);
    handledCompletedSessionsRef.current.clear();
    localStorage.removeItem('nexus_teach_session');
    setTeachSessionId(null);
    setDraftSkill(null);
    setEventsCount(0);
    setRecentActions([]);

    if (typeof window !== 'undefined' && window.electronAPI) {
      window.electronAPI.hideAutomationPill?.();
      window.electronAPI.showWindow?.();
    }

    try {
      const headers = await getRequestHeaders();
      await fetch("http://127.0.0.1:8000/api/skills/teach/discard", {
        method: "POST",
        headers,
      });
    } catch (_) {}
  };

  const pauseTeach = useCallback(() => {
    setIsPaused(true);
    const existing = localStorage.getItem('nexus_teach_session');
    if (existing) {
      try {
        const d = JSON.parse(existing);
        localStorage.setItem('nexus_teach_session', JSON.stringify({ ...d, isPaused: true }));
      } catch (_) {}
    }
  }, []);

  const resumeTeach = useCallback(() => {
    setIsPaused(false);
    const existing = localStorage.getItem('nexus_teach_session');
    if (existing) {
      try {
        const d = JSON.parse(existing);
        localStorage.setItem('nexus_teach_session', JSON.stringify({ ...d, isPaused: false }));
      } catch (_) {}
    }
  }, []);

  const toggleExpanded = useCallback(() => {
    setIsExpanded(prev => !prev);
  }, []);

  return (
    <SkillsContext.Provider
      value={{
        skills: isGuest || !activeUserId ? [] : skills,
        loading: loading && !hasFetched ? true : loading,
        refreshing,
        error,
        isGuest,
        fetchSkills,
        createSkill,
        rollbackVersion,
        setHealthStatus,
        deleteSkill,
        teachMode: {
          isTeaching,
          teachSessionId,
          teachTimer,
          teachPrompt,
          teachEnvironment,
          eventsCount,
          recentActions,
          extensionConnected,
          draftSkill,
          isCompilingDraft,
          compilationError,
          isPaused,
          isExpanded,
          setDraftSkill,
          startTeach,
          stopTeach,
          discardTeach,
          retryCompilation,
          clearCompilationError,
          pauseTeach,
          resumeTeach,
          toggleExpanded,
        },
      }}
    >
      {children}
    </SkillsContext.Provider>
  );
};

export function useSkills(): SkillsContextType {
  const context = useContext(SkillsContext);
  if (!context) {
    throw new Error("useSkills must be used within a SkillsProvider");
  }
  return context;
}
