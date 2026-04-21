import { render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
  paths: {
    greig: [
      { timestamp_s: 0, position_id: 'standing_neutral', moment_id: 'm1' },
      { timestamp_s: 30, position_id: 'closed_guard_bottom', moment_id: 'm2' }
    ],
    anthony: []
  }
};

// Minimal Cytoscape + cose-bilkent stub for tests.
function stubCytoscape() {
  const handlers: Record<string, Array<(evt: { target: { id: () => string } }) => void>> = {};
  const mockEle = {
    id: vi.fn(() => 'standing_neutral'),
    position: vi.fn(),
    addClass: vi.fn(),
    removeClass: vi.fn(),
    style: vi.fn()
  };
  const added: Array<{ data: Record<string, unknown>; classes?: string }> = [];
  const cyInstance = {
    on: vi.fn((event: string, _selector: string, handler: (evt: { target: { id: () => string } }) => void) => {
      handlers[event] = handlers[event] || [];
      handlers[event].push(handler);
    }),
    add: vi.fn((eles: Array<{ data: Record<string, unknown>; classes?: string }>) => {
      added.push(...eles);
    }),
    remove: vi.fn(),
    getElementById: vi.fn(() => mockEle),
    nodes: vi.fn(() => ({ forEach: vi.fn(), removeClass: vi.fn(), addClass: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn(), length: added.length })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    resize: vi.fn(),
    destroy: vi.fn(),
    // Expose captured state for tests.
    __captured: { added, handlers }
  };
  const cytoscape = vi.fn(() => cyInstance);
  // cose-bilkent registers itself via cytoscape.use()
  // @ts-expect-error extension method
  cytoscape.use = vi.fn();
  // @ts-expect-error global stub
  globalThis.cytoscape = cytoscape;
  // @ts-expect-error global stub
  globalThis.cytoscapeCoseBilkent = () => {};
  return cyInstance;
}

describe('GraphCluster', () => {
  let cy: ReturnType<typeof stubCytoscape>;

  beforeEach(() => {
    cy = stubCytoscape();
  });

  afterEach(() => {
    // @ts-expect-error cleanup
    delete globalThis.cytoscape;
    // @ts-expect-error cleanup
    delete globalThis.cytoscapeCoseBilkent;
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
