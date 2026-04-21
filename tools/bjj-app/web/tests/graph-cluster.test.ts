import { render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock cytoscape + cose-bilkent imports at module boundary.
// Must be BEFORE the component import so the mock is active when it resolves.
vi.mock('cytoscape', () => {
  const handlers: Record<string, Array<(evt: { target: { id: () => string } }) => void>> = {};
  const added: Array<{ data: Record<string, unknown>; classes?: string }> = [];
  const cyInstance = {
    on: vi.fn(
      (event: string, _selector: string, handler: (evt: { target: { id: () => string } }) => void) => {
        handlers[event] = handlers[event] || [];
        handlers[event].push(handler);
      }
    ),
    add: vi.fn((eles: Array<{ data: Record<string, unknown>; classes?: string }>) => {
      if (Array.isArray(eles)) added.push(...eles);
    }),
    remove: vi.fn(),
    getElementById: vi.fn(() => ({
      id: vi.fn(() => 'standing_neutral'),
      position: vi.fn(),
      addClass: vi.fn(),
      removeClass: vi.fn(),
      style: vi.fn(),
      length: 1
    })),
    nodes: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn(), length: 0, remove: vi.fn() })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn(), remove: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn(), stop: vi.fn() })),
    fit: vi.fn(),
    resize: vi.fn(),
    destroy: vi.fn(),
    __captured: { added, handlers }
  };
  const cytoscape = vi.fn(() => cyInstance);
  (cytoscape as any).use = vi.fn();
  return { default: cytoscape, __cyInstance: cyInstance };
});

vi.mock('cytoscape-cose-bilkent', () => ({ default: () => {} }));

import GraphCluster from '../src/lib/components/GraphCluster.svelte';
import type { GraphPaths, GraphTaxonomy } from '../src/lib/types';

const taxonomy: GraphTaxonomy = {
  categories: [
    { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
    { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
  ],
  positions: [
    { id: 'standing_neutral', name: 'Standing', category: 'standing' },
    { id: 'closed_guard_bottom', name: 'CG Bottom', category: 'guard_bottom' }
  ],
  transitions: [{ from: 'standing_neutral', to: 'closed_guard_bottom' }]
};

const paths: GraphPaths = {
  duration_s: 60,
  player_a_name: 'Player A',
  player_b_name: 'Player B',
  paths: {
    a: [
      { timestamp_s: 0, position_id: 'standing_neutral', moment_id: 'm1' },
      { timestamp_s: 30, position_id: 'closed_guard_bottom', moment_id: 'm2' }
    ],
    b: []
  }
};

describe('GraphCluster', () => {
  let cy: any;

  beforeEach(async () => {
    // Read the shared mock instance exposed by the vi.mock factory.
    const mod = await import('cytoscape');
    cy = (mod as any).__cyInstance;
    // Reset captures between tests.
    cy.__captured.added.length = 0;
    for (const k of Object.keys(cy.__captured.handlers)) {
      delete cy.__captured.handlers[k];
    }
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a container with data-variant="full" by default', async () => {
    const { container } = render(GraphCluster, {
      variant: 'full',
      taxonomy,
      paths
    });
    const host = container.querySelector('[data-graphcluster]');
    expect(host).not.toBeNull();
    expect(host!.getAttribute('data-variant')).toBe('full');
  });

  it('renders a container with data-variant="mini" when variant is mini', () => {
    const { container } = render(GraphCluster, {
      variant: 'mini',
      taxonomy,
      paths
    });
    const host = container.querySelector('[data-graphcluster]');
    expect(host!.getAttribute('data-variant')).toBe('mini');
  });

  it('instantiates Cytoscape with elements derived from the taxonomy', async () => {
    render(GraphCluster, { variant: 'full', taxonomy, paths });
    await waitFor(() => {
      expect(cy.__captured.added.length).toBeGreaterThan(0);
    });
    // Category compound parents emitted
    const categoryNodes = cy.__captured.added.filter(
      (e) => e.data.isCategory === true
    );
    expect(categoryNodes.length).toBe(2);
  });

  it('invokes onnodeclick when a node tap event fires', async () => {
    const onnodeclick = vi.fn();
    render(GraphCluster, { variant: 'full', taxonomy, paths, onnodeclick });
    await waitFor(() => {
      expect(cy.on).toHaveBeenCalledWith('tap', 'node', expect.any(Function));
    });
    const tapHandler = cy.__captured.handlers['tap']?.[0];
    expect(tapHandler).toBeDefined();
    tapHandler!({ target: { id: () => 'standing_neutral' } });
    expect(onnodeclick).toHaveBeenCalledWith('standing_neutral');
  });
});
