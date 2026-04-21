<script lang="ts">
  let {
    scrubTimeS,
    durationS,
    rollId,
    onscrubchange
  }: {
    scrubTimeS: number;
    durationS: number;
    rollId: string;
    onscrubchange: (t: number) => void;
  } = $props();

  const disabled = $derived(!rollId || durationS <= 0);

  function formatMmSs(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function onInput(e: Event) {
    const target = e.target as HTMLInputElement;
    const n = Number(target.value);
    if (!Number.isNaN(n)) {
      onscrubchange(n);
    }
  }

  const reviewHref = $derived(
    rollId ? `/review/${encodeURIComponent(rollId)}?t=${Math.floor(scrubTimeS)}` : '#'
  );
</script>

<div class="flex items-center gap-3 rounded-md border border-white/10 bg-white/[0.02] px-4 py-2">
  <span class="w-12 text-right font-mono text-xs tabular-nums text-white/70">
    {formatMmSs(scrubTimeS)}
  </span>

  <input
    type="range"
    min="0"
    max={durationS}
    step="0.1"
    value={scrubTimeS}
    oninput={onInput}
    disabled={disabled}
    class="flex-1 h-1.5 rounded-full bg-white/10 accent-amber-400 disabled:opacity-40"
  />

  <span class="w-12 font-mono text-xs tabular-nums text-white/50">
    {formatMmSs(durationS)}
  </span>

  <a
    href={reviewHref}
    aria-disabled={disabled}
    class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1 text-[11px] font-medium text-white/80 hover:bg-white/[0.08] {disabled ? 'pointer-events-none opacity-40' : ''}"
  >
    Open in review →
  </a>
</div>
