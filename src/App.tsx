import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { SpotlightBar } from './components/SpotlightBar';
import { ModePills, SpotlightMode } from './components/ModePills';
import { SuggestionsList, SuggestionItem } from './components/SuggestionsList';
import { TaskPanel } from './components/TaskPanel';
import { SettingsPanel } from './components/SettingsPanel';
import { HistoryPanel } from './components/HistoryPanel';
import { SkillsPanel } from './components/SkillsPanel';
import { SchedulePanel } from './components/SchedulePanel';
import { SkillReviewPanel } from './components/SkillReviewPanel';
import { SkillCompilingLoader } from './components/SkillCompilingLoader';
import { KeyboardFooter } from './components/KeyboardFooter';
import { AutomationPill, AUTOMATION_TOOLS } from './components/AutomationPill';
import { RecordingPill } from './components/RecordingPill';
import { AuthPage } from './components/AuthPage';
import { BrowserConnectPage } from './components/BrowserConnectPage';
import { ConnectorsPanel } from './components/ConnectorsPanel';
import { useNexus } from './hooks/useNexus';
import { useSkills } from './hooks/useSkills';
import { useAuth } from './context/AuthContext';
import { useVoiceOutput } from './hooks/useVoiceOutput';
import { TaskState, HistoryItem } from './types/nexus';
import { formatSpokenResponse } from './utils/speechUtils';
import { ExcelCopilot } from './components/ExcelCopilot';
import { getPersonalizedPredictions, recordPredictionFeedback } from './services/recommendationEngine';
import { classifyQuerySafety } from './services/safetyFilter';

