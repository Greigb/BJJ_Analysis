<script lang="ts">
  import type { Section, SummaryPayload } from '$lib/types';

  let {
    scores,
    sections,
    finalisedAt,
    ongoto
  }: {
    scores: SummaryPayload;
    sections: Section[];
    finalisedAt: number;
    ongoto: (sectionId: string) => void;
  } = $props();

  const sectionsById = $derived(
    new Map(sections.map((s) => [s.id, s]))
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

  let rubricOpen = $state(false);
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

  <div class="text-[11px] text-white/50">
    <button
      type="button"
      onclick={() => (rubricOpen = !rubricOpen)}
      class="text-white/60 hover:text-white/85 underline underline-offset-2"
      aria-expanded={rubricOpen}
    >
      {rubricOpen ? 'Hide' : 'What does'} x/10 {rubricOpen ? 'rubric' : 'mean?'}
    </button>
    {#if rubricOpen}
      <div class="mt-2 space-y-2 rounded-md border border-white/10 bg-white/[0.02] p-3 text-white/70">
        <div>
          <div class="text-[10px] font-semibold uppercase tracking-wider text-white/50">Bands</div>
          <ul class="mt-1 list-disc space-y-0.5 pl-5">
            <li><strong class="text-white/80">0–3</strong> — needs focused work; frequent positional loss or stalled execution.</li>
            <li><strong class="text-white/80">4–6</strong> — developing; skill is emerging but inconsistent under pressure.</li>
            <li><strong class="text-white/80">7–10</strong> — reliable; consistent, technical execution against the partner in this footage.</li>
          </ul>
        </div>
        <div>
          <div class="text-[10px] font-semibold uppercase tracking-wider text-white/50">Per metric</div>
          <ul class="mt-1 space-y-0.5">
            <li><strong class="text-white/80">Retention</strong> — ability to recover / hold guard when pressured.</li>
            <li><strong class="text-white/80">Awareness</strong> — reads the partner's posture + responds with the right frame / grip / shape.</li>
            <li><strong class="text-white/80">Transition</strong> — technical fluency moving between positions (passes, sweeps, escapes).</li>
          </ul>
        </div>
        <div class="text-white/50">
          Scores are calibrated per roll — not across BJJ as a whole. A 10 means execution was reliable throughout <em>this</em> footage, not that the practitioner is a world champion.
        </div>
      </div>
    {/if}
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
      {#each scores.key_moments as km, i (i)}
        {@const section = sectionsById.get(km.section_id)}
        <li class="flex items-start justify-between gap-3">
          <div class="flex-1">
            <span class="font-mono tabular-nums text-white/60">
              {section ? `${formatMmSs(section.start_s)} – ${formatMmSs(section.end_s)}` : '?:??'}
            </span>
            <span class="ml-1 text-white/40">—</span>
            <span class="ml-1">{km.note}</span>
          </div>
          <button
            type="button"
            onclick={() => ongoto(km.section_id)}
            aria-label="Go to section"
            class="shrink-0 rounded-md border border-white/15 bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/75 hover:bg-white/[0.08]"
          >
            Go to →
          </button>
        </li>
      {/each}
    </ul>
  </div>
</section>
