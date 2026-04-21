<script lang="ts">
  import { addAnnotation, analyseMoment, ApiError } from '$lib/api';
  import type { Analysis, AnalyseMomentEvent, Annotation, Moment } from '$lib/types';

  let {
    rollId,
    moment,
    playerAName = 'Player A',
    playerBName = 'Player B',
    onanalysed,
    onannotated
  }: {
    rollId: string;
    moment: Moment;
    playerAName?: string;
    playerBName?: string;
    onanalysed?: (m: Moment) => void;
    onannotated?: (m: Moment) => void;
  } = $props();

  let analysing = $state(false);
  let partial = $state('');
  let analyseError = $state<string | null>(null);
  let localAnalyses = $state<Analysis[]>(moment.analyses);
  let localAnnotations = $state<Annotation[]>(moment.annotations);
  let noteDraft = $state('');
  let adding = $state(false);
  let annotateError = $state<string | null>(null);

  $effect(() => {
    localAnalyses = moment.analyses;
    localAnnotations = moment.annotations;
    partial = '';
    analyseError = null;
    noteDraft = '';
    annotateError = null;
  });

  const playerA = $derived(localAnalyses.find((a) => a.player === 'a'));
  const playerB = $derived(localAnalyses.find((a) => a.player === 'b'));

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatCreatedAt(unix_s: number): string {
    const d = new Date(unix_s * 1000);
    const mm = d.toLocaleString(undefined, { month: 'short' });
    const dd = d.getDate();
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${mm} ${dd} ${hh}:${mi}`;
  }

  async function onAnalyseClick() {
    if (analysing) return;
    analysing = true;
    partial = '';
    analyseError = null;
    try {
      for await (const event of analyseMoment(rollId, moment.frame_idx)) {
        handleAnalyseEvent(event);
      }
    } catch (err) {
      analyseError = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
    }
  }

  function handleAnalyseEvent(event: AnalyseMomentEvent) {
    if (event.stage === 'streaming') {
      partial = event.text;
    } else if (event.stage === 'done') {
      const a = event.analysis;
      const fabricated: Analysis[] = [
        {
          id: `pending-${moment.id}-a`,
          player: 'a',
          position_id: a.player_a.position,
          confidence: a.player_a.confidence,
          description: a.description,
          coach_tip: a.coach_tip
        },
        {
          id: `pending-${moment.id}-b`,
          player: 'b',
          position_id: a.player_b.position,
          confidence: a.player_b.confidence,
          description: null,
          coach_tip: null
        }
      ];
      localAnalyses = fabricated;
      partial = '';
      onanalysed?.({ ...moment, analyses: fabricated, annotations: localAnnotations });
    } else if (event.stage === 'error') {
      if (event.kind === 'rate_limited' && event.retry_after_s) {
        analyseError = `Claude cooldown — ${event.retry_after_s}s until next call`;
      } else {
        analyseError = event.detail ?? `Analyse failed (${event.kind})`;
      }
    }
  }

  async function onAddNote() {
    const body = noteDraft.trim();
    if (!body || adding) return;
    adding = true;
    annotateError = null;
    try {
      const newRow = await addAnnotation(rollId, moment.id, body);
      localAnnotations = [...localAnnotations, newRow];
      noteDraft = '';
      onannotated?.({ ...moment, analyses: localAnalyses, annotations: localAnnotations });
    } catch (err) {
      annotateError = err instanceof ApiError ? err.message : String(err);
    } finally {
      adding = false;
    }
  }

  function onNoteKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      onAddNote();
    }
  }
</script>

<section class="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <header class="flex items-baseline gap-3">
    <span class="text-lg font-mono tabular-nums text-white/90">
      {formatMomentTime(moment.timestamp_s)}
    </span>
    <span class="text-[10px] uppercase tracking-wider text-white/40">Selected moment</span>
  </header>

  {#if analyseError}
    <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {analyseError}
    </div>
  {/if}

  {#if localAnalyses.length > 0}
    <div class="grid gap-2 sm:grid-cols-2">
      {#if playerA}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">{playerAName}</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{playerA.position_id}</div>
          {#if playerA.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(playerA.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
      {#if playerB}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">{playerBName}</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{playerB.position_id}</div>
          {#if playerB.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(playerB.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
    </div>

    {#if playerA?.description}
      <p class="text-sm leading-relaxed text-white/80">{playerA.description}</p>
    {/if}
    {#if playerA?.coach_tip}
      <div class="border-l-2 border-amber-400/60 pl-3 text-sm text-amber-100/90">
        {playerA.coach_tip}
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

  <!-- --- Your notes for this moment --- -->
  <div class="space-y-2 border-t border-white/8 pt-3">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Your notes for this moment
    </div>

    {#if localAnnotations.length > 0}
      <ul class="space-y-1">
        {#each localAnnotations as a (a.id)}
          <li class="text-sm text-white/80">
            <span class="text-[10px] text-white/40">({formatCreatedAt(a.created_at)})</span>
            <span class="ml-1">{a.body}</span>
          </li>
        {/each}
      </ul>
    {/if}

    {#if annotateError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {annotateError}
      </div>
    {/if}

    <textarea
      bind:value={noteDraft}
      onkeydown={onNoteKeydown}
      placeholder="Type a new note…  (Cmd-Enter to submit)"
      class="w-full min-h-[60px] rounded-md border border-white/10 bg-white/[0.02] p-2 text-sm text-white/85 placeholder:text-white/30 focus:border-white/30 outline-none"
    ></textarea>

    <div class="flex items-center justify-end">
      <button
        type="button"
        onclick={onAddNote}
        disabled={adding || !noteDraft.trim()}
        class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-white/85 hover:bg-white/[0.08] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {adding ? 'Adding…' : 'Add note'}
      </button>
    </div>
  </div>
</section>
