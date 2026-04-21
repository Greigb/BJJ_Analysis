<script lang="ts">
  import { analyseMoment, ApiError } from '$lib/api';
  import type { Analysis, AnalyseMomentEvent, Moment } from '$lib/types';

  let { rollId, moment, onanalysed }: {
    rollId: string;
    moment: Moment;
    onanalysed?: (m: Moment) => void;
  } = $props();

  let analysing = $state(false);
  let partial = $state('');
  let error = $state<string | null>(null);
  let localAnalyses = $state<Analysis[]>(moment.analyses);

  // Re-sync when the parent swaps in a different moment.
  $effect(() => {
    localAnalyses = moment.analyses;
    partial = '';
    error = null;
  });

  const greig = $derived(localAnalyses.find((a) => a.player === 'greig'));
  const anthony = $derived(localAnalyses.find((a) => a.player === 'anthony'));

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  async function onAnalyseClick() {
    if (analysing) return;
    analysing = true;
    partial = '';
    error = null;
    try {
      for await (const event of analyseMoment(rollId, moment.frame_idx)) {
        handleEvent(event);
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
    }
  }

  function handleEvent(event: AnalyseMomentEvent) {
    if (event.stage === 'streaming') {
      partial = event.text;
    } else if (event.stage === 'done') {
      const a = event.analysis;
      const fabricated: Analysis[] = [
        {
          id: `pending-${moment.id}-greig`,
          player: 'greig',
          position_id: a.greig.position,
          confidence: a.greig.confidence,
          description: a.description,
          coach_tip: a.coach_tip
        },
        {
          id: `pending-${moment.id}-anthony`,
          player: 'anthony',
          position_id: a.anthony.position,
          confidence: a.anthony.confidence,
          description: null,
          coach_tip: null
        }
      ];
      localAnalyses = fabricated;
      partial = '';
      onanalysed?.({ ...moment, analyses: fabricated });
    } else if (event.stage === 'error') {
      if (event.kind === 'rate_limited' && event.retry_after_s) {
        error = `Claude cooldown — ${event.retry_after_s}s until next call`;
      } else {
        error = event.detail ?? `Analyse failed (${event.kind})`;
      }
    }
    // 'cache' events are informational — nothing to render.
  }
</script>

<section class="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <header class="flex items-baseline gap-3">
    <span class="text-lg font-mono tabular-nums text-white/90">
      {formatMomentTime(moment.timestamp_s)}
    </span>
    <span class="text-[10px] uppercase tracking-wider text-white/40">Selected moment</span>
  </header>

  {#if error}
    <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {error}
    </div>
  {/if}

  {#if localAnalyses.length > 0}
    <div class="grid gap-2 sm:grid-cols-2">
      {#if greig}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">Greig</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{greig.position_id}</div>
          {#if greig.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(greig.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
      {#if anthony}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">Anthony</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{anthony.position_id}</div>
          {#if anthony.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(anthony.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
    </div>

    {#if greig?.description}
      <p class="text-sm leading-relaxed text-white/80">{greig.description}</p>
    {/if}
    {#if greig?.coach_tip}
      <div class="border-l-2 border-amber-400/60 pl-3 text-sm text-amber-100/90">
        {greig.coach_tip}
      </div>
    {/if}
  {:else if analysing}
    <div class="space-y-2">
      <div class="text-xs text-white/55">Streaming from Claude Opus 4.7…</div>
      {#if partial}
        <pre
          class="whitespace-pre-wrap rounded-md bg-black/30 p-2 font-mono text-[11px] text-white/70"
        >{partial}</pre>
      {/if}
    </div>
  {:else}
    <button
      type="button"
      onclick={onAnalyseClick}
      class="rounded-md border border-blue-400/40 bg-blue-500/20 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/30 transition-colors"
    >
      Analyse this moment with Claude Opus 4.7
    </button>
  {/if}
</section>
