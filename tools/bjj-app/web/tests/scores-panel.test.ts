import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import ScoresPanel from '../src/lib/components/ScoresPanel.svelte';
import type { Section, SummaryPayload } from '../src/lib/types';

function sampleScores(): SummaryPayload {
  return {
    summary: 'A strong roll with good guard retention.',
    scores: {
      guard_retention: 8,
      positional_awareness: 6,
      transition_quality: 7
    },
    top_improvements: [
      'Keep elbows tight when posture is broken.',
      'Frame earlier when the pass shot fires.',
      "Don't overcommit to hip-bump sweeps."
    ],
    strengths: ['Patient grips', 'Strong closed guard'],
    key_moments: [
      { section_id: 's1', note: 'Perfect triangle entry timing.' },
      { section_id: 's2', note: 'Got swept here — posture broke first.' },
      { section_id: 's3', note: 'Clean half-guard recovery.' }
    ]
  };
}

const sampleSections: Section[] = [
  { id: 's1', start_s: 180, end_s: 300, sample_interval_s: 1.0, narrative: null, coach_tip: null, analysed_at: null, annotations: [] },
  { id: 's2', start_s: 45, end_s: 90, sample_interval_s: 1.0, narrative: null, coach_tip: null, analysed_at: null, annotations: [] },
  { id: 's3', start_s: 125, end_s: 200, sample_interval_s: 1.0, narrative: null, coach_tip: null, analysed_at: null, annotations: [] }
];

describe('ScoresPanel', () => {
  it('renders three score boxes with the correct values', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText('8/10')).toBeInTheDocument();
    expect(screen.getByText('6/10')).toBeInTheDocument();
    expect(screen.getByText('7/10')).toBeInTheDocument();
  });

  it('renders the one-sentence summary', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(
      screen.getByText('A strong roll with good guard retention.')
    ).toBeInTheDocument();
  });

  it('renders top improvements as a numbered list', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/keep elbows tight/i)).toBeInTheDocument();
    expect(screen.getByText(/frame earlier/i)).toBeInTheDocument();
    expect(screen.getByText(/don't overcommit/i)).toBeInTheDocument();
  });

  it('renders strengths as bullets', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/patient grips/i)).toBeInTheDocument();
    expect(screen.getByText(/strong closed guard/i)).toBeInTheDocument();
  });

  it('renders key moments with section range labels', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    // s1: 180s–300s → 3:00 – 5:00
    expect(screen.getByText(/3:00/)).toBeInTheDocument();
    expect(screen.getByText(/5:00/)).toBeInTheDocument();
    expect(screen.getByText('Perfect triangle entry timing.')).toBeInTheDocument();
  });

  it('key-moment "go to" buttons invoke ongoto with the correct section_id', async () => {
    const ongoto = vi.fn();
    const user = userEvent.setup();
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto
    });
    const buttons = screen.getAllByRole('button', { name: /go to/i });
    expect(buttons.length).toBe(3);
    await user.click(buttons[0]);
    expect(ongoto).toHaveBeenCalledWith('s1');
    await user.click(buttons[2]);
    expect(ongoto).toHaveBeenCalledWith('s3');
  });

  it('renders a finalised timestamp label', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      sections: sampleSections,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/finalised/i)).toBeInTheDocument();
  });
});
