<script lang="ts">
  import type { Moment, SummaryPayload } from '$lib/types';

  let {
    scores,
    moments,
    finalisedAt,
    ongoto
  }: {
    scores: SummaryPayload;
    moments: Moment[];
    finalisedAt: number;
    ongoto: (momentId: string) => void;
  } = $props();

  const momentsById = $derived(
    new Map(moments.map((m) => [m.id, m]))
  );

  function formatMmSs(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatFinalisedAt(unixS: number): string {
    const d = new Date(unixS * 1000);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function scoreColorClass(score: number): string {
    if (score >= 8) return 'border-emerald-400/50 bg-emerald-500/10 text-emerald-100';
    if (score >= 5) return 'border-amber-400/50 bg-amber-500/10 text-amber-100';
    return 'border-rose-400/50 bg-rose-500/10 text-rose-100';
  }
</script>

<section class="space-y-4 rounded-lg border border-white/10 bg-white/[0.02] p-5">
  <header class="flex items-center justify-between gap-3">
    <h2 class="text-sm font-semibold tracking-tight text-white/90">Summary</h2>
    <span class="text-[11px] text-white/40">
      Finalised {formatFinalisedAt(finalisedAt)}
    </span>
  </header>

  <div class="grid grid-cols-3 gap-2">
    <div class="rounded-md border p-3 text-center {scoreColorClass(scores.scores.guard_retention)}">
      <div class="text-xl font-semibold tabular-nums">{scores.scores.guard_retention}/10</div>
      <div class="mt-1 text-[10px] uppercase tracking-wider opacity-75">Retention</div>
    </div>
    <div class="rounded-md border p-3 text-center {scoreColorClass(scores.scores.positional_awareness)}">
      <div class="text-xl font-semibold tabular-nums">{scores.scores.positional_awareness}/10</div>
      <div class="mt-1 text-[10px] uppercase tracking-wider opacity-75">Awareness</div>
    </div>
    <div class="rounded-md border p-3 text-center {scoreColorClass(scores.scores.transition_quality)}">
      <div class="text-xl font-semibold tabular-nums">{scores.scores.transition_quality}/10</div>
      <div class="mt-1 text-[10px] uppercase tracking-wider opacity-75">Transition</div>
    </div>
  </div>

  <p class="text-sm leading-relaxed text-white/85">{scores.summary}</p>

  <div class="space-y-1">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Top improvements
    </div>
    <ol class="list-decimal space-y-1 pl-5 text-sm text-white/80">
      {#each scores.top_improvements as item, i (i)}
        <li>{item}</li>
      {/each}
    </ol>
  </div>

  <div class="space-y-1">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Strengths observed
    </div>
    <ul class="list-disc space-y-1 pl-5 text-sm text-white/80">
      {#each scores.strengths as item, i (i)}
        <li>{item}</li>
      {/each}
    </ul>
  </div>

  <div class="space-y-1">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Key moments
    </div>
    <ul class="space-y-1 text-sm text-white/80">
      {#each scores.key_moments as km (km.moment_id)}
        {@const moment = momentsById.get(km.moment_id)}
        <li class="flex items-start justify-between gap-3">
          <div class="flex-1">
            <span class="font-mono tabular-nums text-white/60">
              {moment ? formatMmSs(moment.timestamp_s) : '?:??'}
            </span>
            <span class="ml-1 text-white/40">—</span>
            <span class="ml-1">{km.note}</span>
          </div>
          <button
            type="button"
            onclick={() => ongoto(km.moment_id)}
            aria-label="Go to moment"
            class="shrink-0 rounded-md border border-white/15 bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/75 hover:bg-white/[0.08]"
          >
            Go to →
          </button>
        </li>
      {/each}
    </ul>
  </div>
</section>
