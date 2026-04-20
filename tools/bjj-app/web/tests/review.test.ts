import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/review/[id]/+page.svelte';

const sampleDetail = {
  id: 'abc123',
  title: 'Roll vs Anthony',
  date: '2026-04-20',
  partner: 'Anthony',
  duration_s: 143.2,
  result: 'unknown',
  video_url: '/assets/abc123/source.mp4'
};

// Minimal readable-store shape — avoids importing svelte/store inside a hoisted factory.
vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { params: { id: string } }) => void) => {
      run({ params: { id: 'abc123' } });
      return () => {};
    }
  }
}));

describe('Review page', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => sampleDetail
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('fetches the roll detail and renders metadata', async () => {
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Roll vs Anthony')).toBeInTheDocument();
    });

    expect(screen.getByText('Anthony')).toBeInTheDocument();
    expect(screen.getByText('2026-04-20')).toBeInTheDocument();
    // Duration rendered as M:SS.
    expect(screen.getByText('2:23')).toBeInTheDocument();
  });

  it('renders a <video> element pointing at the returned video_url', async () => {
    render(Page);

    await waitFor(() => {
      const video = document.querySelector('video');
      expect(video).not.toBeNull();
      expect(video?.querySelector('source')?.getAttribute('src')).toBe(
        '/assets/abc123/source.mp4'
      );
    });
  });

  it('renders a placeholder timeline and a disabled Analyse button', async () => {
    render(Page);

    await waitFor(() => {
      expect(screen.getByText(/timeline populates after analysis/i)).toBeInTheDocument();
    });

    const button = screen.getByRole('button', { name: /analyse/i });
    expect(button).toBeDisabled();
  });
});
