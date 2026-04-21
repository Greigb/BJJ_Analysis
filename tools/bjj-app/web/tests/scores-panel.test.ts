import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import ScoresPanel from '../src/lib/components/ScoresPanel.svelte';
import type { Moment, SummaryPayload } from '../src/lib/types';

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
      { moment_id: 'm1', note: 'Perfect triangle entry timing.' },
      { moment_id: 'm2', note: 'Got swept here — posture broke first.' },
      { moment_id: 'm3', note: 'Clean half-guard recovery.' }
    ]
  };
}

const sampleMoments: Moment[] = [
  { id: 'm1', frame_idx: 3, timestamp_s: 3.0, pose_delta: 1.0, analyses: [], annotations: [] },
  { id: 'm2', frame_idx: 45, timestamp_s: 45.0, pose_delta: 1.0, analyses: [], annotations: [] },
  { id: 'm3', frame_idx: 125, timestamp_s: 125.0, pose_delta: 1.0, analyses: [], annotations: [] }
];

describe('ScoresPanel', () => {
  it('renders three score boxes with the correct values', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
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
      moments: sampleMoments,
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
      moments: sampleMoments,
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
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/patient grips/i)).toBeInTheDocument();
    expect(screen.getByText(/strong closed guard/i)).toBeInTheDocument();
  });

  it('renders key moments with timestamp-formatted labels', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/0:03/)).toBeInTheDocument();
    expect(screen.getByText(/0:45/)).toBeInTheDocument();
    expect(screen.getByText(/2:05/)).toBeInTheDocument();
    expect(screen.getByText('Perfect triangle entry timing.')).toBeInTheDocument();
  });

  it('key-moment "go to" buttons invoke ongoto with the correct moment_id', async () => {
    const ongoto = vi.fn();
    const user = userEvent.setup();
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto
    });
    const buttons = screen.getAllByRole('button', { name: /go to/i });
    expect(buttons.length).toBe(3);
    await user.click(buttons[0]);
    expect(ongoto).toHaveBeenCalledWith('m1');
    await user.click(buttons[2]);
    expect(ongoto).toHaveBeenCalledWith('m3');
  });

  it('renders a finalised timestamp label', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/finalised/i)).toBeInTheDocument();
  });
});
