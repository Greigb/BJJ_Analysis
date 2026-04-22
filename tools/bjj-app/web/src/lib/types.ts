export type RollSummary = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration: string | null;
  result: string | null;
  roll_id: string | null;
};

export type Analysis = {
  id: string;
  player: 'a' | 'b';
  position_id: string;
  confidence: number | null;
  description: string | null;
  coach_tip: string | null;
};

export type Annotation = {
  id: string;
  body: string;
  created_at: number;
};

export interface Section {
  id: string;
  start_s: number;
  end_s: number;
  sample_interval_s: number;
  narrative: string | null;
  coach_tip: string | null;
  analysed_at: number | null;
  annotations: Annotation[];
}

export type Moment = {
  id: string;
  frame_idx: number;
  timestamp_s: number;
  pose_delta: number | null;
  section_id: string | null;
  analyses: Analysis[];
  annotations: Annotation[];
};

export type RollDetail = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration_s: number | null;
  result: string;
  video_url: string;
  vault_path: string | null;
  vault_published_at: number | null;
  player_a_name: string;
  player_b_name: string;
  player_a_description: string | null;
  player_b_description: string | null;
  finalised_at: number | null;
  scores: SummaryPayload | null;
  distribution: Distribution | null;
  sections: Section[];
  moments: Moment[];
};

export type CreateRollInput = {
  title: string;
  date: string;
  partner?: string;
  player_a_name?: string;
  player_b_name?: string;
  player_a_description?: string;
  player_b_description?: string;
  video: File;
};

export type AnalyseEvent =
  | { stage: 'section_started'; section_id: string; start_s: number; end_s: number; idx: number; total: number }
  | { stage: 'section_queued'; section_id: string; retry_after_s: number }
  | { stage: 'section_done'; section_id: string; start_s: number; end_s: number; narrative: string; coach_tip: string }
  | { stage: 'section_error'; section_id: string; error: string }
  | { stage: 'done'; total: number };

export type AnalyseMomentEvent =
  | { stage: 'cache'; hit: boolean }
  | { stage: 'streaming'; text: string }
  | {
      stage: 'done';
      cached: boolean;
      analysis: {
        timestamp: number;
        player_a: { position: string; confidence: number };
        player_b: { position: string; confidence: number };
        description: string;
        coach_tip: string;
      };
    }
  | {
      stage: 'error';
      kind: string;
      detail?: string;
      retry_after_s?: number;
    };

export type PublishSuccess = {
  vault_path: string;
  your_notes_hash: string;
  vault_published_at: number;
};

export type PublishConflict = {
  detail: string;
  current_hash: string;
  stored_hash: string;
};

// ---------- M5: Graph page types ----------

export type GraphCategory = {
  id: string;
  label: string;
  dominance: number;
  tint: string;
};

export type GraphNode = {
  id: string;
  name: string;
  category: string;
};

export type GraphEdge = {
  from: string;
  to: string;
};

export type GraphTaxonomy = {
  categories: GraphCategory[];
  positions: GraphNode[];
  transitions: GraphEdge[];
};

export type PathPoint = {
  timestamp_s: number;
  position_id: string;
  moment_id: string;
};

export type GraphPaths = {
  duration_s: number | null;
  player_a_name: string;
  player_b_name: string;
  paths: {
    a: PathPoint[];
    b: PathPoint[];
  };
};

export type PositionNote = {
  position_id: string;
  name: string;
  markdown: string;
  vault_path: string;
};

export type GraphFilter =
  | { kind: 'all' }
  | { kind: 'category'; id: string }
  | { kind: 'player'; who: 'a' | 'b' };

// ---------- M6a: Summary types ----------

export type Scores = {
  guard_retention: number;
  positional_awareness: number;
  transition_quality: number;
};

export type KeyMoment = {
  section_id: string;
  note: string;
};

export type SummaryPayload = {
  summary: string;
  scores: Scores;
  top_improvements: string[];
  strengths: string[];
  key_moments: KeyMoment[];
};

export type Distribution = {
  timeline: string[];
  counts: Record<string, number>;
  percentages: Record<string, number>;
};

export type SummariseResponse = {
  finalised_at: number;
  scores: SummaryPayload;
  distribution: Distribution;
};

// ---------- M6b: PDF export types ----------

export type ExportPdfResult =
  | { kind: 'ok'; blob: Blob; filename: string }
  | { kind: 'conflict'; blob: Blob; filename: string };
