import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  AppWindow,
  Terminal,
  Globe,
  FileCode,
  Folder,
  FolderOpen,
  Music,
  History,
  Calculator,
  Activity,
  CheckCircle2,
  CornerDownLeft,
  Bot,
  FileText,
  SlidersHorizontal,
  ArrowUpRight,
  RotateCw,
  Cpu,
  Calendar,
  Clock,
  Mail,
  Sparkles,
} from 'lucide-react';
import { SpotlightMode } from './ModePills';
import { HistoryItem } from '../types/nexus';
import { useAuth } from '../context/AuthContext';
import { PredictionItem } from '../services/recommendationEngine';

export interface SuggestionItem {
  id: string;
  title: string;
  subtitle?: string;
  category: 'history' | 'ai' | 'apps' | 'files' | 'calc' | 'action' | 'all';
  icon: React.ElementType;
  iconColor?: string;
  iconBg?: string;
  badge?: string;
  badgeColor?: string;
  fillQuery?: string;
  action?: () => void;
}

interface SuggestionsListProps {
  mode: SpotlightMode;
  query: string;
  rawTypedQuery?: string;
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onExecuteItem: (item: SuggestionItem) => void;
  historyItems?: HistoryItem[];
  onFillQuery?: (text: string) => void;
  suggestionsSeed?: number;
  predictions?: PredictionItem[];
}

function renderPredictionIcon(iconName: string, className = 'w-3.5 h-3.5') {
  switch (iconName) {
    case 'calendar':
      return <Calendar className={className} strokeWidth={1.8} />;
    case 'clock':
      return <Clock className={className} strokeWidth={1.8} />;
    case 'folder':
      return <Folder className={className} strokeWidth={1.8} />;
    case 'file':
      return <FileText className={className} strokeWidth={1.8} />;
    case 'mail':
      return <Mail className={className} strokeWidth={1.8} />;
    case 'terminal':
      return <Terminal className={className} strokeWidth={1.8} />;
    case 'globe':
      return <Globe className={className} strokeWidth={1.8} />;
    case 'sparkles':
    default:
      return <Sparkles className={className} strokeWidth={1.8} />;
  }
}

function renderHighlightedQuery(queryText: string, rawTyped: string) {
  if (!rawTyped || !rawTyped.trim()) {
    return <span className="text-white/90">{queryText}</span>;
  }
  const cleanTyped = rawTyped.trim().toLowerCase();
  const qLower = queryText.toLowerCase();

  if (qLower.startsWith(cleanTyped)) {
    const matched = queryText.slice(0, cleanTyped.length);
    const remainder = queryText.slice(cleanTyped.length);
    return (
      <span className="truncate">
        <span className="font-semibold text-sky-300 drop-shadow-[0_0_8px_rgba(56,189,248,0.35)]">{matched}</span>
        <span className="text-white/80">{remainder}</span>
      </span>
    );
  }

  const idx = qLower.indexOf(cleanTyped);
  if (idx >= 0) {
    const before = queryText.slice(0, idx);
    const matched = queryText.slice(idx, idx + cleanTyped.length);
    const after = queryText.slice(idx + cleanTyped.length);
    return (
      <span className="truncate">
        <span className="text-white/70">{before}</span>
        <span className="font-semibold text-sky-300 drop-shadow-[0_0_8px_rgba(56,189,248,0.35)]">{matched}</span>
        <span className="text-white/80">{after}</span>
      </span>
    );
  }

  return <span className="text-white/90 truncate">{queryText}</span>;
}

