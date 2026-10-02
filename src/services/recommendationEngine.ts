/**
 * NEXUS Personalized Query Recommendation & Autocomplete Engine
 *
 * Implements a Google Search-inspired query prediction system.
 * Intelligently predicts user intent and query completion using multi-signal ranking:
 * - Query similarity (prefix match, token overlap, substring match)
 * - User personalization (frequency, recency, successful execution history)
 * - Semantic similarity & intent aliasing (e.g. ppt -> presentation, sch -> schedule)
 * - Context awareness (active desktop target, application, workspace)
 * - Anti-history UI: Predictions are presented as intelligent suggestions, never as "history logs"
 */

import type { HistoryItem } from '../types/nexus';
import { classifyQuerySafety } from './safetyFilter';

export interface PredictionItem {
  id: string;
  query: string;
  matchedPrefix?: string;
  completionText?: string;
  intent: 'schedule' | 'open' | 'create' | 'analyze' | 'communication' | 'search' | 'code' | 'general';
  category: 'prediction' | 'ai' | 'apps' | 'files' | 'calc';
  badge?: string;
  score: number;
  iconName: 'calendar' | 'clock' | 'folder' | 'file' | 'mail' | 'sparkles' | 'bot' | 'terminal' | 'globe' | 'sliders';
}

export interface PredictionContext {
  activeTarget?: {
    id?: string;
    target_type?: string;
    application?: string;
    window_title?: string;
  };
  userId?: string;
  historyItems?: HistoryItem[];
}

