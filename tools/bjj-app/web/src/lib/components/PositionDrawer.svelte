<script lang="ts">
  import type { PositionNote } from '$lib/types';

  let {
    open,
    positionNote,
    onclose
  }: {
    open: boolean;
    positionNote: PositionNote | null;
    onclose: () => void;
  } = $props();

  // marked is loaded as a global from a CDN <script> in app.html.
  // In tests we stub it on globalThis; in dev/prod it's real.
  function renderMarkdown(md: string): string {
    // @ts-expect-error marked is a global
    const marked = globalThis.marked;
    if (marked && typeof marked.parse === 'function') {
      return marked.parse(md);
    }
    // Fallback: escape + wrap in <pre> so nothing breaks if marked didn't load.
    const escaped = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<pre>${escaped}</pre>`;
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
