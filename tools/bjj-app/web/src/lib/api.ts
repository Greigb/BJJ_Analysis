import type { CreateRollInput, RollDetail, RollSummary } from './types';

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