export interface UserLearnedPattern {
  query: string;
  intent: string;
  successCount: number;
  failureCount: number;
  lastUsed: number;
  contextApp?: string;
  is_sensitive?: boolean;
  sensitivity_category?: string | null;
  recommendation_eligible?: boolean;
  classified_at?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Semantic Intent Maps & Aliases
// ─────────────────────────────────────────────────────────────────────────────

const INTENT_ALIASES: Record<string, string[]> = {
  schedule: [
    'schedule', 'sched', 'sch', 'remind', 'reminder', 'calendar', 'alarm',
    'due', 'later', 'tomorrow', 'tonight', 'weekly', 'daily', 'notify'
  ],
  open: [
    'open', 'launch', 'start', 'show', 'browse', 'navigate', 'goto', 'access', 'view'
  ],
  create: [
    'create', 'make', 'generate', 'build', 'draft', 'write', 'compose', 'new', 'produce'
  ],
  presentation: [
    'presentation', 'ppt', 'pptx', 'slide', 'slides', 'deck', 'pitch', 'powerpoint', 'keynote'
  ],
  excel: [
    'excel', 'sheet', 'sheets', 'spreadsheet', 'xls', 'xlsx', 'csv', 'table', 'workbook', 'grid'
  ],
  document: [
    'document', 'doc', 'docx', 'word', 'paper', 'report', 'memo', 'pdf', 'notes', 'summary'
  ],
  email: [
    'email', 'mail', 'gmail', 'message', 'letter', 'send', 'inbox', 'outbox'
  ],
  research: [
    'research', 'find', 'search', 'lookup', 'analyze', 'summarize', 'investigate', 'explore', 'deep-dive'
  ],
  code: [
    'code', 'develop', 'script', 'program', 'function', 'test', 'repo', 'git', 'terminal', 'powershell'
  ],
};

// ─────────────────────────────────────────────────────────────────────────────
// Core Knowledge Base: Predictive Command Templates
// ─────────────────────────────────────────────────────────────────────────────

interface SeedTemplate {
  query: string;
  intent: PredictionItem['intent'];
  badge: string;
  iconName: PredictionItem['iconName'];
  appContexts?: string[];
  semanticKeywords: string[];
}

const SEED_PREDICTION_TEMPLATES: SeedTemplate[] = [
  // ── Scheduling & Reminders ──
  {
    query: 'Schedule an email for tomorrow',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'email', 'tomorrow', 'mail', 'remind', 'later'],
  },
  {
    query: 'Schedule an email to John wishing him happy birthday at 12 AM on October 15',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'email', 'birthday', 'john', 'october', '12 am', 'happy birthday'],
  },
  {
    query: 'Schedule a research report on AI agents for tomorrow at 6 PM',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'research', 'report', 'ai agents', 'tomorrow', '6 pm'],
  },
  {
    query: 'Schedule a reminder for my meeting',
    intent: 'schedule',
    badge: 'Reminder',
    iconName: 'clock',
    semanticKeywords: ['schedule', 'reminder', 'meeting', 'remind', 'calendar', 'alert'],
  },
  {
    query: 'Schedule a task for tomorrow at 9 AM',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'task', 'tomorrow', '9 am', 'automation'],
  },
  {
    query: 'Schedule a birthday email',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'birthday', 'email', 'mail', 'wish'],
  },
  {
    query: 'Schedule an email to my team',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'email', 'team', 'update', 'weekly'],
  },
  {
    query: 'Schedule a weekly summary every Monday',
    intent: 'schedule',
    badge: 'Schedule',
    iconName: 'calendar',
    semanticKeywords: ['schedule', 'weekly', 'summary', 'monday', 'recurrence'],
  },

  // ── Opening Files, Projects & Applications ──
  {
    query: 'Open my Downloads folder',
    intent: 'open',
    badge: 'Folder',
    iconName: 'folder',
    semanticKeywords: ['open', 'downloads', 'folder', 'files', 'directory'],
  },
  {
    query: 'Open the latest project',
    intent: 'open',
    badge: 'Project',
    iconName: 'folder',
    semanticKeywords: ['open', 'latest', 'project', 'workspace', 'recent'],
  },
  {
    query: 'Open the Excel file I was working on',
    intent: 'open',
    badge: 'Excel',
    iconName: 'file',
    appContexts: ['excel'],
    semanticKeywords: ['open', 'excel', 'file', 'spreadsheet', 'working on', 'sheets', 'xls', 'xlsx'],
  },
  {
    query: 'Open my NEXUS project',
    intent: 'open',
    badge: 'Workspace',
    iconName: 'folder',
    semanticKeywords: ['open', 'nexus', 'project', 'codebase', 'repository'],
  },
  {
    query: 'Open Visual Studio Code',
    intent: 'open',
    badge: 'App',
    iconName: 'terminal',
    semanticKeywords: ['open', 'visual studio code', 'vscode', 'editor', 'code'],
  },
  {
    query: 'Open Windows Terminal',
    intent: 'open',
    badge: 'App',
    iconName: 'terminal',
    semanticKeywords: ['open', 'windows terminal', 'terminal', 'powershell', 'cmd'],
  },
  {
    query: 'Open Google Chrome',
    intent: 'open',
    badge: 'Browser',
    iconName: 'globe',
    semanticKeywords: ['open', 'google chrome', 'chrome', 'browser', 'web'],
  },
  {
    query: 'Open Documents folder',
    intent: 'open',
    badge: 'Folder',
    iconName: 'folder',
    semanticKeywords: ['open', 'documents', 'folder', 'files'],
  },

  // ── Document & Report Creation ──
  {
    query: 'Create a presentation from this report',
    intent: 'create',
    badge: 'Slides',
    iconName: 'sparkles',
    appContexts: ['word', 'browser'],
    semanticKeywords: ['create', 'presentation', 'ppt', 'slides', 'report', 'deck', 'powerpoint'],
  },
  {
    query: 'Create an Excel report from this data',
    intent: 'create',
    badge: 'Excel',
    iconName: 'file',
    appContexts: ['excel'],
    semanticKeywords: ['create', 'excel', 'report', 'data', 'spreadsheet', 'sheet', 'table', 'csv'],
  },
  {
    query: 'Create a Word document from summary',
    intent: 'create',
    badge: 'Document',
    iconName: 'file',
    appContexts: ['word'],
    semanticKeywords: ['create', 'word', 'document', 'summary', 'doc', 'docx'],
  },
  {
    query: 'Create a research report on AI agents',
    intent: 'create',
    badge: 'Research',
    iconName: 'sparkles',
    semanticKeywords: ['create', 'research', 'report', 'ai agents', 'investigation', 'overview'],
  },
  {
    query: 'Create a summary of this document',
    intent: 'create',
    badge: 'Summary',
    iconName: 'sparkles',
    appContexts: ['word', 'browser'],
    semanticKeywords: ['create', 'summary', 'document', 'summarize', 'notes', 'tldr'],
  },

  // ── Intent-Aware "Make" Patterns ──
  {
    query: 'Make a presentation from this report',
    intent: 'create',
    badge: 'Slides',
    iconName: 'sparkles',
    appContexts: ['word', 'browser'],
    semanticKeywords: ['make', 'presentation', 'ppt', 'slides', 'report', 'deck'],
  },
  {
    query: 'Make a summary of this document',
    intent: 'create',
    badge: 'Summary',
    iconName: 'sparkles',
    appContexts: ['word', 'browser'],
    semanticKeywords: ['make', 'summary', 'document', 'summarize', 'key points'],
  },
  {
    query: 'Make an Excel report from this data',
    intent: 'create',
    badge: 'Excel',
    iconName: 'file',
    appContexts: ['excel'],
    semanticKeywords: ['make', 'excel', 'report', 'data', 'sheet', 'spreadsheet'],
  },
  {
    query: 'Make a quick note of this discussion',
    intent: 'create',
    badge: 'Notes',
    iconName: 'file',
    semanticKeywords: ['make', 'quick note', 'notes', 'discussion', 'memo'],
  },

  // ── Analysis & Computation ──
  {
    query: 'Analyze data in active Excel sheet',
    intent: 'analyze',
    badge: 'Analysis',
    iconName: 'sparkles',
    appContexts: ['excel'],
    semanticKeywords: ['analyze', 'data', 'excel', 'sheet', 'chart', 'trends', 'metrics'],
  },
  {
    query: 'Summarize key insights from active document',
    intent: 'analyze',
    badge: 'Summary',
    iconName: 'sparkles',
    appContexts: ['word'],
    semanticKeywords: ['summarize', 'insights', 'document', 'word', 'report', 'key takeaways'],
  },

  // ── Communication ──
  {
    query: 'Send an email to John with project status',
    intent: 'communication',
    badge: 'Email',
    iconName: 'mail',
    semanticKeywords: ['send', 'email', 'john', 'project status', 'update', 'mail'],
  },
  {
    query: 'Send an email to my team with updates',
    intent: 'communication',
    badge: 'Email',
    iconName: 'mail',
    semanticKeywords: ['send', 'email', 'team', 'updates', 'mail', 'status'],
  },
  {
    query: 'Draft a follow-up email for the meeting',
    intent: 'communication',
    badge: 'Email',
    iconName: 'mail',
    semanticKeywords: ['draft', 'follow-up', 'email', 'meeting', 'mail', 'compose'],
  },

  // ── Web & Research ──
  {
    query: 'Research latest trends in AI agents',
    intent: 'search',
    badge: 'Research',
    iconName: 'globe',
    semanticKeywords: ['research', 'latest trends', 'ai agents', 'search', 'overview'],
  },
  {
    query: 'Search documentation for NEXUS API',
    intent: 'search',
    badge: 'Docs',
    iconName: 'globe',
    semanticKeywords: ['search', 'documentation', 'nexus api', 'docs', 'reference'],
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Local Personalization Storage
// ─────────────────────────────────────────────────────────────────────────────

const STORAGE_PREFIX = 'nexus_personalized_patterns_';

export function getLearnedPatterns(userId?: string): UserLearnedPattern[] {
  try {
    const key = `${STORAGE_PREFIX}${userId || 'default'}`;
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveLearnedPatterns(patterns: UserLearnedPattern[], userId?: string): void {
  try {
    const key = `${STORAGE_PREFIX}${userId || 'default'}`;
    localStorage.setItem(key, JSON.stringify(patterns.slice(0, 150)));
  } catch {}
}

/**
 * Record feedback from a task execution to strengthen or weaken predictive signals.
 * Successful completions receive positive weight; failed or cancelled queries are deprioritized.
 */
export function recordPredictionFeedback(
  query: string,
  status: 'completed' | 'failed' | 'cancelled',
  userId?: string,
  context?: { application?: string; targetType?: string }
): void {
  const clean = query.trim();
  if (!clean || clean.length < 3) return;

  // Input-side safety check: Classify query for NSFW/sensitive content
  const safety = classifyQuerySafety(clean);
  // If classified as sensitive / NSFW, NEVER record as a recommendation personalization signal!
  if (!safety.recommendation_eligible) {
    return;
  }

  const patterns = getLearnedPatterns(userId);
  const normalized = clean.toLowerCase();

  const existingIdx = patterns.findIndex((p) => p.query.toLowerCase() === normalized);

  if (existingIdx >= 0) {
    const item = { ...patterns[existingIdx] };
    if (status === 'completed') {
      item.successCount += 1;
      item.lastUsed = Date.now();
      if (context?.application) item.contextApp = context.application;
      item.is_sensitive = false;
      item.recommendation_eligible = true;
    } else {
      item.failureCount += 1;
    }
    patterns[existingIdx] = item;
  } else {
    patterns.unshift({
      query: clean,
      intent: detectIntent(clean),
      successCount: status === 'completed' ? 1 : 0,
      failureCount: status === 'completed' ? 0 : 1,
      lastUsed: Date.now(),
      contextApp: context?.application,
      is_sensitive: false,
      sensitivity_category: null,
      recommendation_eligible: true,
      classified_at: safety.classified_at,
    });
  }

  saveLearnedPatterns(patterns, userId);
}

// ─────────────────────────────────────────────────────────────────────────────
// Intent Detection Helper
// ─────────────────────────────────────────────────────────────────────────────

function detectIntent(text: string): PredictionItem['intent'] {
  const lower = text.toLowerCase();
  for (const [intent, aliases] of Object.entries(INTENT_ALIASES)) {
    for (const alias of aliases) {
      if (lower.includes(alias)) {
        if (intent === 'schedule') return 'schedule';
        if (intent === 'open') return 'open';
        if (intent === 'create' || intent === 'presentation' || intent === 'excel' || intent === 'document') return 'create';
        if (intent === 'email') return 'communication';
        if (intent === 'research') return 'search';
        if (intent === 'code') return 'code';
      }
    }
  }
  return 'general';
}

function resolveIconForIntent(intent: PredictionItem['intent'], text: string): PredictionItem['iconName'] {
  const lower = text.toLowerCase();
  if (intent === 'schedule' || lower.includes('calendar') || lower.includes('remind') || lower.includes('alarm')) {
    return lower.includes('remind') ? 'clock' : 'calendar';
  }
  if (intent === 'communication' || lower.includes('email') || lower.includes('mail')) {
    return 'mail';
  }
  if (lower.includes('folder') || lower.includes('downloads') || lower.includes('project') || lower.includes('workspace')) {
    return 'folder';
  }
  if (lower.includes('terminal') || lower.includes('powershell') || lower.includes('code')) {
    return 'terminal';
  }
  if (lower.includes('excel') || lower.includes('word') || lower.includes('sheet') || lower.includes('file')) {
    return 'file';
  }
  if (intent === 'search' || lower.includes('chrome') || lower.includes('browser') || lower.includes('web')) {
    return 'globe';
  }
  return 'sparkles';
}

function resolveBadgeForIntent(intent: PredictionItem['intent'], text: string): string {
  const lower = text.toLowerCase();
  if (lower.includes('birthday')) return 'Birthday';
  if (lower.includes('meeting')) return 'Meeting';
  if (lower.includes('remind')) return 'Reminder';
  if (lower.includes('excel') || lower.includes('sheet') || lower.includes('spreadsheet')) return 'Excel';
  if (lower.includes('presentation') || lower.includes('slides') || lower.includes('ppt')) return 'Slides';
  if (lower.includes('word') || lower.includes('doc')) return 'Document';
  if (lower.includes('downloads')) return 'Folder';
  if (lower.includes('nexus')) return 'NEXUS';
  if (lower.includes('email') || lower.includes('mail')) return 'Email';
  if (lower.includes('research')) return 'Research';
  if (intent === 'schedule') return 'Schedule';
  if (intent === 'open') return 'Open';
  if (intent === 'create') return 'Create';
  if (intent === 'analyze') return 'Analyze';
  return 'Predict';
}

// ─────────────────────────────────────────────────────────────────────────────
// Multi-Signal Prediction Ranker
// ─────────────────────────────────────────────────────────────────────────────

interface Candidate {
  query: string;
  intent: PredictionItem['intent'];
  badge: string;
  iconName: PredictionItem['iconName'];
  isFromLearned?: boolean;
  successCount?: number;
  failureCount?: number;
  lastUsed?: number;
  semanticKeywords?: string[];
  appContexts?: string[];
}

export function getPersonalizedPredictions(
  typedQuery: string,
  context: PredictionContext = {}
): PredictionItem[] {
  const raw = typedQuery.trim();
  if (!raw || raw.length < 1) return [];

  const q = raw.toLowerCase();
  const qTokens = q.split(/\s+/).filter(Boolean);

  // 1. Ingest Learned Patterns from localStorage
  const learned = getLearnedPatterns(context.userId);

  // 2. Ingest Historical Tasks (only completed ones, never failed, and strictly safe)
  const historyCompleted: { query: string; timestamp: number }[] = [];
  if (context.historyItems && Array.isArray(context.historyItems)) {
    for (const h of context.historyItems) {
      if (h.prompt && h.status === 'completed') {
        const cleanPrompt = h.prompt.trim();
        if (cleanPrompt.length >= 4 && !cleanPrompt.startsWith('/')) {
          // If already marked as sensitive or ineligible, skip
          if (h.recommendation_eligible === false || h.is_sensitive === true) {
            continue;
          }

          // Protect against historical records created before the filter was introduced
          const safety = classifyQuerySafety(cleanPrompt);
          if (!safety.recommendation_eligible) {
            h.is_sensitive = true;
            h.sensitivity_category = safety.sensitivity_category;
            h.recommendation_eligible = false;
            h.classified_at = safety.classified_at;
            continue; // Exclude from recommendation pool!
          }

          historyCompleted.push({ query: cleanPrompt, timestamp: h.timestamp });
        }
      }
    }
  }

  // 3. Assemble Candidates Pool
  const candidatesMap = new Map<string, Candidate>();

  // Add seed templates (double-checked for safety)
  for (const t of SEED_PREDICTION_TEMPLATES) {
    const safety = classifyQuerySafety(t.query);
    if (!safety.recommendation_eligible) continue;

    candidatesMap.set(t.query.toLowerCase(), {
      query: t.query,
      intent: t.intent,
      badge: t.badge,
      iconName: t.iconName,
      semanticKeywords: t.semanticKeywords,
      appContexts: t.appContexts,
    });
  }

  // Add learned user patterns (strictly filtered)
  for (const lp of learned) {
    // Exclude sensitive or ineligible patterns
    if (lp.recommendation_eligible === false || lp.is_sensitive === true) continue;
    const safety = classifyQuerySafety(lp.query);
    if (!safety.recommendation_eligible) continue;

    // Drop patterns with high failure ratio
    if (lp.failureCount > 0 && lp.failureCount >= lp.successCount * 2) continue;

    const lower = lp.query.toLowerCase();
    const existing = candidatesMap.get(lower);
    if (existing) {
      existing.isFromLearned = true;
      existing.successCount = lp.successCount;
      existing.failureCount = lp.failureCount;
      existing.lastUsed = lp.lastUsed;
    } else {
      candidatesMap.set(lower, {
        query: lp.query,
        intent: lp.intent as PredictionItem['intent'],
        badge: resolveBadgeForIntent(lp.intent as PredictionItem['intent'], lp.query),
        iconName: resolveIconForIntent(lp.intent as PredictionItem['intent'], lp.query),
        isFromLearned: true,
        successCount: lp.successCount,
        failureCount: lp.failureCount,
        lastUsed: lp.lastUsed,
      });
    }
  }

  // Add history completed
  for (const h of historyCompleted) {
    const lower = h.query.toLowerCase();
    const existing = candidatesMap.get(lower);
    if (existing) {
      existing.lastUsed = Math.max(existing.lastUsed || 0, h.timestamp);
      existing.successCount = (existing.successCount || 0) + 1;
    } else {
      const intent = detectIntent(h.query);
      candidatesMap.set(lower, {
        query: h.query,
        intent,
        badge: resolveBadgeForIntent(intent, h.query),
        iconName: resolveIconForIntent(intent, h.query),
        isFromLearned: true,
        successCount: 1,
        lastUsed: h.timestamp,
      });
    }
  }

  // Dynamically inject active target predictions if relevant
  if (context.activeTarget?.target_type) {
    const targetType = context.activeTarget.target_type.toLowerCase();
    const targetTitle = context.activeTarget.window_title || '';

    if (targetType === 'excel' || targetTitle.toLowerCase().endsWith('.xlsx') || targetTitle.toLowerCase().endsWith('.csv')) {
      const excelCandidate = 'Create an Excel report from this data';
      if (!candidatesMap.has(excelCandidate.toLowerCase())) {
        candidatesMap.set(excelCandidate.toLowerCase(), {
          query: excelCandidate,
          intent: 'create',
          badge: 'Excel',
          iconName: 'file',
          appContexts: ['excel'],
        });
      }
    } else if (targetType === 'word' || targetTitle.toLowerCase().endsWith('.docx')) {
      const docCandidate = 'Create a Word document from summary';
      if (!candidatesMap.has(docCandidate.toLowerCase())) {
        candidatesMap.set(docCandidate.toLowerCase(), {
          query: docCandidate,
          intent: 'create',
          badge: 'Document',
          iconName: 'file',
          appContexts: ['word'],
        });
      }
    }
  }

  // 4. Multi-Signal Scoring Engine
  const scoredItems: PredictionItem[] = [];

  for (const candidate of candidatesMap.values()) {
    const cLower = candidate.query.toLowerCase();
    let score = 0;

    // A. Query Similarity: Exact Prefix Match
    if (cLower.startsWith(q)) {
      score += 100;
      // Bonus for how close in length
      score += Math.min(25, (q.length / cLower.length) * 25);
    } else if (cLower.includes(` ${q}`)) {
      // Substring word-boundary match
      score += 70;
    } else if (cLower.includes(q)) {
      // Plain substring match
      score += 45;
    }

    // B. Token Overlap Score
    let tokenHits = 0;
    for (const token of qTokens) {
      if (cLower.includes(token)) {
        tokenHits += 1;
      }
    }
    if (tokenHits > 0) {
      score += (tokenHits / qTokens.length) * 40;
    }

    // C. Semantic Synonym & Intent Match
    let semanticBonus = 0;
    for (const [intentKey, aliases] of Object.entries(INTENT_ALIASES)) {
      const qHasAlias = aliases.some((a) => qTokens.includes(a) || q.startsWith(a));
      if (qHasAlias) {
        // Does this candidate match this semantic intent?
        const cMatchesIntent =
          candidate.intent === intentKey ||
          aliases.some((a) => cLower.includes(a)) ||
          candidate.semanticKeywords?.some((k) => aliases.includes(k));

        if (cMatchesIntent) {
          semanticBonus += 45;
          break;
        }
      }
    }
    score += semanticBonus;

    // D. User Personalization Signal (Frequency & Recency)
    if (candidate.successCount && candidate.successCount > 0) {
      // Frequency boost: +15 pts per successful execution (up to +45)
      score += Math.min(45, candidate.successCount * 15);

      // Recency boost (exponential decay within 14 days)
      if (candidate.lastUsed) {
        const daysDiff = (Date.now() - candidate.lastUsed) / (1000 * 60 * 60 * 24);
        if (daysDiff < 1) {
          score += 30; // Used today
        } else if (daysDiff < 7) {
          score += 20; // Used this week
        } else if (daysDiff < 14) {
          score += 10;
        }
      }
    }

    // Penalty for failure history
    if (candidate.failureCount && candidate.failureCount > 0) {
      score -= Math.min(40, candidate.failureCount * 20);
    }

    // E. Current Context Relevance (Active Target / Application)
    if (context.activeTarget?.target_type) {
      const activeType = context.activeTarget.target_type.toLowerCase();
      if (candidate.appContexts?.includes(activeType)) {
        score += 35;
      }
    }

    // F. Low Confidence Threshold
    // If the score is below threshold (e.g., completely unrelated string like "xyzqwe"), filter out!
    if (score < 40) {
      continue;
    }

    scoredItems.push({
      id: `pred-${candidate.query.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
      query: candidate.query,
      intent: candidate.intent,
      category: 'prediction',
      badge: candidate.badge,
      score: Math.round(score),
      iconName: candidate.iconName,
    });
  }

  // 5. Deduplicate and Rank
  // Sort descending by score
  scoredItems.sort((a, b) => b.score - a.score);

  // Filter near-duplicates (e.g. "Schedule an email for tomorrow" vs "Schedule an email tomorrow")
  const uniqueItems: PredictionItem[] = [];
  const seenNorm = new Set<string>();

  for (const item of scoredItems) {
    // Output-side safety check: Double-sided protection ensures no sensitive recommendation is ever returned
    const safety = classifyQuerySafety(item.query);
    if (!safety.recommendation_eligible) {
      continue;
    }

    const norm = item.query.toLowerCase().replace(/[^a-z0-9]/g, '');
    if (!seenNorm.has(norm)) {
      seenNorm.add(norm);
      uniqueItems.push(item);
    }
    // Limit to top 6 predictions (between 5 and 7, compact and high-confidence)
    if (uniqueItems.length >= 6) break;
  }

  return uniqueItems;
}
