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
    result: 'win_submission'
  },
  {
    id: '2026-04-01 - other',
    title: 'Other roll — continuation',
    date: '2026-04-01',
    partner: 'Bob',
    duration: '1:45',
    result: 'continuation'
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
});
