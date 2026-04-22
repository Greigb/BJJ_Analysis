<script lang="ts">
  let {
    open,
    onOverwrite,
    onCancel
  }: {
    open: boolean;
    onOverwrite: () => void;
    onCancel: () => void;
  } = $props();
</script>

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
  >
    <div class="max-w-md rounded-lg border border-white/12 bg-black/80 p-5 shadow-lg">
      <h2 class="text-sm font-semibold text-white/95">Vault conflict</h2>
      <p class="mt-2 text-sm text-white/70">
        Your Notes, a summary section, or the Report section was edited in Obsidian since you last
        published. If you overwrite, the external edit will be lost (check git if you need to
        recover).
      </p>
      <div class="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          onclick={onCancel}
          class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-white/75 hover:bg-white/[0.08] transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onclick={onOverwrite}
          class="rounded-md border border-rose-500/40 bg-rose-500/20 px-3 py-1.5 text-xs font-medium text-rose-100 hover:bg-rose-500/30 transition-colors"
        >
          Overwrite
        </button>
      </div>
    </div>
  </div>
{/if}
