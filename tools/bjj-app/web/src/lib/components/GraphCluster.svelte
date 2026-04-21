<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { GraphFilter, GraphPaths, GraphTaxonomy } from '$lib/types';
  import {
    buildCytoscapeElements,
    headPositionAt,
    type Point2D
  } from '$lib/graph-layout';

  let {
    variant,
    taxonomy,
    paths,
    scrubTimeS = 0,
    filter = { kind: 'all' } as GraphFilter,
    onnodeclick
  }: {
    variant: 'full' | 'mini';
    taxonomy: GraphTaxonomy;
    paths?: GraphPaths;
    scrubTimeS?: number;
    filter?: GraphFilter;
    onnodeclick?: (positionId: string) => void;
  } = $props();

  let host: HTMLDivElement | undefined = $state();
  let cy: any = null;          // Cytoscape instance
  let coseRegistered = false;  // one-time registration

  const effectivePaths: GraphPaths = $derived(
    paths ?? { duration_s: null, paths: { greig: [], anthony: [] } }
  );

  // ---------- Cytoscape lifecycle ----------

  function registerCoseOnce() {
    if (coseRegistered) return;
    // @ts-expect-error globals from CDN
    if (typeof globalThis.cytoscape === 'function' && typeof globalThis.cytoscapeCoseBilkent === 'function') {
      // @ts-expect-error cytoscape.use global
      globalThis.cytoscape.use(globalThis.cytoscapeCoseBilkent);
      coseRegistered = true;
    }
  }

  function baseStyle(): any[] {
    return [
      {
        selector: 'node[isCategory]',
        style: {
          'background-color': 'data(tint)',
          'background-opacity': 0.25,
          'border-width': 0,
          label: 'data(label)',
          'text-valign': 'top',
          'text-halign': 'center',
          'font-size': 10,
          color: '#ccc',
          'padding-top': '20px',
          'padding-bottom': '20px',
          'padding-left': '20px',
          'padding-right': '20px',
          shape: 'round-rectangle'
        }
      },
      {
        selector: 'node[!isCategory]',
        style: {
          'background-color': '#333',
          'border-color': 'rgba(255,255,255,0.3)',
          'border-width': 1,
          label: 'data(label)',
          'font-size': 9,
          color: 'rgba(255,255,255,0.75)',
          'text-wrap': 'wrap',
          'text-max-width': '70px',
          'text-valign': 'center',
          'text-halign': 'center',
          width: 28,
          height: 28
        }
      },
      {
        selector: 'edge.taxonomy',
        style: {
          width: 1,
          'line-color': 'rgba(255,255,255,0.08)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'none'
        }
      },
      {
        selector: 'edge.path-greig',
        style: {
          width: 3,
          'line-color': 'rgba(255,255,255,0.85)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': 'rgba(255,255,255,0.85)'
        }
      },
      {
        selector: 'edge.path-anthony',
        style: {
          width: 3,
          'line-color': 'rgba(244,63,94,0.85)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': 'rgba(244,63,94,0.85)'
        }
      },
      {
        selector: '.dim',
        style: { opacity: 0.2 }
      },
      {
        selector: '#head-greig',
        style: {
          'background-color': '#ffffff',
          width: 14,
          height: 14,
          'border-width': 2,
          'border-color': '#ffffff',
          'z-index': 999
        }
      },
      {
        selector: '#head-anthony',
        style: {
          'background-color': '#f43f5e',
          width: 14,
          height: 14,
          'border-width': 2,
          'border-color': '#f43f5e',
          'z-index': 999
        }
      }
    ];
  }

  function mount() {
    if (!host) return;
    // @ts-expect-error cytoscape global
    const cytoscape = globalThis.cytoscape;
    if (typeof cytoscape !== 'function') {
      return; // CDN not loaded; graceful no-op
    }

    registerCoseOnce();

    const { nodes, edges } = buildCytoscapeElements(taxonomy, effectivePaths);

    cy = cytoscape({
      container: host,
      elements: [],
      style: baseStyle(),
      layout: {
        name: 'cose-bilkent',
        animate: false,
        randomize: false,
        fit: true,
        padding: 20,
        nodeRepulsion: 4500,
        idealEdgeLength: 80,
        edgeElasticity: 0.1,
        gravityRangeCompound: 1.5,
        gravityCompound: 1.0,
        tile: true
      } as any,
      userZoomingEnabled: variant === 'full',
      userPanningEnabled: variant === 'full',
      boxSelectionEnabled: false,
      autoungrabify: variant === 'mini'
    });

    // Add all taxonomy elements via cy.add so stubs/trackers capture them.
    cy.add([...nodes, ...edges]);

    if (onnodeclick) {
      cy.on('tap', 'node', (evt: { target: { id: () => string } }) => {
        const id = evt.target.id();
        // Ignore taps on compound parent nodes.
        if (!id.startsWith('cat:')) {
          onnodeclick(id);
        }
      });
    }

    // Add player head markers (invisible initially; updated via effect).
    cy.add([
      { data: { id: 'head-greig' }, position: { x: 0, y: 0 }, classes: 'head' },
      { data: { id: 'head-anthony' }, position: { x: 0, y: 0 }, classes: 'head' }
    ]);
  }

  function rebuildElements() {
    if (!cy) return;
    // Remove only path overlay edges + head markers; keep taxonomy intact.
    cy.remove('edge.path-greig, edge.path-anthony');
    const { edges: newEdges } = buildCytoscapeElements(taxonomy, effectivePaths);
    const overlayEdges = newEdges.filter(
      (e) => e.classes === 'path-greig' || e.classes === 'path-anthony'
    );
    cy.add(overlayEdges);
  }

  function updateHeadMarkers() {
    if (!cy) return;
    const nodeLookup = new Map<string, Point2D>();
    cy.nodes('[!isCategory]').forEach((n: any) => {
      const p = n.position();
      nodeLookup.set(n.id(), { x: p.x, y: p.y });
    });

    for (const [who, path] of [
      ['greig', effectivePaths.paths.greig],
      ['anthony', effectivePaths.paths.anthony]
    ] as const) {
      const head = cy.getElementById(`head-${who}`);
      if (!head || head.length === 0) continue;
      const pos = headPositionAt(path, scrubTimeS, nodeLookup);
      if (pos === null) {
        head.style('display', 'none');
      } else {
        head.style('display', 'element');
        head.position(pos);
      }
    }
  }

  function applyFilter() {
    if (!cy) return;
    cy.elements().removeClass('dim');
    if (filter.kind === 'all') return;
    if (filter.kind === 'category') {
      // Dim everything NOT in the selected category.
      cy.nodes('[!isCategory]').forEach((n: any) => {
        // Cytoscape returns parent id via n.data('parent').
        const parent = n.data('parent');
        if (parent !== `cat:${filter.id}`) n.addClass('dim');
      });
      cy.edges('.taxonomy').addClass('dim');
      cy.edges('.path-greig, .path-anthony').addClass('dim');
    } else if (filter.kind === 'player') {
      const other = filter.who === 'greig' ? 'anthony' : 'greig';
      cy.edges(`.path-${other}`).addClass('dim');
      const otherHead = cy.getElementById(`head-${other}`);
      if (otherHead && otherHead.length > 0) otherHead.addClass('dim');
    }
  }

  // Mount once when host is ready.
  $effect(() => {
    if (host && !cy) {
      mount();
      updateHeadMarkers();
    }
  });

  // Rebuild path overlays + markers when paths change.
  $effect(() => {
    // Read so the effect re-runs on changes.
    void effectivePaths;
    if (cy) {
      rebuildElements();
      updateHeadMarkers();
    }
  });

  // Update head markers as scrubTimeS changes.
  $effect(() => {
    void scrubTimeS;
    if (cy) updateHeadMarkers();
  });

  // Apply filter changes.
  $effect(() => {
    void filter;
    if (cy) applyFilter();
  });

  onDestroy(() => {
    if (cy) {
      cy.destroy();
      cy = null;
    }
  });
</script>

<div
  data-graphcluster
  data-variant={variant}
  class="h-full w-full {variant === 'mini' ? 'min-h-[200px]' : 'min-h-[500px]'}"
  bind:this={host}
></div>
