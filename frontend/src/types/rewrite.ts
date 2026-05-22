// Mirrors backend schemas in src/aidetect/schemas/rewrite.py.

import type { DetectionResultBlock, Mode, Severity } from 'src/types/detection';

export type VoicePreset =
  | 'casual_tech_blog'
  | 'personal_essay'
  | 'business_minus_buzzwords'
  | 'linkedin_human';

export interface RewriteOptions {
  voice?: VoicePreset | null;
  preserve?: string[];
  max_iterations?: number;
  target_ai_probability?: number;
}

export interface RewriteRequest {
  text: string;
  language?: string;
  mode?: Mode;
  options?: RewriteOptions;
  custom_voice_instructions?: string | null;
}

export interface IterationDiagnostic {
  index: number;
  ai_probability: number;
  verdict: string;
  summary: string | null;
}

export interface RewriteUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface RewriteResponse {
  id: string;
  object: 'rewrite';
  created_at: string;
  rewritten_text: string;
  changes: string[];
  preserved_note: string | null;
  before: DetectionResultBlock;
  after: DetectionResultBlock;
  iterations: IterationDiagnostic[];
  target_reached: boolean;
  voice: VoicePreset | null;
  model: string;
  duration_ms: number;
  usage: RewriteUsage;
  severity: Severity;
}
