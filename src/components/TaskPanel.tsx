import React, { useState, useEffect, useRef } from 'react';
import { Check, AlertCircle, Bot, ChevronDown, ChevronRight, Minimize2, HelpCircle, Volume2, VolumeX, Pause, Play, Square, RotateCcw, Mic, MicOff, Copy, FolderOpen, Presentation, Zap, ShieldCheck } from 'lucide-react';


import { TaskState, PlanStep } from '../types/nexus';
import { PermissionCard } from './PermissionCard';
import { MarkdownRenderer } from './MarkdownRenderer';
import { renderChoiceChip } from './AutomationPill';
import { DateTimeCard } from './DateTimeCard';
import { formatSpokenResponse } from '../utils/speechUtils';
import { NexusLogoMedia } from './NexusLogoMedia';

interface TaskPanelProps {
  taskState: TaskState;
  onApprovePermission: () => void;
  onRejectPermission: () => void;
  onSubmitUserInput?: (value: string) => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onReset: () => void;
  onSwitchToPillMode?: () => void;
  isSpeaking?: boolean;
  onSpeak?: (text: string) => void;
  onStopSpeaking?: () => void;
}

export const TaskPanel: React.FC<TaskPanelProps> = ({
  taskState,
  onApprovePermission,
  onRejectPermission,
  onSubmitUserInput,
  onPause,
  onResume,
  onCancel,
  onReset,
  onSwitchToPillMode,
  isSpeaking = false,
  onSpeak,
  onStopSpeaking,
}) => {
  const [showObservations, setShowObservations] = useState(false);
  const [showRationale, setShowRationale] = useState(false);
  const [isThinkingOpen, setIsThinkingOpen] = useState(true);
  const [panelInputText, setPanelInputText] = useState('');
  const [isInputVoiceActive, setIsInputVoiceActive] = useState(false);
  const [copied, setCopied] = useState(false);
  const inputRecognitionRef = useRef<any>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const handleCopy = () => {
    if (taskState.finalResponse) {
      navigator.clipboard?.writeText(taskState.finalResponse);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const toggleInputVoice = () => {
    if (isInputVoiceActive) {
      if (inputRecognitionRef.current) {
        try { inputRecognitionRef.current.stop(); } catch (_) {}
      }
      setIsInputVoiceActive(false);
      return;
    }

    const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRec) {
      alert("Speech recognition is not supported in this browser. Please use Chrome or Edge.");
      return;
    }

    try {
      const recognition = new SpeechRec();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onstart = () => {
        setIsInputVoiceActive(true);
      };

      recognition.onresult = (event: any) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        if (transcript) {
          setPanelInputText(transcript);
        }
      };

      recognition.onerror = () => {
        setIsInputVoiceActive(false);
      };

      recognition.onend = () => {
        setIsInputVoiceActive(false);
      };

      inputRecognitionRef.current = recognition;
      recognition.start();
    } catch (err) {
      console.warn('Voice input error:', err);
      setIsInputVoiceActive(false);
    }
  };

  const hasPlan = taskState.plan && taskState.plan.length > 0;
  const isTaskDone = !taskState.isRunning && (Boolean(taskState.finalResponse) || (hasPlan && taskState.plan.every(s => s.status === 'completed')));
  const [isPlanExpanded, setIsPlanExpanded] = useState(!isTaskDone);

  // Automatically collapse steps when task completes, expand while actively running
  useEffect(() => {
    if (isTaskDone) {
      setIsPlanExpanded(false);
    } else if (taskState.isRunning && hasPlan) {
      setIsPlanExpanded(true);
    }
  }, [isTaskDone, taskState.isRunning, hasPlan]);

  const thoughtsContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll thoughts container as new reasoning chunks stream in
  useEffect(() => {
    if (thoughtsContainerRef.current) {
      thoughtsContainerRef.current.scrollTop = thoughtsContainerRef.current.scrollHeight;
    }
  }, [taskState.reasoning, taskState.streamingTokens]);

  // Auto-collapse thinking box once plan arrives, but re-open during reframing
  useEffect(() => {
    if (taskState.statusText?.includes('Reframing')) {
      setIsThinkingOpen(true);
    } else if (hasPlan) {
      setIsThinkingOpen(false);
    } else {
      setIsThinkingOpen(true);
    }
  }, [hasPlan, taskState.statusText]);

  // Auto-scroll to ensure response is visible when it arrives
  useEffect(() => {
    if (taskState.finalResponse && scrollRef.current) {
      scrollRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [taskState.finalResponse]);

  // Auto-scroll down as plan updates, steps advance, or observations arrive
  useEffect(() => {
    if (scrollRef.current && (hasPlan || taskState.observations?.length)) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [hasPlan, taskState.plan?.length, taskState.plan?.map(s => s.status).join(','), taskState.observations?.length]);

  const cleanThought = (text?: string) => {
    if (!text) return '';
    return text.replace(/^Rationale:\s*/i, '').replace(/^[^\w\s]+\s*/, '');
  };

  const getStepIcon = (step: PlanStep) => {
    switch (step.status) {
      case 'running':
        return <NexusLogoMedia type="video" className="w-5 h-5 shrink-0" />;
      case 'completed':
        return <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
      case 'failed':
        return <span className="text-red-400 text-[10px] font-mono shrink-0">[x]</span>;
      default:
        return <span className="w-3 h-3 rounded-full border border-neutral-600 shrink-0" />;
    }
  };

  const isSingleStepAiResponse =
    taskState.plan.length === 1 &&
    taskState.plan[0]?.tool === 'ai_response' &&
    Boolean(taskState.finalResponse);

  const isDateTimeQuery =
    (taskState.plan.length > 0 && taskState.plan.some(s => s.tool === 'get_current_time' || s.tool?.startsWith('calendar_'))) ||
    (Boolean(taskState.goal) && /\b(time|clock|date|today|calendar|weekday|day of the week|month|year|meeting|schedule|appointment)\b/i.test(taskState.goal || ''));

  return (
    <div className="flex flex-col bg-transparent text-neutral-200">
      {/* Top Status Bar */}
      <div className="flex items-center justify-between px-5 py-2.5 border-b border-white/[0.06] shrink-0 gap-3">
        <div className="flex items-center space-x-2 min-w-0 flex-1 overflow-hidden">
          {taskState.isRunning ? (
            <div className="flex items-center space-x-2 min-w-0 shrink">
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400"></span>
              </span>
              <span className="text-xs font-medium text-cyan-200/90 truncate" title={taskState.statusText}>
                {taskState.statusText || 'Working...'}
              </span>
            </div>
          ) : taskState.isPaused ? (
            <div className="flex items-center space-x-2 min-w-0 shrink">
              <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
              <span className="text-xs font-medium text-amber-300 truncate" title={taskState.statusText}>
                {taskState.statusText || 'Paused'}
              </span>
            </div>
          ) : (
            <div className="flex items-center space-x-2 min-w-0 shrink">
              <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
              <span className="text-xs font-medium text-neutral-300 truncate" title={taskState.statusText}>
                {taskState.statusText || 'Ready'}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center space-x-1.5 shrink-0">
          {onSwitchToPillMode && (
            <button
              onClick={onSwitchToPillMode}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-cyan-300 hover:bg-cyan-500/10 border border-transparent hover:border-cyan-500/20 transition-all"
              title="Switch to compact bottom pill"
            >
              <Minimize2 className="w-3.5 h-3.5" />
            </button>
          )}
          {taskState.isRunning && (
            <button
              onClick={onPause}
              className="p-1.5 rounded-lg text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 border border-amber-500/20 transition-all"
              title="Pause task"
            >
              <Pause className="w-3.5 h-3.5" />
            </button>
          )}
          {taskState.isPaused && (
            <button
              onClick={onResume}
              className="p-1.5 rounded-lg text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 border border-emerald-500/20 transition-all"
              title="Resume task"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
            </button>
          )}
          {(taskState.isRunning || taskState.isPaused) && (
            <button
              onClick={onCancel}
              className="p-1.5 rounded-lg text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 border border-rose-500/20 transition-all"
              title="Cancel task"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
            </button>
          )}
          {taskState.finalResponse && !taskState.isRunning && !taskState.isPaused && (
            <button
              onClick={onReset}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium text-neutral-300 hover:text-white bg-white/[0.06] hover:bg-white/[0.10] border border-white/[0.08] transition-all"
              title="New Prompt (Esc)"
            >
              <RotateCcw className="w-3 h-3" />
              <span>New</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Body with natural expansion and smooth scroll if exceeding max height */}
      <div ref={scrollRef} className="overflow-y-auto px-5 py-4 pb-6 space-y-3.5 text-xs max-h-[580px]">
        {/* Permission Request Card */}
        {taskState.pendingPermission && (
          <PermissionCard
            request={taskState.pendingPermission}
            onApprove={onApprovePermission}
            onReject={onRejectPermission}
          />
        )}

        {/* User Input / Choice Request Card */}
        {taskState.userInputRequest && (
          <div className="p-4 rounded-xl bg-sky-950/30 border border-sky-500/35 text-neutral-200 space-y-3 shadow-lg animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-sky-400 font-semibold text-xs">
                <HelpCircle className="w-4 h-4 text-sky-400" />
                <span>User Input & Choice Required</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  const prompt = taskState.userInputRequest?.prompt;
                  if (prompt) {
                    if (isSpeaking) {
                      onStopSpeaking?.();
                    } else if (onSpeak) {
                      onSpeak(prompt);
                    } else if (typeof window !== 'undefined' && window.speechSynthesis) {
                      const u = new SpeechSynthesisUtterance(prompt);
                      window.speechSynthesis.speak(u);
                    }
                  }
                }}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 transition-colors"
                title="Read question aloud"
              >
                <Volume2 className="w-3 h-3" />
                <span>Listen</span>
              </button>
            </div>
            <p className="text-xs text-neutral-200 font-medium leading-relaxed">
              {taskState.userInputRequest.prompt}
            </p>

            {taskState.userInputRequest.options && taskState.userInputRequest.options.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {taskState.userInputRequest.options.map((opt, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={async () => {
                      if (opt.toLowerCase().includes('file explorer') || opt.toLowerCase().includes('browse')) {
                        if (window.electronAPI?.selectSavePath) {
                          try {
                            const filenameMatch = taskState.userInputRequest?.prompt?.match(/\(([^)]+\.pptx|[^)]+\.xlsx|[^)]+\.docx)\)/i);
                            const defaultFilename = filenameMatch ? filenameMatch[1] : 'presentation.pptx';
                            const selected = await window.electronAPI.selectSavePath(defaultFilename);
                            if (selected) {
                              onSubmitUserInput?.(selected);
                              return;
                            }
                          } catch (err) {
                            console.warn('Native save dialog error:', err);
                          }
                        } else {
                          try {
                            const filenameMatch = taskState.userInputRequest?.prompt?.match(/\(([^)]+\.pptx|[^)]+\.xlsx|[^)]+\.docx)\)/i);
                            const defaultFilename = filenameMatch ? filenameMatch[1] : 'presentation.pptx';
                            const res = await fetch('http://127.0.0.1:8000/api/nexus/pick-save-path?default_filename=' + encodeURIComponent(defaultFilename), { method: 'POST' });
                            if (res.ok) {
                              const d = await res.json();
                              if (d.selected_path) {
                                onSubmitUserInput?.(d.selected_path);
                                return;
                              }
                            }
                          } catch (_) {}
                        }
                      }
                      onSubmitUserInput?.(opt);
                    }}
                    className="px-3 py-1.5 rounded-full text-xs font-medium bg-white/10 hover:bg-sky-500/25 text-neutral-200 hover:text-white border border-white/15 hover:border-sky-500/50 transition-all shadow-sm"
                  >
                    {renderChoiceChip(opt)}
                  </button>
                ))}
              </div>
            )}


            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (panelInputText.trim()) {
                  if (isInputVoiceActive && inputRecognitionRef.current) {
                    try { inputRecognitionRef.current.stop(); } catch (_) {}
                    setIsInputVoiceActive(false);
                  }
                  onSubmitUserInput?.(panelInputText.trim());
                  setPanelInputText('');
                }
              }}
              className="flex items-center gap-2 pt-1"
            >
              <input
                type="text"
                value={panelInputText}
                onChange={(e) => setPanelInputText(e.target.value)}
                placeholder={taskState.userInputRequest.placeholder || "Type or speak your answer..."}
                autoFocus
                className={`flex-1 px-3 py-1.5 text-xs rounded-lg bg-black/40 border ${
                  isInputVoiceActive ? 'border-red-500/60 ring-2 ring-red-500/20' : 'border-white/15 focus:border-sky-400'
                } text-white placeholder-neutral-500 focus:outline-none transition-all`}
              />
              <button
                type="button"
                onClick={toggleInputVoice}
                className={`p-1.5 rounded-lg border transition-all flex items-center justify-center ${
                  isInputVoiceActive
                    ? 'bg-red-500/20 border-red-500/50 text-red-400 animate-pulse ring-2 ring-red-500/20'
                    : 'bg-white/5 hover:bg-white/10 border-white/15 text-neutral-300 hover:text-white'
                }`}
                title={isInputVoiceActive ? "Listening... click to stop" : "Speak response (Microphone)"}
              >
                {isInputVoiceActive ? <MicOff className="w-4 h-4 text-red-400" /> : <Mic className="w-4 h-4" />}
              </button>
              <button
                type="submit"
                className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-colors flex items-center gap-1 shadow-sm"
              >
                <span>Submit</span>
                <span className="text-[10px] opacity-70">↵</span>
              </button>
            </form>

            {isInputVoiceActive && (
              <div className="flex items-center gap-2 text-[11px] text-red-400 animate-pulse pt-0.5">
                <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                <span>Listening to your voice... say your answer</span>
              </div>
            )}
          </div>
        )}


        {/* MINIMAL & HUMAN THINKING STATE */}
        {taskState.isRunning && (
          <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.07] text-neutral-200 space-y-2.5 transition-all">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2.5 min-w-0 flex-1">
                {/* Authentic Nexus 3D Animated Ribbon Loader with Skeleton */}
                <NexusLogoMedia type="video" className="w-7 h-7 shrink-0" />
                <div className="min-w-0 flex-1 flex items-center gap-2">
                  <span className="text-xs font-normal text-white/85">
                    {taskState.statusText && taskState.statusText !== 'Local System' ? taskState.statusText : 'Thinking...'}
                  </span>
                </div>
              </div>

              {/* Minimal Thought Disclosure */}
              {(hasPlan || taskState.reasoning || taskState.streamingTokens) && (
                <button
                  type="button"
                  onClick={() => setIsThinkingOpen(!isThinkingOpen)}
                  className="flex items-center gap-1 text-[11px] text-white/40 hover:text-white/80 transition-colors ml-2 shrink-0 py-0.5 px-2 rounded-md hover:bg-white/[0.05]"
                  title={isThinkingOpen ? "Hide thought process" : "View thought process"}
                >
                  <span>{isThinkingOpen ? "Hide thoughts" : "Thought process"}</span>
                  {isThinkingOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                </button>
              )}
            </div>

            {/* Expanded minimal thoughts */}
            {isThinkingOpen && (
              <div className="pt-2 border-t border-white/[0.05] space-y-2">
                {taskState.streamingTokens ? (
                  <div
                    ref={thoughtsContainerRef}
                    className="pl-2.5 border-l border-cyan-400/40 text-xs text-white/80 font-mono leading-relaxed whitespace-pre-wrap break-words max-h-48 overflow-y-auto"
                  >
                    {taskState.streamingTokens}
                    <span className="inline-block w-1.5 h-3 bg-cyan-400 ml-1 animate-pulse align-middle" />
                  </div>
                ) : taskState.reasoning ? (
                  <div
                    ref={thoughtsContainerRef}
                    className="pl-2.5 border-l border-cyan-400/30 text-xs text-white/70 font-mono leading-relaxed max-h-48 overflow-y-auto space-y-1"
                  >
                    <MarkdownRenderer content={cleanThought(taskState.reasoning)} />
                    {!isTaskDone && (
                      <span className="inline-block w-1.5 h-3 bg-cyan-400/80 ml-1 animate-pulse align-middle" />
                    )}
                  </div>
                ) : (
                  <div className="pl-2.5 border-l border-white/10 text-[11px] text-white/40">
                    Formulating response...
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Execution Plan Checklist (multi-step operations & tool execution) */}
        {taskState.plan && taskState.plan.length > 0 && !isSingleStepAiResponse && (
          <div className="space-y-1.5">
            <button
              onClick={() => setIsPlanExpanded(!isPlanExpanded)}
              className="w-full flex items-center justify-between text-[11px] font-medium text-neutral-400 hover:text-neutral-200 transition-colors uppercase tracking-wider py-1 px-1 rounded hover:bg-white/[0.04]"
              title={isPlanExpanded ? "Collapse steps" : "Expand steps"}
            >
              <div className="flex items-center space-x-1.5">
                {isPlanExpanded ? <ChevronDown className="w-3.5 h-3.5 text-neutral-400" /> : <ChevronRight className="w-3.5 h-3.5 text-neutral-400" />}
                <span>
                  Execution Plan ({taskState.plan.filter(s => s.status === 'completed').length}/{taskState.plan.length})
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <span className="text-[10px] text-neutral-500 lowercase font-normal">
                  {isPlanExpanded ? 'hide' : 'show'}
                </span>
              </div>
            </button>

            {isPlanExpanded && (
              <div className="space-y-1.5 bg-black/20 p-2.5 rounded-lg border border-white/[0.06] transition-all">
                {taskState.plan.map((step, idx) => (
                  <div
                    key={step.id || idx}
                    className={`p-2.5 rounded-lg transition-all flex items-start space-x-2.5 ${
                      step.status === 'running'
                        ? 'bg-blue-500/[0.12] border border-blue-500/30'
                        : step.status === 'completed'
                        ? 'bg-white/[0.02]'
                        : 'opacity-70'
                    }`}
                  >
                    <div className="mt-0.5">{getStepIcon(step)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-white text-xs">{step.title}</span>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/10 text-neutral-400">
                          {step.tool}
                        </span>
                      </div>
                      {step.description && (
                        <p className="text-[11px] text-neutral-400 mt-0.5 line-clamp-2">{step.description}</p>
                      )}
                      {step.result && (
                        <div className="mt-2 p-2 rounded-lg bg-black/40 text-[11px] text-neutral-300 max-h-36 overflow-y-auto border border-white/5">
                          <MarkdownRenderer content={step.result} />
                        </div>
                      )}
                      {step.error && (
                        <div className="mt-2 p-2 rounded-lg bg-red-950/40 text-[11px] font-mono text-red-300 break-all border border-red-900/30">
                          {step.error}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Interactive Live Clock & Calendar Widget (or Final Response) */}
        {isDateTimeQuery ? (
          <DateTimeCard userQuery={taskState.goal || ''} />
        ) : (
          taskState.finalResponse && (
            <div className="relative p-4 rounded-xl bg-white/[0.02] border border-white/[0.07] text-neutral-200 space-y-3 transition-all">
              {/* Top actions toolbar (minimal speak & copy) */}
              <div className="flex items-center justify-between pb-2 border-b border-white/[0.05]">
                <div className="flex items-center space-x-1.5 text-xs font-medium">
                  {!isSingleStepAiResponse ? (
                    <div className="flex items-center space-x-1.5 text-emerald-400/90 text-xs">
                      <Check className="w-3.5 h-3.5" />
                      <span>Completed</span>
                    </div>
                  ) : (
                    <span className="text-white/40 text-xs font-normal">Response</span>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  {onSpeak && (
                    <button
                      type="button"
                      onClick={() => {
                        if (isSpeaking) {
                          onStopSpeaking?.();
                        } else {
                          const spokenText = formatSpokenResponse({
                            spokenResponse: taskState.spokenResponse,
                            finalResponse: taskState.finalResponse,
                            error: taskState.error,
                            goal: taskState.goal,
                            plan: taskState.plan,
                          });
                          onSpeak(spokenText);
                        }
                      }}
                      className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] transition-all ${
                        isSpeaking
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/40 animate-pulse'
                          : 'text-white/40 hover:text-white/80 hover:bg-white/[0.06]'
                      }`}
                      title={isSpeaking ? "Stop voice" : "Read spoken summary aloud"}
                    >
                      {isSpeaking ? (
                        <>
                          <VolumeX className="w-3.5 h-3.5 text-cyan-400" />
                          <span className="text-cyan-300">Stop</span>
                        </>
                      ) : (
                        <>
                          <Volume2 className="w-3.5 h-3.5" />
                          <span>Listen</span>
                        </>
                      )}
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleCopy}
                    className="p-1 rounded-md text-white/40 hover:text-white/80 hover:bg-white/[0.06] transition-colors"
                    title={copied ? "Copied to clipboard!" : "Copy response"}
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* Performance Telemetry & Ground-Truth Verification Badge */}
              {taskState.performanceMetrics && (
                <div className="flex flex-wrap items-center gap-1.5 py-1 px-2 rounded-lg bg-white/[0.02] border border-white/[0.05] text-[11px]">
                  <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border ${
                    (taskState.performanceMetrics.fast_path || taskState.performanceMetrics.cache_hit) && taskState.performanceMetrics.llm_calls === 0
                      ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                      : 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300'
                  }`}>
                    <Zap className="w-3 h-3 text-amber-400" />
                    <span>
                      {(taskState.performanceMetrics.fast_path || taskState.performanceMetrics.cache_hit) && taskState.performanceMetrics.llm_calls === 0
                        ? '0 LLM Calls • 100% Deterministic'
                        : `${taskState.performanceMetrics.llm_calls || 1} LLM Call${(taskState.performanceMetrics.llm_calls || 1) > 1 ? 's' : ''}`}
                    </span>
                  </div>

                  {taskState.performanceMetrics.latency_ms !== undefined && taskState.performanceMetrics.latency_ms > 0 && (
                    <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium bg-neutral-800/80 border border-neutral-700/60 text-neutral-300">
                      <span>{taskState.performanceMetrics.latency_ms}ms</span>
                    </div>
                  )}

                  {taskState.performanceMetrics.tokens_saved > 0 && (
                    <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium bg-emerald-500/10 border border-emerald-500/30 text-emerald-300">
                      <span>~{taskState.performanceMetrics.tokens_saved.toLocaleString()} tokens saved</span>
                    </div>
                  )}

                  {taskState.performanceMetrics.validation_passed && (
                    <div
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium bg-cyan-500/10 border border-cyan-500/30 text-cyan-300"
                      title={taskState.performanceMetrics.validation_reason || 'Outcome verified'}
                    >
                      <ShieldCheck className="w-3 h-3 text-cyan-400" />
                      <span>Verified Ground-Truth</span>
                    </div>
                  )}
                </div>
              )}

              {/* Render Rich Markdown with Code Block Copy Button */}
              <div className="text-slate-100 text-[13px] leading-relaxed overflow-x-auto select-text font-normal">
                <MarkdownRenderer content={taskState.finalResponse} />
              </div>

              {/* Action shortcuts for saved files (e.g. PowerPoint presentations) */}
              {(() => {
                const fullText = (taskState.finalResponse || '') + ' ' + (taskState.plan?.map(s => s.result || '').join(' '));
                const match = fullText.match(/([a-zA-Z]:[\\/][^\s\n"']+\.(?:pptx|xlsx|docx))/i) ||
                              fullText.match(/(?:saved.*?to:\s*|path:\s*)([^\s\n"']+\.(?:pptx|xlsx|docx))/i);
                const filePath = match ? match[1] : null;

                if (!filePath) return null;
                const isPptx = filePath.toLowerCase().endsWith('.pptx');

                return (
                  <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-white/[0.06]">
                    <button
                      type="button"
                      onClick={() => {
                        if (window.electronAPI?.showInFolder) {
                          window.electronAPI.showInFolder(filePath);
                        } else {
                          fetch('http://127.0.0.1:8000/api/nexus/reveal-in-explorer', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ path: filePath }),
                          }).catch(() => {});
                        }
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 border border-sky-500/30 text-sky-300 text-xs font-medium transition-all shadow-sm"
                      title="Show file in Windows File Explorer"
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      <span>Show in File Explorer</span>
                    </button>

                    {isPptx && (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.electronAPI?.openPath) {
                            window.electronAPI.openPath(filePath);
                          }
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/25 border border-orange-500/30 text-orange-300 text-xs font-medium transition-all shadow-sm"
                        title="Open PowerPoint presentation"
                      >
                        <Presentation className="w-3.5 h-3.5" />
                        <span>Open Presentation</span>
                      </button>
                    )}
                  </div>
                );
              })()}
            </div>
          )
        )}


        {/* Collapsed Thought Process (when completed) */}
        {taskState.reasoning && !taskState.isRunning && (
          <div className="pt-0.5">
            <button
              onClick={() => setShowRationale(!showRationale)}
              className="text-[11px] text-neutral-400 hover:text-neutral-200 flex items-center space-x-1.5 transition-colors"
            >
              {showRationale ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <Bot className="w-3 h-3 text-neutral-400" />
              <span>Thought process</span>
            </button>
            {showRationale && (
              <div className="mt-2 p-3 rounded-lg bg-white/[0.03] border border-white/[0.06] text-neutral-300 text-xs leading-relaxed font-sans max-h-60 overflow-y-auto">
                <MarkdownRenderer content={cleanThought(taskState.reasoning)} />
              </div>
            )}
          </div>
        )}

        {/* Error Notice */}
        {taskState.error && (
          <div className="p-3 rounded-lg bg-red-950/30 border border-red-500/30 text-red-200 space-y-1">
            <div className="flex items-center space-x-1.5 text-red-400 font-semibold text-xs">
              <AlertCircle className="w-3.5 h-3.5" />
              <span>Execution Issue</span>
            </div>
            <div className="text-xs text-red-300 font-mono break-all">{taskState.error}</div>
          </div>
        )}

        {/* Observations toggle */}
        {taskState.observations && taskState.observations.length > 0 && (
          <div className="pt-0.5">
            <button
              onClick={() => setShowObservations(!showObservations)}
              className="text-[11px] text-neutral-400 hover:text-neutral-200 flex items-center space-x-1.5 transition-colors"
            >
              {showObservations ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
              <span>Observation Log ({taskState.observations.length})</span>
            </button>
            {showObservations && (
              <div className="mt-2 space-y-1 p-2 rounded bg-black/30 border border-white/5 font-mono text-[11px] text-neutral-400 max-h-32 overflow-y-auto">
                {taskState.observations.map((obs, i) => (
                  <div key={i} className="leading-tight">{obs}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
