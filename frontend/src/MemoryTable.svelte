<script lang="ts">
  import { tick } from 'svelte';
  import { hex } from './api';
  import type { StepResult } from './api';
  import { byteChanged, word } from './memory';
  import type { MemoryWindow } from './memory';
  let { window, step, sp = null, active = true }: { window: MemoryWindow; step: StepResult | null; sp?: number | null; active?: boolean } = $props();
  let viewport: HTMLDivElement;
  $effect(() => {
    // Center the SP row inside the scroll pane without moving the whole page.
    window; sp;
    if (!active) return;
    let mounted = true;
    void tick().then(() => {
      if (!mounted || !viewport) return;
      const marker = viewport.querySelector<HTMLElement>('tr.current');
      viewport.scrollTop = marker
        ? viewport.scrollTop + marker.getBoundingClientRect().top - viewport.getBoundingClientRect().top - viewport.clientHeight / 2
        : 0;
    });
    return () => { mounted = false; };
  });
  const rows = $derived(Array.from({ length: Math.ceil((window.address % 4 + window.length) / 4) }, (_, i) => {
    const address = window.address - window.address % 4 + i * 4;
    const cells = Array.from({ length: 4 }, (_, j) => {
      const offset = address + j - window.address;
      return offset >= 0 && offset < window.cells.length ? window.cells[offset] : null;
    });
    return { address, cells };
  }));
</script>
<!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users must be able to scroll the bounded table.) -->
<div bind:this={viewport} class="memory-table" tabindex="0" role="region" aria-label="Memory words and bytes">
  <table>
    <thead><tr><th>Address</th><th>Bytes (ascending address)</th><th>Little-endian word</th><th>Source</th></tr></thead>
    <tbody>{#each rows as row}
      <tr data-address={hex(row.address)} class:current={row.address === sp}>
        <th><code>{hex(row.address)}</code>{row.address === sp ? ' ← SP' : ''}</th>
        <td>{#each row.cells as cell, index}<span class:changed={cell && byteChanged(row.address + index, step)}><code>{cell ? cell.value === null ? '??' : cell.value.toString(16).padStart(2, '0') : '—'}</code>{cell && byteChanged(row.address + index, step) ? ' Δ' : ''}</span> {/each}</td>
        <td><code>{word(row.cells.filter(cell => cell !== null))}</code></td>
        <td>{[...new Set(row.cells.filter(cell => cell !== null).map(cell => cell.origin === 'stack' ? 'synthetic stack' : cell.origin))].join(', ')}</td>
      </tr>
    {/each}</tbody>
  </table>
</div>
