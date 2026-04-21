import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/review/[id]/+page.svelte';

// See M2a new.test.ts — vi.mock factories are hoisted, so any referenced
// variables must be hoisted with vi.hoisted.
const { mockId } = vi.hoisted(() => ({ mockId: { value: 'abc123' } }));

vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { params: { id: string } }) => void) => {
      run({ params: { id: mockId.value } });
      return () => {};
    }
  }
}));

function detailWithoutMoments() {
  return {
    id: 'abc123',
    title: 'Review analyse test',
    date: '2026-04-20',
    partner: null,
    duration_s: 10.0,
    result: 'unknown',
    video_url: '/assets/abc123/source.mp4',
    moments: []
  };
}

function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 2, timestamp_s: 2.0, pose_delta: 0.5, analyses: [] },
      { id: 'm2', frame_idx: 5, timestamp_s: 5.0, pose_delta: 1.2, analyses: [] }
    ]
  };
}

// Build an SSE-format response body from a list of events.
function sseBody(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
      }
      controller.close();
    }
  });
}

describe('Review page — analyse flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders an enabled Analyse button when the roll has no moments yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithoutMoments()
      })
    );

    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    const button = screen.getByRole('button', { name: /analyse/i });
    expect(button).not.toBeDisabled();
  });

  it('renders existing moments as chips when the roll was already analysed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithMoments()
      })
    );

    render(Page);

    await waitFor(() => {
      // Chips are rendered as buttons labeled with their timestamp (M:SS).
      expect(screen.getByRole('button', { name: /0:02/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:05/i })).toBeInTheDocument();
    });
  });

  it('clicking Analyse streams progress and then renders new chips', async () => {
    const fetchMock = vi.fn();
    // First call: GET roll detail. Second: POST analyse (SSE body).
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithoutMoments()
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: sseBody([
        { stage: 'frames', pct: 0 },
        { stage: 'frames', pct: 100 },
        { stage: 'pose', pct: 0 },
        { stage: 'pose', pct: 100 },
        {
          stage: 'done',
          moments: [
            { frame_idx: 3, timestamp_s: 3.0, pose_delta: 0.8 },
            { frame_idx: 7, timestamp_s: 7.0, pose_delta: 1.4 }
          ]
        }
      ])
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /analyse/i }));

    // After streaming completes, chips for the returned moments appear.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /0:03/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:07/i })).toBeInTheDocument();
    });
  });
});
