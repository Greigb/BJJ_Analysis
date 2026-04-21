<script lang="ts">
  import { goto } from '$app/navigation';
  import { createRoll, ApiError } from '$lib/api';

  const today = new Date().toISOString().slice(0, 10);

  let title = $state('');
  let date = $state(today);
  let playerAName = $state('');
  let playerBName = $state('');
  let file = $state<File | null>(null);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  function onFileChange(event: Event) {
    const input = event.target as HTMLInputElement;
    file = input.files?.[0] ?? null;
  }

  async function onSubmit(event: Event) {
    event.preventDefault();
    if (!file || submitting) return;
    submitting = true;
    error = null;
    try {
      const roll = await createRoll({
        title: title || `Roll ${date}`,
        date,
        player_a_name: playerAName || undefined,
        player_b_name: playerBName || undefined,
        video: file
      });
      await goto(`/review/${encodeURIComponent(roll.id)}`);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      error = `Upload failed: ${msg}`;
      submitting = false;
    }
  }
</script>

<section class="space-y-6 max-w-xl">
  <h1 class="text-2xl font-semibold tracking-tight">New Roll</h1>

  <!--
    novalidate: works around a jsdom + user-event quirk where <input type="file" required>
    silently aborts requestSubmit() in tests. Real-browser UX is preserved by the disabled
    submit button (no file → disabled) and the `if (!file || submitting) return` guard above.
  -->
  <form class="space-y-5" novalidate onsubmit={onSubmit}>
    <label class="block space-y-1">
      <span class="text-sm text-white/70">Title</span>
      <input
        type="text"
        placeholder={`Roll ${date}`}
        bind:value={title}
        class="w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm focus:outline-none focus:border-blue-400/50"
      />
    </label>

    <label class="block space-y-1">
      <span class="text-sm text-white/70">Date</span>
      <input
        type="date"
        bind:value={date}
        required
        class="w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm focus:outline-none focus:border-blue-400/50"
      />
    </label>

    <label class="flex flex-col gap-1 text-xs text-white/70">
      Player A
      <input
        type="text"
        bind:value={playerAName}
        placeholder="Player A"
        class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-sm text-white/90 placeholder:text-white/30"
      />
    </label>

    <label class="flex flex-col gap-1 text-xs text-white/70">
      Player B
      <input
        type="text"
        bind:value={playerBName}
        placeholder="Player B"
        class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-sm text-white/90 placeholder:text-white/30"
      />
    </label>

    <label class="block space-y-1">
      <span class="text-sm text-white/70">Video file</span>
      <input
        type="file"
        accept="video/*"
        onchange={onFileChange}
        required
        class="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-white/10 file:bg-white/5 file:px-3 file:py-1.5 file:text-white/80 hover:file:bg-white/10"
      />
    </label>

    {#if error}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
        {error}
      </div>
    {/if}

    <button
      type="submit"
      disabled={!file || submitting}
      class="rounded-md bg-blue-500/20 border border-blue-400/40 text-blue-100 px-4 py-2 text-sm font-medium hover:bg-blue-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {submitting ? 'Uploading…' : 'Upload'}
    </button>
  </form>
</section>
