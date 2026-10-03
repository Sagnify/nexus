import { useState, useEffect, useCallback, useRef } from 'react';
import { TaskState, NexusSettings, AvailableModel } from '../types/nexus';
import { useAuth } from '../context/AuthContext';

const BACKEND_URL = 'http://127.0.0.1:8000';

const initialTaskState: TaskState = {
  taskId: null,
  isRunning: false,
  isPaused: false,
  statusText: '',
  plan: [],
  observations: [],
  issues: [],
  pendingPermission: null,
  userInputRequest: null,
  finalResponse: null,
  spokenResponse: null,
  streamingTokens: '',
  error: null,
  performanceMetrics: null,
};


export function useNexus() {
  const { idToken, user, dbUser } = useAuth();
  const [taskState, setTaskState] = useState<TaskState>(initialTaskState);
  const [settings, setSettings] = useState<NexusSettings>({});
  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [isSettingsLoading, setIsSettingsLoading] = useState(false);
  const [settingsSavedSuccess, setSettingsSavedSuccess] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Fetch settings & available models
  const loadSettings = useCallback(async () => {
    try {
      setIsSettingsLoading(true);
      const [settingsRes, modelsRes] = await Promise.all([
        fetch(`${BACKEND_URL}/api/settings`),
        fetch(`${BACKEND_URL}/api/settings/models`)
      ]);

      if (settingsRes.ok) {
        const data = await settingsRes.json();
        setSettings(data);
      }
      if (modelsRes.ok) {
        const models = await modelsRes.json();
        setAvailableModels(models);
      }
    } catch (err) {
      console.warn('Backend not reachable or settings error:', err);
    } finally {
      setIsSettingsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const saveSettings = async (newSettings: Partial<NexusSettings>) => {
    try {
      setIsSettingsLoading(true);
      const res = await fetch(`${BACKEND_URL}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings),
      });
      if (res.ok) {
        const data = await res.json();
        setSettings(data.settings);
        setSettingsSavedSuccess(true);
        setTimeout(() => setSettingsSavedSuccess(false), 3000);
        return true;
      }
    } catch (err) {
      console.error('Failed to save settings:', err);
    } finally {
      setIsSettingsLoading(false);
    }
    return false;
  };

  const cleanupStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  };

const isDateTimeQuery = (input: string): boolean => {
  const q = input.trim().toLowerCase().replace(/[?!.,]/g, '');
  return (
    q === 'time' ||
    q === 'date' ||
    q === 'clock' ||
    q === 'calendar' ||
    q === 'today' ||
    q === 'day' ||
    q.includes('what time') ||
    q.includes('what is the time') ||
    q.includes("what's the time") ||
    q.includes('current time') ||
    q.includes('current date') ||
    q.includes('what is the date') ||
    q.includes("what's the date") ||
    q.includes("today's date") ||
    q.includes("todays date") ||
    q.includes('what day is it') ||
    q.includes('what is today')
  );
};

  const runTask = async (input: string) => {
    if (!input.trim()) return;

    const previousTaskId = taskState.taskId;
    const previousTaskIsActive = Boolean(
      taskState.isRunning ||
      taskState.isPaused ||
      taskState.pendingPermission ||
      taskState.userInputRequest
    );
    cleanupStream();

    if (previousTaskId && previousTaskIsActive) {
      try {
        await fetch(`${BACKEND_URL}/api/nexus/cancel/${previousTaskId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        });
      } catch (err) {
        console.warn('Could not cancel previous task before starting a new one:', err);
      }
    }

    // Instant local handling for time & date queries (0ms, no cloud LLM lag or thinking state)
    if (isDateTimeQuery(input)) {
      setTaskState({
        ...initialTaskState,
        isRunning: false,
        statusText: 'Local System',
        intent: 'time',
        model: 'system-clock',
        goal: input,
        finalResponse: 'Current system time and date rendered above.',
        plan: [],
      });
      return;
    }

    setTaskState({
      ...initialTaskState,
      isRunning: true,
      statusText: 'Connecting to agent runtime...',
    });

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (idToken) {
        headers['Authorization'] = `Bearer ${idToken}`;
      }

      const userName = user?.displayName || dbUser?.display_name || undefined;
      const res = await fetch(`${BACKEND_URL}/api/nexus/run`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ input, user_name: userName }),
      });

      if (!res.ok) {
        throw new Error(`Execution error: ${res.statusText}`);
      }

      const data = await res.json();
      const taskId = data.task_id;

      setTaskState(prev => ({
        ...prev,
        taskId,
        statusText: 'Thinking...',
      }));

      // Connect SSE
      const sse = new EventSource(`${BACKEND_URL}/api/nexus/stream/${taskId}`);
      eventSourceRef.current = sse;

      sse.addEventListener('status', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          statusText: d.message || d.status,
          isPaused: d.status === 'paused' ? true : d.status === 'executing' ? false : prev.isPaused,
        }));
      });

      sse.addEventListener('pause_state', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          isPaused: Boolean(d.is_paused),
          statusText: d.is_paused ? 'Automation Paused' : 'Executing...',
        }));
      });

      sse.addEventListener('intent', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          intent: d.intent,
          goal: d.goal,
          model: d.model,
          statusText: 'Thinking...',
        }));
      });

      sse.addEventListener('token', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          streamingTokens: (prev.streamingTokens || '') + (d.chunk || ''),
          statusText: 'Thinking...',
        }));
      });

      sse.addEventListener('reasoning', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          reasoning: d.thought,
          statusText: 'Thinking...',
        }));
      });

      sse.addEventListener('reasoning_chunk', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          reasoning: d.thought || ((prev.reasoning || '') + (d.delta || '')),
          statusText: prev.statusText === 'Reframing steps with AI...' ? prev.statusText : 'Thinking...',
        }));
      });

      sse.addEventListener('plan', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        const isDirectAnswer = d.steps?.length === 1 && d.steps[0]?.tool === 'ai_response';
        setTaskState(prev => ({
          ...prev,
          plan: d.steps || [],
          streamingTokens: '',  // Clear streaming text once plan is materialised
          statusText: isDirectAnswer ? 'Thinking...' : 'Working on it...',
        }));
      });

      sse.addEventListener('step_progress', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          plan: d.plan || prev.plan,
        }));
      });

      sse.addEventListener('observation', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          observations: [...prev.observations, d.observation],
        }));
      });

      sse.addEventListener('permission_required', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          isRunning: false,
          statusText: 'Requires Approval',
          pendingPermission: {
            taskId,
            stepId: d.plan?.[d.current_step]?.id || 'step',
            items: d.items || [],
            plan: d.plan || prev.plan,
            currentStep: d.current_step,
          },
        }));
      });

      sse.addEventListener('user_input_request', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          statusText: 'Input Required',
          userInputRequest: {
            taskId: d.task_id || taskId,
            prompt: d.prompt || 'Please provide input:',
            options: d.options || [],
            placeholder: d.placeholder || 'Type your answer...',
          },
        }));
      });

      sse.addEventListener('user_input_resolved', () => {
        setTaskState(prev => ({
          ...prev,
          userInputRequest: null,
          statusText: prev.isRunning ? 'Executing...' : prev.statusText,
        }));
      });

      sse.addEventListener('issue', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        const newIssue = {
          id: d.id || Math.random().toString(36).substring(2),
          type: d.type || 'warning',
          message: d.message || d.error || 'Issue detected',
          timestamp: d.timestamp || new Date().toLocaleTimeString(),
          step: d.step,
        };
        setTaskState(prev => {
          const existing = (prev.issues || []).find(i => i.message === newIssue.message);
          if (existing) {
            return {
              ...prev,
              issues: (prev.issues || []).map(i => i.message === newIssue.message ? { ...i, count: (i.count || 1) + 1, timestamp: newIssue.timestamp } : i)
            };
          }
          return {
            ...prev,
            issues: [...(prev.issues || []), newIssue],
          };
        });
      });

      sse.addEventListener('performance_metrics', (e: MessageEvent) => {
        try {
          const d = JSON.parse(e.data);
          setTaskState(prev => ({
            ...prev,
            performanceMetrics: d,
          }));
        } catch (err) {
          console.error('Failed to parse performance_metrics:', err);
        }
      });

      sse.addEventListener('completed', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        setTaskState(prev => ({
          ...prev,
          isRunning: false,
          statusText: 'Completed',
          finalResponse: d.final_response,
          spokenResponse: d.spoken_response || null,
          plan: d.plan || prev.plan,
          performanceMetrics: d.performance_metrics || prev.performanceMetrics || null,
        }));
      });

      sse.addEventListener('error', (e: MessageEvent) => {
        const d = JSON.parse(e.data);
        const errText = d.error || 'Execution stopped.';
        const errIssue = {
          id: Math.random().toString(36).substring(2),
          type: 'failure',
          message: errText,
          timestamp: new Date().toLocaleTimeString(),
        };
        setTaskState(prev => ({
          ...prev,
          isRunning: false,
          statusText: 'Error',
          error: errText,
          plan: d.plan || prev.plan,
          finalResponse: d.final_response || prev.finalResponse,
          spokenResponse: d.spoken_response || null,
          issues: [...(prev.issues || []).filter(i => i.message !== errText), errIssue],
        }));
      });

      sse.addEventListener('done', () => {
        cleanupStream();
        setTaskState(prev => ({ ...prev, isRunning: false }));
      });

      sse.onerror = () => {
        cleanupStream();
        setTaskState(prev => {
          if (prev.isRunning && !prev.finalResponse) {
            return { ...prev, isRunning: false, error: 'Connection to agent stream lost.' };
          }
          return { ...prev, isRunning: false };
        });
      };

    } catch (err: any) {
      setTaskState(prev => ({
        ...prev,
        isRunning: false,
        error: err.message || 'Failed to start agent task.',
      }));
    }
  };

  const respondPermission = async (approved: boolean) => {
    const perm = taskState.pendingPermission;
    if (!perm) return;

    try {
      setTaskState(prev => ({
        ...prev,
        isRunning: approved,
        statusText: approved ? 'Resuming execution...' : 'Rejected by user',
      }));

      const res = await fetch(`${BACKEND_URL}/api/nexus/permission/${perm.taskId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          step_id: perm.stepId,
          approved,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Permission request failed (${res.status}).`);
      }
      const expectedStatus = approved ? 'resumed' : 'rejected';
      if (data.status !== expectedStatus) {
        throw new Error(data.detail || `Unexpected permission response: ${data.status || 'empty response'}.`);
      }
      setTaskState(prev => ({
        ...prev,
        pendingPermission: null,
        isRunning: approved,
        statusText: approved ? 'Resuming execution...' : 'Rejected by user',
      }));
    } catch (err: any) {
      setTaskState(prev => ({
        ...prev,
        isRunning: false,
        pendingPermission: perm,
        statusText: 'Approval could not be processed',
        error: err.message || 'Permission request failed.',
      }));
    }
  };

  const pauseTask = async () => {
    if (!taskState.taskId) return;
    try {
      setTaskState(prev => ({ ...prev, isPaused: true, statusText: 'Automation Paused' }));
      await fetch(`${BACKEND_URL}/api/nexus/pause/${taskState.taskId}`, {
        method: 'POST',
      });
    } catch (err) {
      console.warn('Error pausing:', err);
    }
  };

  const resumeTask = async () => {
    if (!taskState.taskId) return;
    try {
      setTaskState(prev => ({ ...prev, isPaused: false, statusText: 'Resuming automation...' }));
      await fetch(`${BACKEND_URL}/api/nexus/resume/${taskState.taskId}`, {
        method: 'POST',
      });
    } catch (err) {
      console.warn('Error resuming:', err);
    }
  };

  const submitUserInput = async (value: string, explicitTaskId?: string) => {
    const req = taskState.userInputRequest;
    const tid = explicitTaskId || req?.taskId || taskState.taskId;
    try {
      setTaskState(prev => ({
        ...prev,
        userInputRequest: null,
        statusText: 'Processing input...',
      }));
      await fetch(`${BACKEND_URL}/api/nexus/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value, task_id: tid }),
      });
    } catch (err: any) {
      console.warn('Error submitting user input:', err);
    }
  };

  const cancelTask = async () => {
    try {
      cleanupStream();
      const cancelUrl = taskState.taskId
        ? `${BACKEND_URL}/api/nexus/cancel/${taskState.taskId}`
        : `${BACKEND_URL}/api/nexus/cancel`;
      await fetch(cancelUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
    } catch (err) {
      console.warn('Error cancelling:', err);
    } finally {
      setTaskState(prev => ({
        ...prev,
        isRunning: false,
        isPaused: false,
        statusText: 'Cancelled',
      }));
    }
  };

  const resetTask = () => {
    cleanupStream();
    setTaskState(initialTaskState);
  };

  useEffect(() => {
    return () => cleanupStream();
  }, []);

  return {
    taskState,
    settings,
    availableModels,
    isSettingsLoading,
    settingsSavedSuccess,
    runTask,
    respondPermission,
    submitUserInput,
    pauseTask,
    resumeTask,
    cancelTask,
    resetTask,
    saveSettings,
    loadSettings,
  };
}

