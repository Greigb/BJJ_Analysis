import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/+page.svelte';

const sampleRolls = [
  {
    id: '2026-04-14 - sample',
    title: 'Roll 1: Greig vs Anthony — WIN by Submission',
    date: '2026-04-14',
    partner: 'Anthony',
    duration: '2:23',
    result: 'win_submission',
    roll_id: 'roll-uuid-1'
  },
  {
    id: '2026-04-01 - other',
    title: 'Other roll — continuation',
    date: '2026-04-01',
    partner: 'Bob',
    duration: '1:45',
    result: 'continuation',
    roll_id: 'roll-uuid-2'
  }
];

describe('Home page', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => sampleRolls
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a list item for each roll returned by the API', async () => {
    render(Page);

    await waitFor(() => {
      expect(
        screen.getByText('Roll 1: Greig vs Anthony — WIN by Submission')
      ).toBeInTheDocument();
    });

    expect(screen.getByText('Other roll — continuation')).toBeInTheDocument();
    expect(screen.getByText('Anthony')).toBeInTheDocument();
    expect(screen.getByText('2:23')).toBeInTheDocument();
  });

  it('shows an empty-state message when no rolls are returned', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => []
      })
    );

    render(Page);

    await waitFor(() => {
      expect(screen.getByText(/No rolls analysed yet/i)).toBeInTheDocument();
    });
  });

  it('renders a clickable anchor for rolls with a roll_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [
          {
            id: '2026-04-21 - sample',
            title: 'Sample roll',
            date: '2026-04-21',
            partner: 'Anthony',
            duration: '3:45',
            result: 'unknown',
            roll_id: 'abc123'
          }
        ]
      })
    );

    const { default: Page } = await import('../src/routes/+page.svelte');
    render(Page);

    await waitFor(() => {
      const link = screen.getByRole('link', { name: /sample roll/i });
      expect(link).toHaveAttribute('href', '/review/abc123');
    });
  });

  it('renders a non-link tile for rolls without a roll_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [
          {
            id: '2026-04-14 - legacy',
            title: 'Legacy roll',
            date: '2026-04-14',
            partner: null,
            duration: null,
            result: null,
            roll_id: null
          }
        ]
      })
    );

    const { default: Page } = await import('../src/routes/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText(/legacy roll/i)).toBeInTheDocument();
      // No link with that text exists.
      expect(screen.queryByRole('link', { name: /legacy roll/i })).toBeNull();
      // An ".md only" badge is rendered.
      expect(screen.getByText(/md only/i)).toBeInTheDocument();
    });
  });
});
