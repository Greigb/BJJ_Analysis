<script lang="ts">
  import type { PositionNote } from '$lib/types';
  import { marked } from 'marked';

  let {
    open,
    positionNote,
    onclose
  }: {
    open: boolean;
    positionNote: PositionNote | null;
    onclose: () => void;
  } = $props();

  function renderMarkdown(md: string): string {
    const result = marked.parse(md);
    // marked v11 returns string | Promise<string>; we use it synchronously so coerce.
    return typeof result === 'string' ? result : '';
  }

  const rendered = $derived(positionNote ? renderMarkdown(positionNote.markdown) : '');

  function onKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      onclose();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
  <aside
    role="dialog"
    aria-modal="true"
    aria-label="Position details"
    class="fixed right-0 top-0 z-40 h-full w-full max-w-[400px] overflow-y-auto border-l border-white/10 bg-black/90 backdrop-blur-md shadow-lg"
  >
    <header class="flex items-center justify-between gap-2 border-b border-white/10 p-4">
      {#if !positionNote}
        <h2 class="text-sm font-semibold text-white/95">Position</h2>
      {:else}
        <span class="text-[10px] uppercase tracking-wider text-white/40">Position details</span>
      {/if}
      <button
        type="button"
        onclick={onclose}
        aria-label="Close"
        class="rounded-md border border-white/15 bg-white/[0.04] px-2 py-1 text-xs text-white/75 hover:bg-white/[0.08]"
      >
        Close
      </button>
    </header>

    <div class="prose prose-invert max-w-none p-4 text-sm text-white/80">
      {#if positionNote}
        {@html rendered}
      {:else}
        <p class="text-white/55">No vault note for this position yet.</p>
      {/if}
    </div>
  </aside>
{/if}
