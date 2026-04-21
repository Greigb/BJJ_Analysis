import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

// $app/stores has to be mocked for page store access (matches home.test.ts pattern).
vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { url: URL }) => void) => {
      run({ url: new URL('http://localhost/graph') });
      return () => {};
    }
  }
}));

vi.mock('cytoscape', () => {
  const cyInstance: any = {
    on: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    getElementById: vi.fn(() => ({ length: 0, style: vi.fn(), position: vi.fn(), addClass: vi.fn(), removeClass: vi.fn() })),
    nodes: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn(), length: 0, remove: vi.fn() })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn(), remove: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn(), stop: vi.fn() })),
    fit: vi.fn(),
    resize: vi.fn(),
    destroy: vi.fn()
  };
  const cytoscape = vi.fn(() => cyInstance);
  (cytoscape as any).use = vi.fn();
  return { default: cytoscape };
});
vi.mock('cytoscape-cose-bilkent', () => ({ default: () => {} }));
vi.mock('marked', () => ({ marked: { parse: (s: string) => s } }));

describe('/graph page', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches taxonomy on mount and renders the GraphCluster', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [] // GET /api/rolls → empty list
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [{ id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' }],
        positions: [{ id: 'standing_neutral', name: 'Standing', category: 'standing' }],
        transitions: []
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const { default: Page } = await import('../src/routes/graph/+page.svelte');
    const { container } = render(Page);

    await waitFor(() => {
      expect(container.querySelector('[data-graphcluster]')).not.toBeNull();
    });
  });

  it('fetches paths when a roll is selected and passes them to GraphCluster', async () => {
    const fetchMock = vi.fn();
    // 1. GET /api/rolls
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [
        {
          id: '2026-04-21 - sample',
          title: 'Sample roll',
          date: '2026-04-21',
          partner: null,
          duration: null,
          result: null,
          roll_id: 'uuid-123'
        }
      ]
    });
    // 2. GET /api/graph
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [{ id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' }],
        positions: [{ id: 'standing_neutral', name: 'Standing', category: 'standing' }],
        transitions: []
      })
    });
    // 3. GET /api/graph/paths/uuid-123
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        duration_s: 60,
        player_a_name: 'Greig',
        player_b_name: 'Anthony',
        paths: { a: [], b: [] }
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/graph/+page.svelte');
    render(Page);

    // Wait for the dropdown to appear and select the roll.
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByRole('combobox'), 'uuid-123');

    await waitFor(() => {
      const pathsCall = fetchMock.mock.calls.find((c) => c[0].includes('/graph/paths/'));
      expect(pathsCall).toBeDefined();
    });
  });

  it('renders filter chips once the taxonomy has loaded', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => []
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [
          { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
          { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
        ],
        positions: [],
        transitions: []
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const { default: Page } = await import('../src/routes/graph/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^standing$/i })).toBeInTheDocument();
    });
  });
});
