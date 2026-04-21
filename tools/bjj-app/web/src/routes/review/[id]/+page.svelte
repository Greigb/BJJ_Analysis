<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import {
    analyseRoll,
    ApiError,
    getGraph,
    getGraphPaths,
    getRoll,
    publishRoll,
    PublishConflictError,
    summariseRoll,
    SummariseRateLimitedError
  } from '$lib/api';
  import GraphCluster from '$lib/components/GraphCluster.svelte';
  import MomentDetail from '$lib/components/MomentDetail.svelte';
  import PublishConflictDialog from '$lib/components/PublishConflictDialog.svelte';
  import ScoresPanel from '$lib/components/ScoresPanel.svelte';
  import type { AnalyseEvent, GraphPaths, GraphTaxonomy, Moment, RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let analysing = $state(false);
  let progress = $state<{ stage: string; pct: number } | null>(null);
  let selectedMomentId = $state<string | null>(null);
  let publishing = $state(false);
  let publishError = $state<string | null>(null);
  let publishToast = $state<string | null>(null);
  let conflictOpen = $state(false);
  let finalising = $state(false);
  let finaliseError = $state<string | null>(null);

  let videoEl: HTMLVideoElement | undefined = $state();
  let graphTaxonomy = $state<GraphTaxonomy | null>(null);
  let graphPaths = $state<GraphPaths | null>(null);

  const selectedMoment = $derived(
    roll?.moments.find((m) => m.id === selectedMomentId) ?? null
  );

  const hasAnyAnalyses = $derived(
    roll?.moments?.some((m) => m.analyses.length > 0) ?? false
  );

  onMount(async () => {
    const id = $page.params.id;
    try {
      roll = await getRoll(id);
      try {
        graphTaxonomy = await getGraph();
        graphPaths = await getGraphPaths(id);
      } catch {
        // Mini graph is a nice-to-have; ignore failures so the review page still loads.
      }

      // Honor ?t=<seconds> by pre-seeking the video once it's loaded.
      const queryT = $page.url.searchParams.get('t');
      if (queryT !== null && videoEl) {
        const t = Number(queryT);
        if (!Number.isNaN(t)) {
          // If the video metadata hasn't loaded yet, defer the seek.
          const seek = () => {
            if (videoEl) videoEl.currentTime = t;
          };
          if (videoEl.readyState >= 1) {
            seek();
          } else {
            videoEl.addEventListener('loadedmetadata', seek, { once: true });
          }
        }
      }
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
      roll.moments = event.moments.map((m) => ({
        id: `pending-${m.frame_idx}`,
        frame_idx: m.frame_idx,
        timestamp_s: m.timestamp_s,
        pose_delta: m.pose_delta,
        analyses: [],
        annotations: []
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

  function onChipClick(moment: Moment) {
    selectedMomentId = moment.id;
    if (videoEl) {
      videoEl.currentTime = moment.timestamp_s;
      const playPromise = videoEl.play();
      if (playPromise !== undefined) {
        playPromise.catch(() => {
          /* autoplay may be blocked; that's fine */
        });
      }
    }
  }

  function onMomentAnalysed(updated: Moment) {
    if (!roll) return;
    roll.moments = roll.moments.map((m) => (m.id === updated.id ? updated : m));
  }

  function onMomentAnnotated(updated: Moment) {
    if (!roll) return;
    roll.moments = roll.moments.map((m) => (m.id === updated.id ? updated : m));
  }

  function chipStateClass(m: Moment, isSelected: boolean): string {
    const base = 'rounded-md px-2.5 py-1 text-xs font-mono tabular-nums transition-colors';
    if (m.analyses.length > 0) {
      return `${base} border bg-emerald-500/15 border-emerald-400/40 text-emerald-100 hover:bg-emerald-500/25${
        isSelected ? ' ring-1 ring-emerald-300' : ''
      }`;
    }
    return `${base} border border-dashed bg-white/[0.02] border-white/20 text-white/75 hover:bg-white/[0.05] hover:border-white/40${
      isSelected ? ' ring-1 ring-white/40' : ''
    }`;
  }

  async function onSaveToVault(options: { force?: boolean } = {}) {
    if (!roll || publishing) return;
    publishing = true;
    publishError = null;
    publishToast = null;
    try {
      const result = await publishRoll(roll.id, options);
      publishToast = `Published to ${result.vault_path}`;
      roll.vault_path = result.vault_path;
      roll.vault_published_at = result.vault_published_at;
    } catch (err) {
      if (err instanceof PublishConflictError) {
        conflictOpen = true;
      } else {
        publishError = err instanceof ApiError ? err.message : String(err);
      }
    } finally {
      publishing = false;
    }
  }

  async function onOverwrite() {
    conflictOpen = false;
    await onSaveToVault({ force: true });
  }

  function onCancelConflict() {
    conflictOpen = false;
  }

  async function onFinaliseClick() {
    if (!roll || finalising) return;
    if (!hasAnyAnalyses) return;
    finalising = true;
    finaliseError = null;
    try {
      const result = await summariseRoll(roll.id);
      roll.finalised_at = result.finalised_at;
      roll.scores = result.scores;
      roll.distribution = result.distribution;
    } catch (err) {
      if (err instanceof SummariseRateLimitedError) {
        finaliseError = `Claude cooldown — ${err.retryAfterS}s until next call`;
      } else if (err instanceof ApiError) {
        finaliseError = err.message;
      } else {
        finaliseError = String(err);
      }
    } finally {
      finalising = false;
    }
  }

  function onKeyMomentGoTo(momentId: string) {
    const moment = roll?.moments.find((m) => m.id === momentId);
    if (moment) onChipClick(moment);
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
              onclick={() => onChipClick(moment)}
              class={chipStateClass(moment, moment.id === selectedMomentId)}
            >
              {formatMomentTime(moment.timestamp_s)}
            </button>
          {/each}
        </div>
      </div>

      {#if roll.scores && roll.finalised_at}
        <ScoresPanel
          scores={roll.scores}
          moments={roll.moments}
          finalisedAt={roll.finalised_at}
          ongoto={onKeyMomentGoTo}
        />
      {/if}

      {#if selectedMoment}
        <MomentDetail
          rollId={roll.id}
          moment={selectedMoment}
          playerAName={roll.player_a_name}
          playerBName={roll.player_b_name}
          onanalysed={onMomentAnalysed}
          onannotated={onMomentAnnotated}
        />
        {#if graphTaxonomy && graphPaths}
          <section class="space-y-2 border-t border-white/8 pt-4">
            <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Graph at this moment
            </div>
            <div class="h-[220px] rounded-md overflow-hidden border border-white/8">
              <GraphCluster
                variant="mini"
                taxonomy={graphTaxonomy}
                paths={graphPaths}
                scrubTimeS={selectedMoment.timestamp_s}
              />
            </div>
            <div class="text-right">
              <a
                href={`/graph?roll=${encodeURIComponent(roll.id)}&t=${Math.floor(selectedMoment.timestamp_s)}`}
                class="text-[11px] text-white/60 hover:text-white/85 underline"
              >
                Open full BJJ graph →
              </a>
            </div>
          </section>
        {/if}
      {:else}
        <p class="text-[11px] text-white/35">
          Click a chip to see the moment and analyse it with Claude.
        </p>
      {/if}
    {:else if !analysing}
      <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
        <p class="text-sm text-white/60">No moments yet.</p>
        <p class="mt-1 text-xs text-white/35">
          Click <strong>Analyse</strong> to run the pose pre-pass and flag interesting moments.
        </p>
      </div>
    {/if}

    <div class="flex items-center justify-between gap-3 border-t border-white/8 pt-4">
      <div class="text-[11px] text-white/40">
        {#if !hasAnyAnalyses}
          Analyse at least one moment first.
        {:else if roll.finalised_at}
          Finalised. Click to recompute with the latest analyses + notes.
        {:else}
          Not yet finalised.
        {/if}
      </div>
      <button
        type="button"
        onclick={onFinaliseClick}
        disabled={finalising || !hasAnyAnalyses}
        class="rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {finalising ? 'Finalising…' : roll.finalised_at ? 'Re-finalise' : 'Finalise'}
      </button>
    </div>

    {#if finaliseError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {finaliseError}
      </div>
    {/if}

    <footer class="flex items-center justify-between gap-3 border-t border-white/8 pt-4">
      <div class="text-[11px] text-white/40">
        {#if roll.vault_path}
          Vault: <span class="font-mono">{roll.vault_path}</span>
        {:else}
          Not yet published to vault.
        {/if}
      </div>
      <button
        type="button"
        onclick={() => onSaveToVault()}
        disabled={publishing}
        class="rounded-md border border-amber-400/40 bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {publishing ? 'Publishing…' : 'Save to Vault'}
      </button>
    </footer>

    {#if publishToast}
      <div class="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
        {publishToast}
      </div>
    {/if}
    {#if publishError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {publishError}
      </div>
    {/if}

    <PublishConflictDialog
      open={conflictOpen}
      onOverwrite={onOverwrite}
      onCancel={onCancelConflict}
    />
  </section>
{/if}
