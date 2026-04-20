<script lang="ts">
  import { onMount } from 'svelte';
  import { listRolls } from '$lib/api';
  import type { RollSummary } from '$lib/types';

  let rolls = $state<RollSummary[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      rolls = await listRolls();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load rolls';
    } finally {
      loading = false;
    }
  });

  function resultBadgeClass(result: string | null): string {
    if (!result) return 'bg-white/5 text-white/60';
    if (result.startsWith('win')) return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
    if (result.startsWith('loss')) return 'bg-rose-500/15 text-rose-300 border-rose-500/40';
    return 'bg-white/5 text-white/60 border-white/10';
  }

  function resultLabel(result: string | null): string {
    if (!result) return 'unknown';
    return result.replace(/_/g, ' ');
  }
</script>

<section class="space-y-4">
  <div class="flex items-baseline justify-between">
    <h1 class="text-2xl font-semibold tracking-tight">Rolls</h1>
    <p class="text-sm text-white/50">
      {rolls.length} analysed
    </p>
  </div>

  {#if loading}
    <p class="text-white/50 text-sm">Loading rolls from vault…</p>
  {:else if error}
    <div class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
      <strong>Couldn't load rolls:</strong>
      {error}
    </div>
  {:else if rolls.length === 0}
    <div class="rounded-lg border border-white/10 bg-white/[0.02] p-8 text-center">
      <p class="text-white/70">No rolls analysed yet.</p>
      <p class="text-white/40 text-sm mt-2">
        Upload a video to get started — the <code>Roll Log/</code> folder in your vault is empty.
      </p>
    </div>
  {:else}
    <ul class="space-y-2">
      {#each rolls as roll (roll.id)}
        <li>
          <a
            href={`/review/${encodeURIComponent(roll.id)}`}
            class="block rounded-lg border border-white/8 bg-white/[0.02] hover:bg-white/[0.05] p-4 transition-colors"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <h2 class="text-base font-medium leading-tight truncate">{roll.title}</h2>
                <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/55">
                  <span>{roll.date}</span>
                  {#if roll.partner}<span>{roll.partner}</span>{/if}
                  {#if roll.duration}<span>{roll.duration}</span>{/if}
                </div>
              </div>
              <span
                class={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${resultBadgeClass(roll.result)}`}
              >
                {resultLabel(roll.result)}
              </span>
            </div>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</section>
