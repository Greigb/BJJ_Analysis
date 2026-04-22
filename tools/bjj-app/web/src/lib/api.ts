import type {
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  ExportPdfResult,
  GraphPaths,
  GraphTaxonomy,
  PositionNote,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary,
  SummariseResponse
} from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.headers ?? {})
    }
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function listRolls(): Promise<RollSummary[]> {
  return request<RollSummary[]>('/api/rolls');
}

export function getRoll(id: string): Promise<RollDetail> {
  return request<RollDetail>(`/api/rolls/${encodeURIComponent(id)}`);
}

export function createRoll(input: CreateRollInput): Promise<RollDetail> {
  const form = new FormData();
  form.append('title', input.title);
  form.append('date', input.date);
  if (input.partner) form.append('partner', input.partner);
  if (input.player_a_name) form.append('player_a_name', input.player_a_name);
  if (input.player_b_name) form.append('player_b_name', input.player_b_name);
  form.append('video', input.video);

  return request<RollDetail>('/api/rolls', {
    method: 'POST',
    body: form
  });
}

export interface SectionInput {
  start_s: number;
  end_s: number;
  sample_interval_s: number;
}

/**
 * Analyse a roll — POSTs sections config and returns the raw SSE Response.
 * Callers are responsible for reading the body as an SSE stream.
 *
 * Usage:
 *   const response = await analyseRoll(id, sections);
 */
export async function analyseRoll(
  rollId: string,
  sections: SectionInput[],
): Promise<Response> {
  return fetch(`/api/rolls/${encodeURIComponent(rollId)}/analyse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sections }),
  });
}

/**
 * Analyse a single moment with Claude — async iterator over SSE events.
 *
 * Usage:
 *   for await (const event of analyseMoment(rollId, frameIdx)) { ... }
 *
 * Throws ApiError on non-streaming error statuses (e.g. 404, 429).
 */
export async function* analyseMoment(
  rollId: string,
  frameIdx: number
): AsyncIterator<AnalyseMomentEvent> {
  const response = await fetch(
    `/api/rolls/${encodeURIComponent(rollId)}/moments/${frameIdx}/analyse`,
    { method: 'POST' }
  );
  if (!response.ok) {
    // Try to surface the server's detail payload for 429 / 404.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }
  if (!response.body) {
    throw new Error('Analyse response has no body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const dataLine = frame.split('\n').find((line) => line.startsWith('data: '));
        if (!dataLine) continue;
        yield JSON.parse(dataLine.slice(6)) as AnalyseMomentEvent;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function addAnnotation(
  rollId: string,
  momentId: string,
  body: string
): Promise<Annotation> {
  return request<Annotation>(
    `/api/rolls/${encodeURIComponent(rollId)}/moments/${encodeURIComponent(momentId)}/annotations`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body })
    }
  );
}

/**
 * Publish a roll to the vault. Returns PublishSuccess on 200.
 * On 409, throws a ConflictError carrying the current/stored hashes.
 */
export class PublishConflictError extends Error {
  constructor(public readonly payload: PublishConflict) {
    super(payload.detail);
  }
}

export async function publishRoll(
  rollId: string,
  options: { force?: boolean } = {}
): Promise<PublishSuccess> {
  const response = await fetch(`/api/rolls/${encodeURIComponent(rollId)}/publish`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ force: options.force ?? false })
  });
  if (response.status === 409) {
    const payload = (await response.json()) as PublishConflict;
    throw new PublishConflictError(payload);
  }
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as PublishSuccess;
}

export function getGraph(): Promise<GraphTaxonomy> {
  return request<GraphTaxonomy>('/api/graph');
}

export function getGraphPaths(rollId: string): Promise<GraphPaths> {
  return request<GraphPaths>(`/api/graph/paths/${encodeURIComponent(rollId)}`);
}

export async function getPositionNote(positionId: string): Promise<PositionNote | null> {
  const response = await fetch(
    `/api/vault/position/${encodeURIComponent(positionId)}`,
    { headers: { Accept: 'application/json' } }
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as PositionNote;
}

/**
 * Finalise a roll — one Claude call across all analysed moments + annotations.
 * Returns the parsed summary payload + locally-computed distribution.
 */
export class SummariseRateLimitedError extends Error {
  constructor(
    public readonly retryAfterS: number,
    message: string
  ) {
    super(message);
  }
}

export async function summariseRoll(rollId: string): Promise<SummariseResponse> {
  const response = await fetch(
    `/api/rolls/${encodeURIComponent(rollId)}/summarise`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    }
  );
  if (response.status === 429) {
    const body = await response.json().catch(() => ({}));
    const retryAfter = Number(response.headers.get('Retry-After') ?? body.retry_after_s ?? 60);
    throw new SummariseRateLimitedError(retryAfter, body.detail ?? 'Rate limited');
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as SummariseResponse;
}

/** POST /api/rolls/:id/export-pdf — returns PDF blob + conflict flag. */
export async function exportRollPdf(rollId: string, overwrite = false): Promise<ExportPdfResult> {
  const url = `/api/rolls/${encodeURIComponent(rollId)}/export-pdf${overwrite ? '?overwrite=1' : ''}`;
  const response = await fetch(url, { method: 'POST' });

  if (response.status === 200 || response.status === 409) {
    const blob = await response.blob();
    const filename = parseFilenameFromContentDisposition(response.headers.get('content-disposition'));
    const kind = response.status === 409 ? 'conflict' : 'ok';
    return { kind, blob, filename };
  }

  // Error paths return JSON.
  const error = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
  throw new ApiError(response.status, error.detail ?? `Export failed (${response.status})`);
}

function parseFilenameFromContentDisposition(header: string | null): string {
  if (!header) return 'match-report.pdf';
  const m = header.match(/filename="([^"]+)"/);
  return m?.[1] ?? 'match-report.pdf';
}
