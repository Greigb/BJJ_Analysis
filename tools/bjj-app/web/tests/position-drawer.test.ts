import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('marked', () => ({
  marked: {
    parse: vi.fn((md: string) => `<h1>Closed Guard (Bottom)</h1><p>Body text.</p>`)
  }
}));

import PositionDrawer from '../src/lib/components/PositionDrawer.svelte';
import type { PositionNote } from '../src/lib/types';

const sampleNote: PositionNote = {
  position_id: 'closed_guard_bottom',
  name: 'Closed Guard (Bottom)',
  markdown: '# Closed Guard (Bottom)\n\nBody text.\n',
  vault_path: 'Positions/Closed Guard (Bottom).md'
};

describe('PositionDrawer', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing when open is false', () => {
    render(PositionDrawer, { open: false, positionNote: sampleNote, onclose: vi.fn() });
    expect(screen.queryByText(/closed guard/i)).toBeNull();
  });

  it('renders markdown when open with a note', () => {
    render(PositionDrawer, { open: true, positionNote: sampleNote, onclose: vi.fn() });
    expect(screen.getByText(/closed guard \(bottom\)/i)).toBeInTheDocument();
    expect(screen.getByText(/body text/i)).toBeInTheDocument();
  });

  it('renders fallback text when open with a null note', () => {
    render(PositionDrawer, { open: true, positionNote: null, onclose: vi.fn() });
    expect(screen.getByText(/no vault note for this position/i)).toBeInTheDocument();
  });

  it('calls onclose when the close button is clicked', async () => {
    const onclose = vi.fn();
    const user = userEvent.setup();
    render(PositionDrawer, { open: true, positionNote: sampleNote, onclose });
    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(onclose).toHaveBeenCalledTimes(1);
  });

  it('calls onclose on Escape key', async () => {
    const onclose = vi.fn();
    const user = userEvent.setup();
    render(PositionDrawer, { open: true, positionNote: sampleNote, onclose });
    await user.keyboard('{Escape}');
    expect(onclose).toHaveBeenCalledTimes(1);
  });
});
