export type Citation = { chunk_id: string; quoted_span: string };

export type Verdict = {
  chunk_id: string;
  quoted_span: string;
  valid: boolean;
  reason: "ok" | "unknown_chunk" | "span_not_found";
};

export type Source = {
  chunk_id: string;
  doc_id: string;
  header: string;
  page_start: number;
  page_end: number;
  score: number;
};

export type TraceEvent = {
  trace_id: string;
  refused: boolean;
  chunks_retrieved: number;
  filters: Record<string, unknown>;
  timings: Record<string, number>;
  total_ms: number;
  usage: { prompt_tokens: number; completion_tokens: number };
  estimated_cost_usd: number;
  sources: Source[];
};

export type ValidationEvent = {
  verdicts: Verdict[];
  validity: number;
  failures: number;
};

export type RunSummary = {
  id: string;
  config_id: string;
  trigger: string;
  status: string;
  started_at: string;
  question_set?: string;
  judge_model?: string;
  question_count?: number;
  doc_ids?: string[];
  question_types?: Record<string, number>;
  metrics: Record<string, number>;
};

export type RunQuestionMetric = {
  metric_name: string;
  value: number | null;
  reason?: string;
  judge_tokens?: number;
};

export type RunQuestionDetail = {
  question_id: string;
  question: string;
  q_type: string;
  answerable: boolean;
  gold_answer: string;
  gold_chunk_ids: string[];
  trace_id: string;
  metrics: RunQuestionMetric[];
};

export type RunSummaryDetailed = {
  run_id: string;
  config_id: string;
  trigger: string;
  status: string;
  judge_model: string;
  n_questions: number;
  overall: Record<string, number>;
  by_question_type: Record<string, Record<string, number>>;
};

export type CompareMatrix = {
  metrics: string[];
  configs: Record<string, Record<string, number>>;
};

/** Gate floors, mirrored from evals/thresholds.yaml so a score is never shown
 *  without the bar it has to clear. */
export const THRESHOLDS: Record<string, number> = {
  citation_validity: 0.95,
  context_hit_rate: 0.8,
  mrr: 0.6,
  refusal_correct: 0.85,
  numeric_exactness: 0.8,
  fiscal_period_correctness: 0.85,
  faithfulness: 0.85,
  answer_relevancy: 0.8,
  context_precision: 0.75,
  context_recall: 0.8,
};

export const METRIC_LABELS: Record<string, string> = {
  citation_validity: "Citation validity",
  citation_precision: "Citation precision",
  citation_recall: "Citation recall",
  context_hit_rate: "Context hit rate",
  mrr: "MRR",
  refusal_correct: "Refusal accuracy",
  numeric_exactness: "Numeric exactness",
  fiscal_period_correctness: "Fiscal period",
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevancy",
  context_precision: "Context precision",
  context_recall: "Context recall",
};

export function label(metric: string): string {
  return METRIC_LABELS[metric] ?? metric.replace(/_/g, " ");
}

export type ChunkEmbedding = {
  dims: number;
  norm: number;
  preview: number[];
};

export type ChunkView = {
  id: string;
  chunk_index: number;
  section_path: string;
  page_start: number;
  page_end: number;
  contains_table: boolean;
  token_count: number;
  context_header: string;
  body: string;
  content: string;
  embedding?: ChunkEmbedding;
};

export type IngestResult = {
  doc_id: string;
  filename: string;
  indexed: boolean;
  indexed_count?: number;
  from_cache?: boolean;
  pages: number;
  blocks?: number;
  embed_dims?: number;
  chunk_settings?: {
    target_tokens: number;
    overlap_tokens: number;
    max_tokens: number;
  };
  chunks: ChunkView[];
  relevance?: Relevance;
  forced?: boolean;
  detail?: string | { message: string; relevance: Relevance };
};

export type CorpusDocument = {
  id: string;
  company: string;
  ticker: string;
  doc_type: string;
  fiscal_year: number | null;
  page_count: number;
  chunk_count: number;
  indexed: number;
  created_at: string;
};

export type IndexedDocument = {
  doc_id: string;
  company: string;
  ticker: string;
  doc_type: string;
  fiscal_year: number | null;
  chunk_count: number;
  has_vectors: boolean;
  page_count?: number;
};

export type Relevance = {
  accepted: boolean;
  score: number;
  matched: Record<string, string[]>;
  matched_categories: string[];
  missing_categories: string[];
  reason: string;
};
