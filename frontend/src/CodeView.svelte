<script lang="ts">
  import { hex } from './api';
  import type { Program, State } from './api';
  let { program, state, disabled, select }: { program: Program | null; state: State | null; disabled: boolean; select: (pc: number) => void } = $props();
  let pane: HTMLDivElement;
  const pc = $derived(state?.pc ?? null);
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
        <small>{program.mode.toUpperCase()} · {program.instruction_count} instructions{#if program.ignored_line_count} · {program.ignored_line_count} ignored{/if}</small>
      {/if}
    </h2>
  </div>
  <div class="code-pane" bind:this={pane}>
    {#if program}
      {#each program.instructions as instruction (instruction.address)}
        <div class:current={pc === instruction.address} class="instruction" data-address={instruction.address} aria-current={pc === instruction.address ? 'step' : undefined}>
          <button {disabled} onclick={() => select(instruction.address)} aria-label={`Select PC ${hex(instruction.address)}`} title="Fill the PC field without executing">{pc === instruction.address ? '▶' : '·'}</button>
          <span class="address">{hex(instruction.address)}</span>
          <span class="bytes">{instruction.bytes.match(/../g)?.join(' ')}</span>
          <div class="instruction-content">
            <strong>{instruction.decoded_text}</strong>
            {#if instruction.display_text !== instruction.decoded_text}<small class="diff-input">Input: {instruction.display_text}</small>{/if}
            {#if instruction.source_line !== null}<small class="source-line">Source line {instruction.source_line}</small>{/if}
            {#if instruction.feature_exclusion}<small class="error">! Unsupported: {instruction.feature_exclusion}</small>{/if}
          </div>
        </div>
      {/each}
    {:else}
      <p class="muted" style="padding: 16px;">Load a program to inspect its decoded instructions.</p>
    {/if}
  </div>
  {#if program}
    <details style="margin-top: 8px;"><summary>Loaded original source</summary><pre>{program.source_text}</pre></details>
  {/if}
</section>
