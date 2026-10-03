import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';

export interface ScheduleDefinition {
  frequency: 'once' | 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'interval';
  target_time?: string;
  time?: string;
  days?: string[];
  day_of_month?: number;
  interval_minutes?: number;
}

export interface ScheduledTaskData {
  id: string;
  user_id: string;
  device_id: string;
  name: string;
  description: string | null;
  task_type: 'reminder' | 'automation';
  prompt: string;
  schedule_type: 'one_time' | 'recurring';
  schedule_definition: ScheduleDefinition;
  timezone: string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_status?: string | null;
  total_runs: number;
  consecutive_failures: number;
  missed_policy: 'skip' | 'run_once';
  normalized_intent?: Record<string, any>;
  execution_config?: Record<string, any>;
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface TaskArtifact {
  name: string;
  path: string;
  size_bytes: number;
  mime_type: string;
  created_at: string;
}

export interface ScheduledTaskRunData {
  id: string;
  scheduled_task_id: string;
  user_id: string;
  scheduled_for: string;
  started_at: string | null;
  completed_at: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'skipped' | 'blocked';
  result: string | null;
  error: string | null;
  execution_id: string | null;
  worker_id?: string | null;
  claimed_at?: string | null;
  artifacts?: TaskArtifact[];
  metadata: Record<string, any>;
  created_at: string;
}

export interface ParseResult {
  is_schedule: boolean;
  task_type: 'reminder' | 'automation';
  name: string;
  prompt: string;
  schedule_type: 'one_time' | 'recurring';
  schedule_definition: ScheduleDefinition;
  timezone: string;
  next_run_at: string | null;
  is_ambiguous: boolean;
  clarification_question: string | null;
  confidence: number;
  normalized_intent?: Record<string, any>;
  execution_config?: Record<string, any>;
}

export interface CreateScheduledTaskPayload {
  name: string;
  prompt: string;
  task_type: 'reminder' | 'automation';
  schedule_type: 'one_time' | 'recurring';
  schedule_definition: ScheduleDefinition;
  timezone?: string;
  missed_policy?: 'skip' | 'run_once';
  description?: string;
  normalized_intent?: Record<string, any>;
  execution_config?: Record<string, any>;
}

export const useSchedules = () => {
  const [tasks, setTasks] = useState<ScheduledTaskData[]>([]);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const { user, idToken, isGuest } = useAuth();

  const getHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (isGuest) return headers;
    if (user?.getIdToken) {
      try {
        const token = await user.getIdToken();
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
          return headers;
        }
      } catch (_) {}
    }
    if (idToken) {
      headers['Authorization'] = `Bearer ${idToken}`;
    }
    return headers;
  }, [user, idToken, isGuest]);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const headers = await getHeaders();
      const res = await fetch('http://localhost:8000/api/scheduled-tasks', { headers });
      if (!res.ok) {
        throw new Error(`Failed to load scheduled tasks (${res.status})`);
      }
      const data: ScheduledTaskData[] = await res.json();
      setTasks(data);
      const deviceRes = await fetch('http://localhost:8000/api/scheduled-tasks/device-id', { headers });
      if (deviceRes.ok) {
        const deviceData: { device_id: string } = await deviceRes.json();
        setDeviceId(deviceData.device_id);
      }
    } catch (err: any) {
      setError(err?.message || 'Error fetching scheduled tasks');
    } finally {
      setLoading(false);
    }
  }, [getHeaders]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const createTask = useCallback(async (payload: CreateScheduledTaskPayload): Promise<ScheduledTaskData> => {
    const headers = await getHeaders();
    const res = await fetch('http://localhost:8000/api/scheduled-tasks', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create scheduled task');
    }
    const created: ScheduledTaskData = await res.json();
    setTasks((prev) => [created, ...prev]);
    return created;
  }, [getHeaders]);

  const parseScheduleText = useCallback(async (text: string, timezone?: string): Promise<ParseResult> => {
    const headers = await getHeaders();
    const res = await fetch('http://localhost:8000/api/scheduled-tasks/parse', {
      method: 'POST',
      headers,
      body: JSON.stringify({ text, timezone: timezone || 'Asia/Kolkata' }),
    });
    if (!res.ok) {
      throw new Error('Failed to parse schedule');
    }
    return await res.json();
  }, [getHeaders]);

  const createFromText = useCallback(async (text: string, timezone?: string): Promise<{ created: boolean; is_ambiguous: boolean; clarification_question?: string; task?: ScheduledTaskData }> => {
    const headers = await getHeaders();
    const res = await fetch('http://localhost:8000/api/scheduled-tasks/create-from-text', {
      method: 'POST',
      headers,
      body: JSON.stringify({ text, timezone: timezone || 'Asia/Kolkata' }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create schedule from text');
    }
    const data = await res.json();
    if (data.created && data.task) {
      setTasks((prev) => [data.task, ...prev]);
    }
    return data;
  }, [getHeaders]);

  const togglePause = useCallback(async (taskId: string, currentEnabled: boolean) => {
    const endpoint = currentEnabled ? 'pause' : 'resume';
    const headers = await getHeaders();
    const res = await fetch(`http://localhost:8000/api/scheduled-tasks/${taskId}/${endpoint}`, {
      method: 'POST',
      headers,
    });
    if (!res.ok) {
      throw new Error(`Failed to ${endpoint} task`);
    }
    const updated: ScheduledTaskData = await res.json();
    setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
    return updated;
  }, [getHeaders]);

  const runNow = useCallback(async (taskId: string) => {
    const headers = await getHeaders();
    const res = await fetch(`http://localhost:8000/api/scheduled-tasks/${taskId}/run-now`, {
      method: 'POST',
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to trigger run now');
    }
    return await res.json();
  }, [getHeaders]);

  const moveToThisDevice = useCallback(async (taskId: string) => {
    const headers = await getHeaders();
    const res = await fetch(`http://localhost:8000/api/scheduled-tasks/${taskId}/move-to-this-device`, {
      method: 'POST',
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to move schedule to this device');
    }
    const updated: ScheduledTaskData = await res.json();
    setTasks((prev) => prev.map((task) => (task.id === taskId ? updated : task)));
    return updated;
  }, [getHeaders]);

  const deleteTask = useCallback(async (taskId: string) => {
    const headers = await getHeaders();
    const res = await fetch(`http://localhost:8000/api/scheduled-tasks/${taskId}`, {
      method: 'DELETE',
      headers,
    });
    if (!res.ok) {
      throw new Error('Failed to delete task');
    }
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
  }, [getHeaders]);

  const fetchRuns = useCallback(async (taskId: string): Promise<ScheduledTaskRunData[]> => {
    const headers = await getHeaders();
    const res = await fetch(`http://localhost:8000/api/scheduled-tasks/${taskId}/runs`, {
      headers,
    });
    if (!res.ok) {
      throw new Error('Failed to fetch runs');
    }
    return await res.json();
  }, [getHeaders]);

  return {
    tasks,
    deviceId,
    loading,
    error,
    fetchTasks,
    createTask,
    parseScheduleText,
    createFromText,
    togglePause,
    runNow,
    moveToThisDevice,
    deleteTask,
    fetchRuns,
  };
};
