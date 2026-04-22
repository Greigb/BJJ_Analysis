import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('cytoscape', () => {
  const cyInstance: any = {
    on: vi.fn(), add: vi.fn(), remove: vi.fn(),
    getElementById: vi.fn(() => ({
      length: 0, style: vi.fn(), position: vi.fn(),
      addClass: vi.fn(), removeClass: vi.fn(),
    })),
    nodes: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn() })),
    edges: vi.fn(() => ({
      forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn(),
      length: 0, remove: vi.fn(),
    })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn(), remove: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn(), stop: vi.fn() })),
    fit: vi.fn(), resize: vi.fn(), destroy: vi.fn(),
  };
  const cytoscape = vi.fn(() => cyInstance);
  (cytoscape as any).use = vi.fn();
  return { default: cytoscape };
});
vi.mock('cytoscape-cose-bilkent', () => ({ default: () => {} }));
vi.mock('marked', () => ({ marked: { parse: (s: string) => s } }));

import Page from '../src/routes/review/[id]/+page.svelte';

const { mockId } = vi.hoisted(() => ({ mockId: { value: 'abc123' } }));

vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: {
      params: { id: string };
      url: { searchParams: { get: () => null } };
    }) => void) => {
      run({ params: { id: mockId.value }, url: { searchParams: { get: () => null } } });
      return () => {};
    },
  },
}));

function detailWithoutMoments() {
  return {
    id: 'abc123',
    title: 'Review M9 test',
    date: '2026-04-22',
    partner: null,
    duration_s: 30.0,
    result: 'unknown',
    video_url: '/assets/abc123/source.mp4',
    vault_path: null,
    vault_published_at: null,
    player_a_name: 'Player A',
    player_b_name: 'Player B',
    finalised_at: null,
    scores: null,
    distribution: null,
    moments: [],
    sections: [],
  };
}

function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 0, timestamp_s: 3.0, pose_delta: null, section_id: 's1', analyses: [], annotations: [] },
      { id: 'm2', frame_idx: 1, timestamp_s: 4.0, pose_delta: null, section_id: 's1', analyses: [], annotations: [] },
    ],
    sections: [
      { id: 's1', start_s: 3.0, end_s: 5.0, sample_interval_s: 1.0 },
    ],
  };
}

function sseBody(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
      }
      controller.close();
    },
  });
}

describe('Review page — M9 section flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders the SectionPicker when the roll has no moments yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithoutMoments(),
      }),
    );
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9 test')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /mark start/i })).toBeInTheDocument();
  });

  it('renders existing moments as chips when the roll was already analysed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithMoments(),
      }),
    );
    render(Page);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /0:03/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:04/i })).toBeInTheDocument();
    });
  });

  it('Mark start + Mark end + Analyse ranges streams progress and renders new chips', async () => {
    const fetchMock = vi.fn();
    // GET roll detail
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithoutMoments(),
    });
    // graph taxonomy fails; swallowed
    fetchMock.mockRejectedValueOnce(new Error('graph not needed'));
    // POST /analyse returns SSE
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: sseBody([
        { stage: 'frames', pct: 0 },
        { stage: 'frames', pct: 100, total: 2 },
        {
          stage: 'done',
          total: 2,
          moments: [
            { id: 'm-a', frame_idx: 0, timestamp_s: 3.0, section_id: 'sec-a' },
            { id: 'm-b', frame_idx: 1, timestamp_s: 4.0, section_id: 'sec-a' },
          ],
        },
      ]),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9 test')).toBeInTheDocument();
    });

    const video = document.querySelector('video') as HTMLVideoElement;
    Object.defineProperty(video, 'currentTime', { writable: true, value: 3 });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    Object.defineProperty(video, 'currentTime', { writable: true, value: 5 });
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /0:03/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:04/i })).toBeInTheDocument();
    });
  });

  it('clicking Finalise on a roll with analyses calls POST /summarise and shows the scores panel', async () => {
    const fetchMock = vi.fn();
    const detailWithAnalyses = {
      ...detailWithMoments(),
      moments: [
        {
          id: 'm1', frame_idx: 0, timestamp_s: 3.0, pose_delta: null,
          section_id: 's1',
          analyses: [{
            id: 'a1', player: 'a', position_id: 'closed_guard_bottom',
            confidence: 0.8, description: 'd', coach_tip: 't',
          }],
          annotations: [],
        },
      ],
    };
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => detailWithAnalyses });
    fetchMock.mockRejectedValueOnce(new Error('graph not needed'));
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        finalised_at: 1713700000,
        scores: {
          summary: 'Solid.',
          scores: { guard_retention: 7, positional_awareness: 6, transition_quality: 7 },
          top_improvements: ['a'], strengths: ['b'], key_moments: [],
        },
        distribution: { timeline: [], counts: {}, percentages: { guard_bottom: 100 } },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9 test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /finalise/i }));

    await waitFor(() => {
      expect(screen.getByText(/solid/i)).toBeInTheDocument();
    });
  });
});
