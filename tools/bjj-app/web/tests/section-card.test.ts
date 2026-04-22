import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import SectionCard from '../src/lib/components/SectionCard.svelte';

const baseSection = {
  id: 'sec1',
  start_s: 3.0,
  end_s: 7.0,
  sample_interval_s: 1.0,
  narrative: 'Player A passes to side control.',
  coach_tip: 'Stay heavy.',
  analysed_at: 1713700000,
  annotations: [],
};

describe('SectionCard', () => {
  it('renders timestamp range, narrative and coach tip', () => {
    render(SectionCard, {
      section: baseSection,
      busy: false,
      onSeek: vi.fn(),
      onDelete: vi.fn(),
      onAddAnnotation: vi.fn(),
    });
    expect(screen.getByText(/0:03\s*–\s*0:07/)).toBeInTheDocument();
    expect(screen.getByText('Player A passes to side control.')).toBeInTheDocument();
    expect(screen.getByText('Stay heavy.')).toBeInTheDocument();
  });

  it('clicking Seek fires onSeek with start_s', async () => {
    const onSeek = vi.fn();
    render(SectionCard, {
      section: baseSection, busy: false,
      onSeek, onDelete: vi.fn(), onAddAnnotation: vi.fn(),
    });
    await userEvent.click(screen.getByRole('button', { name: /seek/i }));
    expect(onSeek).toHaveBeenCalledWith(3.0);
  });

  it('clicking Delete fires onDelete with section_id', async () => {
    const onDelete = vi.fn();
    render(SectionCard, {
      section: baseSection, busy: false,
      onSeek: vi.fn(), onDelete, onAddAnnotation: vi.fn(),
    });
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith('sec1');
  });

  it('shows "Analysing…" when narrative is null and busy', () => {
    render(SectionCard, {
      section: { ...baseSection, narrative: null, coach_tip: null, analysed_at: null },
      busy: true,
      onSeek: vi.fn(), onDelete: vi.fn(), onAddAnnotation: vi.fn(),
    });
    expect(screen.getByText(/analysing/i)).toBeInTheDocument();
  });

  it('submits a new annotation via textarea + Add button', async () => {
    const onAddAnnotation = vi.fn();
    render(SectionCard, {
      section: baseSection, busy: false,
      onSeek: vi.fn(), onDelete: vi.fn(), onAddAnnotation,
    });
    const user = userEvent.setup();
    await user.type(screen.getByRole('textbox', { name: /add note/i }), 'new note');
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    expect(onAddAnnotation).toHaveBeenCalledWith('sec1', 'new note');
  });

  it('renders existing annotations as bullets', () => {
    render(SectionCard, {
      section: {
        ...baseSection,
        annotations: [
          { id: 'a1', body: 'triangle was there', created_at: 1713700000 },
          { id: 'a2', body: 'too eager', created_at: 1713700100 },
        ],
      },
      busy: false,
      onSeek: vi.fn(), onDelete: vi.fn(), onAddAnnotation: vi.fn(),
    });
    expect(screen.getByText('triangle was there')).toBeInTheDocument();
    expect(screen.getByText('too eager')).toBeInTheDocument();
  });
});
