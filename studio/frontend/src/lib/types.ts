/**
 * Mark II Studio — TypeScript Types
 */

export interface Session {
  id: string;
  intake_mode: 'prompt' | 'github' | 'zip' | 'paste';
  profile_type: string | null;
  build_mode?: 'fast' | 'balanced' | 'max_quality';
  planned_builders?: string[];
  architecture_json?: Record<string, unknown>;
  preview_mode?: 'iframe' | 'api_playground' | 'none' | null;
  status: SessionStatus;
  github_repo_url: string | null;
  original_prompt: string | null;
  created_at: string;
  updated_at: string;
}

export type SessionStatus =
  | 'created'
  | 'interviewing'
  | 'spec_review'
  | 'building'
  | 'judging'
  | 'hardening'
  | 'complete'
  | 'failed';

export interface RequirementSpec {
  id: string;
  version: number;
  confirmed: boolean;
  summary: string;
  requirements_json: Record<string, unknown>;
  detected_framework: string | null;
  detected_profile: string | null;
  created_at: string;
}

export interface BuildCandidate {
  id: string;
  provider: string;
  model: string;
  status: string;
  score: number | null;
  build_duration_ms?: number | null;
  is_baseline: boolean;
  preview_url: string | null;
  build_log: string;
  module_scope_json?: Record<string, unknown>;
  review_notes_json?: Array<Record<string, unknown>>;
  candidate_format: string;
  patch_summary: string | null;
  created_at: string;
}

export interface ChangeRequest {
  id: string;
  user_comment: string;
  classification: string;
  structured_instruction: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface JudgeDecision {
  id: string;
  winning_candidate_id: string | null;
  reasoning: string;
  scores_json: Record<string, unknown>;
  criteria_json: string[];
  created_at: string;
}

export interface MarkRun {
  id: string;
  mark_number: number;
  mark_name: string;
  passed: boolean;
  result_type?: 'passed' | 'breach' | 'inconclusive';
  failure_type: string | null;
  rejection_reason?: string | null;
  swarm_report_json: Record<string, unknown>;
  patch_summary: string | null;
  repair_provider: string | null;
  score: number | null;
  created_at: string;
}

export interface InterviewMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  spec_ready?: boolean;
}

export interface SSEEvent {
  event_type: string;
  session_id: string;
  timestamp: string;
  data: Record<string, unknown>;
}
