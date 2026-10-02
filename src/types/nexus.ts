export type RiskLevel = 'READ_ONLY' | 'SAFE' | 'MODIFYING' | 'NETWORK' | 'DESTRUCTIVE' | 'PRIVILEGED';

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface PlanStep {
  id: string;
  title: string;
  description: string;
  tool: string;
  args: Record<string, any>;
  risk_level: RiskLevel;
  status: StepStatus;
  result?: string | null;
  error?: string | null;
}

export interface PermissionRequest {
  taskId: string;
  stepId: string;
  items: string[];
  plan: PlanStep[];
  currentStep: number;
}

export interface HistoryItem {
  id: string;
  timestamp: number;
  prompt: string;
  mode?: string;
  status: 'completed' | 'failed' | 'cancelled' | 'running';
  finalResponse?: string | null;
  error?: string | null;
  stepCount?: number;
  is_sensitive?: boolean;
  sensitivity_category?: string | null;
  recommendation_eligible?: boolean;
  classified_at?: number;
}

export interface NexusSettings {
  groq_api_key?: string;
  gemma_api_key?: string;
  groq_fast_model?: string;
  groq_reasoning_model?: string;
  groq_vision_model?: string;
  groq_tool_model?: string;
  postgres_url?: string;
  embedding_model?: string;
  voice_input_enabled?: boolean;
  voice_wake_word_enabled?: boolean;
  voice_auto_submit?: boolean;
  voice_output_enabled?: boolean;
  voice_output_voice?: string;
  voice_output_speed?: string;
}

export interface AvailableModel {
  name: string;
  model_id: string;
  context_window: number;
  speed: string;
  reasoning: boolean;
  tool_calling: boolean;
  vision: boolean;
}

export interface IssueItem {
  id?: string;
  type?: string;
  message: string;
  timestamp?: string;
  step?: number | string;
  count?: number;
}

export interface UserInputRequest {
  taskId: string;
  prompt: string;
  options?: string[];
  placeholder?: string;
}

export interface PerformanceMetrics {
  llm_calls: number;
  deterministic_steps: number;
  tokens_saved: number;
  latency_ms: number;
  fast_path?: string | null;
  cache_hit?: boolean;
  validation_tier?: string | null;
  validation_passed?: boolean | null;
  validation_reason?: string | null;
}

export interface TaskState {
  taskId: string | null;
  isRunning: boolean;
  isPaused?: boolean;
  statusText: string;
  intent?: string;
  goal?: string;
  model?: string;
  reasoning?: string;
  plan: PlanStep[];
  observations: string[];
  issues?: IssueItem[];
  pendingPermission: PermissionRequest | null;
  userInputRequest?: UserInputRequest | null;
  finalResponse: string | null;
  spokenResponse?: string | null;
  streamingTokens?: string;   // Live LLM tokens arriving during planning
  performanceMetrics?: PerformanceMetrics | null;
  error: string | null;
}


