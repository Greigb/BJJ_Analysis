<script lang="ts">
  import { onDestroy } from 'svelte';
  import cytoscape from 'cytoscape';
  import coseBilkent from 'cytoscape-cose-bilkent';
  import type { GraphFilter, GraphPaths, GraphTaxonomy } from '$lib/types';
  import {
    buildCytoscapeElements,
    currentPositionIds,
    headPositionAt,
    type Point2D
  } from '$lib/graph-layout';

  // Register the cose-bilkent layout extension exactly once, at module load.
  // `cytoscape.use` is idempotent — duplicate calls are no-ops.
  cytoscape.use(coseBilkent as unknown as cytoscape.Ext);

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

  const effectivePaths: GraphPaths = $derived(
    paths ?? { duration_s: null, player_a_name: 'Greig', player_b_name: 'Anthony', paths: { a: [], b: [] } }
  );

  // ---------- Cytoscape lifecycle ----------

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
        selector: 'edge.path-a',
        style: {
          width: 3,
          'line-color': 'rgba(255,255,255,0.85)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': 'rgba(255,255,255,0.85)'
        }
      },
      {
        selector: 'edge.path-b',
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
        selector: '#head-a',
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
        selector: '#head-b',
        style: {
          'background-color': '#f43f5e',
          width: 14,
          height: 14,
          'border-width': 2,
          'border-color': '#f43f5e',
          'z-index': 999
        }
      },
      {
        selector: '.mini-bg node[isCategory]',
        style: { 'background-opacity': 0.1 }
      },
      {
        selector: '.mini-bg node[!isCategory]',
        style: { opacity: 0.35 }
      },
      {
        selector: '.mini-bg edge.taxonomy',
        style: { opacity: 0.35 }
      },
      {
        selector: '.mini-bg edge.path-a, .mini-bg edge.path-b',
        style: { 'line-style': 'dashed' }
      },
      {
        selector: 'node.current-moment',
        style: {
          'border-width': 4,
          'border-color': 'rgba(251,191,36,0.85)',
          opacity: 1.0
        }
      }
    ];
  }

  function mount() {
    if (!host) return;

    const { nodes, edges } = buildCytoscapeElements(
      taxonomy,
      effectivePaths,
      variant === 'mini' ? scrubTimeS : undefined
    );

    cy = cytoscape({
      container: host,
      elements: [],
      style: baseStyle(),
      userZoomingEnabled: variant === 'full',
      userPanningEnabled: variant === 'full',
      boxSelectionEnabled: false,
      autoungrabify: variant === 'mini'
    });

    // Add all taxonomy elements via cy.add so stubs/trackers capture them.
    const miniClass = variant === 'mini' ? ' mini-bg' : '';
    const taggedNodes = nodes.map((n) => ({
      ...n,
      classes: ((n as any).classes ? (n as any).classes + ' ' : '') + miniClass.trim()
    }));
    const taggedEdges = edges.map((e) => ({
      ...e,
      classes: ((e.classes ?? '') + ' ' + miniClass).trim()
    }));
    cy.add([...taggedNodes, ...taggedEdges]);

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
      { data: { id: 'head-a' }, position: { x: 0, y: 0 }, classes: 'head' },
      { data: { id: 'head-b' }, position: { x: 0, y: 0 }, classes: 'head' }
    ]);

    // Layout the taxonomy nodes. Must run AFTER cy.add(), because the
    // constructor `layout` option only applies to elements present at
    // construction time (we construct with an empty elements list so the
    // test stub can observe add calls).
    cy.layout({
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
    } as any).run();

    updateCurrentMomentPulse();
  }

  function rebuildElements() {
    if (!cy) return;
    // Remove only path overlay edges + head markers; keep taxonomy intact.
    cy.remove('edge.path-a, edge.path-b');
    const { edges: newEdges } = buildCytoscapeElements(
      taxonomy,
      effectivePaths,
      variant === 'mini' ? scrubTimeS : undefined
    );
    const overlayEdges = newEdges.filter(
      (e) => e.classes === 'path-a' || e.classes === 'path-b'
    );
    const miniClass = variant === 'mini' ? ' mini-bg' : '';
    const taggedOverlays = overlayEdges.map((e) => ({
      ...e,
      classes: ((e.classes ?? '') + ' ' + miniClass).trim()
    }));
    cy.add(taggedOverlays);
    updateCurrentMomentPulse();
  }

  function updateHeadMarkers() {
    if (!cy) return;
    const nodeLookup = new Map<string, Point2D>();
    cy.nodes('[!isCategory]').forEach((n: any) => {
      const p = n.position();
      nodeLookup.set(n.id(), { x: p.x, y: p.y });
    });

    for (const [who, path] of [
      ['a', effectivePaths.paths.a],
      ['b', effectivePaths.paths.b]
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
        const parent = n.data('parent');
        if (parent !== `cat:${filter.id}`) n.addClass('dim');
      });
      cy.nodes('[isCategory]').forEach((n: any) => {
        if (n.id() !== `cat:${filter.id}`) n.addClass('dim');
      });
      cy.edges('.taxonomy').addClass('dim');
      cy.edges('.path-greig, .path-anthony').addClass('dim');
    } else if (filter.kind === 'player') {
      const other = filter.who === 'a' ? 'b' : 'a';
      cy.edges(`.path-${other}`).addClass('dim');
      const otherHead = cy.getElementById(`head-${other}`);
      if (otherHead && otherHead.length > 0) otherHead.addClass('dim');
    }
  }

  function updateCurrentMomentPulse() {
    if (!cy || variant !== 'mini') return;
    cy.nodes('.current-moment').removeClass('current-moment');
    const ids = currentPositionIds(effectivePaths, scrubTimeS);
    if (ids.a) {
      const n = cy.getElementById(ids.a);
      if (n && n.length > 0) n.addClass('current-moment');
    }
    if (ids.b) {
      const n = cy.getElementById(ids.b);
      if (n && n.length > 0) n.addClass('current-moment');
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

  // Update current-moment pulse on the mini variant.
  $effect(() => {
    void scrubTimeS;
    void effectivePaths;
    if (cy) updateCurrentMomentPulse();
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