export const App: React.FC = () => {
  const urlParams = new URLSearchParams(window.location.search);
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#\/?/, ''));
  const isExcelCopilotView = urlParams.get('view') === 'excel-copilot' || hashParams.get('view') === 'excel-copilot';
  const isPillOnlyWindow = urlParams.get('view') === 'pill' || hashParams.get('view') === 'pill';
  const isAuthPage = urlParams.get('view') === 'auth' || hashParams.get('view') === 'auth';
  const isConnectPage = urlParams.get('view') === 'connect' || hashParams.get('view') === 'connect';

  if (isExcelCopilotView) {
    const hwndVal = urlParams.get('hwnd') || hashParams.get('hwnd');
    const wbVal = urlParams.get('workbook') || hashParams.get('workbook');
    return <ExcelCopilot hwnd={hwndVal} workbook={wbVal} />;
  }

  if (isConnectPage) {
    return <BrowserConnectPage />;
  }

  if (isAuthPage) {
    return <AuthPage />;
  }

  const [query, setQuery] = useState('');
  const [rawTypedQuery, setRawTypedQuery] = useState('');
  const [isSuggestionsDismissed, setIsSuggestionsDismissed] = useState(false);
  const [activeTarget, setActiveTarget] = useState<any>(null);
  const [mode, setMode] = useState<SpotlightMode>('all');
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isSkillsOpen, setIsSkillsOpen] = useState(false);
  const [isScheduleOpen, setIsScheduleOpen] = useState(false);
  const [isConnectorsOpen, setIsConnectorsOpen] = useState(false);
  const [skillsInitialTab, setSkillsInitialTab] = useState<'library' | 'teach'>('library');
  const [isSkillReviewOpen, setIsSkillReviewOpen] = useState(false);
  const [skillSaveError, setSkillSaveError] = useState<string | null>(null);
  const { teachMode, createSkill } = useSkills();
  const { isGuest, user } = useAuth();
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>(() => {
    try {
      const raw = localStorage.getItem('nexus_task_history');
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });
  const [suggestionsSeed, setSuggestionsSeed] = useState(() => Date.now());
  const cardRef = useRef<HTMLDivElement>(null);

  const {
    taskState,
    settings,
    availableModels,
    settingsSavedSuccess,
    runTask,
    respondPermission,
    submitUserInput,
    pauseTask,
    resumeTask,
    cancelTask,
    resetTask,
    saveSettings,
  } = useNexus();

  const taskStateRef = useRef(taskState);
  taskStateRef.current = taskState;

  const wasVoiceSubmittedRef = useRef(false);
  const lastSpokenResponseRef = useRef<string | null>(null);

  const {
    speak,
    stopSpeaking,
    isSpeaking,
  } = useVoiceOutput({
    defaultVoice: settings.voice_output_voice || 'en-US-AriaNeural',
    defaultSpeed: settings.voice_output_speed || '1.0x',
  });

  const queryRef = useRef(query);
  queryRef.current = query;

  const isDedicatedPage = Boolean(
    isScheduleOpen ||
    isSettingsOpen ||
    isConnectorsOpen ||
    isSkillsOpen ||
    isHistoryOpen ||
    isSkillReviewOpen ||
    (teachMode && teachMode.isTeaching)
  );

  const searchSeed = rawTypedQuery || query;

  const predictions = useMemo(() => {
    if (isDedicatedPage || !searchSeed.trim() || isSuggestionsDismissed) return [];
    return getPersonalizedPredictions(searchSeed, {
      activeTarget,
      userId: user?.uid,
      historyItems,
    });
  }, [searchSeed, isDedicatedPage, isSuggestionsDismissed, activeTarget, user?.uid, historyItems]);

  const handleArrowDown = useCallback(() => {
    if (predictions.length === 0) return false;
    const baseTyped = rawTypedQuery || query;
    if (!rawTypedQuery && query) {
      setRawTypedQuery(query);
    }
    const nextIndex = selectedIndex < predictions.length - 1 ? selectedIndex + 1 : -1;
    setSelectedIndex(nextIndex);
    setQuery(nextIndex === -1 ? baseTyped : predictions[nextIndex].query);
    return true;
  }, [predictions, selectedIndex, rawTypedQuery, query]);

  const handleArrowUp = useCallback(() => {
    if (predictions.length === 0) return false;
    const baseTyped = rawTypedQuery || query;
    if (!rawTypedQuery && query) {
      setRawTypedQuery(query);
    }
    const prevIndex = selectedIndex > 0 ? selectedIndex - 1 : selectedIndex === 0 ? -1 : predictions.length - 1;
    setSelectedIndex(prevIndex);
    setQuery(prevIndex === -1 ? baseTyped : predictions[prevIndex].query);
    return true;
  }, [predictions, selectedIndex, rawTypedQuery, query]);

  const handleEscape = useCallback(() => {
    if (predictions.length > 0 && !isSuggestionsDismissed) {
      setIsSuggestionsDismissed(true);
      setSelectedIndex(-1);
      if (rawTypedQuery) {
        setQuery(rawTypedQuery);
      }
      return true;
    }
    return false;
  }, [predictions.length, isSuggestionsDismissed, rawTypedQuery]);

  const handleRawInputChange = useCallback((typedVal: string) => {
    setRawTypedQuery(typedVal);
    setSelectedIndex(-1);
    setIsSuggestionsDismissed(false);
  }, []);

  useEffect(() => {
    if (!isGuest) return;
    setIsSkillsOpen(false);
    setIsSkillReviewOpen(false);
  }, [isGuest]);

  // State synced from mainWindow to pillWindow via IPC
  const [syncedTaskState, setSyncedTaskState] = useState<TaskState>(taskState);

  // In pillWindow: listen for state updates from mainWindow
  useEffect(() => {
    if (!isPillOnlyWindow) return;
    window.electronAPI?.sendPillAction?.('request-state-sync');
    const unsub = window.electronAPI?.onTaskStateUpdate((newState) => {
      if (newState) {
        setSyncedTaskState(newState);
      }
    });
    return () => {
      if (unsub) unsub();
    };
  }, [isPillOnlyWindow]);

  // In mainWindow: broadcast taskState to pillWindow whenever it updates
  useEffect(() => {
    if (isPillOnlyWindow) return;
    window.electronAPI?.syncTaskState?.(taskState);
  }, [isPillOnlyWindow, taskState]);

  // In mainWindow: handle actions forwarded from pillWindow
  useEffect(() => {
    if (isPillOnlyWindow) return;
    const unsub = window.electronAPI?.onPillAction(({ action, payload }) => {
      if (action === 'request-state-sync') {
        window.electronAPI?.syncTaskState?.(taskStateRef.current);
      } else if (action === 'pause') pauseTask();
      else if (action === 'resume') resumeTask();
      else if (action === 'cancel') cancelTask();
      else if (action === 'reset') resetTask();
      else if (action === 'approve') respondPermission(true);
      else if (action === 'reject') respondPermission(false);
      else if (action === 'submit_input') submitUserInput(payload?.value || '');
      else if (action === 'teach_finish') {
        window.electronAPI?.hideAutomationPill();
        window.electronAPI?.showWindow();
        teachMode.stopTeach();
      } else if (action === 'teach_discard') {
        window.electronAPI?.hideAutomationPill();
        window.electronAPI?.showWindow();
        teachMode.discardTeach();
      } else if (action === 'teach_pause') {
        teachMode.pauseTeach();
      } else if (action === 'teach_resume') {
        teachMode.resumeTeach();
      }
    });
    return () => {
      if (unsub) unsub();
    };
  }, [isPillOnlyWindow, pauseTask, resumeTask, cancelTask, resetTask, respondPermission, submitUserInput, teachMode]);


  // Active state to render depending on window context
  const activeTaskState = isPillOnlyWindow ? syncedTaskState : taskState;

  // Determine if agent execution is currently active in any capacity
  const isAgentActive =
    activeTaskState.isRunning ||
    activeTaskState.isPaused ||
    activeTaskState.plan.length > 0 ||
    activeTaskState.finalResponse !== null ||
    activeTaskState.error !== null;

  // Only trigger the floating bottom pill if the task actually performs physical on-screen UI
  // or live browser automation. Connector & MCP tasks (Gmail, GitHub, Slack, etc.) or CLI tasks
  // run silently via APIs in the background — Spotlight must stay centered and open for them.
  const requiresUiAutomation = activeTaskState.plan.some((step) => {
    const tool = step.tool || '';
    return (
      AUTOMATION_TOOLS.has(tool) ||
      tool.startsWith('browser_') ||
      tool.startsWith('inspect_screen') ||
      tool.startsWith('click_mouse') ||
      tool.startsWith('type_text')
    );
  });

  const isAutomationPlaying =
    (activeTaskState.isRunning ||
      activeTaskState.isPaused ||
      Boolean(activeTaskState.pendingPermission) ||
      Boolean(activeTaskState.userInputRequest)) &&
    (activeTaskState.plan.length === 0 ? teachMode.isTeaching : requiresUiAutomation);

  const shouldShowPill = teachMode.isTeaching || isAutomationPlaying;

  // If in independent Pill Window: sync pill height directly
  const syncPillHeight = useCallback(() => {
    const el = cardRef.current;
    if (!el || !window.electronAPI?.resizePill) return;
    const cardH = Math.ceil(Math.max(el.getBoundingClientRect().height, el.scrollHeight, el.offsetHeight));
    window.electronAPI.resizePill(cardH + 8);
  }, []);

  useEffect(() => {
    if (!isPillOnlyWindow) return;
    syncPillHeight();
    const ro = new ResizeObserver(syncPillHeight);
    if (cardRef.current) ro.observe(cardRef.current);
    return () => ro.disconnect();
  }, [isPillOnlyWindow, syncPillHeight, activeTaskState]);

  const pillVisibilityRef = useRef<'hidden' | 'shown'>('hidden');

  useEffect(() => {
    if (isPillOnlyWindow) return;
    if (taskState.taskId) {
      window.electronAPI?.syncTaskState(taskState);
    }
    if (shouldShowPill && pillVisibilityRef.current !== 'shown') {
      pillVisibilityRef.current = 'shown';
      setIsSkillsOpen(false);
      setIsSettingsOpen(false);
      setIsHistoryOpen(false);
      window.electronAPI?.showAutomationPill();
      window.electronAPI?.hideWindow();
    } else if (!shouldShowPill && pillVisibilityRef.current !== 'hidden') {
      pillVisibilityRef.current = 'hidden';
      window.electronAPI?.hideAutomationPill();
      // On completion of automation task, bring back spotlight with the final response/result!
      window.electronAPI?.showWindow();
    }
  }, [isPillOnlyWindow, teachMode.isTeaching, shouldShowPill, taskState.taskId]);

  // When draft skill is compiled (from desktop pill or browser extension finish), show review modal in Spotlight
  useEffect(() => {
    if (isPillOnlyWindow) return;
    if (teachMode.draftSkill) {
      setIsSkillReviewOpen(true);
      window.electronAPI?.showWindow();
    }
  }, [isPillOnlyWindow, teachMode.draftSkill]);

  // Send exact card height to Electron main process to resize Spotlight window
  const lastHeightRef = useRef<number>(0);
  const syncSpotlightHeight = useCallback(() => {
    if (isPillOnlyWindow) return;
    const el = cardRef.current;
    if (!el || !window.electronAPI?.resizeWindow) return;
    const cardH = Math.ceil(Math.max(el.getBoundingClientRect().height, el.scrollHeight, el.offsetHeight));
    const totalH = Math.min(cardH + 116, 940);
    if (totalH > 60 && Math.abs(totalH - lastHeightRef.current) > 2) {
      lastHeightRef.current = totalH;
      window.electronAPI.resizeWindow(860, totalH, 'center');
    }
  }, [isPillOnlyWindow]);

  useEffect(() => {
    if (isPillOnlyWindow) return;
    const el = cardRef.current;
    if (!el) return;
    // Only observe cardRef, NEVER observe rootEl or window resize to prevent feedback loops
    const ro = new ResizeObserver(syncSpotlightHeight);
    ro.observe(el);

    const handleWindowShow = () => {
      // Rotate suggested tasks on every launcher opening
      setSuggestionsSeed(prev => prev + 1);

      // If a previous task has completed/failed/stopped, reset back to clean normal spotlight when triggered with shortcut
      if (!taskStateRef.current.isRunning && !taskStateRef.current.isPaused) {
        if (
          taskStateRef.current.finalResponse !== null ||
          taskStateRef.current.error !== null ||
          taskStateRef.current.plan.length > 0 ||
          queryRef.current !== ''
        ) {
          resetTask();
          setQuery('');
          setIsSettingsOpen(false);
          setIsConnectorsOpen(false);
          setSelectedIndex(0);
        }
      }
      syncSpotlightHeight();
    };

    const unsubShow = window.electronAPI?.onWindowShow?.(handleWindowShow);

    return () => {
      ro.disconnect();
      if (unsubShow) unsubShow();
    };
  }, [isPillOnlyWindow, syncSpotlightHeight, resetTask]);

  useEffect(() => {
    if (isPillOnlyWindow) return;
    syncSpotlightHeight();
    const t1 = setTimeout(syncSpotlightHeight, 40);
    const t2 = setTimeout(syncSpotlightHeight, 120);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [isPillOnlyWindow, taskState, isSettingsOpen, isHistoryOpen, isSkillsOpen, isScheduleOpen, isConnectorsOpen, query, mode, selectedIndex, syncSpotlightHeight, teachMode.isCompilingDraft, teachMode.draftSkill, isSkillReviewOpen]);

  const handleClose = () => window.electronAPI?.hideWindow();

  const handleSelectMode = useCallback((newMode: SpotlightMode) => {
    setMode(newMode);
    setSelectedIndex(0);
  }, []);

  const handleNextMode = useCallback((direction: 1 | -1 = 1) => {
    const modes: SpotlightMode[] = ['all', 'apps', 'files', 'ai'];
    setMode(prev => {
      const idx = modes.indexOf(prev);
      const nextIdx = (idx + direction + modes.length) % modes.length;
      return modes[nextIdx];
    });
    setSelectedIndex(0);
  }, []);

  // Persist history to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('nexus_task_history', JSON.stringify(historyItems));
    } catch {}
  }, [historyItems]);

  // Sync task state outcome with latest history item & record prediction feedback
  useEffect(() => {
    if (taskState.taskId && !taskState.isRunning) {
      setHistoryItems(prev => {
        if (prev.length === 0) return prev;
        const updated = [...prev];
        const latest = { ...updated[0] };
        if (latest.status === 'running') {
          const isEligible = latest.recommendation_eligible !== false;
          if (taskState.finalResponse) {
            latest.status = 'completed';
            latest.finalResponse = taskState.finalResponse;
            if (isEligible) {
              recordPredictionFeedback(queryRef.current, 'completed', user?.uid, {
                application: activeTarget?.application,
                targetType: activeTarget?.target_type,
              });
            }
          } else if (taskState.error) {
            latest.status = 'failed';
            latest.error = taskState.error;
            if (isEligible) {
              recordPredictionFeedback(queryRef.current, 'failed', user?.uid);
            }
          } else if (!taskState.isPaused) {
            latest.status = 'completed';
            if (isEligible) {
              recordPredictionFeedback(queryRef.current, 'completed', user?.uid, {
                application: activeTarget?.application,
                targetType: activeTarget?.target_type,
              });
            }
          }
          latest.stepCount = taskState.plan.length;
          updated[0] = latest;
        }
        return updated;
      });
    }
  }, [taskState.isRunning, taskState.finalResponse, taskState.error, taskState.taskId, taskState.plan.length, taskState.isPaused, user?.uid, activeTarget]);

  const handleSubmit = (text: string, isVoice = false) => {
    if (!text.trim()) return;
    stopSpeaking();
    wasVoiceSubmittedRef.current = isVoice;
    lastSpokenResponseRef.current = null;
    setIsSettingsOpen(false);
    setIsHistoryOpen(false);
    setRawTypedQuery('');
    setSelectedIndex(-1);
    setIsSuggestionsDismissed(true);

    const safety = classifyQuerySafety(text.trim());

    // Save to history (retains query for personal record, but marks sensitivity)
    const newItem: HistoryItem = {
      id: `hist_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      timestamp: Date.now(),
      prompt: text.trim(),
      mode,
      status: 'running',
      is_sensitive: safety.is_sensitive,
      sensitivity_category: safety.sensitivity_category,
      recommendation_eligible: safety.recommendation_eligible,
      classified_at: safety.classified_at,
    };
    setHistoryItems(prev => [newItem, ...prev.slice(0, 99)]);

    // Detect if user is requesting skill recording / teach mode
    const lower = text.trim().toLowerCase();
    if (
      lower === 'record' ||
      lower.startsWith('record ') ||
      lower.startsWith('teach ') ||
      lower.startsWith('learn ')
    ) {
      const isDesktop = lower.includes('desktop') || lower.includes('app') || lower.includes('windows') || lower.includes('native');
      const isBrowser = lower.includes('browser') || lower.includes('web') || lower.includes('chrome') || !isDesktop;
      const promptIntent = text
        .replace(/^(record\s+(browser\s+|desktop\s+|workflow\s+|automation\s+)?|teach\s+(nexus\s+|skill\s+)?|learn\s+skill\s+)/i, '')
        .trim();
      teachMode.startTeach(promptIntent || 'Workflow Demonstration', isBrowser ? 'browser' : 'desktop');
      return;
    }

    runTask(text);
  };

  // Auto-speak response aloud if conversational voice response is enabled and prompt was submitted via voice
  useEffect(() => {
    if ((taskState.finalResponse || taskState.spokenResponse || taskState.error) && !taskState.isRunning && !taskState.isPaused) {
      const spokenText = formatSpokenResponse({
        spokenResponse: taskState.spokenResponse,
        finalResponse: taskState.finalResponse,
        error: taskState.error,
        goal: taskState.goal,
        prompt: query,
        plan: taskState.plan,
      });
      const autoSpeakEnabled = settings.voice_output_enabled ?? true;

      if (autoSpeakEnabled && wasVoiceSubmittedRef.current && spokenText && lastSpokenResponseRef.current !== spokenText) {
        lastSpokenResponseRef.current = spokenText;
        speak(spokenText, settings.voice_output_voice, settings.voice_output_speed);
      }
    }
  }, [taskState.finalResponse, taskState.spokenResponse, taskState.error, taskState.isRunning, taskState.isPaused, taskState.goal, taskState.plan, query, settings, speak]);

  const handleExecuteItem = (item: SuggestionItem) => {
    if (item.action) {
      item.action();
      return;
    }
    if (item.category === 'calc') {
      const result = item.title.replace(/^=\s*/, '');
      try {
        navigator.clipboard?.writeText(result);
      } catch {}
      setQuery(result);
      return;
    }
    if (item.id === 'search-web') {
      const q = query.trim();
      const url = `https://www.google.com/search?q=${encodeURIComponent(q)}`;
      if (window.electronAPI?.openExternal) {
        window.electronAPI.openExternal(url);
      } else {
        window.open(url, '_blank');
      }
      return;
    }
    if (item.category === 'history') {
      // Don't auto-rerun on history item click! Just load query & open history to view prompt & AI response
      setQuery(item.fillQuery || item.title);
      setIsHistoryOpen(true);
      return;
    }
    if (item.category === 'ai' || item.id === 'ai-prompt' || item.category === 'action' || (item as any).category === 'prediction') {
      const promptToRun = item.fillQuery || (query.trim() ? (item.id === 'ai-prompt' ? query : item.title) : item.title);
      setQuery(promptToRun);
      setRawTypedQuery(promptToRun);
      setSelectedIndex(-1);
      setIsSuggestionsDismissed(true);
      handleSubmit(promptToRun);
    } else {
      const promptToRun = item.fillQuery || item.title;
      setQuery(promptToRun);
      setRawTypedQuery(promptToRun);
      setSelectedIndex(-1);
      setIsSuggestionsDismissed(true);
      handleSubmit(promptToRun);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isFromInput = (e.target as HTMLElement)?.tagName === 'INPUT';
      if (e.key === 'Escape') {
        e.preventDefault();
        if (isSpeaking) {
          stopSpeaking();
          return;
        }
        if (handleEscape()) {
          return;
        }
        if (isPillOnlyWindow) {
          window.electronAPI?.hideAutomationPill();
        } else if (isSkillReviewOpen) {
          setIsSkillReviewOpen(false);
          teachMode.setDraftSkill(null);
        } else if (isHistoryOpen) {
          setIsHistoryOpen(false);
        } else if (isSettingsOpen) {
          setIsSettingsOpen(false);
        } else if (isSkillsOpen) {
          setIsSkillsOpen(false);
        } else if (isScheduleOpen) {
          setIsScheduleOpen(false);
        } else if (isConnectorsOpen) {
          setIsConnectorsOpen(false);
        } else if (taskState.isRunning) {
          cancelTask();
        } else if (taskState.finalResponse || taskState.error || taskState.plan.length > 0) {
          resetTask();
        } else if (query) {
          setQuery('');
          setRawTypedQuery('');
        } else {
          handleClose();
        }
      } else if (!isPillOnlyWindow && e.key === 'Tab' && !isDedicatedPage && !isSkillReviewOpen && !taskState.isRunning) {
        e.preventDefault();
        handleNextMode(e.shiftKey ? -1 : 1);
      } else if (!isPillOnlyWindow && !isFromInput && e.key === 'ArrowDown' && !isDedicatedPage && !isSkillReviewOpen && !taskState.isRunning) {
        if (handleArrowDown()) {
          e.preventDefault();
        }
      } else if (!isPillOnlyWindow && !isFromInput && e.key === 'ArrowUp' && !isDedicatedPage && !isSkillReviewOpen && !taskState.isRunning) {
        if (handleArrowUp()) {
          e.preventDefault();
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isPillOnlyWindow, isDedicatedPage, isSkillReviewOpen, taskState, query, handleNextMode, handleArrowDown, handleArrowUp, handleEscape, cancelTask, resetTask, isSpeaking, stopSpeaking]);

  // If this window is the dedicated Automation Pill Window:
  if (isPillOnlyWindow) {
    // Teach mode recording pill always renders when teaching, universally for both browser and OS applications
    if (teachMode.isTeaching) {
      return (
        <RecordingPill
          isTeaching={teachMode.isTeaching}
          environment={teachMode.teachEnvironment}
          prompt={teachMode.teachPrompt}
          timerSeconds={teachMode.teachTimer}
          eventsCount={teachMode.eventsCount}
          recentActions={teachMode.recentActions}
          isPaused={teachMode.isPaused}
          isExpanded={teachMode.isExpanded}
          onToggleExpand={teachMode.toggleExpanded}
          onPause={() => {
            if (isPillOnlyWindow) {
              window.electronAPI?.sendPillAction('teach_pause');
            } else {
              teachMode.pauseTeach();
            }
          }}
          onResume={() => {
            if (isPillOnlyWindow) {
              window.electronAPI?.sendPillAction('teach_resume');
            } else {
              teachMode.resumeTeach();
            }
          }}
          onFinish={async () => {
            window.electronAPI?.hideAutomationPill();
            window.electronAPI?.showWindow();
            if (isPillOnlyWindow) {
              window.electronAPI?.sendPillAction('teach_finish');
            } else {
              await teachMode.stopTeach();
            }
          }}
          onDiscard={async () => {
            window.electronAPI?.hideAutomationPill();
            window.electronAPI?.showWindow();
            if (isPillOnlyWindow) {
              window.electronAPI?.sendPillAction('teach_discard');
            } else {
              await teachMode.discardTeach();
            }
          }}
        />
      );
    }
    return (
      <div className="w-full select-none p-1.5" ref={cardRef}>
        <AutomationPill
          isRunning={activeTaskState.isRunning}
          isPaused={activeTaskState.isPaused}
          statusText={activeTaskState.statusText}
          plan={activeTaskState.plan}
          issues={activeTaskState.issues}
          onPause={() => {
            pauseTask();
            window.electronAPI?.sendPillAction('pause');
          }}
          onResume={() => {
            resumeTask();
            window.electronAPI?.sendPillAction('resume');
          }}
          onCancel={() => {
            cancelTask();
            window.electronAPI?.sendPillAction('cancel');
            window.electronAPI?.hideAutomationPill();
          }}
          onReset={() => {
            resetTask();
            window.electronAPI?.sendPillAction('reset');
            window.electronAPI?.hideAutomationPill();
          }}
          finalResponse={activeTaskState.finalResponse}
          error={activeTaskState.error}
          pendingPermission={activeTaskState.pendingPermission}
          onApprovePermission={() => {
            respondPermission(true);
            window.electronAPI?.sendPillAction('approve');
          }}
          onRejectPermission={() => {
            respondPermission(false);
            window.electronAPI?.sendPillAction('reject');
          }}
          userInputRequest={activeTaskState.userInputRequest}
          onSubmitUserInput={(val) => {
            submitUserInput(val);
            window.electronAPI?.sendPillAction('submit_input', { value: val });
          }}
          onAutoDismiss={() => {
            pillVisibilityRef.current = 'hidden';
            window.electronAPI?.hideAutomationPill();
          }}
        />
      </div>
    );
  }

  // ─── Teach Mode Guard ────────────────────────────────────────────────────────
  // While teaching (recording → compiling → reviewing draft) the spotlight bar
  // is completely hidden. Only the relevant teach-phase UI is shown.
  // The spotlight comes back only after the draft is saved or discarded.
  const isInTeachFlow =
    teachMode.isTeaching ||
    teachMode.isCompilingDraft ||
    Boolean(teachMode.draftSkill) ||
    isSkillReviewOpen;

  if (isInTeachFlow) {
    return (
      <div className="w-[860px] max-w-[860px] min-w-[860px] select-none pt-4 px-12 pb-24 mx-auto">
        <div className="w-full max-w-[680px] mx-auto rounded-[20px] overflow-hidden">
          {/* Phase 1: Recording (non-Electron fallback pill inside the window) */}
          {teachMode.isTeaching && !window.electronAPI && (
            <RecordingPill
              isTeaching={teachMode.isTeaching}
              environment={teachMode.teachEnvironment}
              prompt={teachMode.teachPrompt}
              timerSeconds={teachMode.teachTimer}
              eventsCount={teachMode.eventsCount}
              recentActions={teachMode.recentActions}
              isPaused={teachMode.isPaused}
              isExpanded={teachMode.isExpanded}
              onToggleExpand={teachMode.toggleExpanded}
              onPause={teachMode.pauseTeach}
              onResume={teachMode.resumeTeach}
              onFinish={async () => { await teachMode.stopTeach(); }}
              onDiscard={teachMode.discardTeach}
            />
          )}

          {/* Phase 2: Compiling */}
          {!teachMode.isTeaching && teachMode.isCompilingDraft && (
            <SkillCompilingLoader
              key={teachMode.teachSessionId || "compiling-loader"}
              prompt={teachMode.teachPrompt}
              eventsCount={teachMode.eventsCount}
              environment={teachMode.teachEnvironment}
              error={teachMode.compilationError}
              onRetry={teachMode.retryCompilation}
              onCancel={teachMode.discardTeach}
            />
          )}

          {/* Phase 3: Review draft → back to spotlight after save/discard */}
          {!teachMode.isTeaching && !teachMode.isCompilingDraft && teachMode.draftSkill && (
            <SkillReviewPanel
              draft={teachMode.draftSkill}
              saveError={skillSaveError}
              validationIssues={(teachMode.draftSkill as any).validation?.issues || []}
              onClose={() => {
                setIsSkillReviewOpen(false);
                teachMode.setDraftSkill(null);
                setSkillSaveError(null);
              }}
              onSave={(approved) => {
                setSkillSaveError(null);
                setIsSkillReviewOpen(false);
                teachMode.setDraftSkill(null);
                void createSkill(approved).catch((err: any) => {
                  setSkillSaveError(err?.message || "Skill save failed. Your draft is restored for retry.");
                  teachMode.setDraftSkill(approved);
                  setIsSkillReviewOpen(true);
                });
              }}
            />
          )}
        </div>
      </div>
    );
  }

  let disabledReason = '';
  if (isScheduleOpen) disabledReason = 'Spotlight inactive on Scheduled Tasks';
  else if (isSettingsOpen) disabledReason = 'Spotlight inactive in Settings';
  else if (isConnectorsOpen) disabledReason = 'Spotlight inactive on Connectors';
  else if (isSkillsOpen) disabledReason = 'Spotlight inactive in Skills & Teach';
  else if (isHistoryOpen) disabledReason = 'Spotlight inactive in History';
  else if (isSkillReviewOpen) disabledReason = 'Spotlight inactive during Skill Review';
  else if (teachMode?.isTeaching) disabledReason = 'Spotlight inactive during Skill Recording';

  // Otherwise, this is the main Spotlight window:
  return (
    <div
      className="w-[860px] max-w-[860px] min-w-[860px] select-none pt-4 px-12 pb-24 mx-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget && !taskState.isRunning) {
          handleClose();
        }
      }}
    >
      <div
        ref={cardRef}
        className="w-full max-w-[680px] mx-auto rounded-[20px] glass-panel overflow-hidden"
      >
        <SpotlightBar
          query={query}
          setQuery={setQuery}
          onRawInputChange={handleRawInputChange}
          onArrowDown={handleArrowDown}
          onArrowUp={handleArrowUp}
          onEscape={handleEscape}
          onTargetChange={setActiveTarget}
          mode={mode}
          onSubmit={(text, isVoice) => handleSubmit(text, isVoice)}
          onClear={() => {
            stopSpeaking();
            setQuery('');
            setRawTypedQuery('');
            resetTask();
          }}
          isLoading={taskState.isRunning}
          isAgentActive={isAgentActive}
          isInputDisabled={isDedicatedPage}
          disabledReason={disabledReason}
          onToggleSettings={() => {
            setIsSettingsOpen(prev => !prev);
            setIsHistoryOpen(false);
            setIsSkillsOpen(false);
            setIsScheduleOpen(false);
            setIsConnectorsOpen(false);
          }}
          isSettingsOpen={isSettingsOpen}
          onToggleHistory={() => {
            setIsHistoryOpen(prev => !prev);
            setIsSettingsOpen(false);
            setIsSkillsOpen(false);
            setIsScheduleOpen(false);
            setIsConnectorsOpen(false);
          }}
          isHistoryOpen={isHistoryOpen}
          onToggleSkills={(tab) => {
            if (tab) setSkillsInitialTab(tab);
            setIsSkillsOpen(prev => !prev);
            setIsSettingsOpen(false);
            setIsHistoryOpen(false);
            setIsScheduleOpen(false);
            setIsConnectorsOpen(false);
          }}
          isSkillsOpen={isSkillsOpen}
          onToggleSchedule={() => {
            setIsScheduleOpen(prev => !prev);
            setIsSettingsOpen(false);
            setIsHistoryOpen(false);
            setIsSkillsOpen(false);
            setIsConnectorsOpen(false);
          }}
          isScheduleOpen={isScheduleOpen}
          onToggleConnectors={() => {
            setIsConnectorsOpen(prev => !prev);
            setIsSettingsOpen(false);
            setIsHistoryOpen(false);
            setIsSkillsOpen(false);
            setIsScheduleOpen(false);
          }}
          isConnectorsOpen={isConnectorsOpen}
          voiceEnabled={settings.voice_input_enabled ?? true}
          wakeWordEnabled={settings.voice_wake_word_enabled ?? true}
          autoSubmitVoice={settings.voice_auto_submit ?? true}
          onInterruptSpeech={stopSpeaking}
          onOpenAuthModal={() => {
            const authUrl = 'http://localhost:5173/?view=auth';
            if (window.electronAPI?.openExternal) {
              window.electronAPI.openExternal(authUrl);
            } else {
              window.open(authUrl, '_blank');
            }
          }}
        />

        {!isSettingsOpen && !isHistoryOpen && !isSkillsOpen && !isScheduleOpen && !isConnectorsOpen && !isAgentActive && !isSkillReviewOpen && (
          <ModePills currentMode={mode} onSelectMode={handleSelectMode} />
        )}

        {isScheduleOpen ? (
          <SchedulePanel
            onClose={() => setIsScheduleOpen(false)}
            onRunPrompt={(p) => {
              setQuery(p);
              setIsScheduleOpen(false);
              handleSubmit(p);
            }}
          />
        ) : isHistoryOpen ? (
          <HistoryPanel
            items={historyItems}
            onRerunPrompt={(p) => {
              setQuery(p);
              setIsHistoryOpen(false);
              handleSubmit(p);
            }}
            onInsertPrompt={(p) => {
              setQuery(p);
              setIsHistoryOpen(false);
            }}
            onClearAll={() => setHistoryItems([])}
            onDeleteItem={(id) => setHistoryItems(prev => prev.filter(it => it.id !== id))}
            onClose={() => setIsHistoryOpen(false)}
          />
        ) : isSettingsOpen ? (
          <SettingsPanel
            settings={settings}
            models={availableModels}
            onSave={saveSettings}
            onClose={() => setIsSettingsOpen(false)}
            isSavedSuccess={settingsSavedSuccess}
            onOpenSchedule={() => {
              setIsSettingsOpen(false);
              setIsScheduleOpen(true);
            }}
          />
        ) : isSkillsOpen ? (
          <SkillsPanel
            initialTab={skillsInitialTab}
            currentQuery={query}
            onClose={() => setIsSkillsOpen(false)}
            onRunPrompt={(p) => {
              setQuery(p);
              setIsSkillsOpen(false);
              handleSubmit(p);
            }}
            onOpenReviewModal={() => setIsSkillReviewOpen(true)}
          />
        ) : isConnectorsOpen ? (
          <ConnectorsPanel onClose={() => setIsConnectorsOpen(false)} />
        ) : isAgentActive ? (
          <TaskPanel
            taskState={taskState}
            onApprovePermission={() => respondPermission(true)}
            onRejectPermission={() => respondPermission(false)}
            onSubmitUserInput={submitUserInput}
            onPause={pauseTask}
            onResume={resumeTask}
            onCancel={cancelTask}
            onReset={() => {
              stopSpeaking();
              resetTask();
              setQuery('');
            }}
            isSpeaking={isSpeaking}
            onSpeak={(text) => speak(text, settings.voice_output_voice, settings.voice_output_speed)}
            onStopSpeaking={stopSpeaking}
          />
        ) : (
          <SuggestionsList
            mode={mode}
            query={query}
            rawTypedQuery={rawTypedQuery}
            selectedIndex={selectedIndex}
            onSelectIndex={setSelectedIndex}
            onExecuteItem={handleExecuteItem}
            historyItems={historyItems}
            onFillQuery={(text) => setQuery(text)}
            suggestionsSeed={suggestionsSeed}
            predictions={predictions}
          />
        )}

        {!isDedicatedPage && !isAgentActive && <KeyboardFooter />}
      </div>
    </div>
  );
};

export default App;
