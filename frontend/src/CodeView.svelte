<script lang="ts">
  import { hex } from './api';
  import type { DataRegion, Instruction, Mode, Program, State } from './api';

  let {
    program,
    state,
    disabled,
    select,
    onToggleBreakpoint
  }: {
    program: Program | null;
    state: State | null;
    disabled: boolean;
    select: (pc: number) => void;
    onToggleBreakpoint?: (address: number, mode?: Mode) => void;
  } = $props();

  let pane: HTMLDivElement;
  const pc = $derived(state?.pc ?? null);
  const breakpoints = $derived(state?.breakpoints ?? []);

  function hasBp(addr: number): boolean {
    return breakpoints.some((b) => b.address === addr);
  }

  type Row =
    | { kind: 'instruction'; address: number; instruction: Instruction; mode: Mode }
    | { kind: 'data'; address: number; dataRegion: DataRegion; mode: 'data' };

  const rows = $derived.by<Row[]>(() => {
    if (!program) return [];
    const list: Row[] = [];
    for (const inst of program.instructions) {
      list.push({
        kind: 'instruction',
        address: inst.address,
        instruction: inst,
        mode: inst.mode ?? program.mode
      });
    }
    if (program.data_regions) {
      for (const dr of program.data_regions) {
        list.push({
          kind: 'data',
          address: dr.address,
          dataRegion: dr,
          mode: 'data'
        });
      }
    }
    list.sort((a, b) => a.address - b.address);
    return list;
  });

  const symbolsByAddress = $derived.by<Record<number, string[]>>(() => {
    const map: Record<number, string[]> = {};
    if (program?.metadata?.symbols) {
      for (const s of program.metadata.symbols) {
        if (!map[s.address]) map[s.address] = [];
        map[s.address].push(s.name);
      }
    }
    return map;
  });

  const linesByAddress = $derived.by<Record<number, string>>(() => {
    const map: Record<number, string> = {};
    if (program?.metadata?.lines) {
      for (const l of program.metadata.lines) {
        map[l.address] = `${l.file}:${l.line}`;
      }
    }
    return map;
  });

  const isMixed = $derived.by(() => {
    if (!program) return false;
    if (program.data_regions && program.data_regions.length > 0) return true;
    const firstMode = program.instructions[0]?.mode;
    return program.instructions.some((i) => i.mode && i.mode !== firstMode);
  });

  function showSectionHeader(index: number, currentMode: string): boolean {
    if (!isMixed) return false;
    if (index === 0) return true;
    return rows[index - 1].mode !== currentMode;
  }

  $effect(() => {
    state; // Scroll after every authoritative response, including a self-branch or Reset.
    const current = pc;
    program;
    if (current !== null) pane?.querySelector(`[data-address="${current}"]`)?.scrollIntoView?.({ block: 'nearest' });
  });
</script>

<section aria-labelledby="code-title">
  <div class="panel-header">
    <h2 id="code-title">
      Instructions
      {#if program}
        <small>{program.mode.toUpperCase()} · {program.instruction_count} instructions{#if program.ignored_line_count} · {program.ignored_line_count} ignored{/if}{#if program.data_regions?.length} · {program.data_regions.length} data{/if}</small>
      {/if}
    </h2>
  </div>
  <div class="code-pane" bind:this={pane}>
    {#if program}
      {#each rows as row, index (row.address)}
        {#if showSectionHeader(index, row.mode)}
          <div class="section-divider section-{row.mode}">
            <span class="section-badge">{row.mode === 'arm' ? '$a · ARM' : row.mode === 'thumb' ? '$t · Thumb' : '$d · DATA'}</span>
          </div>
        {/if}
        {#if symbolsByAddress[row.address]}
          <div class="symbol-label">🏷️ {symbolsByAddress[row.address].join(', ')}:</div>
        {/if}
        {#if row.kind === 'instruction'}
          {@const isCurrent = pc === row.instruction.address}
          {@const bpActive = hasBp(row.instruction.address)}
          <div class:current={isCurrent} class="instruction" data-address={row.instruction.address} aria-current={isCurrent ? 'step' : undefined}>
            <div class="gutter">
              <button
                type="button"
                class="breakpoint-btn"
                class:has-bp={bpActive}
                disabled={disabled}
                onclick={() => onToggleBreakpoint?.(row.instruction.address, row.instruction.mode)}
                aria-label={`Toggle breakpoint at ${hex(row.instruction.address)}`}
                title={bpActive ? 'Remove breakpoint' : 'Add breakpoint'}
              >
                {bpActive ? '●' : '○'}
              </button>
              <button
                type="button"
                class="pc-select-btn"
                {disabled}
                onclick={() => select(row.instruction.address)}
                aria-label={`Select PC ${hex(row.instruction.address)}`}
                title="Fill the PC field without executing"
              >
                {isCurrent && bpActive ? '▶●' : isCurrent ? '▶' : bpActive ? '●' : '·'}
              </button>
            </div>
            {#if isMixed}
              <span class="mode-badge mode-{row.instruction.mode ?? program.mode}">{row.instruction.mode === 'thumb' ? '$t' : '$a'}</span>
            {/if}
            <span class="address">{hex(row.instruction.address)}</span>
            <span class="bytes">{row.instruction.bytes.match(/../g)?.join(' ')}</span>
            <div class="instruction-content">
              <strong>{row.instruction.decoded_text}</strong>
              {#if linesByAddress[row.instruction.address]}<small class="dwarf-line">📍 {linesByAddress[row.instruction.address]}</small>{/if}
              {#if row.instruction.display_text !== row.instruction.decoded_text}<small class="diff-input">Input: {row.instruction.display_text}</small>{/if}
              {#if row.instruction.source_line !== null}<small class="source-line">Source line {row.instruction.source_line}</small>{/if}
              {#if row.instruction.feature_exclusion}<small class="error">! Unsupported: {row.instruction.feature_exclusion}</small>{/if}
            </div>
          </div>
        {:else}
          <div class="instruction data-row" data-address={row.dataRegion.address}>
            <div class="gutter">
              <button
                type="button"
                class="breakpoint-btn data-bp"
                disabled
                aria-label={`Data at ${hex(row.dataRegion.address)}`}
                title="Cannot set breakpoint on data"
              >
                ·
              </button>
              <span class="gutter-spacer">·</span>
            </div>
            {#if isMixed}
              <span class="mode-badge mode-data">$d</span>
            {/if}
            <span class="address">{hex(row.dataRegion.address)}</span>
            <span class="bytes">{row.dataRegion.bytes.match(/../g)?.join(' ')}</span>
            <div class="instruction-content">
              <strong class="data-text">DATA ({row.dataRegion.size} bytes)</strong>
              {#if row.dataRegion.source_line !== null}<small class="source-line">Source line {row.dataRegion.source_line}</small>{/if}
            </div>
          </div>
        {/if}
      {/each}
    {:else}
      <p class="muted" style="padding: 16px;">Load a program to inspect its decoded instructions.</p>
    {/if}
  </div>
  {#if program}
    <details style="margin-top: 8px;"><summary>Loaded original source</summary><pre>{program.source_text}</pre></details>
  {/if}
</section>
