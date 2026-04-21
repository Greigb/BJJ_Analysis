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
    vault_path: null,
    vault_published_at: null,
    moments: []
  };
}

function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 2, timestamp_s: 2.0, pose_delta: 0.5, analyses: [], annotations: [] },
      { id: 'm2', frame_idx: 5, timestamp_s: 5.0, pose_delta: 1.2, analyses: [], annotations: [] }
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

  it('clicking Save to Vault calls POST /publish and toasts on success', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithMoments()
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        vault_path: 'Roll Log/2026-04-20 - Review analyse test.md',
        your_notes_hash: 'newhash',
        vault_published_at: 1700000000
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save to vault/i }));

    await waitFor(() => {
      expect(screen.getByText(/published to/i)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const publishCall = fetchMock.mock.calls[1];
    expect(publishCall[0]).toContain('/publish');
  });

  it('shows the conflict dialog on 409 and re-sends with force on Overwrite', async () => {
    const fetchMock = vi.fn();
    // 1. GET detail
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithMoments()
    });
    // 2. first POST /publish → 409
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        detail: 'Your Notes was edited in Obsidian since last publish',
        current_hash: 'cur',
        stored_hash: 'stored'
      })
    });
    // 3. second POST /publish with force → 200
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        vault_path: 'Roll Log/x.md',
        your_notes_hash: 'newhash',
        vault_published_at: 1700000999
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save to vault/i }));
    // Dialog appears
    await waitFor(() => {
      expect(screen.getByText(/edited in obsidian/i)).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /overwrite/i }));
    // Success toast after force retry
    await waitFor(() => {
      expect(screen.getByText(/published to/i)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const forceCall = fetchMock.mock.calls[2];
    const forceBody = JSON.parse(forceCall[1].body);
    expect(forceBody.force).toBe(true);
  });
});
