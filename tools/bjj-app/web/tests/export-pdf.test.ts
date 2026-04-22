import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('marked', () => ({ marked: { parse: (s: string) => s } }));

import Page from '../src/routes/review/[id]/+page.svelte';

const { mockId } = vi.hoisted(() => ({ mockId: { value: 'abcdef1234567890abcdef1234567890' } }));

vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { params: { id: string }; url: { searchParams: { get: () => null } } }) => void) => {
      run({ params: { id: mockId.value }, url: { searchParams: { get: () => null } } });
      return () => {};
    }
  }
}));

function unfinalisedDetail() {
  return {
    id: 'abcdef1234567890abcdef1234567890',
    title: 'Export PDF test',
    date: '2026-04-21',
    partner: null,
    duration_s: 245.0,
    result: 'unknown',
    video_url: '/assets/abcdef1234567890abcdef1234567890/source.mp4',
    vault_path: null,
    vault_published_at: null,
    player_a_name: 'Greig',
    player_b_name: 'Partner',
    finalised_at: null,
    scores: null,
    distribution: null,
    moments: [],
    sections: []
  };
}

function finalisedDetail() {
  return {
    ...unfinalisedDetail(),
    finalised_at: 1713700100,
    scores: {
      summary: 'Solid roll.',
      scores: { guard_retention: 7, positional_awareness: 3, transition_quality: 8 },
      top_improvements: ['a'],
      strengths: ['b'],
      key_moments: []
    },
    distribution: {
      timeline: [],
      counts: {},
      percentages: { guard_bottom: 50, guard_top: 50 }
    }
  };
}

function pdfResponse(opts: { status: number; conflict?: boolean } = { status: 200 }) {
  const headers = new Headers({
    'Content-Type': 'application/pdf',
    'Content-Disposition': 'attachment; filename="export-pdf-test-2026-04-21.pdf"'
  });
  if (opts.conflict) headers.set('X-Conflict', 'report');
  // 5-byte PDF-magic-header blob — enough for the blob to be non-empty.
  const body = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], { type: 'application/pdf' });
  return new Response(body, { status: opts.status, headers });
}

describe('Review page — Export PDF', () => {
  let originalCreateObjectURL: any;
  let originalRevokeObjectURL: any;

  beforeEach(() => {
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:fake-url');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('disables the Export PDF button when the roll is not finalised', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => unfinalisedDetail()
      })
    );

    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Export PDF test')).toBeInTheDocument();
    });

    const btn = screen.queryByRole('button', { name: /export pdf/i });
    expect(btn).toBeDisabled();
  });

  it('enables the Export PDF button when the roll is finalised', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => finalisedDetail()
      })
    );

    render(Page);

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /export pdf/i });
      expect(btn).toBeEnabled();
    });
  });

  it('clicks the button → POST /export-pdf → triggers blob download', async () => {
    const fetchMock = vi.fn();
    // 1. GET detail
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => finalisedDetail()
    });
    // 2. POST /export-pdf
    fetchMock.mockResolvedValueOnce(pdfResponse({ status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Export PDF test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /export pdf/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/rolls/abcdef1234567890abcdef1234567890/export-pdf'),
        expect.objectContaining({ method: 'POST' })
      );
      expect(URL.createObjectURL).toHaveBeenCalled();
    });
  });

  it('409 opens the conflict dialog AND still triggers the download', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => finalisedDetail()
    });
    fetchMock.mockResolvedValueOnce(pdfResponse({ status: 409, conflict: true }));
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Export PDF test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /export pdf/i }));

    await waitFor(() => {
      expect(URL.createObjectURL).toHaveBeenCalled();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText(/Report section/i)).toBeInTheDocument();
    });
  });

  it('clicking Overwrite from the conflict dialog retries with overwrite=1', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => finalisedDetail()
    });
    // First export attempt → 409
    fetchMock.mockResolvedValueOnce(pdfResponse({ status: 409, conflict: true }));
    // Second attempt (with overwrite=1) → 200
    fetchMock.mockResolvedValueOnce(pdfResponse({ status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Export PDF test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /export pdf/i }));

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /overwrite/i }));

    await waitFor(() => {
      // Two export-pdf calls total (positions 2 and 3 after GET detail).
      const exportCalls = fetchMock.mock.calls.filter((c: any[]) => String(c[0]).includes('/export-pdf'));
      expect(exportCalls.length).toBe(2);
      expect(String(exportCalls[1][0])).toContain('overwrite=1');
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it("shows 'Exporting…' while the request is in flight", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => finalisedDetail()
    });

    let resolve: any;
    const pending = new Promise<Response>((r) => { resolve = r; });
    fetchMock.mockReturnValueOnce(pending);
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Export PDF test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /export pdf/i }));

    await waitFor(() => {
      const busy = screen.getByRole('button', { name: /exporting/i });
      expect(busy).toBeDisabled();
    });

    resolve(pdfResponse({ status: 200 }));
  });
});
