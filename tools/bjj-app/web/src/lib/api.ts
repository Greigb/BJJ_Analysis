import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  GraphPaths,
  GraphTaxonomy,
  PositionNote,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary
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
  form.append('video', input.video);

  return request<RollDetail>('/api/rolls', {
    method: 'POST',
    body: form
  });
}

/**
 * Analyse a roll — returns an async iterator of SSE events from the backend.
 *
 * Usage:
 *   for await (const event of analyseRoll(id)) { ... }
 */
export async function* analyseRoll(id: string): AsyncIterator<AnalyseEvent> {
  const response = await fetch(`/api/rolls/${encodeURIComponent(id)}/analyse`, {
    method: 'POST'
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
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

      // SSE frames are separated by blank lines.
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        const dataLine = frame
          .split('\n')
          .find((line) => line.startsWith('data: '));
        if (!dataLine) continue;
        yield JSON.parse(dataLine.slice(6)) as AnalyseEvent;
      }
    }
  } finally {
    // Cancel drains any buffered body bytes and closes the underlying fetch
    // so the server's TCP connection isn't held open if the iterator is
    // abandoned (e.g. user navigates away mid-stream).
    try {
      await reader.cancel();
    } catch {
      /* already cancelled or errored — safe to ignore */
    }
    reader.releaseLock();
  }
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