// Format relative time helper
function formatTimeAgo(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return 'Just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Safe math evaluator for smart calculator
function evaluateMath(expr: string): string | null {
  const cleaned = expr.trim().replace(/^calc(?:ulate)?\s+/i, '');
  if (!/^[\d\s+\-*/().%^]+$/.test(cleaned) || !/\d/.test(cleaned) || !/[+\-*/%^]/.test(cleaned)) {
    return null;
  }
  try {
    const sanitized = cleaned.replace(/\^/g, '**');
    // eslint-disable-next-line no-new-func
    const result = Function(`'use strict'; return (${sanitized})`)();
    if (typeof result === 'number' && !Number.isNaN(result) && Number.isFinite(result)) {
      return Number.isInteger(result) ? result.toLocaleString() : result.toFixed(4).replace(/\.?0+$/, '');
    }
  } catch {
    return null;
  }
  return null;
}

// Comprehensive registry of system applications
const SYSTEM_APPLICATIONS: SuggestionItem[] = [
  {
    id: 'app-vscode',
    title: 'Visual Studio Code',
    subtitle: 'Code Editor & Development Environment',
    category: 'apps',
    icon: AppWindow,
    badge: 'Editor',
    fillQuery: 'Open Visual Studio Code',
  },
  {
    id: 'app-terminal',
    title: 'Terminal / PowerShell',
    subtitle: 'Command Line Shell & Developer Tools',
    category: 'apps',
    icon: Terminal,
    badge: 'Shell',
    fillQuery: 'Open Terminal',
  },
  {
    id: 'app-spotify',
    title: 'Spotify',
    subtitle: 'Music, Podcasts & Audio Playback',
    category: 'apps',
    icon: Music,
    badge: 'Media',
    fillQuery: 'Open Spotify',
  },
  {
    id: 'app-chrome',
    title: 'Google Chrome',
    subtitle: 'Web Browser & Internet Navigation',
    category: 'apps',
    icon: Globe,
    badge: 'Browser',
    fillQuery: 'Open Chrome',
  },
  {
    id: 'app-explorer',
    title: 'File Explorer',
    subtitle: 'Windows File System & Drives Manager',
    category: 'apps',
    icon: Folder,
    badge: 'System',
    fillQuery: 'Open File Explorer',
  },
  {
    id: 'app-taskmgr',
    title: 'Task Manager',
    subtitle: 'System Performance & Process Monitor',
    category: 'apps',
    icon: Activity,
    badge: 'System',
    fillQuery: 'Open Task Manager',
  },
  {
    id: 'app-notepad',
    title: 'Notepad',
    subtitle: 'Quick Text Editor',
    category: 'apps',
    icon: FileText,
    badge: 'Utility',
    fillQuery: 'Open Notepad',
  },
  {
    id: 'app-calculator',
    title: 'Calculator',
    subtitle: 'Standard, Scientific & Programmer Calculator',
    category: 'apps',
    icon: Calculator,
    badge: 'Utility',
    fillQuery: 'Open Calculator',
  },
  {
    id: 'app-settings',
    title: 'Windows Settings',
    subtitle: 'System Preferences, Network & Devices',
    category: 'apps',
    icon: SlidersHorizontal,
    badge: 'System',
    fillQuery: 'Open Windows Settings',
  },
];

// Comprehensive registry of workspaces & directories
const SYSTEM_DIRECTORIES: SuggestionItem[] = [
  {
    id: 'file-nexus',
    title: 'nexus workspace',
    subtitle: 'd:/Codes/nexus • Main Development Repository',
    category: 'files',
    icon: FolderOpen,
    badge: 'Workspace',
    fillQuery: 'Open d:/Codes/nexus',
  },
  {
    id: 'file-codes',
    title: 'Codes Directory',
    subtitle: 'd:/Codes • Developer Projects & Repositories',
    category: 'files',
    icon: Folder,
    badge: 'Directory',
    fillQuery: 'Open d:/Codes',
  },
  {
    id: 'file-documents',
    title: 'Documents Folder',
    subtitle: 'C:/Users/sagni/Documents • Personal Files & Notes',
    category: 'files',
    icon: Folder,
    badge: 'Folder',
    fillQuery: 'Open Documents folder',
  },
  {
    id: 'file-downloads',
    title: 'Downloads Folder',
    subtitle: 'C:/Users/sagni/Downloads • Recent Downloads',
    category: 'files',
    icon: Folder,
    badge: 'Folder',
    fillQuery: 'Open Downloads folder',
  },
  {
    id: 'file-desktop',
    title: 'Desktop Directory',
    subtitle: 'C:/Users/sagni/Desktop • Desktop Files & Shortcuts',
    category: 'files',
    icon: Folder,
    badge: 'Folder',
    fillQuery: 'Open Desktop folder',
  },
];

// ──────────────────────────────────────────────────────────────────────────
// COMPREHENSIVE POOL OF DYNAMIC SUGGESTED TASKS
// Spans 6 distinct domains: Reasoning, Coding, Diagnostics, Research, Media, Productivity
// ──────────────────────────────────────────────────────────────────────────
interface DynamicSuggestedTask {
  id: string;
  title: string;
  subtitle: string;
  badge: string;
  domain: 'reasoning' | 'coding' | 'diagnostics' | 'research' | 'media' | 'productivity';
  icon: React.ElementType;
  fillQuery: string;
}

const DYNAMIC_TASKS_POOL: DynamicSuggestedTask[] = [
  // ─── REASONING & ARCHITECTURE ───
  {
    id: 'dt-quantum',
    title: 'Explain Quantum Computing in 3 sentences',
    subtitle: 'Deep conceptual reasoning with concise clarity',
    badge: 'Reasoning',
    domain: 'reasoning',
    icon: Bot,
    fillQuery: 'Explain Quantum Computing in 3 sentences',
  },
  {
    id: 'dt-mamba',
    title: 'Compare Transformer attention vs Mamba state-space',
    subtitle: 'Architectural analysis and inference compute trade-offs',
    badge: 'Architecture',
    domain: 'reasoning',
    icon: Bot,
    fillQuery: 'Compare Transformer attention vs Mamba state-space models in detail',
  },
  {
    id: 'dt-raft',
    title: 'Explain Raft leader election & log consensus',
    subtitle: 'Distributed systems state-machine consensus made clear',
    badge: 'Distributed',
    domain: 'reasoning',
    icon: Bot,
    fillQuery: 'Explain Raft leader election and log consensus protocol simply',
  },
  {
    id: 'dt-monolith',
    title: 'Evaluate Monolith vs Microservices trade-offs',
    subtitle: 'System boundaries, operational complexity & scalability',
    badge: 'Strategy',
    domain: 'reasoning',
    icon: Bot,
    fillQuery: 'Evaluate architectural trade-offs between modular monolith and microservices',
  },

  // ─── CODING & SYSTEMS ───
  {
    id: 'dt-fastapi',
    title: 'Write a Python FastAPI async websocket endpoint',
    subtitle: 'Production-ready backend architecture generation',
    badge: 'Coding',
    domain: 'coding',
    icon: FileCode,
    fillQuery: 'Write a Python FastAPI async websocket endpoint with connection management',
  },
  {
    id: 'dt-debounce',
    title: 'Write a TypeScript debounce hook with unit tests',
    subtitle: 'Type-safe React utility with timer cleanup',
    badge: 'Frontend',
    domain: 'coding',
    icon: FileCode,
    fillQuery: 'Write a TypeScript useDebounce hook with cleanup and unit tests',
  },
  {
    id: 'dt-docker',
    title: 'Generate Docker compose with Postgres & Redis',
    subtitle: 'Isolated developer containers with persistent volumes',
    badge: 'DevOps',
    domain: 'coding',
    icon: Terminal,
    fillQuery: 'Generate Docker compose file with Postgres, Redis and healthchecks',
  },
  {
    id: 'dt-retry',
    title: 'Implement exponential backoff retry wrapper in Go',
    subtitle: 'Resilient network fault-tolerance with jitter',
    badge: 'Systems',
    domain: 'coding',
    icon: FileCode,
    fillQuery: 'Implement an exponential backoff retry wrapper with jitter in Go',
  },
  {
    id: 'dt-svg',
    title: 'Convert SVG markup to accessible React component',
    subtitle: 'Tailwind-friendly SVG component with ARIA props',
    badge: 'React',
    domain: 'coding',
    icon: FileCode,
    fillQuery: 'Convert SVG markup into an accessible, typed React component',
  },

  // ─── SYSTEM DIAGNOSTICS & HEALTH ───
  {
    id: 'dt-diagnostics',
    title: 'Inspect system performance & memory usage',
    subtitle: 'System diagnostic analysis & hardware health',
    badge: 'Diagnostics',
    domain: 'diagnostics',
    icon: Activity,
    fillQuery: 'Inspect system performance, CPU load and memory usage',
  },
  {
    id: 'dt-disk',
    title: 'Scan drive D: for largest folders and files',
    subtitle: 'Disk space analyzer and storage consumption stats',
    badge: 'Storage',
    domain: 'diagnostics',
    icon: Folder,
    fillQuery: 'Scan drive D: for the largest folders and files taking disk space',
  },
  {
    id: 'dt-ports',
    title: 'Check active TCP listening ports and processes',
    subtitle: 'Identify socket bindings and background network listeners',
    badge: 'Network',
    domain: 'diagnostics',
    icon: Activity,
    fillQuery: 'Check active TCP listening ports and their associated process IDs',
  },
  {
    id: 'dt-stress',
    title: 'Inspect thermal throttles & hardware power draw',
    subtitle: 'CPU temperature, clock frequencies and fan profiles',
    badge: 'Hardware',
    domain: 'diagnostics',
    icon: Cpu,
    fillQuery: 'Inspect hardware performance counters and thermal states',
  },

  // ─── RESEARCH & INTELLIGENCE ───
  {
    id: 'dt-research',
    title: 'Search trending open source AI agent frameworks',
    subtitle: 'Autonomous deep web research and synthesis',
    badge: 'Research',
    domain: 'research',
    icon: Globe,
    fillQuery: 'Search trending open source AI agent frameworks on GitHub and summarize',
  },
  {
    id: 'dt-papers',
    title: 'Find latest breakthroughs in reasoning models',
    subtitle: 'Chain-of-thought, search-based scaling & verification',
    badge: 'Intelligence',
    domain: 'research',
    icon: Globe,
    fillQuery: 'Find latest AI papers on test-time search and reasoning compute scaling',
  },
  {
    id: 'dt-batteries',
    title: 'Investigate commercial solid-state battery status',
    subtitle: 'Energy density milestones and automotive deployment timeline',
    badge: 'Science',
    domain: 'research',
    icon: Globe,
    fillQuery: 'Investigate latest commercial viability and timeline of solid-state batteries',
  },
  {
    id: 'dt-weather',
    title: 'Check local weather radar & 3-day forecast',
    subtitle: 'Atmospheric conditions, precipitation and humidity',
    badge: 'Forecast',
    domain: 'research',
    icon: Globe,
    fillQuery: 'Check current local weather radar and forecast',
  },

  // ─── MEDIA & FOCUS AMBIENCE ───
  {
    id: 'dt-lofi',
    title: 'Play Lo-Fi chill beats for focus',
    subtitle: 'Media playback & focus environment control',
    badge: 'Media',
    domain: 'media',
    icon: Music,
    fillQuery: 'Play Lo-Fi chill beats on Spotify',
  },
  {
    id: 'dt-synthwave',
    title: 'Play Synthwave coding playlist on Spotify',
    subtitle: 'High-tempo electronic rhythm for deep flow state',
    badge: 'Focus',
    domain: 'media',
    icon: Music,
    fillQuery: 'Play Synthwave coding playlist on Spotify',
  },
  {
    id: 'dt-zimmer',
    title: 'Play Hans Zimmer soundtracks on Spotify',
    subtitle: 'Immersive cinematic orchestral composition',
    badge: 'Audio',
    domain: 'media',
    icon: Music,
    fillQuery: 'Play Hans Zimmer soundtracks on Spotify',
  },
  {
    id: 'dt-ambient',
    title: 'Play ambient rain & cafe focus sounds',
    subtitle: 'Calm background noise masking for concentration',
    badge: 'Ambience',
    domain: 'media',
    icon: Music,
    fillQuery: 'Play ambient rainfall and cafe white noise on Spotify',
  },

  // ─── PRODUCTIVITY & AUTOMATION ───
  {
    id: 'dt-commit',
    title: 'Summarize git commits from the last 24 hours',
    subtitle: 'Generate structured changelog and release notes',
    badge: 'Git',
    domain: 'productivity',
    icon: Terminal,
    fillQuery: 'Summarize recent git commits and changes from the last 24 hours',
  },
  {
    id: 'dt-report',
    title: 'Draft a concise engineering standup update',
    subtitle: 'Completed tasks, active blockers & daily deliverables',
    badge: 'Productivity',
    domain: 'productivity',
    icon: FileText,
    fillQuery: 'Draft a concise engineering standup status report',
  },
  {
    id: 'dt-regex',
    title: 'Write a regex to extract semantic version strings',
    subtitle: 'SemVer 2.0 pattern matching with test cases',
    badge: 'Utility',
    domain: 'productivity',
    icon: FileCode,
    fillQuery: 'Write a regular expression to validate and extract SemVer 2.0 version strings',
  },
];

// All AI capabilities mapped from pool
const AI_WORKFLOWS: SuggestionItem[] = DYNAMIC_TASKS_POOL.map((t) => ({
  id: t.id,
  title: t.title,
  subtitle: t.subtitle,
  category: 'ai' as const,
  icon: t.icon,
  badge: t.badge,
  fillQuery: t.fillQuery,
}));

// Diversity-guaranteed dynamic selector (ensures 4 distinct domains per opening)
function pickDynamicTasks(_seed: number): SuggestionItem[] {
  const domains: Array<DynamicSuggestedTask['domain']> = [
    'reasoning',
    'coding',
    'diagnostics',
    'research',
    'media',
    'productivity',
  ];

  // Randomize domains
  const shuffledDomains = [...domains].sort(() => Math.random() - 0.5);
  const selectedDomains = shuffledDomains.slice(0, 4);

  const chosen: DynamicSuggestedTask[] = [];

  for (const dom of selectedDomains) {
    const candidates = DYNAMIC_TASKS_POOL.filter((t) => t.domain === dom);
    if (candidates.length > 0) {
      const idx = Math.floor(Math.random() * candidates.length);
      chosen.push(candidates[idx]);
    }
  }

  // Safety fallback
  if (chosen.length < 4) {
    for (const t of DYNAMIC_TASKS_POOL) {
      if (!chosen.some((c) => c.id === t.id)) {
        chosen.push(t);
        if (chosen.length === 4) break;
      }
    }
  }

  return chosen.map((t) => ({
    id: t.id,
    title: t.title,
    subtitle: t.subtitle,
    category: 'ai' as const,
    icon: t.icon,
    badge: t.badge,
    fillQuery: t.fillQuery,
  }));
}

export const SuggestionsList: React.FC<SuggestionsListProps> = ({
  mode,
  query,
  rawTypedQuery = '',
  selectedIndex,
  onSelectIndex,
  onExecuteItem,
  historyItems = [],
  suggestionsSeed = 0,
  predictions = [],
}) => {
  const [currentTime, setCurrentTime] = useState<Date>(new Date());
  const [dynamicTasks, setDynamicTasks] = useState<SuggestionItem[]>(() => pickDynamicTasks(suggestionsSeed));
  const [isRotating, setIsRotating] = useState(false);

  // Update dynamic tasks whenever suggestionsSeed updates (on every launcher opening)
  useEffect(() => {
    setDynamicTasks(pickDynamicTasks(suggestionsSeed || Date.now()));
  }, [suggestionsSeed]);

  const handleManualRefresh = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsRotating(true);
    setDynamicTasks(pickDynamicTasks(Date.now()));
    setTimeout(() => setIsRotating(false), 350);
  }, []);

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const { user, dbUser } = useAuth();

  // Extract user's first name for personal touch
  const firstName = useMemo(() => {
    let raw = user?.displayName || dbUser?.display_name;
    if (!raw && user?.email) {
      raw = user.email.split('@')[0];
    }
    if (!raw) {
      try {
        const cached = localStorage.getItem('nexus_desktop_auth');
        if (cached) {
          const parsed = JSON.parse(cached);
          raw = parsed?.user?.display_name || parsed?.user?.displayName || parsed?.user?.email?.split('@')[0];
        }
      } catch {
        // ignore
      }
    }
    if (!raw) return '';
    const clean = raw.trim().split(/[\s._-]+/)[0];
    if (!clean) return '';
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  }, [user, dbUser]);

  // iPhone-inspired time presentation (Hours & Minutes main hero, small ticking seconds)
  const { hoursFormatted, minutesFormatted, secondsFormatted, amPmString, dateString } = useMemo(() => {
    const hours = currentTime.getHours();
    const minutes = currentTime.getMinutes().toString().padStart(2, '0');
    const seconds = currentTime.getSeconds().toString().padStart(2, '0');
    const isPm = hours >= 12;
    const formattedHours = (hours % 12 || 12).toString();

    const dStr = currentTime.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });

    return {
      hoursFormatted: formattedHours,
      minutesFormatted: minutes,
      secondsFormatted: seconds,
      amPmString: isPm ? 'PM' : 'AM',
      dateString: dStr,
    };
  }, [currentTime]);

  // Dynamic, personalized greeting calculated based on time of day & activation seed
  const greeting = useMemo(() => {
    const hours = currentTime.getHours();
    let options: string[] = [];

    if (hours >= 22 || hours < 5) {
      options = firstName
        ? [
            `Working late, ${firstName}?`,
            `Burning the midnight oil, ${firstName}?`,
            `Night owl mode, ${firstName}?`,
            `Late night hustle, ${firstName}?`,
            `Still building, ${firstName}?`,
            `Quiet hours, ${firstName}.`,
          ]
        : [
            'Working late?',
            'Burning the midnight oil?',
            'Night owl mode.',
            'Quiet hours hustle.',
          ];
    } else if (hours >= 5 && hours < 12) {
      options = firstName
        ? [
            `Good morning, ${firstName}!`,
            `Rise and shine, ${firstName}!`,
            `Ready for the day, ${firstName}?`,
            `Morning focus, ${firstName}.`,
            `Early bird shift, ${firstName}!`,
          ]
        : ['Good morning!', 'Rise and shine!', 'Morning focus.'];
    } else if (hours >= 12 && hours < 17) {
      options = firstName
        ? [
            `Good afternoon, ${firstName}!`,
            `Midday momentum, ${firstName}.`,
            `Crushing the afternoon, ${firstName}?`,
            `Stay in the flow, ${firstName}.`,
            `Productive afternoon, ${firstName}!`,
          ]
        : ['Good afternoon!', 'Midday momentum.', 'Stay in the flow.'];
    } else {
      options = firstName
        ? [
            `Good evening, ${firstName}!`,
            `Evening focus, ${firstName}.`,
            `Winding down, ${firstName}?`,
            `Wrapping up the day, ${firstName}?`,
            `Great to see you, ${firstName}!`,
          ]
        : ['Good evening!', 'Evening focus.', 'Wrapping up the day?'];
    }

    const index = Math.abs(Math.floor(suggestionsSeed || 0)) % options.length;
    return options[index];
  }, [currentTime.getHours(), firstName, suggestionsSeed]);

  // ──────────────────────────────────────────────────────────────────────────
  // SEARCH FILTERING (When query is present)
  // Strictly filtered by selected category mode!
  // ──────────────────────────────────────────────────────────────────────────
  const searchResults = useMemo((): SuggestionItem[] => {
    const q = query.toLowerCase().trim();
    if (!q) return [];

    const items: SuggestionItem[] = [];

    // ───────────────── APPS MODE ─────────────────
    if (mode === 'apps') {
      for (const app of SYSTEM_APPLICATIONS) {
        if (
          app.title.toLowerCase().includes(q) ||
          (app.subtitle && app.subtitle.toLowerCase().includes(q))
        ) {
          items.push(app);
        }
      }
      return items;
    }

    // ───────────────── FILES MODE ─────────────────
    if (mode === 'files') {
      for (const file of SYSTEM_DIRECTORIES) {
        if (
          file.title.toLowerCase().includes(q) ||
          (file.subtitle && file.subtitle.toLowerCase().includes(q))
        ) {
          items.push(file);
        }
      }
      // Also search file-related entries in history
      for (const h of historyItems) {
        if (
          h.prompt &&
          (h.prompt.toLowerCase().includes(q) || h.mode === 'files') &&
          (h.prompt.includes('/') || h.prompt.includes('\\') || h.prompt.toLowerCase().includes('file') || h.prompt.toLowerCase().includes('folder'))
        ) {
          if (!items.some(it => it.title === h.prompt)) {
            items.push({
              id: `hist-file-${h.id}`,
              title: h.prompt,
              subtitle: `Recent File Task • ${formatTimeAgo(h.timestamp)}`,
              category: 'files',
              icon: FileText,
              badge: 'History',
              fillQuery: h.prompt,
            });
          }
        }
      }
      return items;
    }

    // ───────────────── AI MODE ─────────────────
    if (mode === 'ai') {
      // 1. Math calculation if valid
      const calcResult = evaluateMath(q);
      if (calcResult !== null) {
        items.push({
          id: 'calc-result',
          title: `= ${calcResult}`,
          subtitle: `Computed math expression "${query}"`,
          category: 'calc',
          icon: Calculator,
          badge: 'Math',
        });
      }

      // 2. Direct AI prompt action
      items.push({
        id: 'ai-prompt-direct',
        title: `Ask NEXUS: "${query}"`,
        subtitle: 'Execute full companion reasoning & action pipeline',
        category: 'ai',
        icon: Bot,
        badge: 'Intelligence',
      });

      // 3. AI contextual workflow completions
      if (/^(how|what|why|where|who|when|can|explain|tell|summarize)\b/i.test(q)) {
        items.push({
          id: 'ai-explain-comp',
          title: `Explain ${query.replace(/^(?:explain|tell me about)\s+/i, '')} in depth`,
          subtitle: 'Comprehensive conceptual breakdown with examples',
          category: 'ai',
          icon: Bot,
          badge: 'Reasoning',
        });
      } else if (/^(write|code|create|build|generate|implement)\b/i.test(q)) {
        items.push({
          id: 'ai-code-comp',
          title: `Generate production-ready code for "${query}"`,
          subtitle: 'Clean implementation with types and comments',
          category: 'ai',
          icon: FileCode,
          badge: 'Code',
        });
      }

      // 4. Relevant AI workflows
      for (const wf of AI_WORKFLOWS) {
        if (wf.title.toLowerCase().includes(q) || (wf.subtitle && wf.subtitle.toLowerCase().includes(q))) {
          items.push(wf);
        }
      }

      return items;
    }

    // ───────────────── ALL MODE (UNIFIED) ─────────────────
    // 1. Math calculation check
    const calcResult = evaluateMath(q);
    if (calcResult !== null) {
      items.push({
        id: 'calc-result',
        title: `= ${calcResult}`,
        subtitle: `Calculate "${query}"`,
        category: 'calc',
        icon: Calculator,
        badge: 'Math',
      });
    }

    // 2. Matching history items
    const matchedPrompts: string[] = [];
    for (const h of historyItems) {
      if (h.prompt && h.prompt.toLowerCase().includes(q)) {
        if (!matchedPrompts.includes(h.prompt)) {
          matchedPrompts.push(h.prompt);
          items.push({
            id: `hist-${h.id}`,
            title: h.prompt,
            subtitle: `Ran ${formatTimeAgo(h.timestamp)} • ${h.status === 'completed' ? 'Completed' : 'Task'}`,
            category: 'history',
            icon: History,
            badge: 'History',
            fillQuery: h.prompt,
          });
          if (items.length >= 3) break;
        }
      }
    }

    // 3. Matching applications
    for (const app of SYSTEM_APPLICATIONS) {
      if (app.title.toLowerCase().includes(q) || (app.subtitle && app.subtitle.toLowerCase().includes(q))) {
        items.push(app);
      }
    }

    // 4. Matching workspaces and files
    for (const file of SYSTEM_DIRECTORIES) {
      if (file.title.toLowerCase().includes(q) || (file.subtitle && file.subtitle.toLowerCase().includes(q))) {
        items.push(file);
      }
    }

    // 5. Primary AI action
    items.push({
      id: 'ai-prompt',
      title: `Ask NEXUS: "${query}"`,
      subtitle: 'Execute full companion workflow & intelligence',
      category: 'ai',
      icon: Bot,
      badge: 'NEXUS',
    });

    // 6. Web Search Fallback
    items.push({
      id: 'search-web',
      title: `Search Google for "${query}"`,
      subtitle: 'Open default web browser',
      category: 'all',
      icon: Globe,
      badge: 'Browser',
    });

    return items;
  }, [query, mode, historyItems]);

  // ──────────────────────────────────────────────────────────────────────────
  // VIEW A: NORMAL IDLE VIEW (When query is empty)
  // Distinct views rendered dynamically based on selected category tab!
  // ──────────────────────────────────────────────────────────────────────────
  if (!query.trim()) {
    return (
      <div className="flex flex-col py-2.5 px-3.5 space-y-3 select-none border-t border-white/[0.06]">
        {/* iOS-Inspired Desktop Time & Status Presentation */}
        <div className="relative flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-gradient-to-r from-white/[0.035] via-white/[0.02] to-transparent border border-white/[0.07] overflow-hidden shadow-sm">
          {/* Subtle top ambient light line */}
          <div className="absolute top-0 left-4 right-4 h-[1px] bg-gradient-to-r from-transparent via-white/10 to-transparent pointer-events-none" />

          {/* Prominent Digital Clock & Natural Greeting */}
          <div className="flex items-center gap-3.5">
            <div className="flex items-baseline gap-1 select-none">
              {/* iPhone-Style Hero Digital Clock (Hours & Minutes main focus) */}
              <span className="text-2xl font-light text-white/95 tracking-tight tabular-nums drop-shadow-sm">
                {hoursFormatted}:{minutesFormatted}
              </span>
              {/* Subtle ticking seconds counter & AM/PM badge */}
              <span className="text-[11px] font-mono text-white/40 tabular-nums">
                :{secondsFormatted}
              </span>
              <span className="text-[9.5px] font-semibold text-sky-400 tracking-wider uppercase ml-0.5">
                {amPmString}
              </span>
            </div>

            <div className="h-6 w-[1px] bg-white/[0.08]" />

            <div className="flex flex-col">
              <span className="text-[10.5px] font-medium text-white/45 tracking-wider uppercase font-mono">
                {dateString}
              </span>
              <span className="text-xs text-white/85 font-medium tracking-tight mt-0.5">
                {greeting}
              </span>
            </div>
          </div>

          {/* Signature NEXUS Core Indicator (De-emphasized model names) */}
          <div className="flex items-center gap-2">
            <div
              className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-sky-500/[0.08] border border-sky-400/20 text-[11px] font-medium text-sky-300 select-none shadow-[0_0_12px_rgba(56,189,248,0.10)]"
              title="NEXUS Core is ready for commands"
            >
              <div className="relative flex items-center justify-center w-3 h-3">
                <span className="absolute w-3 h-3 rounded-full border border-sky-400/35 animate-[nexusOrbit_8s_linear_infinite]" />
                <span className="relative w-1.5 h-1.5 rounded-full bg-sky-400 shadow-[0_0_6px_#38bdf8] animate-[nexusCorePulse_3s_ease-in-out_infinite]" />
              </div>
              <span className="tracking-tight text-white/95 font-semibold text-[11.5px]">NEXUS</span>
              <span className="text-white/25 text-[10px]">•</span>
              <span className="text-sky-300/90 text-[10.5px] font-medium">Ready</span>
            </div>
          </div>
        </div>

        {/* ───────────────── ALL VIEW ───────────────── */}
        {mode === 'all' && (
          <>
            {/* Dynamic Suggested Tasks (rotates on every opening) */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-white/35 font-mono">
                    Suggested Tasks
                  </span>
                  <button
                    type="button"
                    onClick={handleManualRefresh}
                    title="Roll new suggestions"
                    className="p-0.5 rounded text-white/30 hover:text-sky-400 hover:bg-white/[0.06] transition-all cursor-pointer"
                  >
                    <RotateCw className={`w-2.5 h-2.5 transition-transform duration-300 ${isRotating ? 'rotate-180 text-sky-400' : ''}`} />
                  </button>
                </div>
                <span className="text-[10px] text-white/25 font-mono">Click or type to launch</span>
              </div>

              <div className="grid grid-cols-2 gap-2">
                {dynamicTasks.map((rec) => {
                  const Icon = rec.icon;
                  return (
                    <div
                      key={rec.id}
                      onClick={() => onExecuteItem(rec)}
                      className="group relative flex items-center gap-2.5 p-2 rounded-xl bg-white/[0.02] hover:bg-white/[0.05] border border-white/[0.05] hover:border-white/[0.12] transition-all duration-120 cursor-pointer min-w-0"
                    >
                      <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.06] text-white/60 group-hover:text-sky-400 group-hover:bg-sky-400/10 group-hover:border-sky-400/20 flex items-center justify-center flex-shrink-0 transition-colors">
                        <Icon className="w-3.5 h-3.5" strokeWidth={1.8} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1.5">
                          <span className="text-xs font-medium text-white/85 group-hover:text-white truncate">
                            {rec.title}
                          </span>
                          <span className="text-[9px] font-mono px-1 py-0.2 rounded border border-white/[0.06] bg-white/[0.02] text-white/40 flex-shrink-0">
                            {rec.badge}
                          </span>
                        </div>
                        <span className="text-[10px] text-white/35 truncate block mt-0.5">
                          {rec.subtitle}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Recent Activity Timeline */}
            {historyItems.length > 0 && (
              <div className="space-y-1.5 pt-0.5">
                <div className="flex items-center justify-between px-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-white/35 font-mono">
                    Recent Activity
                  </span>
                  <span className="text-[10px] text-white/25 font-mono">{historyItems.slice(0, 3).length} recorded</span>
                </div>

                <div className="space-y-1">
                  {historyItems.slice(0, 3).map((item) => (
                    <div
                      key={item.id}
                      onClick={() => onExecuteItem({
                        id: item.id,
                        title: item.prompt,
                        subtitle: 'Recent History',
                        category: 'history',
                        icon: History,
                      })}
                      className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white/[0.015] hover:bg-white/[0.045] border border-white/[0.04] hover:border-white/[0.08] transition-colors cursor-pointer group"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <History className="w-3.5 h-3.5 text-white/35 group-hover:text-white/70 flex-shrink-0 transition-colors" strokeWidth={1.8} />
                        <span className="text-xs text-white/75 group-hover:text-white truncate">
                          {item.prompt}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0 pl-2">
                        <span className="text-[10px] font-mono text-white/30">
                          {formatTimeAgo(item.timestamp)}
                        </span>
                        {item.status === 'completed' ? (
                          <CheckCircle2 className="w-3 h-3 text-emerald-400/80" strokeWidth={2} />
                        ) : (
                          <CornerDownLeft className="w-3 h-3 text-white/20 group-hover:text-sky-400 transition-colors" />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Quick-Launch Toolbar */}
            <div className="flex items-center justify-between pt-1 border-t border-white/[0.05] px-1">
              <span className="text-[10px] font-mono text-white/30 uppercase tracking-wider">
                Quick Launch
              </span>
              <div className="flex items-center gap-1.5">
                {[
                  { name: 'VS Code', icon: AppWindow, prompt: 'Open Visual Studio Code' },
                  { name: 'Terminal', icon: Terminal, prompt: 'Open Terminal' },
                  { name: 'Spotify', icon: Music, prompt: 'Play music on Spotify' },
                  { name: 'Browser', icon: Globe, prompt: 'Open Chrome' },
                ].map(app => {
                  const AppIcon = app.icon;
                  return (
                    <button
                      key={app.name}
                      type="button"
                      onClick={() => onExecuteItem({
                        id: `app-${app.name}`,
                        title: app.prompt,
                        category: 'apps',
                        icon: app.icon,
                      })}
                      className="group flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/[0.025] hover:bg-white/[0.06] border border-white/[0.06] hover:border-white/[0.10] text-[11px] text-white/60 hover:text-white transition-colors"
                    >
                      <AppIcon className="w-3 h-3 text-white/40 group-hover:text-sky-400 transition-colors" strokeWidth={1.8} />
                      <span>{app.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {/* ───────────────── APPS VIEW ───────────────── */}
        {mode === 'apps' && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between px-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-white/35 font-mono">
                Applications & Tools ({SYSTEM_APPLICATIONS.length})
              </span>
              <span className="text-[10px] text-white/25 font-mono">Click or press Enter to launch</span>
            </div>

            <div className="grid grid-cols-2 gap-2 max-h-[300px] overflow-y-auto pr-0.5">
              {SYSTEM_APPLICATIONS.map((app) => {
                const Icon = app.icon;
                return (
                  <div
                    key={app.id}
                    onClick={() => onExecuteItem(app)}
                    className="group flex items-center gap-2.5 p-2 rounded-xl bg-white/[0.02] hover:bg-white/[0.06] border border-white/[0.05] hover:border-white/[0.12] transition-colors cursor-pointer min-w-0"
                  >
                    <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.06] text-white/50 group-hover:text-sky-400 group-hover:bg-sky-400/10 group-hover:border-sky-400/20 flex items-center justify-center flex-shrink-0 transition-colors">
                      <Icon className="w-3.5 h-3.5" strokeWidth={1.8} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-1.5">
                        <span className="text-xs font-medium text-white/85 group-hover:text-white truncate">
                          {app.title}
                        </span>
                        <span className="text-[9px] font-mono px-1 py-0.2 rounded border border-white/[0.06] bg-white/[0.02] text-white/40 flex-shrink-0">
                          {app.badge}
                        </span>
                      </div>
                      <span className="text-[10px] text-white/35 truncate block mt-0.5">
                        {app.subtitle}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ───────────────── FILES VIEW ───────────────── */}
        {mode === 'files' && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between px-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-white/35 font-mono">
                Workspaces & Directories
              </span>
              <span className="text-[10px] text-white/25 font-mono">Open in file manager or editor</span>
            </div>

            <div className="space-y-1 max-h-[300px] overflow-y-auto pr-0.5">
              {SYSTEM_DIRECTORIES.map((file) => {
                const Icon = file.icon;
                return (
                  <div
                    key={file.id}
                    onClick={() => onExecuteItem(file)}
                    className="group flex items-center justify-between p-2 rounded-xl bg-white/[0.02] hover:bg-white/[0.06] border border-white/[0.05] hover:border-white/[0.12] transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-2">
                      <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.06] text-white/50 group-hover:text-sky-400 group-hover:bg-sky-400/10 group-hover:border-sky-400/20 flex items-center justify-center flex-shrink-0 transition-colors">
                        <Icon className="w-3.5 h-3.5" strokeWidth={1.8} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-white/85 group-hover:text-white truncate">
                            {file.title}
                          </span>
                          <span className="text-[9px] font-mono px-1 py-0.2 rounded border border-white/[0.06] bg-white/[0.02] text-white/40 flex-shrink-0">
                            {file.badge}
                          </span>
                        </div>
                        <span className="text-[10px] text-white/35 truncate block mt-0.5 font-mono">
                          {file.subtitle}
                        </span>
                      </div>
                    </div>
                    <ArrowUpRight className="w-3.5 h-3.5 text-white/20 group-hover:text-sky-400 flex-shrink-0 transition-colors" />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ───────────────── AI VIEW ───────────────── */}
        {mode === 'ai' && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between px-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-white/35 font-mono">
                NEXUS AI Capabilities
              </span>
              <span className="text-[10px] text-white/25 font-mono">Select a workflow or type prompt</span>
            </div>

            <div className="space-y-1 max-h-[300px] overflow-y-auto pr-0.5">
              {AI_WORKFLOWS.map((wf) => {
                const Icon = wf.icon;
                return (
                  <div
                    key={wf.id}
                    onClick={() => onExecuteItem(wf)}
                    className="group flex items-center justify-between p-2 rounded-xl bg-white/[0.02] hover:bg-white/[0.06] border border-white/[0.05] hover:border-white/[0.12] transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-2">
                      <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.06] text-white/50 group-hover:text-sky-400 group-hover:bg-sky-400/10 group-hover:border-sky-400/20 flex items-center justify-center flex-shrink-0 transition-colors">
                        <Icon className="w-3.5 h-3.5" strokeWidth={1.8} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-white/85 group-hover:text-white truncate">
                            {wf.title}
                          </span>
                          <span className="text-[9px] font-mono px-1 py-0.2 rounded border border-white/[0.06] bg-white/[0.02] text-white/40 flex-shrink-0">
                            {wf.badge}
                          </span>
                        </div>
                        <span className="text-[10px] text-white/35 truncate block mt-0.5">
                          {wf.subtitle}
                        </span>
                      </div>
                    </div>
                    <CornerDownLeft className="w-3.5 h-3.5 text-white/20 group-hover:text-sky-400 flex-shrink-0 transition-colors" />
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ──────────────────────────────────────────────────────────────────────────
  // VIEW B: ACTIVE PREDICTIONS & SEARCH RESULTS (When query is present)
  // Clean, Google Search-style prediction dropdown or app/file results
  // ──────────────────────────────────────────────────────────────────────────

  // Primary: Personalized Query Predictions for 'all' and 'ai' modes
  if (predictions && predictions.length > 0 && (mode === 'all' || mode === 'ai')) {
    return (
      <div className="py-1 max-h-[380px] overflow-y-auto border-t border-white/[0.06] space-y-0.5 px-1.5 animate-in fade-in duration-100">
        {predictions.map((item, index) => {
          const isSelected = index === selectedIndex;

          return (
            <div
              key={item.id}
              role="option"
              aria-selected={isSelected}
              onMouseEnter={() => onSelectIndex(index)}
              onClick={() => {
                onSelectIndex(index);
                onExecuteItem({
                  id: item.id,
                  title: item.query,
                  fillQuery: item.query,
                  category: 'ai',
                  icon: Sparkles,
                  badge: item.badge,
                });
              }}
              className={`group flex items-center justify-between gap-3 px-3 py-2 rounded-xl transition-all cursor-pointer ${
                isSelected
                  ? 'bg-sky-500/12 border border-sky-400/30 text-white shadow-[0_0_20px_rgba(56,189,248,0.12)]'
                  : 'hover:bg-white/[0.04] border border-transparent text-white/85'
              }`}
            >
              {/* Intent / Action Icon */}
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div
                  className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors ${
                    isSelected
                      ? 'bg-sky-400/20 text-sky-300 border border-sky-400/35'
                      : 'bg-white/[0.04] text-white/50 border border-white/[0.06] group-hover:text-white/80'
                  }`}
                >
                  {renderPredictionIcon(item.iconName, 'w-3.5 h-3.5')}
                </div>

                {/* Highlighted Predictive Query */}
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <div className="text-[13px] tracking-[-0.01em] truncate font-normal">
                    {renderHighlightedQuery(item.query, rawTypedQuery || query)}
                  </div>
                </div>
              </div>

              {/* Badge & Enter Action */}
              <div className="flex items-center gap-2 flex-shrink-0">
                {item.badge && (
                  <span
                    className={`text-[9.5px] font-mono font-medium px-2 py-0.5 rounded-full border transition-colors ${
                      isSelected
                        ? 'bg-sky-400/15 border-sky-400/30 text-sky-200'
                        : 'bg-white/[0.03] border-white/[0.06] text-white/40'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}

                {isSelected ? (
                  <div className="flex items-center gap-1 text-[10.5px] text-sky-400 font-mono pl-1">
                    <span>Run</span>
                    <CornerDownLeft className="w-3 h-3 text-sky-400" />
                  </div>
                ) : (
                  <ArrowUpRight className="w-3.5 h-3.5 text-white/20 group-hover:text-white/40 transition-colors" />
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  // Secondary: Mode-specific results (Apps or Files)
  if ((mode === 'apps' || mode === 'files') && searchResults.length > 0) {
    return (
      <div className="py-1 max-h-[380px] overflow-y-auto border-t border-white/[0.06] space-y-0.5 px-1.5 animate-in fade-in duration-100">
        {searchResults.map((item, index) => {
          const Icon = item.icon;
          const isSelected = index === selectedIndex;

          return (
            <div
              key={item.id}
              onMouseEnter={() => onSelectIndex(index)}
              onClick={() => onExecuteItem(item)}
              className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg transition-colors cursor-pointer ${
                isSelected
                  ? 'bg-white/[0.07] border border-white/[0.09] text-white'
                  : 'hover:bg-white/[0.035] border border-transparent text-white/80'
              }`}
            >
              <div
                className={`w-6.5 h-6.5 rounded-md flex items-center justify-center flex-shrink-0 transition-colors ${
                  isSelected
                    ? 'bg-sky-400/15 border border-sky-400/30 text-sky-400'
                    : 'bg-white/[0.04] border border-white/[0.06] text-white/50'
                }`}
              >
                <Icon className="w-3.5 h-3.5" strokeWidth={1.8} />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs truncate ${
                      isSelected ? 'font-medium text-white' : 'font-normal text-white/85'
                    }`}
                  >
                    {item.title}
                  </span>

                  {item.badge && (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded border text-white/35 bg-white/[0.03] border-white/[0.06] flex-shrink-0">
                      {item.badge}
                    </span>
                  )}
                </div>

                {item.subtitle && (
                  <p className="text-[10.5px] text-white/35 truncate mt-0.5">
                    {item.subtitle}
                  </p>
                )}
              </div>

              {isSelected && (
                <div className="flex items-center gap-1 text-[10.5px] text-white/40 font-mono flex-shrink-0 pl-2">
                  <span>Run</span>
                  <CornerDownLeft className="w-3 h-3 text-sky-400" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  // Low confidence / No meaningful predictions -> suppress dropdown completely
  return null;
};
