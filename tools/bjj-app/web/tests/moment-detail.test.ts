import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import MomentDetail from '../src/lib/components/MomentDetail.svelte';

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

function momentWithoutAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [],
    annotations: []
  };
}

function momentWithAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [
      {
        id: 'a1',
        player: 'a',
        position_id: 'closed_guard_bottom',
        confidence: 0.82,
        description: 'Player A is working from closed guard.',
        coach_tip: 'Break posture.'
      },
      {
        id: 'a2',
        player: 'b',
        position_id: 'closed_guard_top',
        confidence: 0.78,
        description: null,
        coach_tip: null
      }
    ],
    annotations: []
  };
}

describe('MomentDetail', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows an Analyse button when the moment has no saved analyses', () => {
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });
    expect(screen.getByRole('button', { name: /analyse this moment/i })).toBeInTheDocument();
  });

  it('renders saved analyses instead of the Analyse button when they exist', () => {
    render(MomentDetail, { rollId: 'r1', moment: momentWithAnalyses() });
    expect(screen.queryByRole('button', { name: /analyse this moment/i })).toBeNull();
    expect(screen.getByText(/closed_guard_bottom/i)).toBeInTheDocument();
    expect(screen.getByText(/closed_guard_top/i)).toBeInTheDocument();
    expect(screen.getByText(/break posture/i)).toBeInTheDocument();
  });

  it('streams partial text into the panel and then renders the final analysis', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        body: sseBody([
          { stage: 'cache', hit: false },
          { stage: 'streaming', text: '{"player_a":' },
          { stage: 'streaming', text: '{"player_a":{"position":"standing_neutral"' },
          {
            stage: 'done',
            cached: false,
            analysis: {
              timestamp: 3.0,
              player_a: { position: 'standing_neutral', confidence: 0.9 },
              player_b: { position: 'standing_neutral', confidence: 0.88 },
              description: 'Both standing neutral.',
              coach_tip: 'Engage first.'
            }
          }
        ])
      })
    );

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.click(screen.getByRole('button', { name: /analyse this moment/i }));

    // Partial chunks render during streaming (may be one or two elements once final state lands).
    await waitFor(() => {
      expect(screen.getAllByText(/standing_neutral/i).length).toBeGreaterThan(0);
    });

    // Final parsed analysis renders the coach tip + description.
    await waitFor(() => {
      expect(screen.getByText(/engage first/i)).toBeInTheDocument();
      expect(screen.getByText(/both standing neutral/i)).toBeInTheDocument();
    });
  });

  it('shows an error message when the server returns 429', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
        json: async () => ({ detail: 'Claude cooldown — 42s until next call', retry_after_s: 42 })
      })
    );

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.click(screen.getByRole('button', { name: /analyse this moment/i }));

    await waitFor(() => {
      expect(screen.getByText(/cooldown/i)).toBeInTheDocument();
    });
  });

  it('renders an empty notes thread with a textarea + Add button', () => {
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });
    expect(screen.getByPlaceholderText(/type a new note/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add note/i })).toBeInTheDocument();
  });

  it('renders prior annotations in the thread in chronological order', () => {
    const moment = {
      ...momentWithoutAnalyses(),
      annotations: [
        { id: 'a1', body: 'earlier thought', created_at: 100 },
        { id: 'a2', body: 'later thought', created_at: 200 }
      ]
    };
    render(MomentDetail, { rollId: 'r1', moment });
    const earlier = screen.getByText('earlier thought');
    const later = screen.getByText('later thought');
    expect(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('submitting a new note via Add button calls PATCH and appends to the thread', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ id: 'a-new', body: 'fresh note', created_at: 999 })
      })
    );

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.type(screen.getByPlaceholderText(/type a new note/i), 'fresh note');
    await user.click(screen.getByRole('button', { name: /add note/i }));

    await waitFor(() => {
      expect(screen.getByText('fresh note')).toBeInTheDocument();
    });
    // Textarea clears after submit.
    expect((screen.getByPlaceholderText(/type a new note/i) as HTMLTextAreaElement).value).toBe(
      ''
    );
  });

  it('does not submit when the textarea is empty or whitespace', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.click(screen.getByRole('button', { name: /add note/i }));
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(screen.getByPlaceholderText(/type a new note/i), '   ');
    await user.click(screen.getByRole('button', { name: /add note/i }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
