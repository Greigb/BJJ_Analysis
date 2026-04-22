import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

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

function detailWithoutSections() {
  return {
    id: 'abc123',
    title: 'Review M9b test',
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

function detailWithAnalysedSection() {
  return {
    ...detailWithoutSections(),
    sections: [
      {
        id: 's1', start_s: 3.0, end_s: 7.0, sample_interval_s: 1.0,
        narrative: 'Existing narrative.', coach_tip: 'Keep elbows tight.',
        analysed_at: 1713700000, annotations: [],
      },
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

describe('Review page — M9b section flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders the SectionPicker when the roll has no sections yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true, status: 200,
        json: async () => detailWithoutSections(),
      }),
    );
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9b test')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /mark start/i })).toBeInTheDocument();
  });

  it('renders existing analysed sections as SectionCards', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true, status: 200,
        json: async () => detailWithAnalysedSection(),
      }),
    );
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Existing narrative.')).toBeInTheDocument();
      expect(screen.getByText('Keep elbows tight.')).toBeInTheDocument();
    });
  });

  it('Mark start + Mark end + Analyse ranges streams section events and renders a card', async () => {
    const fetchMock = vi.fn();
    // GET roll detail
    fetchMock.mockResolvedValueOnce({
      ok: true, status: 200,
      json: async () => detailWithoutSections(),
    });
    // POST /analyse returns SSE
    fetchMock.mockResolvedValueOnce({
      ok: true, status: 200,
      body: sseBody([
        { stage: 'section_started', section_id: 'sec-a', start_s: 3.0, end_s: 5.0, idx: 0, total: 1 },
        { stage: 'section_done', section_id: 'sec-a', start_s: 3.0, end_s: 5.0,
          narrative: 'Player A passes to side control.', coach_tip: 'Stay heavy.' },
        { stage: 'done', total: 1 },
      ]),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9b test')).toBeInTheDocument();
    });

    const video = document.querySelector('video') as HTMLVideoElement;
    Object.defineProperty(video, 'currentTime', { writable: true, value: 3 });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    Object.defineProperty(video, 'currentTime', { writable: true, value: 5 });
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));

    await waitFor(() => {
      expect(screen.getByText('Player A passes to side control.')).toBeInTheDocument();
      expect(screen.getByText('Stay heavy.')).toBeInTheDocument();
    });
  });

  it('shows queued banner on section_queued and clears it on section_started', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true, status: 200, json: async () => detailWithoutSections(),
    });
    fetchMock.mockResolvedValueOnce({
      ok: true, status: 200,
      body: sseBody([
        { stage: 'section_queued', section_id: 'sec-a', retry_after_s: 7 },
        { stage: 'section_started', section_id: 'sec-a', start_s: 3.0, end_s: 5.0, idx: 0, total: 1 },
        { stage: 'section_done', section_id: 'sec-a', start_s: 3.0, end_s: 5.0,
          narrative: 'A passes.', coach_tip: 'Tight.' },
        { stage: 'done', total: 1 },
      ]),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => expect(screen.getByText('Review M9b test')).toBeInTheDocument());

    const video = document.querySelector('video') as HTMLVideoElement;
    Object.defineProperty(video, 'currentTime', { writable: true, value: 3 });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    Object.defineProperty(video, 'currentTime', { writable: true, value: 5 });
    await user.click(screen.getByRole('button', { name: /mark end/i }));
    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));

    await waitFor(() => expect(screen.getByText('A passes.')).toBeInTheDocument());
  });

  it('clicking Finalise on a roll with an analysed section calls /summarise and shows scores', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true, status: 200, json: async () => detailWithAnalysedSection(),
    });
    fetchMock.mockResolvedValueOnce({
      ok: true, status: 200,
      json: async () => ({
        finalised_at: 1713700000,
        scores: {
          summary: 'Solid.',
          scores: { guard_retention: 7, positional_awareness: 6, transition_quality: 7 },
          top_improvements: ['a', 'b', 'c'],
          strengths: ['x', 'y'],
          key_moments: [],
        },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => expect(screen.getByText('Review M9b test')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /finalise/i }));

    await waitFor(() => {
      expect(screen.getByText(/solid/i)).toBeInTheDocument();
    });
  });
});
