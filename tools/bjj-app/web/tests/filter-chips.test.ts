import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import FilterChips from '../src/lib/components/FilterChips.svelte';
import type { GraphCategory } from '../src/lib/types';

const categories: GraphCategory[] = [
  { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
  { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
];

describe('FilterChips', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders an "All" chip plus one chip per category plus two player chips', () => {
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'all' },
      onfilterchange: vi.fn()
    });
    expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^standing$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /guard \(bottom\)/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^player a$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^player b$/i })).toBeInTheDocument();
  });

  it('calls onfilterchange with category filter when a category chip is clicked', async () => {
    const onfilterchange = vi.fn();
    const user = userEvent.setup();
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'all' },
      onfilterchange
    });
    await user.click(screen.getByRole('button', { name: /^standing$/i }));
    expect(onfilterchange).toHaveBeenCalledWith({ kind: 'category', id: 'standing' });
  });

  it('calls onfilterchange with player filter when a player chip is clicked', async () => {
    const onfilterchange = vi.fn();
    const user = userEvent.setup();
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'all' },
      onfilterchange
    });
    await user.click(screen.getByRole('button', { name: /^player a$/i }));
    expect(onfilterchange).toHaveBeenCalledWith({ kind: 'player', who: 'a' });
  });

  it('calls onfilterchange with {kind:"all"} when "All" is clicked', async () => {
    const onfilterchange = vi.fn();
    const user = userEvent.setup();
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'category', id: 'standing' },
      onfilterchange
    });
    await user.click(screen.getByRole('button', { name: /^all$/i }));
    expect(onfilterchange).toHaveBeenCalledWith({ kind: 'all' });
  });

  it('marks the active chip with aria-pressed=true', () => {
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'category', id: 'standing' },
      onfilterchange: vi.fn()
    });
    const chip = screen.getByRole('button', { name: /^standing$/i });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    const allChip = screen.getByRole('button', { name: /^all$/i });
    expect(allChip).toHaveAttribute('aria-pressed', 'false');
  });
});
