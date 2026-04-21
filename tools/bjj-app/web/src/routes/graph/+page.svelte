<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import {
    ApiError,
    getGraph,
    getGraphPaths,
    getPositionNote,
    listRolls
  } from '$lib/api';
  import FilterChips from '$lib/components/FilterChips.svelte';
  import GraphCluster from '$lib/components/GraphCluster.svelte';
  import GraphScrubber from '$lib/components/GraphScrubber.svelte';
  import PositionDrawer from '$lib/components/PositionDrawer.svelte';
  import type {
    GraphFilter,
    GraphPaths,
    GraphTaxonomy,
    PositionNote,
    RollSummary
  } from '$lib/types';

  let rolls = $state<RollSummary[]>([]);
  let taxonomy = $state<GraphTaxonomy | null>(null);
  let paths = $state<GraphPaths | null>(null);
  let selectedRollId = $state<string>('');
  let scrubTimeS = $state(0);
  let filter = $state<GraphFilter>({ kind: 'all' });
  let drawerOpen = $state(false);
  let drawerNote = $state<PositionNote | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      const [rollsRes, taxonomyRes] = await Promise.all([listRolls(), getGraph()]);
      rolls = rollsRes.filter((r) => r.roll_id !== null);
      taxonomy = taxonomyRes;
      // Apply ?roll= and ?t= query params if present.
      const url = $page.url;
      const queryRoll = url.searchParams.get('roll');
      const queryT = url.searchParams.get('t');
      if (queryRoll && rolls.find((r) => r.roll_id === queryRoll)) {
        selectedRollId = queryRoll;
        await loadPaths(queryRoll);
      }
      if (queryT !== null) {
        const t = Number(queryT);
        if (!Number.isNaN(t)) scrubTimeS = t;
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    }
  });

  async function onRollChange(e: Event) {
    const target = e.target as HTMLSelectElement;
    selectedRollId = target.value;
    if (selectedRollId) {
      await loadPaths(selectedRollId);
    } else {
      paths = null;
      scrubTimeS = 0;
    }
  }

  async function loadPaths(rollId: string) {
    try {
      paths = await getGraphPaths(rollId);
      if (scrubTimeS === 0 && paths.duration_s) {
        // leave at 0 unless query param already set it above
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    }
  }

  async function onNodeClick(positionId: string) {
    try {
      drawerNote = await getPositionNote(positionId);
    } catch (err) {
      drawerNote = null;
    }
    drawerOpen = true;
  }

  function onCloseDrawer() {
    drawerOpen = false;
  }

  function onFilterChange(next: GraphFilter) {
    filter = next;
  }

  function onScrubChange(t: number) {
    scrubTimeS = t;
  }

  const durationS = $derived(paths?.duration_s ?? 0);
</script>

<section class="flex h-[calc(100vh-4rem)] flex-col gap-3">
  <header class="flex flex-wrap items-center justify-between gap-3 px-4 py-2">
    <div class="flex items-center gap-3">
      <h1 class="text-lg font-semibold tracking-tight">BJJ Graph</h1>
      {#if taxonomy}
        <select
          aria-label="Select roll"
          value={selectedRollId}
          onchange={onRollChange}
          class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1 text-xs text-white/85"
        >
          <option value="">— select a roll —</option>
          {#each rolls as roll (roll.roll_id)}
            <option value={roll.roll_id}>{roll.title}</option>
          {/each}
        </select>
      {/if}
    </div>
    {#if taxonomy}
      <FilterChips
        categories={taxonomy.categories}
        activeFilter={filter}
        playerAName={paths?.player_a_name ?? 'Greig'}
        playerBName={paths?.player_b_name ?? 'Anthony'}
        onfilterchange={onFilterChange}
      />
    {/if}
  </header>

  {#if error}
    <div class="mx-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {error}
    </div>
  {/if}

  <div class="relative flex-1 overflow-hidden border-y border-white/8">
    {#if taxonomy}
      <GraphCluster
        variant="full"
        taxonomy={taxonomy}
        paths={paths ?? { duration_s: null, player_a_name: 'Greig', player_b_name: 'Anthony', paths: { a: [], b: [] } }}
        scrubTimeS={scrubTimeS}
        filter={filter}
        onnodeclick={onNodeClick}
      />
    {:else}
      <p class="p-6 text-sm text-white/50">Loading graph…</p>
    {/if}
  </div>

  <div class="px-4 pb-2">
    <GraphScrubber
      scrubTimeS={scrubTimeS}
      durationS={durationS}
      rollId={selectedRollId}
      onscrubchange={onScrubChange}
    />
  </div>

  <PositionDrawer open={drawerOpen} positionNote={drawerNote} onclose={onCloseDrawer} />
</section>
