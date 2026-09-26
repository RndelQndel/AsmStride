<script lang="ts">
  import { hex } from './api';
  import { patch, range, STACK_WINDOW_BYTES } from './memory';
  import type { PageSession } from './session.svelte';
  import MemoryTable from './MemoryTable.svelte';
  let { session }: { session: PageSession } = $props();
  let address = $state('0x20000000');
  let length = $state('64');
  let patchAddress = $state('0x20000000');
  let kind = $state<'bytes' | 'word' | 'zero'>('bytes');
  let input = $state('');
  let error = $state('');
  let inspectError = $state('');
  const step = $derived(session.uncertainty ? null : session.state?.last_step ?? null);
  async function inspect(event: SubmitEvent) {
    event.preventDefault();
    try {
      const selected = range(address, length, 4096);
      inspectError = '';
      await session.inspect(selected.address, selected.length);
    } catch (cause) { inspectError = (cause as Error).message; }
  }
  async function apply(event: SubmitEvent) {
    event.preventDefault();
    try { error = (await session.patchMemory(patch(patchAddress, kind, input))) ?? ''; }
    catch (cause) { error = (cause as Error).message; }
  }
  function move(distance: number) {
    const sp = session.state?.registers.sp?.value ?? 0;
    return scroll((session.stackMemory?.address ?? 0) + distance - sp + STACK_WINDOW_BYTES / 2);
  }
  function scroll(offset: number) {
    return session.inspect(session.memoryAddress, session.memoryLength, offset);
  }
</script>
<div class="memory-workspace">
  <section aria-labelledby="memory-title">
    <div class="panel-header">
      <h2 id="memory-title">Memory</h2>
      <span class="muted">Hex bytes &amp; words</span>
    </div>
    <form onsubmit={inspect}><fieldset disabled={!session.editable} class="fields">
      <label>Memory address<input bind:value={address} /></label>
      <label>Inspection bytes<input bind:value={length} /></label>
      <button>Inspect memory</button>
    </fieldset></form>
    {#if inspectError}<p class="error" role="alert">{inspectError}</p>{/if}
    <p class="muted" style="margin: 6px 0;">?? = unknown; inspection never allocates memory. Δ = changed by latest Step.</p>
    {#if session.memory}<MemoryTable window={session.memory} {step} />{:else}<p class="muted">Memory view unavailable.</p>{/if}
    <form onsubmit={apply}><fieldset disabled={!session.editable}>
      <div class="fields">
        <label>Patch address<input bind:value={patchAddress} /></label>
        <label>Patch type<select bind:value={kind}><option value="bytes">Hex bytes</option><option value="word">32-bit word (little-endian)</option><option value="zero">Zero-fill</option></select></label>
      </div>
      <label style="margin-top: 6px;">{kind === 'zero' ? 'Zero-fill length (bytes)' : kind === 'word' ? 'Word value' : 'Hex bytes'}<input bind:value={input} /></label>
      <button style="margin-top: 6px;">{kind === 'zero' ? 'Zero-fill memory' : 'Apply memory patch'}</button>
    </fieldset></form>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <p class="muted" style="margin-top: 6px;">Manual edits update the reset baseline. Patches limited to 64 KiB; code is read-only.</p>
  </section>
  <section aria-labelledby="stack-title">
    <div class="panel-header">
      <h2 id="stack-title">Stack</h2>
      <span class="muted">Scratch stack &amp; SP</span>
    </div>
    <p style="margin: 0 0 6px;">Synthetic scratch stack: <code>{hex(session.state?.stack?.base ?? null)}</code> – <code>{hex(session.state?.stack ? session.state.stack.base + session.state.stack.size : null)}</code> (exclusive top)</p>
    <p style="margin: 0 0 8px;">SP: <code>{hex(session.state?.registers.sp?.value ?? null)}</code> <span class="muted">· Editing SP does not allocate memory.</span></p>
    <div class="fields" style="margin-bottom: 8px;">
      <button disabled={!session.editable || !session.stackMemory || session.stackMemory.address === 0} onclick={() => move(-STACK_WINDOW_BYTES)}>Lower addresses</button>
      <button disabled={!session.editable} onclick={() => scroll(0)}>Follow SP</button>
      <button disabled={!session.editable || !session.stackMemory || session.stackMemory.address + STACK_WINDOW_BYTES >= 0x100000000} onclick={() => move(STACK_WINDOW_BYTES)}>Higher addresses</button>
    </div>
    {#if session.stackMemory}<MemoryTable window={session.stackMemory} {step} sp={session.state?.registers.sp?.value ?? null} />{:else}<p class="muted">Stack view unavailable.</p>{/if}
  </section>
</div>
{#if session.memoryError}<p class="error" role="alert">{session.memoryError} Use Inspect memory to retry.</p>{/if}
