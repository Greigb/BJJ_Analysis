<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import {
    addAnnotation,
    analyseRoll,
    ApiError,
    deleteSection,
    exportRollPdf,
    getRoll,
    publishRoll,
    PublishConflictError,
    summariseRoll,
    SummariseRateLimitedError
  } from '$lib/api';
  import type { SectionInput } from '$lib/api';
  import PublishConflictDialog from '$lib/components/PublishConflictDialog.svelte';
  import ScoresPanel from '$lib/components/ScoresPanel.svelte';
  import SectionCard from '$lib/components/SectionCard.svelte';
  import SectionPicker from '$lib/components/SectionPicker.svelte';
  import type { AnalyseEvent, RollDetail, Section } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let analysing = $state(false);
  let queuedBanner = $state<{ sectionId: string; retryAfterS: number } | null>(null);
  let publishing = $state(false);
  let publishError = $state<string | null>(null);
  let publishToast = $state<string | null>(null);
  let conflictOpen = $state(false);
  let finalising = $state(false);
  let finaliseError = $state<string | null>(null);
  let exporting = $state(false);
  let exportConflictOpen = $state(false);
  let exportError = $state<string | null>(null);
  let videoEl: HTMLVideoElement | undefined = $state();

  const hasAnyAnalysedSection = $derived(
    roll?.sections?.some((s) => s.narrative != null) ?? false
  );

  onMount(async () => {
    const id = $page.params.id;
    try {
      roll = await getRoll(id);
      const queryT = $page.url.searchParams.get('t');
      if (queryT !== null && videoEl) {
        const t = Number(queryT);
        if (!Number.isNaN(t)) {
          const seekFn = () => {
            if (videoEl) videoEl.currentTime = t;
          };
          if (videoEl.readyState >= 1) {
            seekFn();
          } else {
            videoEl.addEventListener('loadedmetadata', seekFn, { once: true });
          }
        }
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      loading = false;
    }
  });

  async function onAnalyseSections(sections: SectionInput[]) {
    if (!roll || analysing) return;
    analysing = true;
    queuedBanner = null;
    try {
      const response = await analyseRoll(roll.id, sections);
      if (!response.ok || !response.body) {
        error = `Analyse failed (${response.status})`;
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (!chunk.startsWith('data: ')) continue;
          const event = JSON.parse(chunk.slice(6)) as AnalyseEvent;
          handleAnalyseEvent(event);
        }
      }
    } finally {
      analysing = false;
      queuedBanner = null;
    }
  }

  function handleAnalyseEvent(event: AnalyseEvent) {
    if (!roll) return;
    if (event.stage === 'section_started') {
      queuedBanner = null;
      const placeholder: Section = {
        id: event.section_id,
        start_s: event.start_s,
        end_s: event.end_s,
        sample_interval_s: 1.0,
        narrative: null,
        coach_tip: null,
        analysed_at: null,
        annotations: []
      };
      if (!roll.sections.some((s) => s.id === event.section_id)) {
        roll.sections = [...roll.sections, placeholder];
      }
    } else if (event.stage === 'section_queued') {
      queuedBanner = { sectionId: event.section_id, retryAfterS: event.retry_after_s };
    } else if (event.stage === 'section_done') {
      roll.sections = roll.sections.map((s) =>
        s.id === event.section_id
          ? {
              ...s,
              narrative: event.narrative,
              coach_tip: event.coach_tip,
              analysed_at: Math.floor(Date.now() / 1000)
            }
          : s
      );
    } else if (event.stage === 'section_error') {
      // Leave the section in its placeholder state; no narrative means "not analysed".
      queuedBanner = null;
    }
    // stage === 'done' → nothing; the loop exits naturally.
  }

  async function onSectionDelete(sectionId: string) {
    if (!roll) return;
    try {
      await deleteSection(roll.id, sectionId);
      roll.sections = roll.sections.filter((s) => s.id !== sectionId);
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    }
  }

  async function onSectionAnnotate(sectionId: string, body: string) {
    if (!roll) return;
    try {
      const ann = await addAnnotation(roll.id, sectionId, body);
      roll.sections = roll.sections.map((s) =>
        s.id === sectionId ? { ...s, annotations: [...s.annotations, ann] } : s
      );
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    }
  }

  function seek(t: number) {
    if (!videoEl) return;
    videoEl.currentTime = t;
    const playPromise = videoEl.play();
    if (playPromise !== undefined) {
      playPromise.catch(() => {
        /* autoplay may be blocked; that's fine */
      });
    }
  }

  function formatDuration(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  async function onSaveToVault(options: { force?: boolean } = {}) {
    if (!roll || publishing) return;
    publishing = true;
    publishError = null;
    publishToast = null;
    try {
      const result = await publishRoll(roll.id, options);
      publishToast = `Published to ${result.vault_path}`;
      roll.vault_path = result.vault_path;
      roll.vault_published_at = result.vault_published_at;
    } catch (err) {
      if (err instanceof PublishConflictError) {
        conflictOpen = true;
      } else {
        publishError = err instanceof ApiError ? err.message : String(err);
      }
    } finally {
      publishing = false;
    }
  }

  async function onOverwrite() {
    conflictOpen = false;
    await onSaveToVault({ force: true });
  }

  function onCancelConflict() {
    conflictOpen = false;
  }

  async function triggerDownload(blob: Blob, filename: string): Promise<void> {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function onExportClick(overwrite = false) {
    if (!roll || exporting) return;
    if (!roll.finalised_at) return;
    exporting = true;
    exportError = null;
    try {
      const result = await exportRollPdf(roll.id, overwrite);
      if (!overwrite) {
        await triggerDownload(result.blob, result.filename);
      }
      if (result.kind === 'conflict') {
        exportConflictOpen = true;
      }
    } catch (err) {
      exportError = err instanceof ApiError ? err.message : String(err);
    } finally {
      exporting = false;
    }
  }

  function onExportOverwrite() {
    exportConflictOpen = false;
    onExportClick(true);
  }

  function onExportCancel() {
    exportConflictOpen = false;
  }

  async function onFinaliseClick() {
    if (!roll || finalising) return;
    if (!hasAnyAnalysedSection) return;
    finalising = true;
    finaliseError = null;
    try {
      const result = await summariseRoll(roll.id);
      roll.finalised_at = result.finalised_at;
      roll.scores = result.scores;
    } catch (err) {
      if (err instanceof SummariseRateLimitedError) {
        finaliseError = `Claude cooldown — ${err.retryAfterS}s until next call`;
      } else if (err instanceof ApiError) {
        finaliseError = err.message;
      } else {
        finaliseError = String(err);
      }
    } finally {
      finalising = false;
    }
  }

  function onKeyMomentGoTo(sectionId: string) {
    const section = roll?.sections.find((s) => s.id === sectionId);
    if (section) seek(section.start_s);
  }
</script>

{#if loading}
  <p class="text-white/50 text-sm">Loading roll…</p>
{:else if error || !roll}
  <div class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
    <strong>Couldn't load roll:</strong>
    {error ?? 'Unknown error'}
  </div>
{:else}
  <section class="space-y-5">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight">{roll.title}</h1>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/55">
          <span>{roll.date}</span>
          {#if roll.partner}<span>{roll.partner}</span>{/if}
          <span>{formatDuration(roll.duration_s)}</span>
        </div>
      </div>
    </header>

    <div class="rounded-lg overflow-hidden border border-white/8 bg-black">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videoEl}
        controls
        preload="metadata"
        class="w-full aspect-video bg-black"
      >
        <source src={roll.video_url} type="video/mp4" />
        Your browser can't play this video file.
      </video>
    </div>

    <SectionPicker
      videoEl={videoEl}
      durationS={roll.duration_s ?? 0}
      onAnalyse={onAnalyseSections}
      busy={analysing}
    />

    {#if queuedBanner}
      <div
        class="rounded-md border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100"
        role="status"
      >
        Queued — Claude cooldown, retrying in {queuedBanner.retryAfterS}s…
      </div>
    {/if}

    {#if roll.sections && roll.sections.length > 0}
      <div class="space-y-3">
        {#each roll.sections as section (section.id)}
          <SectionCard
            {section}
            busy={analysing && section.narrative === null}
            onSeek={(t) => seek(t)}
            onDelete={(id) => onSectionDelete(id)}
            onAddAnnotation={(id, body) => onSectionAnnotate(id, body)}
          />
        {/each}
      </div>

      {#if roll.scores && roll.finalised_at}
        <ScoresPanel
          scores={roll.scores}
          sections={roll.sections}
          finalisedAt={roll.finalised_at}
          ongoto={onKeyMomentGoTo}
        />
      {/if}
    {:else if !analysing}
      <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
        <p class="text-sm text-white/60">No sections yet.</p>
        <p class="mt-1 text-xs text-white/35">
          Pick sections above by playing the video and clicking <strong>Mark start</strong> / <strong>Mark end</strong>, then click <strong>Analyse ranges</strong>.
        </p>
      </div>
    {/if}

    <div class="flex items-center justify-between gap-3 border-t border-white/8 pt-4">
      <div class="text-[11px] text-white/40">
        {#if !hasAnyAnalysedSection}
          Analyse at least one section first.
        {:else if roll.finalised_at}
          Finalised. Click to recompute with the latest analyses + notes.
        {:else}
          Not yet finalised.
        {/if}
      </div>
      <button
        type="button"
        onclick={onFinaliseClick}
        disabled={finalising || !hasAnyAnalysedSection}
        class="rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {finalising ? 'Finalising…' : roll.finalised_at ? 'Re-finalise' : 'Finalise'}
      </button>
    </div>

    {#if finaliseError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {finaliseError}
      </div>
    {/if}

    <footer class="flex items-center justify-between gap-3 border-t border-white/8 pt-4">
      <div class="text-[11px] text-white/40">
        {#if roll.vault_path}
          Vault: <span class="font-mono">{roll.vault_path}</span>
        {:else}
          Not yet published to vault.
        {/if}
      </div>
      <div class="flex gap-2">
        <button
          type="button"
          onclick={() => onExportClick()}
          disabled={exporting || !roll.finalised_at}
          class="rounded-md border border-violet-400/40 bg-violet-500/15 px-3 py-1.5 text-xs font-medium text-violet-100 hover:bg-violet-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {exporting ? 'Exporting…' : 'Export PDF'}
        </button>
        <button
          type="button"
          onclick={() => onSaveToVault()}
          disabled={publishing}
          class="rounded-md border border-amber-400/40 bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {publishing ? 'Publishing…' : 'Save to Vault'}
        </button>
      </div>
    </footer>

    {#if publishToast}
      <div class="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
        {publishToast}
      </div>
    {/if}
    {#if publishError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {publishError}
      </div>
    {/if}
    {#if exportError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {exportError}
      </div>
    {/if}

    <PublishConflictDialog
      open={conflictOpen}
      onOverwrite={onOverwrite}
      onCancel={onCancelConflict}
    />
    <PublishConflictDialog
      open={exportConflictOpen}
      onOverwrite={onExportOverwrite}
      onCancel={onExportCancel}
    />
  </section>
{/if}
