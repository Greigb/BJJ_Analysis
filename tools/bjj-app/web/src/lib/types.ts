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
  player: 'greig' | 'anthony';
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

export type Moment = {
  id: string;
  frame_idx: number;
  timestamp_s: number;
  pose_delta: number | null;
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
  moments: Moment[];
};

export type CreateRollInput = {
  title: string;
  date: string;
  partner?: string;
  video: File;
};

export type AnalyseEvent =
  | { stage: 'frames'; pct: number; total?: number }
  | { stage: 'pose'; pct: number; total?: number }
  | {
      stage: 'done';
      total?: number;
      moments: Array<{ frame_idx: number; timestamp_s: number; pose_delta: number | null }>;
    };

export type AnalyseMomentEvent =
  | { stage: 'cache'; hit: boolean }
  | { stage: 'streaming'; text: string }
  | {
      stage: 'done';
      cached: boolean;
      analysis: {
        timestamp: number;
        greig: { position: string; confidence: number };
        anthony: { position: string; confidence: number };
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
