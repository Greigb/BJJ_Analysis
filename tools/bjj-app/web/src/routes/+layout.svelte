<script lang="ts">
  import '../app.css';

  let { children } = $props();
</script>

<div class="min-h-screen flex flex-col">
  <header
    class="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-white/[0.02]"
  >
    <a href="/" class="flex items-center gap-2">
      <div class="size-8 rounded-lg bg-white/10 grid place-items-center text-sm font-bold">
        B
      </div>
      <div>
        <div class="text-[15px] font-semibold tracking-tight">BJJ Review</div>
        <div class="text-[11px] text-white/50">Tempo Jiu Jitsu</div>
      </div>
    </a>
    <nav class="flex gap-1 text-sm">
      <a
        class="px-3 py-1.5 rounded-md bg-blue-500/15 text-blue-200 border border-blue-400/40"
        href="/new"
      >
        + New Roll
      </a>
    </nav>
  </header>

  <main class="flex-1 max-w-4xl w-full mx-auto px-4 sm:px-6 py-6">
    {@render children?.()}
  </main>

  <footer class="px-6 py-4 text-center text-[11px] text-white/35">
    Analyses powered by Claude Opus 4.7 via local CLI · v0.1.0
  </footer>
</div>
