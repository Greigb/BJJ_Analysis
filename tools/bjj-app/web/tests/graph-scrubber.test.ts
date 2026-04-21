import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import GraphScrubber from '../src/lib/components/GraphScrubber.svelte';

describe('GraphScrubber', () => {
  it('renders a range slider with max = durationS', () => {
    render(GraphScrubber, {
      scrubTimeS: 0,
      durationS: 225,
      rollId: 'abc',
      onscrubchange: vi.fn()
    });
    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('max', '225');
    expect((slider as HTMLInputElement).value).toBe('0');
  });

  it('calls onscrubchange with new numeric value when slider moves', async () => {
    const onscrubchange = vi.fn();
    render(GraphScrubber, {
      scrubTimeS: 0,
      durationS: 100,
      rollId: 'abc',
      onscrubchange
    });
    const slider = screen.getByRole('slider') as HTMLInputElement;
    // Simulate input value change + input event.
    slider.value = '42';
    slider.dispatchEvent(new Event('input', { bubbles: true }));
    expect(onscrubchange).toHaveBeenCalledWith(42);
  });

  it('renders the "Open in review" link with roll + t query params', () => {
    render(GraphScrubber, {
      scrubTimeS: 42,
      durationS: 100,
      rollId: 'abc',
      onscrubchange: vi.fn()
    });
    const link = screen.getByRole('link', { name: /open in review/i });
    expect(link).toHaveAttribute('href', '/review/abc?t=42');
  });

  it('renders the mm:ss time display for scrubTimeS', () => {
    render(GraphScrubber, {
      scrubTimeS: 125,
      durationS: 300,
      rollId: 'abc',
      onscrubchange: vi.fn()
    });
    expect(screen.getByText(/2:05/)).toBeInTheDocument();
    expect(screen.getByText(/5:00/)).toBeInTheDocument();
  });

  it('disables the slider when rollId is empty or durationS is 0', () => {
    render(GraphScrubber, {
      scrubTimeS: 0,
      durationS: 0,
      rollId: '',
      onscrubchange: vi.fn()
    });
    const slider = screen.getByRole('slider');
    expect(slider).toBeDisabled();
  });
});
