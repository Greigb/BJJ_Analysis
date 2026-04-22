<script lang="ts">
  import type { SectionInput } from '$lib/api';

  interface StagedSection {
    id: string;
    start_s: number;
    end_s: number;
    sample_interval_s: number;
  }

  let {
    videoEl,
    durationS,
    onAnalyse,
    busy,
  }: {
    videoEl: HTMLVideoElement | undefined;
    durationS: number;
    onAnalyse: (sections: SectionInput[]) => void;
    busy: boolean;
  } = $props();

  let sections = $state<StagedSection[]>([]);
  let pendingStart = $state<number | null>(null);

  function formatMmSs(s: number): string {
    const total = Math.max(0, Math.floor(s));
    const m = Math.floor(total / 60);
    const sec = total % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }

  function parseMmSs(value: string): number | null {
    const match = value.trim().match(/^(\d+):([0-5]?\d)$/);
    if (!match) return null;
    return parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
  }

  function currentT(): number {
    return videoEl ? videoEl.currentTime : 0;
  }

  function onMarkStart() {
    if (!videoEl) return;
    pendingStart = currentT();
  }

  function onMarkEnd() {
    if (pendingStart === null || !videoEl) return;
    const start = pendingStart;
    const end = currentT();
    if (end <= start) return;
    sections = [
      ...sections,
      {
        id: crypto.randomUUID(),
        start_s: Math.round(start * 10) / 10,
        end_s: Math.round(end * 10) / 10,
        sample_interval_s: 1.0,
      },
    ];
    pendingStart = null;
  }

  function onCancel() {
    pendingStart = null;
  }

  function onDelete(id: string) {
    sections = sections.filter((s) => s.id !== id);
  }

  function onEditStart(id: string, value: string) {
    const parsed = parseMmSs(value);
    if (parsed === null) return;
    sections = sections.map((s) => (s.id === id ? { ...s, start_s: parsed } : s));
  }

  function onEditEnd(id: string, value: string) {
    const parsed = parseMmSs(value);
    if (parsed === null) return;
    sections = sections.map((s) => (s.id === id ? { ...s, end_s: parsed } : s));
  }

  function onSeek(start_s: number) {
    if (videoEl) {
      videoEl.currentTime = start_s;
      void videoEl.play();
    }
  }

  function onAnalyseClick() {
    if (busy || sections.length === 0) return;
    onAnalyse(
      sections.map(({ start_s, end_s, sample_interval_s }) => ({
        start_s,
        end_s,
        sample_interval_s,
      })),
    );
  }
</script>

<section class="flex flex-col gap-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <div class="flex flex-wrap items-center gap-2 text-xs">
    <button
      type="button"
      class="rounded-md border border-emerald-400/40 bg-emerald-500/15 px-3 py-1.5 font-medium text-emerald-100 hover:bg-emerald-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      onclick={onMarkStart}
      disabled={pendingStart !== null}
    >
      Mark start
    </button>
    <button
      type="button"
      class="rounded-md border border-rose-400/40 bg-rose-500/15 px-3 py-1.5 font-medium text-rose-100 hover:bg-rose-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      onclick={onMarkEnd}
      disabled={pendingStart === null}
    >
      Mark end
    </button>
    {#if pendingStart !== null}
      <span class="text-white/60">
        Pending section starting at {formatMmSs(pendingStart)} — play and click Mark end.
      </span>
      <button
        type="button"
        class="rounded-md border border-white/15 bg-white/[0.04] px-2 py-1 text-white/70 hover:bg-white/[0.08] transition-colors"
        onclick={onCancel}
      >
        Cancel
      </button>
    {/if}
  </div>

  {#if sections.length > 0}
    <ul class="flex flex-col gap-2">
      {#each sections as section (section.id)}
        <li class="flex items-center gap-2 rounded-md border border-white/12 bg-white/[0.03] px-3 py-2">
          <span class="text-white/85 font-mono text-xs">{formatMmSs(section.start_s)}</span>
          <input
            type="text"
            aria-label="Section start"
            class="sr-only"
            value={formatMmSs(section.start_s)}
            onblur={(e) => onEditStart(section.id, (e.target as HTMLInputElement).value)}
          />
          <span class="text-white/50">–</span>
          <span class="text-white/85 font-mono text-xs">{formatMmSs(section.end_s)}</span>
          <input
            type="text"
            aria-label="Section end"
            class="sr-only"
            value={formatMmSs(section.end_s)}
            onblur={(e) => onEditEnd(section.id, (e.target as HTMLInputElement).value)}
          />
          <button
            type="button"
            class="rounded border border-white/15 bg-white/[0.04] px-2 py-0.5 text-xs text-white/70 hover:bg-white/[0.08]"
            onclick={() => onSeek(section.start_s)}
            aria-label="Seek to section"
          >
            Seek
          </button>
          <button
            type="button"
            class="ml-auto rounded border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-xs text-rose-100 hover:bg-rose-500/25"
            onclick={() => onDelete(section.id)}
            aria-label="Delete section"
          >
            Delete
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <button
    type="button"
    class="self-start rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    onclick={onAnalyseClick}
    disabled={busy || sections.length === 0}
  >
    Analyse ranges
  </button>
</section>
