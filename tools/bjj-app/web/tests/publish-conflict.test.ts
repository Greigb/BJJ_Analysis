import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import PublishConflictDialog from '../src/lib/components/PublishConflictDialog.svelte';

describe('PublishConflictDialog', () => {
  it('renders the conflict message and both buttons when open', () => {
    render(PublishConflictDialog, { open: true, onOverwrite: vi.fn(), onCancel: vi.fn() });
    expect(screen.getByText(/edited in Obsidian/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /overwrite/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('renders nothing when closed', () => {
    render(PublishConflictDialog, { open: false, onOverwrite: vi.fn(), onCancel: vi.fn() });
    expect(screen.queryByText(/edited in Obsidian/i)).toBeNull();
  });

  it('calls onOverwrite when Overwrite is clicked', async () => {
    const onOverwrite = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(PublishConflictDialog, { open: true, onOverwrite, onCancel });
    await user.click(screen.getByRole('button', { name: /overwrite/i }));
    expect(onOverwrite).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('calls onCancel when Cancel is clicked', async () => {
    const onOverwrite = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(PublishConflictDialog, { open: true, onOverwrite, onCancel });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onOverwrite).not.toHaveBeenCalled();
  });
});
