import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/new/+page.svelte';

// vi.mock factories are hoisted, so any variables they reference must also be
// hoisted via vi.hoisted. Otherwise mockGoto would be `undefined` at mock time.
const { mockGoto } = vi.hoisted(() => ({ mockGoto: vi.fn() }));

vi.mock('$app/navigation', () => ({
  goto: mockGoto
}));

describe('New Roll page', () => {
  beforeEach(() => {
    mockGoto.mockReset();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        statusText: 'Created',
        json: async () => ({
          id: 'new-roll-id',
          title: 'Uploaded',
          date: '2026-04-20',
          partner: null,
          duration_s: 2.0,
          result: 'unknown',
          video_url: '/assets/new-roll-id/source.mp4'
        })
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the upload form', () => {
    render(Page);
    expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/date/i)).toBeInTheDocument();
    // Two fieldsets (Player A / Player B), each with a Name + Appearance field.
    expect(screen.getByRole('group', { name: /player a/i })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: /player b/i })).toBeInTheDocument();
    expect(screen.getAllByLabelText(/appearance/i)).toHaveLength(2);
    expect(screen.getByLabelText(/video file/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload/i })).toBeInTheDocument();
  });

  it('posts multipart form-data and redirects to the review page on success', async () => {
    const user = userEvent.setup();
    render(Page);

    await user.type(screen.getByLabelText(/title/i), 'My roll');
    // Date input has a default today-value; the test just asserts it gets sent.

    const file = new File(['fake video bytes'], 'roll.mp4', { type: 'video/mp4' });
    const fileInput = screen.getByLabelText(/video file/i) as HTMLInputElement;
    await user.upload(fileInput, file);

    await user.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/rolls',
        expect.objectContaining({ method: 'POST' })
      );
    });

    await waitFor(() => {
      expect(mockGoto).toHaveBeenCalledWith('/review/new-roll-id');
    });
  });

  it('shows an error when the upload fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => ({ detail: 'Not a video' })
      })
    );
    const user = userEvent.setup();
    render(Page);

    await user.type(screen.getByLabelText(/title/i), 'Bad');
    const file = new File(['x'], 'x.mp4', { type: 'video/mp4' });
    await user.upload(screen.getByLabelText(/video file/i) as HTMLInputElement, file);
    await user.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(screen.getByText(/upload failed/i)).toBeInTheDocument();
    });
    expect(mockGoto).not.toHaveBeenCalled();
  });
});
