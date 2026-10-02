import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Cpu,
  Mic,
  Volume2,
  VolumeX,
  X,
  Key,
  Eye,
  EyeOff,
  Check,
  Activity,
  ExternalLink,
  ChevronDown,
  CalendarClock,
} from 'lucide-react';
import { NexusSettings, AvailableModel } from '../types/nexus';
import { MicDiagnosticTool } from './MicDiagnosticTool';
import { useVoiceOutput, DEFAULT_CURATED_VOICES } from '../hooks/useVoiceOutput';
import nexusLogo from '../assets/nexus-logo.png';

interface SettingsPanelProps {
  settings: NexusSettings;
  models: AvailableModel[];
  onSave: (settings: Partial<NexusSettings>) => Promise<boolean>;
  onClose: () => void;
  isSavedSuccess: boolean;
  onOpenSchedule?: () => void;
}

type TabType = 'intelligence' | 'voice' | 'diagnostics';

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  settings,
  models,
  onSave,
  onClose,
  isSavedSuccess,
  onOpenSchedule,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('intelligence');
  const [formData, setFormData] = useState<NexusSettings>(settings);
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [gemmaApiKeyInput, setGemmaApiKeyInput] = useState('');
  const [showGemmaKey, setShowGemmaKey] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const { speak: previewSpeak, stopSpeaking: stopPreviewSpeak, isSpeaking: isPreviewSpeaking } = useVoiceOutput();

  useEffect(() => {
    return () => {
      stopPreviewSpeak();
    };
  }, [stopPreviewSpeak]);

  useEffect(() => {
    setFormData(settings);
  }, [settings]);

  const handleChange = (key: keyof NexusSettings, value: any) => {
    setFormData(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = async (e?: React.FormEvent | React.MouseEvent) => {
    if (e && 'preventDefault' in e) e.preventDefault();
    setIsSaving(true);
    const payload: Partial<NexusSettings> = { ...formData };

    if (apiKeyInput.trim()) {
      payload.groq_api_key = apiKeyInput.trim();
    } else if (formData.groq_api_key && !formData.groq_api_key.includes('•') && !formData.groq_api_key.includes('\u2022')) {
      payload.groq_api_key = formData.groq_api_key.trim();
    } else {
      delete payload.groq_api_key;
    }

    if (gemmaApiKeyInput.trim()) {
      payload.gemma_api_key = gemmaApiKeyInput.trim();
    } else if (formData.gemma_api_key && !formData.gemma_api_key.includes('•') && !formData.gemma_api_key.includes('\u2022')) {
      payload.gemma_api_key = formData.gemma_api_key.trim();
    } else {
      delete payload.gemma_api_key;
    }

    const success = await onSave(payload);
    setIsSaving(false);
    if (success) {
      if (apiKeyInput.trim()) setApiKeyInput('');
      if (gemmaApiKeyInput.trim()) setGemmaApiKeyInput('');
    }
  };

  // Keyboard escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <form onSubmit={handleSave} className="flex flex-col bg-[#101116]/95 text-white/90 select-none animate-in fade-in duration-150">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-2.5">
          <div className="w-6 h-6 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center p-0.5 shadow-[0_0_8px_rgba(56,189,248,0.2)]">
            <img src={nexusLogo} alt="Nexus" className="w-4 h-4 object-contain drop-shadow-[0_0_4px_rgba(56,189,248,0.6)]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-white tracking-tight">Nexus Settings</span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/[0.05] text-white/45 border border-white/[0.07]">
                ~/.nexus
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onOpenSchedule && (
            <button
              onClick={onOpenSchedule}
              type="button"
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium text-sky-400 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-400/25 transition-colors"
              title="Open Scheduled Tasks"
            >
              <CalendarClock className="w-3.5 h-3.5" strokeWidth={1.8} />
              <span>Schedules</span>
            </button>
          )}

          <button
            onClick={onClose}
            type="button"
            title="Close (Esc)"
            className="w-6 h-6 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08] transition-colors"
          >
            <X className="w-3.5 h-3.5" strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {/* Modern Segmented Navigation Tabs */}
      <div className="px-5 pt-3 pb-2 border-b border-white/[0.05]">
        <div className="flex items-center p-0.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('intelligence')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium text-[11.5px] transition-all duration-150 ${
              activeTab === 'intelligence'
                ? 'bg-white/[0.12] text-white shadow-sm border border-white/[0.10]'
                : 'text-white/45 hover:text-white/80 hover:bg-white/[0.03]'
            }`}
          >
            <Cpu className={`w-3.5 h-3.5 ${activeTab === 'intelligence' ? 'text-sky-400' : 'text-white/40'}`} strokeWidth={1.8} />
            <span>AI & Models</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('voice')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium text-[11.5px] transition-all duration-150 ${
              activeTab === 'voice'
                ? 'bg-white/[0.12] text-white shadow-sm border border-white/[0.10]'
                : 'text-white/45 hover:text-white/80 hover:bg-white/[0.03]'
            }`}
          >
            <Mic className={`w-3.5 h-3.5 ${activeTab === 'voice' ? 'text-sky-400' : 'text-white/40'}`} strokeWidth={1.8} />
            <span>Voice & Audio</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('diagnostics')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium text-[11.5px] transition-all duration-150 ${
              activeTab === 'diagnostics'
                ? 'bg-white/[0.12] text-white shadow-sm border border-white/[0.10]'
                : 'text-white/45 hover:text-white/80 hover:bg-white/[0.03]'
            }`}
          >
            <Activity className={`w-3.5 h-3.5 ${activeTab === 'diagnostics' ? 'text-sky-400' : 'text-white/40'}`} strokeWidth={1.8} />
            <span>Diagnostics</span>
          </button>
        </div>
      </div>

      {/* Main Tab Panels Container */}
      <div className="overflow-y-auto px-5 py-4 space-y-4 text-xs max-h-[380px] custom-scrollbar">
        {/* ─── TAB 1: AI & MODELS ─── */}
        {activeTab === 'intelligence' && (
          <div className="space-y-4">
            {/* API Credentials Card */}
            <div className="space-y-3.5 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  API Credentials
                </span>
                <span className="text-[10px] text-white/30 font-mono">Encrypted locally</span>
              </div>

              {/* Groq API Key */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-[11.5px] font-medium text-white/80 flex items-center gap-1.5">
                    <Key className="w-3 h-3 text-sky-400" strokeWidth={1.8} />
                    <span>Groq API Key</span>
                  </label>
                  {settings.groq_api_key ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono text-emerald-300 bg-emerald-500/10 border border-emerald-500/20">
                      <span className="w-1 h-1 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
                      <span>Configured ({settings.groq_api_key.slice(-4)})</span>
                    </span>
                  ) : (
                    <span className="text-[10px] text-white/35">Required for reasoning & search</span>
                  )}
                </div>

                <div className="relative flex items-center">
                  <input
                    type={showKey ? 'text' : 'password'}
                    placeholder={settings.groq_api_key ? "Key is saved. Enter new key only to replace..." : "gsk_..."}
                    value={apiKeyInput}
                    onChange={e => setApiKeyInput(e.target.value)}
                    className="w-full bg-black/40 border border-white/[0.08] hover:border-white/[0.14] focus:border-sky-500/50 focus:ring-1 focus:ring-sky-500/25 rounded-lg px-3 py-2 pr-9 text-white placeholder-white/20 transition-all font-mono text-xs outline-none"
                    autoComplete="off"
                    spellCheck="false"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-2.5 text-white/40 hover:text-white transition-colors"
                    title={showKey ? "Hide key" : "Show key"}
                  >
                    {showKey ? <EyeOff className="w-3.5 h-3.5" strokeWidth={1.8} /> : <Eye className="w-3.5 h-3.5" strokeWidth={1.8} />}
                  </button>
                </div>
                <div className="flex items-center justify-between text-[10.5px] text-white/40">
                  <span>Fast inference on Groq LPUs for instant tool execution.</span>
                  <a
                    href="https://console.groq.com/keys"
                    target="_blank"
                    rel="noreferrer"
                    className="text-sky-400 hover:text-sky-300 flex items-center gap-1 transition-colors"
                  >
                    <span>Get Key</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                </div>
              </div>

              <div className="h-[1px] bg-white/[0.04]" />

              {/* Google AI Studio (Gemma) Key */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-[11.5px] font-medium text-white/80 flex items-center gap-1.5">
                    <Sparkles className="w-3 h-3 text-sky-400" strokeWidth={1.8} />
                    <span>Google AI Studio Key (Gemma)</span>
                  </label>
                  {settings.gemma_api_key ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono text-emerald-300 bg-emerald-500/10 border border-emerald-500/20">
                      <span className="w-1 h-1 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
                      <span>Configured ({settings.gemma_api_key.slice(-4)})</span>
                    </span>
                  ) : (
                    <span className="text-[10px] text-white/35">Optional secondary engine</span>
                  )}
                </div>

                <div className="relative flex items-center">
                  <input
                    type={showGemmaKey ? 'text' : 'password'}
                    placeholder={settings.gemma_api_key ? "Key is saved. Enter new key only to replace..." : "AIzaSy..."}
                    value={gemmaApiKeyInput}
                    onChange={e => setGemmaApiKeyInput(e.target.value)}
                    className="w-full bg-black/40 border border-white/[0.08] hover:border-white/[0.14] focus:border-sky-500/50 focus:ring-1 focus:ring-sky-500/25 rounded-lg px-3 py-2 pr-9 text-white placeholder-white/20 transition-all font-mono text-xs outline-none"
                    autoComplete="off"
                    spellCheck="false"
                  />
                  <button
                    type="button"
                    onClick={() => setShowGemmaKey(!showGemmaKey)}
                    className="absolute right-2.5 text-white/40 hover:text-white transition-colors"
                    title={showGemmaKey ? "Hide key" : "Show key"}
                  >
                    {showGemmaKey ? <EyeOff className="w-3.5 h-3.5" strokeWidth={1.8} /> : <Eye className="w-3.5 h-3.5" strokeWidth={1.8} />}
                  </button>
                </div>
                <div className="flex items-center justify-between text-[10.5px] text-white/40">
                  <span>Provides high-capacity reasoning fallback via Gemma models.</span>
                  <a
                    href="https://aistudio.google.com/app/apikey"
                    target="_blank"
                    rel="noreferrer"
                    className="text-sky-400 hover:text-sky-300 flex items-center gap-1 transition-colors"
                  >
                    <span>Get Key</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                </div>
              </div>
            </div>

            {/* Model Architecture & Routing */}
            <div className="space-y-3.5 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  Model Routing & Orchestration
                </span>
                <span className="text-[10px] text-white/30">Dynamic LPU Dispatch</span>
              </div>

              {/* Reasoning & Planning Model */}
              <div className="space-y-1">
                <label className="text-[11.5px] font-medium text-white/80 block">Reasoning & Autonomous Planning</label>
                <div className="relative">
                  <select
                    value={formData.groq_reasoning_model || 'qwen/qwen3.8-27b'}
                    onChange={e => handleChange('groq_reasoning_model', e.target.value)}
                    className="w-full appearance-none bg-black/40 border border-white/[0.08] hover:border-white/[0.14] focus:border-sky-500/50 rounded-lg px-3 py-2 pr-8 text-xs text-white/90 outline-none transition-colors"
                  >
                    {models.length > 0 ? (
                      models.filter(m => m.reasoning).map(m => (
                        <option key={m.model_id} value={m.model_id} className="bg-[#121319] text-white">
                          {m.name} ({m.model_id})
                        </option>
                      ))
                    ) : (
                      <>
                        <option value="qwen/qwen3.8-27b" className="bg-[#121319] text-white">Qwen 3.8 27B (Recommended)</option>
                        <option value="openai/gpt-oss-120b" className="bg-[#121319] text-white">OpenAI GPT OSS 120B</option>
                        <option value="allam-2-7b" className="bg-[#121319] text-white">Allam 2 7B</option>
                      </>
                    )}
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-white/40 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>

              {/* Fast Intent Routing */}
              <div className="space-y-1">
                <label className="text-[11.5px] font-medium text-white/80 block">Fast Intent & Command Classification</label>
                <div className="relative">
                  <select
                    value={formData.groq_fast_model || 'qwen/qwen3.8-27b'}
                    onChange={e => handleChange('groq_fast_model', e.target.value)}
                    className="w-full appearance-none bg-black/40 border border-white/[0.08] hover:border-white/[0.14] focus:border-sky-500/50 rounded-lg px-3 py-2 pr-8 text-xs text-white/90 outline-none transition-colors"
                  >
                    {models.length > 0 ? (
                      models.filter(m => m.speed === 'fast' || m.speed === 'instant').map(m => (
                        <option key={m.model_id} value={m.model_id} className="bg-[#121319] text-white">
                          {m.name} ({m.model_id})
                        </option>
                      ))
                    ) : (
                      <>
                        <option value="qwen/qwen3.8-27b" className="bg-[#121319] text-white">Qwen 3.8 27B (Sub-100ms)</option>
                        <option value="openai/gpt-oss-20b" className="bg-[#121319] text-white">OpenAI GPT OSS 20B</option>
                        <option value="allam-2-7b" className="bg-[#121319] text-white">Allam 2 7B</option>
                      </>
                    )}
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-white/40 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>

              {/* Vision & Multimodal Model */}
              <div className="space-y-1">
                <label className="text-[11.5px] font-medium text-white/80 block">Vision & Screen Analysis</label>
                <div className="relative">
                  <select
                    value={formData.groq_vision_model || 'qwen/qwen3.8-27b'}
                    onChange={e => handleChange('groq_vision_model', e.target.value)}
                    className="w-full appearance-none bg-black/40 border border-white/[0.08] hover:border-white/[0.14] focus:border-sky-500/50 rounded-lg px-3 py-2 pr-8 text-xs text-white/90 outline-none transition-colors"
                  >
                    <option value="qwen/qwen3.8-27b" className="bg-[#121319] text-white">Qwen 3.8 27B (Multimodal VLM)</option>
                    <option value="openai/gpt-oss-120b" className="bg-[#121319] text-white">OpenAI GPT OSS 120B</option>
                    <option value="allam-2-7b" className="bg-[#121319] text-white">Allam 2 7B</option>
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-white/40 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 2: VOICE & AUDIO ─── */}
        {activeTab === 'voice' && (
          <div className="space-y-4">
            {/* Voice Input Section */}
            <div className="space-y-3.5 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40 block">
                Speech Input & Dictation
              </span>

              {/* Spotlight Voice Input Switch */}
              <div className="flex items-center justify-between py-1">
                <div className="space-y-0.5 pr-4">
                  <div className="text-[12px] font-medium text-white">Spotlight Voice Input</div>
                  <div className="text-[11px] text-white/40 leading-snug">
                    Enables microphone button in Spotlight bar with real-time waveform visualization.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleChange('voice_input_enabled', !(formData.voice_input_enabled ?? true))}
                  className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out ${
                    (formData.voice_input_enabled ?? true) ? 'bg-sky-500' : 'bg-white/10'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition duration-200 ease-in-out mt-[3px] ${
                      (formData.voice_input_enabled ?? true) ? 'translate-x-[18px]' : 'translate-x-[3px]'
                    }`}
                  />
                </button>
              </div>

              <div className="h-[1px] bg-white/[0.04]" />

              {/* Wake Word Switch */}
              <div className="flex items-center justify-between py-1">
                <div className="space-y-0.5 pr-4">
                  <div className="text-[12px] font-medium text-white flex items-center gap-1.5">
                    <span>Wake Word ("Hey Nexus")</span>
                    <span className="text-[9.5px] px-1 py-0.2 rounded bg-sky-500/10 text-sky-400 font-mono border border-sky-500/20">
                      Passive
                    </span>
                  </div>
                  <div className="text-[11px] text-white/40 leading-snug">
                    Listens for "Hey Nexus" while Spotlight is visible to automatically transcribe and execute.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleChange('voice_wake_word_enabled', !(formData.voice_wake_word_enabled ?? true))}
                  className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out ${
                    (formData.voice_wake_word_enabled ?? true) ? 'bg-sky-500' : 'bg-white/10'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition duration-200 ease-in-out mt-[3px] ${
                      (formData.voice_wake_word_enabled ?? true) ? 'translate-x-[18px]' : 'translate-x-[3px]'
                    }`}
                  />
                </button>
              </div>

              <div className="h-[1px] bg-white/[0.04]" />

              {/* Auto-Submit Switch */}
              <div className="flex items-center justify-between py-1">
                <div className="space-y-0.5 pr-4">
                  <div className="text-[12px] font-medium text-white">Auto-Submit on Pause</div>
                  <div className="text-[11px] text-white/40 leading-snug">
                    Automatically executes transcribed speech after a natural 1.5-second pause.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleChange('voice_auto_submit', !(formData.voice_auto_submit ?? true))}
                  className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out ${
                    (formData.voice_auto_submit ?? true) ? 'bg-sky-500' : 'bg-white/10'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition duration-200 ease-in-out mt-[3px] ${
                      (formData.voice_auto_submit ?? true) ? 'translate-x-[18px]' : 'translate-x-[3px]'
                    }`}
                  />
                </button>
              </div>
            </div>

            {/* Neural Speech Output (TTS) */}
            <div className="space-y-3.5 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5 pr-4">
                  <div className="text-[12px] font-medium text-white">Spoken Audio Briefs</div>
                  <div className="text-[11px] text-white/40 leading-snug">
                    Naturally reads concise spoken summaries aloud when completing voice interactions.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleChange('voice_output_enabled', !(formData.voice_output_enabled ?? true))}
                  className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out ${
                    (formData.voice_output_enabled ?? true) ? 'bg-sky-500' : 'bg-white/10'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition duration-200 ease-in-out mt-[3px] ${
                      (formData.voice_output_enabled ?? true) ? 'translate-x-[18px]' : 'translate-x-[3px]'
                    }`}
                  />
                </button>
              </div>

              {(formData.voice_output_enabled ?? true) && (
                <div className="space-y-3 pt-2 border-t border-white/[0.05]">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {/* Voice Model */}
                    <div className="space-y-1">
                      <label className="text-[11px] font-medium text-white/70 block">Voice Persona</label>
                      <div className="relative">
                        <select
                          value={formData.voice_output_voice || 'en-US-AriaNeural'}
                          onChange={e => handleChange('voice_output_voice', e.target.value)}
                          className="w-full appearance-none bg-black/40 border border-white/[0.08] hover:border-white/[0.14] focus:border-sky-500/50 rounded-lg px-2.5 py-1.5 pr-7 text-xs text-white outline-none"
                        >
                          {DEFAULT_CURATED_VOICES.map(v => (
                            <option key={v.id} value={v.id} className="bg-[#121319] text-white">
                              {v.name} ({v.gender})
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="w-3.5 h-3.5 text-white/40 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
                      </div>
                    </div>

                    {/* Speed Selector */}
                    <div className="space-y-1">
                      <label className="text-[11px] font-medium text-white/70 block">Speaking Rate</label>
                      <div className="grid grid-cols-4 gap-1">
                        {['0.9x', '1.0x', '1.1x', '1.2x'].map(spd => {
                          const isSelected = (formData.voice_output_speed || '1.0x') === spd;
                          return (
                            <button
                              key={spd}
                              type="button"
                              onClick={() => handleChange('voice_output_speed', spd)}
                              className={`py-1 rounded text-[11px] font-mono transition-all ${
                                isSelected
                                  ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40 font-medium'
                                  : 'bg-white/[0.03] text-white/45 hover:text-white/80 border border-white/[0.05]'
                              }`}
                            >
                              {spd}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>

                  {/* Preview Button */}
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-[10.5px] text-white/35 font-mono">
                      Cloud Neural Audio Engine
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        if (isPreviewSpeaking) {
                          stopPreviewSpeak();
                        } else {
                          previewSpeak(
                            "Hello. NEXUS is ready to assist you.",
                            formData.voice_output_voice || 'en-US-AriaNeural',
                            formData.voice_output_speed || '1.0x'
                          );
                        }
                      }}
                      className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all ${
                        isPreviewSpeaking
                          ? 'bg-sky-500/20 text-sky-300 border border-sky-400/30 animate-pulse'
                          : 'bg-white/[0.06] hover:bg-white/[0.10] text-white/80 border border-white/[0.08]'
                      }`}
                    >
                      {isPreviewSpeaking ? (
                        <>
                          <VolumeX className="w-3.5 h-3.5 text-sky-400" />
                          <span>Stop Preview</span>
                        </>
                      ) : (
                        <>
                          <Volume2 className="w-3.5 h-3.5 text-white/60" />
                          <span>Preview Voice</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─── TAB 3: SYSTEM DIAGNOSTICS ─── */}
        {activeTab === 'diagnostics' && (
          <div className="space-y-4">
            <MicDiagnosticTool />
          </div>
        )}
      </div>

      {/* Action Footer */}
      <div className="flex items-center justify-between px-5 py-3 border-t border-white/[0.07] bg-black/30">
        <div className="text-[11px] min-h-[20px] flex items-center">
          {isSavedSuccess && (
            <span className="text-emerald-400 font-medium flex items-center gap-1.5 animate-in fade-in slide-in-from-left-2 duration-150">
              <Check className="w-3.5 h-3.5" strokeWidth={2} />
              <span>Configuration saved successfully</span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-lg text-white/60 hover:text-white hover:bg-white/[0.06] border border-white/[0.06] text-xs font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            onClick={handleSave}
            disabled={isSaving}
            className="px-4 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-xs font-medium shadow-sm shadow-sky-500/25 transition-all flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
          >
            {isSaving ? (
              <>
                <div className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                <span>Saving...</span>
              </>
            ) : (
              <span>Save Changes</span>
            )}
          </button>
        </div>
      </div>
    </form>
  );
};
