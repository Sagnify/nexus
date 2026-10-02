/**
 * NEXUS Safety & NSFW Sensitivity Filter
 *
 * Provides high-speed, privacy-first classification for search queries.
 * Prevents NSFW, pornographic, or sexually explicit content from leaking into:
 * - Query Autocomplete & Predictions
 * - Personalized Suggestions
 * - Frequently-used Query Patterns & Learned Vectors
 *
 * Implements double-sided protection (Input-side signal exclusion + Output-side filtering)
 * while preserving innocent technical, scientific, and culinary contexts.
 */

export interface SafetyClassificationResult {
  is_sensitive: boolean;
  sensitivity_category: 'nsfw' | 'sexual_intent' | 'explicit_terms' | 'suggestive' | null;
  recommendation_eligible: boolean;
  confidence: number;
  classified_at: number;
  reason?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Normalization & De-obfuscation
// ─────────────────────────────────────────────────────────────────────────────

function normalizeForSafety(query: string): string {
  let text = query.toLowerCase().trim();

  // Handle single-character spaced/dotted sequences before leetspeak:
  // e.g. "p.o.r.n" -> "porn", "p_o_r_n" -> "porn"
  text = text.replace(/\b([a-z](?:[._\-][a-z])+)\b/gi, (match) => match.replace(/[._\-]/g, ''));
  // e.g. "p o r n" (at least 3 single letters spaced) -> "porn"
  text = text.replace(/\b([a-z](?:\s+[a-z]){2,})\b/gi, (match) => match.replace(/\s+/g, ''));

  // Common leetspeak substitutions
  text = text
    .replace(/[@4]/g, 'a')
    .replace(/[3]/g, 'e')
    .replace(/[1!|]/g, 'i')
    .replace(/[0]/g, 'o')
    .replace(/[$5]/g, 's')
    .replace(/[+]/g, 't')
    .replace(/[*#]/g, '');

  // Collapse multiple whitespaces
  return text.replace(/\s+/g, ' ');
}

// ─────────────────────────────────────────────────────────────────────────────
// Explicit Patterns & Regexes
// ─────────────────────────────────────────────────────────────────────────────

// Explicit sexual keywords that unconditionally trigger NSFW classification
const STRICT_EXPLICIT_TERMS = new Set([
  'porn', 'porno', 'pornography', 'pornstar', 'xxx', 'hentai', 'erotica',
  'blowjob', 'handjob', 'cumshot', 'deepthroat', 'threesome', 'gangbang',
  'cunnilingus', 'fellatio', 'masturbat', 'masturbation', 'orgasm',
  'dildo', 'vibrator', 'fleshlight', 'sex toy', 'sex toys', 'onlyfans leak',
  'onlyfans leaks', 'camgirl', 'camgirls', 'stripper', 'strippers', 'strip club',
  'stripclub', 'milf', 'bdsm', 'bondage', 'creampie', 'hardcore porn',
  'softcore porn', 'rule34', 'r34', 'nsfw', 'smut', 'lewd', 'deepfake nude',
  'undress ai', 'strip ai', 'boobs', 'tits', 'titties', 'pussy', 'vagina',
  'penis', 'cock', 'dick pic', 'dick pics', 'nude pics', 'send nudes',
  'escort service', 'escort services', 'hooker', 'prostitute', 'brothel',
  'cybersex', 'sexting', 'sext',
]);

// Regular expressions for compound phrases and intent
const EXPLICIT_PHRASE_PATTERNS: RegExp[] = [
  /\b(?:watch|free|download|stream)\s+(?:porn|xxx|sex|hentai|erotica)\b/i,
  /\b(?:nude|naked)\s+(?:pics|pictures|photos|video|videos|leak|leaks|girls|women|men|celebrity|celebrities)\b/i,
  /\b(?:sex|sexual)\s+(?:video|videos|tape|tapes|movie|movies|chat|clips|positions?|acts?)\b/i,
  /\b(?:how\s+to\s+have|wanna\s+have|want\s+to\s+have)\s+sex\b/i,
  /\b(?:hot\s+girls?|sexy\s+girls?|hot\s+women)\s+(?:strip|naked|undress|nude)\b/i,
  /\b(?:dirty\s+talk|erotic\s+roleplay|erotic\s+novel|smut\s+fanfic|adult\s+game|sex\s+game)\b/i,
  /\b(?:undress|strip)\s+(?:photo|photos|picture|pictures|app|filter)\b/i,
  /\b(?:anal|oral|group)\s+sex\b/i,
  /\brule\s*(?:34|3a)\b/i,
  /\br(?:34|3a)\b/i,
];

// ─────────────────────────────────────────────────────────────────────────────
// False Positive Exceptions (Benign Technical / Scientific Contexts)
// ─────────────────────────────────────────────────────────────────────────────

interface BenignContextRule {
  triggerWord: RegExp;
  benignContexts: RegExp;
}

const BENIGN_CONTEXT_RULES: BenignContextRule[] = [
  {
    // 'strip' in programming, comics, or physical items
    triggerWord: /\bstrip(?:ping|ped|s)?\b/i,
    benignContexts: /\b(?:string|whitespace|split|code|python|pandas|dataframe|trim|regex|comic|cartoon|vegas\s+strip|gaza\s+strip|strip\s+plot|bacon|test\s+strip|power\s+strip|weather\s+strip|copper\s+strip|metal\s+strip)\b/i,
  },
  {
    // 'penetration' in cybersecurity & business
    triggerWord: /\bpenetrat(?:ion|ing|e)\b/i,
    benignContexts: /\b(?:test|testing|tester|security|cyber|network|vulnerability|kali|audit|market|pricing|depth|radar|shield)\b/i,
  },
  {
    // 'adult' in education, demographics, medicine
    triggerWord: /\badult(?:s)?\b/i,
    benignContexts: /\b(?:learning|education|literacy|supervision|demographic|novel|ya|young\s+adult|pediatric|medicine|care|patient|immunization|dose|ticket)\b/i,
  },
  {
    // 'sex' in biology, demographics, genetics
    triggerWord: /\bsex(?:ual)?\b/i,
    benignContexts: /\b(?:chromosome|chromosomes|ratio|biology|biological|determination|dimorphism|gender|demographics|survey|census|disaggregated|offender\s+registry)\b/i,
  },
  {
    // 'nude' in cosmetics, fashion, palette, art history
    triggerWord: /\bnude(?:s)?\b/i,
    benignContexts: /\b(?:lipstick|makeup|nail\s+polish|shoes|heels|dress|color|palette|shades?|art\s+history|renaissance|statue|painting|sculpture)\b/i,
  },
  {
    // 'hot' in weather, physics, food, technology
    triggerWord: /\bhot\b/i,
    benignContexts: /\b(?:reload|reloading|fix|fixes|chocolate|coffee|dog|dogs|sauce|water|springs?|weather|temperature|topic|key|keys|spot|potato)\b/i,
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// High-Speed In-Memory Classification Cache
// ─────────────────────────────────────────────────────────────────────────────

const MAX_CACHE_SIZE = 1000;
const classificationCache = new Map<string, SafetyClassificationResult>();

/**
 * Classifies a query for NSFW or sexually explicit sensitivity.
 * Returns recommendation eligibility and detailed classification metadata.
 */
export function classifyQuerySafety(rawQuery: string): SafetyClassificationResult {
  const query = rawQuery.trim();
  if (!query) {
    return {
      is_sensitive: false,
      sensitivity_category: null,
      recommendation_eligible: true,
      confidence: 1.0,
      classified_at: Date.now(),
    };
  }

  // Check LRU cache
  const cached = classificationCache.get(query);
  if (cached) {
    return cached;
  }

  // Pre-check for numeric explicit phrases (like rule 34 / r34) before leetspeak transformations
  if (/\b(?:rule\s*34|r34)\b/i.test(query)) {
    const result: SafetyClassificationResult = {
      is_sensitive: true,
      sensitivity_category: 'sexual_intent',
      recommendation_eligible: false,
      confidence: 0.98,
      classified_at: Date.now(),
      reason: 'explicit_phrase_match: rule 34',
    };
    cacheResult(query, result);
    return result;
  }

  const normalized = normalizeForSafety(query);
  const words = normalized.split(/\s+/);

  // Step 1: Check for Benign Context Overrides first (to prevent false positives)
  let hasBenignContextOverride = false;
  for (const rule of BENIGN_CONTEXT_RULES) {
    if (rule.triggerWord.test(normalized)) {
      if (rule.benignContexts.test(normalized)) {
        // Ensure no explicit sexual modifiers are also present
        const hasExplicitModifier = Array.from(STRICT_EXPLICIT_TERMS).some((term) =>
          words.includes(term) || (term.includes(' ') && normalized.includes(term))
        );
        if (!hasExplicitModifier) {
          hasBenignContextOverride = true;
          break;
        }
      }
    }
  }

  if (hasBenignContextOverride) {
    const result: SafetyClassificationResult = {
      is_sensitive: false,
      sensitivity_category: null,
      recommendation_eligible: true,
      confidence: 0.95,
      classified_at: Date.now(),
      reason: 'benign_context_override',
    };
    cacheResult(query, result);
    return result;
  }

  // Step 2: Check strict explicit words
  for (const term of STRICT_EXPLICIT_TERMS) {
    if (term.includes(' ')) {
      if (normalized.includes(term)) {
        const result: SafetyClassificationResult = {
          is_sensitive: true,
          sensitivity_category: 'explicit_terms',
          recommendation_eligible: false,
          confidence: 0.98,
          classified_at: Date.now(),
          reason: `explicit_term_match: ${term}`,
        };
        cacheResult(query, result);
        return result;
      }
    } else {
      if (words.includes(term)) {
        const result: SafetyClassificationResult = {
          is_sensitive: true,
          sensitivity_category: 'explicit_terms',
          recommendation_eligible: false,
          confidence: 0.98,
          classified_at: Date.now(),
          reason: `explicit_word_match: ${term}`,
        };
        cacheResult(query, result);
        return result;
      }
    }
  }

  // Step 3: Check regex patterns for compound sexual intent
  for (const pattern of EXPLICIT_PHRASE_PATTERNS) {
    if (pattern.test(normalized)) {
      const result: SafetyClassificationResult = {
        is_sensitive: true,
        sensitivity_category: 'sexual_intent',
        recommendation_eligible: false,
        confidence: 0.95,
        classified_at: Date.now(),
        reason: 'sexual_phrase_intent_detected',
      };
      cacheResult(query, result);
      return result;
    }
  }

  // Step 4: Check for suggestive combinations (e.g. "naked" + person / name)
  if (/\b(?:naked|nude|undressed)\b/i.test(normalized)) {
    // If not caught by benign context, treat bare naked/nude as sensitive for recommendations
    const result: SafetyClassificationResult = {
      is_sensitive: true,
      sensitivity_category: 'suggestive',
      recommendation_eligible: false,
      confidence: 0.85,
      classified_at: Date.now(),
      reason: 'suggestive_unqualified_nudity',
    };
    cacheResult(query, result);
    return result;
  }

  // Safe Query
  const result: SafetyClassificationResult = {
    is_sensitive: false,
    sensitivity_category: null,
    recommendation_eligible: true,
    confidence: 0.99,
    classified_at: Date.now(),
  };
  cacheResult(query, result);
  return result;
}

function cacheResult(key: string, result: SafetyClassificationResult): void {
  if (classificationCache.size >= MAX_CACHE_SIZE) {
    const firstKey = classificationCache.keys().next().value;
    if (firstKey) classificationCache.delete(firstKey);
  }
  classificationCache.set(key, result);
}

/**
 * Filter an array of items to ensure only recommendation-eligible queries pass through.
 */
export function filterSafeSuggestions<T extends { query?: string; title?: string }>(items: T[]): T[] {
  return items.filter((item) => {
    const text = item.query || item.title || '';
    if (!text) return false;
    const safety = classifyQuerySafety(text);
    return safety.recommendation_eligible;
  });
}
