<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { getRoll, ApiError } from '$lib/api';
  import type { RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  onMount(async () => {
    const id = $page.params.id;
    try {
      roll = await getRoll(id);
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      loading = false;
    }
  });

  function formatDuration(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }
</script>

{#if loading}
  <p class="text-white/50 text-sm">Loading roll…</p>
{:else if error || !roll}
  <div class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
    <strong>Couldn't load roll:</strong>
    {error ?? 'Unknown error'}
  </div>
{:else}
  <section class="space-y-5">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight">{roll.title}</h1>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/55">
          <span>{roll.date}</span>
          {#if roll.partner}<span>{roll.partner}</span>{/if}
          <span>{formatDuration(roll.duration_s)}</span>
        </div>
      </div>
      <div class="flex gap-2">
        <button
          type="button"
          disabled
          title="Pose pre-pass arrives in M2b"
          class="rounded-md px-3 py-1.5 text-xs font-medium bg-white/5 border border-white/10 text-white/50 cursor-not-allowed"
        >
          Analyse
        </button>
      </div>
    </header>

    <div class="rounded-lg overflow-hidden border border-white/8 bg-black">
      <video controls preload="metadata" class="w-full aspect-video bg-black">
        <source src={roll.video_url} type="video/mp4" />
        Your browser can't play this video file.
      </video>
    </div>

    <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
      <p class="text-sm text-white/60">Timeline populates after analysis.</p>
      <p class="mt-1 text-xs text-white/35">
        Pose pre-pass + Claude Opus 4.7 moment analysis arrive in upcoming milestones.
      </p>
    </div>
  </section>
{/if}
