// Mirrors backend Pydantic schemas in src/aidetect/schemas/detection.py.
// Keep in sync when the API contract evolves.

export type Verdict = 'human' | 'likely_human' | 'uncertain' | 'likely_ai' | 'ai';
export type Severity = 'low' | 'medium' | 'high';
export type Mode = 'fast' | 'balanced' | 'thorough';
export type ChunkStrategy = 'none' | 'sentence' | 'paragraph' | 'auto';

export interface PatternMatch {
  category: string;
  name: string;
  span: [number, number];
  severity: Severity;
  suggestion: string | null;
}

export interface BurstinessContrib {
  sd: number | null;
  sentence_count: number;
  human_score?: number;
  flag?: string;
}

export interface TtrContrib {
  ttr: number | null;
  unique_words?: number;
  total_words?: number;
  in_range?: boolean;
  human_score?: number;
  flag?: string;
}

export interface SentenceCvContrib {
  cv: number | null;
  sd?: number;
  mean?: number;
  human_score?: number;
  flag?: string;
}

export interface FormattingContrib {
  bold_md_count: number;
  emoji_count: number;
  emdash_count: number;
  has_unicode_bold: boolean;
  hashtag_count: number;
  violations: number;
  flags: string[];
  human_score: number;
}

export interface StatisticalSignal {
  score: number;
  contributors: {
    human_score?: number;
    burstiness?: BurstinessContrib;
    ttr?: TtrContrib;
    sentence_cv?: SentenceCvContrib;
    formatting?: FormattingContrib;
    flag?: string;
  };
}

export interface PatternsSignal {
  score: number;
  matches: PatternMatch[];
}

export interface SentenceScore {
  index: number;
  text: string;
  score: number;
  reason: string | null;
}

export interface SentenceAggregate {
  count: number;
  mean: number;
  max: number;
  fraction_ai_like: number;
}

export interface LLMUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface LLMJudgeSignal {
  score: number;
  model: string;
  summary: string | null;
  error?: string | null;
  sentence_scores?: SentenceScore[] | null;
  sentence_aggregate?: SentenceAggregate | null;
  usage?: LLMUsage | null;
}

export interface Signals {
  statistical?: StatisticalSignal;
  patterns?: PatternsSignal;
  llm_judge?: LLMJudgeSignal;
}

export interface RubricDimensionScore {
  score: number;
  evidence: string | null;
}

export interface EvidenceSpan {
  start: number;
  end: number;
  type: string;
  severity: Severity;
  reason: string;
}

export interface Evidence {
  spans: EvidenceSpan[];
  annotated_html?: string | null;
  annotated_markdown?: string | null;
}

export interface DetectionResultBlock {
  ai_probability: number;
  human_probability: number;
  verdict: Verdict;
  confidence: number;
  severity: Severity;
}

export interface RequestDetails {
  text_hash: string;
  length_chars: number;
  length_tokens?: number | null;
  language_detected?: string | null;
}

export interface ResponseMetadata {
  model_version: string;
  rubric_version: string;
  mode: Mode;
  duration_ms: number;
  cached: boolean;
  cost_credits: number;
}

export interface DetectionResult {
  id: string;
  object: 'detection';
  created_at: string;
  result: DetectionResultBlock;
  signals?: Signals;
  rubric_scores?: Record<string, RubricDimensionScore>;
  evidence?: Evidence;
  request: RequestDetails;
  metadata: ResponseMetadata;
}

export interface DetectionOptions {
  include_evidence?: boolean;
  include_signals?: boolean;
  include_rubric_scores?: boolean;
  chunk_strategy?: ChunkStrategy;
}

export interface DetectionContext {
  platform?: string;
  expected_register?: string;
}

export interface DetectionRequest {
  text: string;
  language?: string;
  mode?: Mode;
  options?: DetectionOptions;
  context?: DetectionContext;
  rubric_version?: string;
  model_version?: string;
}
