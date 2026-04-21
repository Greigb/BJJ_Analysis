<script lang="ts">
  import type { GraphCategory, GraphFilter } from '$lib/types';

  let {
    categories,
    activeFilter,
    playerAName = 'Greig',
    playerBName = 'Anthony',
    onfilterchange
  }: {
    categories: GraphCategory[];
    activeFilter: GraphFilter;
    playerAName?: string;
    playerBName?: string;
    onfilterchange: (filter: GraphFilter) => void;
  } = $props();

  function isActive(kind: GraphFilter['kind'], key?: string): boolean {
    if (activeFilter.kind !== kind) return false;
    if (kind === 'category') return activeFilter.kind === 'category' && activeFilter.id === key;
    if (kind === 'player') return activeFilter.kind === 'player' && activeFilter.who === key;
    return true;
  }
</script>

<div class="flex flex-wrap items-center gap-1.5">
  <button
    type="button"
    aria-pressed={activeFilter.kind === 'all'}
    onclick={() => onfilterchange({ kind: 'all' })}
    class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
           {activeFilter.kind === 'all'
             ? 'bg-white/10 border-white/30 text-white'
             : 'border-white/15 text-white/55 hover:bg-white/5'}"
  >
    All
  </button>

  {#each categories as cat (cat.id)}
    <button
      type="button"
      aria-pressed={isActive('category', cat.id)}
      onclick={() => onfilterchange({ kind: 'category', id: cat.id })}
      style:--chip-tint={cat.tint}
      class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
             {isActive('category', cat.id)
               ? 'bg-[var(--chip-tint)] text-black border-transparent'
               : 'border-white/15 text-white/55 hover:bg-white/5'}"
    >
      {cat.label}
    </button>
  {/each}

  <span class="mx-1 h-4 w-px bg-white/15"></span>

  <button
    type="button"
    aria-pressed={isActive('player', 'a')}
    onclick={() => onfilterchange({ kind: 'player', who: 'a' })}
    class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
           {isActive('player', 'a')
             ? 'bg-white/20 border-white/40 text-white'
             : 'border-white/15 text-white/55 hover:bg-white/5'}"
  >
    {playerAName}
  </button>
  <button
    type="button"
    aria-pressed={isActive('player', 'b')}
    onclick={() => onfilterchange({ kind: 'player', who: 'b' })}
    class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
           {isActive('player', 'b')
             ? 'bg-rose-500/30 border-rose-400/50 text-rose-100'
             : 'border-white/15 text-white/55 hover:bg-white/5'}"
  >
    {playerBName}
  </button>
</div>
