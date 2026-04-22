<script lang="ts">
  import type { Section } from '$lib/types';

  let {
    section,
    busy,
    onSeek,
    onDelete,
    onAddAnnotation,
  }: {
    section: Section;
    busy: boolean;
    onSeek: (start_s: number) => void;
    onDelete: (section_id: string) => void;
    onAddAnnotation: (section_id: string, body: string) => void;
  } = $props();

  let draft = $state('');

  function formatMmSs(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function onAdd() {
    const body = draft.trim();
    if (!body) return;
    onAddAnnotation(section.id, body);
    draft = '';
  }
</script>

<section class="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <header class="flex items-center justify-between gap-2">
    <span class="font-mono tabular-nums text-white/85">
      {formatMmSs(section.start_s)} – {formatMmSs(section.end_s)}
    </span>
    <div class="flex gap-2">
      <button
        type="button"
        class="rounded border border-white/15 bg-white/[0.04] px-2 py-0.5 text-xs text-white/75 hover:bg-white/[0.08]"
        onclick={() => onSeek(section.start_s)}
      >
        Seek
      </button>
      <button
        type="button"
        class="rounded border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-xs text-rose-100 hover:bg-rose-500/25"
        onclick={() => onDelete(section.id)}
      >
        Delete
      </button>
    </div>
  </header>

  {#if section.narrative}
    <p class="text-sm leading-relaxed text-white/85">{section.narrative}</p>
    {#if section.coach_tip}
      <div class="rounded-md border border-blue-400/30 bg-blue-500/10 px-3 py-2 text-xs text-blue-100">
        <span class="font-semibold">Coach tip:</span>
        {section.coach_tip}
      </div>
    {/if}
  {:else if busy}
    <p class="text-xs text-white/55">Analysing…</p>
  {:else}
    <p class="text-xs text-white/55">Not analysed yet.</p>
  {/if}

  {#if section.annotations.length > 0}
    <ul class="list-disc space-y-1 pl-5 text-xs text-white/75">
      {#each section.annotations as ann (ann.id)}
        <li>{ann.body}</li>
      {/each}
    </ul>
  {/if}

  <div class="flex gap-2">
    <label class="sr-only" for="ann-{section.id}">Add note</label>
    <textarea
      id="ann-{section.id}"
      aria-label="Add note"
      class="flex-1 rounded-md border border-white/10 bg-black/30 px-2 py-1 text-xs text-white/85"
      rows="2"
      bind:value={draft}
    ></textarea>
    <button
      type="button"
      class="self-end rounded-md border border-emerald-400/40 bg-emerald-500/15 px-3 py-1 text-xs text-emerald-100 hover:bg-emerald-500/25"
      onclick={onAdd}
    >
      Add
    </button>
  </div>
</section>
