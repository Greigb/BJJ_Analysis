import { describe, expect, it } from 'vitest';

import {
  buildCytoscapeElements,
  currentPositionIds,
  headPositionAt,
  lerp
} from '../src/lib/graph-layout';
import type { GraphPaths, GraphTaxonomy, PathPoint } from '../src/lib/types';

const tinyTaxonomy: GraphTaxonomy = {
  categories: [
    { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
    { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
  ],
  positions: [
    { id: 'standing_neutral', name: 'Standing', category: 'standing' },
    { id: 'closed_guard_bottom', name: 'CG Bottom', category: 'guard_bottom' },
    { id: 'half_guard_bottom', name: 'HG Bottom', category: 'guard_bottom' }
  ],
  transitions: [{ from: 'standing_neutral', to: 'closed_guard_bottom' }]
};

const emptyPaths: GraphPaths = {
  duration_s: 60,
  paths: { greig: [], anthony: [] }
};

function path(points: Array<[number, string]>): PathPoint[] {
  return points.map(([t, id], i) => ({
    timestamp_s: t,
    position_id: id,
    moment_id: `m-${i}`
  }));
}

describe('lerp', () => {
  it('returns a at t=0', () => {
    expect(lerp(10, 20, 0)).toBe(10);
  });
  it('returns b at t=1', () => {
    expect(lerp(10, 20, 1)).toBe(20);
  });
  it('interpolates midpoint at t=0.5', () => {
    expect(lerp(10, 20, 0.5)).toBe(15);
  });
});

describe('buildCytoscapeElements', () => {
  it('emits compound parent nodes per category', () => {
    const { nodes } = buildCytoscapeElements(tinyTaxonomy, emptyPaths);
    const compoundNodes = nodes.filter((n) => n.data.isCategory === true);
    expect(compoundNodes.map((n) => n.data.id).sort()).toEqual([
      'cat:guard_bottom',
      'cat:standing'
    ]);
  });

  it('emits a position node for every taxonomy position with the correct parent', () => {
    const { nodes } = buildCytoscapeElements(tinyTaxonomy, emptyPaths);
    const posNodes = nodes.filter((n) => n.data.isCategory !== true);
    expect(posNodes.length).toBe(3);
    const cg = posNodes.find((n) => n.data.id === 'closed_guard_bottom')!;
    expect(cg.data.parent).toBe('cat:guard_bottom');
    expect(cg.data.label).toBe('CG Bottom');
  });

  it('emits taxonomy edges with a "taxonomy" class', () => {
    const { edges } = buildCytoscapeElements(tinyTaxonomy, emptyPaths);
    const taxEdges = edges.filter((e) => e.classes === 'taxonomy');
    expect(taxEdges.length).toBe(1);
    expect(taxEdges[0].data.source).toBe('standing_neutral');
    expect(taxEdges[0].data.target).toBe('closed_guard_bottom');
  });

  it('emits path overlay edges for each consecutive pair of analysed moments', () => {
    const paths: GraphPaths = {
      duration_s: 60,
      paths: {
        greig: path([
          [3, 'standing_neutral'],
          [10, 'closed_guard_bottom'],
          [30, 'half_guard_bottom']
        ]),
        anthony: []
      }
    };
    const { edges } = buildCytoscapeElements(tinyTaxonomy, paths);
    const overlay = edges.filter((e) => e.classes === 'path-greig');
    expect(overlay.length).toBe(2);
    expect(overlay[0].data.source).toBe('standing_neutral');
    expect(overlay[0].data.target).toBe('closed_guard_bottom');
    expect(overlay[1].data.source).toBe('closed_guard_bottom');
    expect(overlay[1].data.target).toBe('half_guard_bottom');
  });

  it('does not emit overlay edges for a path with fewer than 2 points', () => {
    const paths: GraphPaths = {
      duration_s: 60,
      paths: {
        greig: path([[3, 'standing_neutral']]),
        anthony: []
      }
    };
    const { edges } = buildCytoscapeElements(tinyTaxonomy, paths);
    const overlay = edges.filter(
      (e) => e.classes === 'path-greig' || e.classes === 'path-anthony'
    );
    expect(overlay.length).toBe(0);
  });
});

describe('headPositionAt', () => {
  const nodeLookup = new Map([
    ['standing_neutral', { x: 0, y: 0 }],
    ['closed_guard_bottom', { x: 100, y: 0 }],
    ['half_guard_bottom', { x: 100, y: 100 }]
  ]);

  it('returns null when path is empty', () => {
    expect(headPositionAt([], 5, nodeLookup)).toBeNull();
  });

  it('returns null when scrub time is before the first path point', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    expect(headPositionAt(p, 5, nodeLookup)).toBeNull();
  });

  it('returns the last node position when scrub time is after the last point', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    const pos = headPositionAt(p, 30, nodeLookup);
    expect(pos).toEqual({ x: 100, y: 0 });
  });

  it('returns the exact node position at a point timestamp', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    expect(headPositionAt(p, 10, nodeLookup)).toEqual({ x: 0, y: 0 });
  });

  it('interpolates linearly between consecutive points', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    const pos = headPositionAt(p, 15, nodeLookup);
    // Halfway between (0,0) and (100,0) at t=0.5 → (50, 0).
    expect(pos).toEqual({ x: 50, y: 0 });
  });

  it('interpolates on the correct segment when given multiple points', () => {
    const p = path([
      [0, 'standing_neutral'],
      [10, 'closed_guard_bottom'],
      [20, 'half_guard_bottom']
    ]);
    // At t=15 we should be halfway on the CG->HG edge: (100,0) -> (100,100) → (100,50).
    const pos = headPositionAt(p, 15, nodeLookup);
    expect(pos).toEqual({ x: 100, y: 50 });
  });

  it('returns null when a referenced node is missing from the lookup', () => {
    const p = path([[10, 'unknown_id'], [20, 'closed_guard_bottom']]);
    expect(headPositionAt(p, 15, nodeLookup)).toBeNull();
  });
});

describe('currentPositionIds', () => {
  const paths: GraphPaths = {
    duration_s: 60,
    paths: {
      greig: [
        { timestamp_s: 5, position_id: 'standing_neutral', moment_id: 'g1' },
        { timestamp_s: 20, position_id: 'closed_guard_bottom', moment_id: 'g2' }
      ],
      anthony: [
        { timestamp_s: 5, position_id: 'standing_neutral', moment_id: 'a1' }
      ]
    }
  };

  it('returns null for players with no points before scrubTimeS', () => {
    const ids = currentPositionIds(paths, 2);
    expect(ids).toEqual({ greig: null, anthony: null });
  });

  it('returns the last position each player was at as of scrubTimeS', () => {
    const ids = currentPositionIds(paths, 10);
    expect(ids).toEqual({
      greig: 'standing_neutral',
      anthony: 'standing_neutral'
    });
  });

  it('advances greig to closed_guard_bottom after his second point', () => {
    const ids = currentPositionIds(paths, 25);
    expect(ids).toEqual({
      greig: 'closed_guard_bottom',
      anthony: 'standing_neutral'
    });
  });
});
