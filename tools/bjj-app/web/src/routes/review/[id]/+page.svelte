<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { analyseRoll, ApiError, getRoll } from '$lib/api';
  import type { AnalyseEvent, Moment, RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let analysing = $state(false);
  let progress = $state<{ stage: string; pct: number } | null>(null);

  // Refs for video seeking from chip clicks.
  let videoEl: HTMLVideoElement | undefined = $state();

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

  async function onAnalyseClick() {
    if (!roll || analysing) return;
    analysing = true;
    progress = { stage: 'frames', pct: 0 };
    try {
      for await (const event of analyseRoll(roll.id)) {
        handleAnalyseEvent(event);
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
      progress = null;
    }
  }

  function handleAnalyseEvent(event: AnalyseEvent) {
    if (event.stage === 'done') {
      if (!roll) return;
      // Server assigns ids on persistence; for immediate UI we fabricate
      // stable keys from frame_idx — they'll be replaced on the next refresh.
      roll.moments = event.moments.map((m) => ({
        id: `pending-${m.frame_idx}`,
        frame_idx: m.frame_idx,
        timestamp_s: m.timestamp_s,
        pose_delta: m.pose_delta
      })) as Moment[];
      progress = { stage: 'done', pct: 100 };
    } else {
      progress = { stage: event.stage, pct: event.pct };
    }
  }

  function formatDuration(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function progressLabel(p: { stage: string; pct: number } | null): string {
    if (!p) return '';
    if (p.stage === 'frames') return `Extracting frames… ${p.pct}%`;
    if (p.stage === 'pose') return `Detecting poses… ${p.pct}%`;
    if (p.stage === 'done') return 'Analysis complete';
    return `${p.stage}… ${p.pct}%`;
  }

  function seekTo(seconds: number) {
    if (videoEl) {
      videoEl.currentTime = seconds;
      videoEl.play().catch(() => {
        /* autoplay may be blocked; it's fine */
      });
    }
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
          onclick={onAnalyseClick}
          disabled={analysing}
          class="rounded-md px-3 py-1.5 text-xs font-medium bg-blue-500/20 border border-blue-400/40 text-blue-100 hover:bg-blue-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {analysing ? 'Analysing…' : 'Analyse'}
        </button>
      </div>
    </header>

    <div class="rounded-lg overflow-hidden border border-white/8 bg-black">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videoEl}
        controls
        preload="metadata"
        class="w-full aspect-video bg-black"
      >
        <source src={roll.video_url} type="video/mp4" />
        Your browser can't play this video file.
      </video>
    </div>

    {#if progress}
      <div
        class="rounded-md border border-white/10 bg-white/[0.02] px-4 py-2 text-xs text-white/65"
        role="status"
      >
        {progressLabel(progress)}
      </div>
    {/if}

    {#if roll.moments.length > 0}
      <div class="space-y-2">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
          Moments ({roll.moments.length})
        </div>
        <div class="flex flex-wrap gap-1.5">
          {#each roll.moments as moment (moment.id)}
            <button
              type="button"
              onclick={() => seekTo(moment.timestamp_s)}
              class="rounded-md border border-dashed border-white/20 bg-white/[0.02] hover:bg-white/[0.05] hover:border-white/40 px-2.5 py-1 text-xs font-mono tabular-nums text-white/75 transition-colors"
            >
              {formatMomentTime(moment.timestamp_s)}
            </button>
          {/each}
        </div>
        <p class="text-[11px] text-white/35">
          Click a chip to jump the video there. Position classification via Claude Opus 4.7
          arrives in M3.
        </p>
      </div>
    {:else if !analysing}
      <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
        <p class="text-sm text-white/60">No moments yet.</p>
        <p class="mt-1 text-xs text-white/35">
          Click <strong>Analyse</strong> to run the pose pre-pass and flag interesting moments.
        </p>
      </div>
    {/if}
  </section>
{/if}
