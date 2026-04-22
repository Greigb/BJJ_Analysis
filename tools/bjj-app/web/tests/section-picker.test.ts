import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import SectionPicker from '../src/lib/components/SectionPicker.svelte';

function makeVideoEl(currentTime = 0, duration = 60) {
  const el: any = document.createElement('video');
  Object.defineProperty(el, 'currentTime', {
    writable: true,
    value: currentTime,
  });
  Object.defineProperty(el, 'duration', {
    writable: true,
    value: duration,
  });
  return el as HTMLVideoElement;
}

describe('SectionPicker', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the Mark start button', () => {
    const video = makeVideoEl(0, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    expect(screen.getByRole('button', { name: /mark start/i })).toBeInTheDocument();
  });

  it('Mark end is disabled until Mark start has been pressed', async () => {
    const video = makeVideoEl(0, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    const end = screen.getByRole('button', { name: /mark end/i });
    expect(end).toBeDisabled();
  });

  it('pressing Mark start then Mark end commits a new chip', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    // Move the playhead to 7.
    (video as any).currentTime = 7;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await waitFor(() => {
      expect(screen.getByText(/0:03/)).toBeInTheDocument();
      expect(screen.getByText(/0:07/)).toBeInTheDocument();
    });
  });

  it('Cancel resets the pending start without committing', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(screen.getByRole('button', { name: /mark end/i })).toBeDisabled();
  });

  it('delete button removes a chip', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));
    expect(screen.getByText(/0:03/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /delete/i }));
    expect(screen.queryByText(/0:03/)).not.toBeInTheDocument();
  });

  it('density dropdown changes sample_interval_s', async () => {
    const user = userEvent.setup();
    const onAnalyse = vi.fn();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse, busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    const dropdown = screen.getByRole('combobox', { name: /density/i });
    await user.selectOptions(dropdown, '0.5');

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));
    expect(onAnalyse).toHaveBeenCalledWith([
      expect.objectContaining({ sample_interval_s: 0.5 }),
    ]);
  });

  it('Analyse ranges is disabled when no sections', () => {
    const video = makeVideoEl(0, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    const btn = screen.getByRole('button', { name: /analyse ranges/i });
    expect(btn).toBeDisabled();
  });

  it('Analyse ranges is disabled while busy', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    const { rerender } = render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await rerender({ videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: true });

    expect(screen.getByRole('button', { name: /analyse ranges/i })).toBeDisabled();
  });

  it('editing mm:ss input updates the section timestamps', async () => {
    const user = userEvent.setup();
    const onAnalyse = vi.fn();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse, busy: false },
    });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    const startInput = screen.getByLabelText(/section start/i) as HTMLInputElement;
    await user.clear(startInput);
    await user.type(startInput, '0:02');
    startInput.blur();

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));
    expect(onAnalyse).toHaveBeenCalledWith([
      expect.objectContaining({ start_s: 2.0, end_s: 5.0 }),
    ]);
  });
});
