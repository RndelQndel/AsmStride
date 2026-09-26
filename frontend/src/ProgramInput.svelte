<script lang="ts">
  import { uint32 } from './api';
  import type { LoadRequest, Mode } from './api';
  let { disabled, load }: { disabled: boolean; load: (request: LoadRequest) => Promise<string | null> } = $props();
  let kind = $state<'assembly' | 'disassembly'>('assembly');
  let mode = $state<Mode>('arm');
  let source = $state('mov r0, #5\nadd r1, r0, #3\ncmp r1, #8');
  let imported = $state('0x1000: E3A00005 MOV r0,#5\n0x1004: E2801003 ADD r1,r0,#3');
  let base = $state('0x1000');
  let format = $state<'auto' | 'fromelf' | 'objdump' | 'generic'>('auto');
  let encoding = $state<'auto' | 'words' | 'bytes'>('auto');
  let customStack = $state(false);
  let stackBase = $state('0x200f0000');
  let stackSize = $state('65536');
  let error = $state('');
  let reading = $state(false);
  async function readFile(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (!file || disabled) return;
    const selectedKind = kind;
    reading = true;
    try {
      if (file.size > 1048576) throw new Error('Text file exceeds 1 MiB.');
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      if (selectedKind === 'assembly') source = text; else imported = text;
      error = '';
    } catch (cause) { error = `File could not be read: ${(cause as Error).message}`; }
    finally { reading = false; }
  }
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (disabled || reading) return;
    try {
      const text = kind === 'assembly' ? source : imported;
      if (!text.trim()) throw new Error('Enter source or disassembly text.');
      if (new TextEncoder().encode(text).length > 1048576) throw new Error('Input exceeds 1 MiB.');
      const common = { text, mode, ...(customStack ? { stack: { base: uint32(stackBase), size: uint32(stackSize) } } : {}) };
      const request: LoadRequest = kind === 'assembly'
        ? { ...common, input_kind: kind, base_address: uint32(base) }
        : { ...common, input_kind: kind, format, encoding };
      error = (await load(request)) ?? '';
    } catch (cause) { error = (cause as Error).message; }
  }
</script>
<section aria-labelledby="input-title">
  <div class="panel-header">
    <h2 id="input-title">Program input</h2>
    <span class="muted">Assemble ARM/Thumb snippet or import disassembly</span>
  </div>
  <form onsubmit={submit}>
    <fieldset disabled={disabled || reading}>
      <div class="input-layout">
        <div class="input-config">
          <div class="fields-grid">
            <label>Input<select bind:value={kind}><option value="assembly">Assembly source</option><option value="disassembly">Disassembly import</option></select></label>
            <label>Mode<select bind:value={mode}><option value="arm">ARM</option><option value="thumb">Thumb / Thumb-2</option></select></label>
            {#if kind === 'assembly'}
              <label>Base address<input bind:value={base} spellcheck="false" /></label>
            {:else}
              <label>Format<select bind:value={format}>{#each ['auto', 'fromelf', 'objdump', 'generic'] as option}<option>{option}</option>{/each}</select></label>
              <label>Encoding<select bind:value={encoding}>{#each ['auto', 'words', 'bytes'] as option}<option>{option}</option>{/each}</select></label>
            {/if}
          </div>
          <div class="file-load-row">
            <label class="file-label">Read local text file<input type="file" accept="text/*,.s,.asm,.lst,.log" onchange={readFile} /></label>
            <button type="submit" class="primary load-btn">Load</button>
          </div>
        </div>
        <div class="input-editor">
          {#if kind === 'assembly'}
            <label>Assembly source<textarea bind:value={source} rows="4" spellcheck="false"></textarea></label>
          {:else}
            <label>Disassembly text<textarea bind:value={imported} rows="4" spellcheck="false"></textarea></label>
          {/if}
          <details class="stack-setup"><summary>Scratch stack setup</summary>
            <label class="inline"><input type="checkbox" bind:checked={customStack} />Use custom scratch stack</label>
            {#if customStack}<div class="fields" style="margin-top: 6px;"><label>Stack base<input bind:value={stackBase} /></label><label>Stack size (bytes)<input bind:value={stackSize} /></label></div>{/if}
            <p class="muted" style="margin: 4px 0 0;">Default: 64 KiB initialized zero at 0x200f0000. SP starts at top (0x20100000).</p>
          </details>
        </div>
      </div>
    </fieldset>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </form>
  <p class="muted info-footer">Load replaces the experiment with fresh defaults. Files are read as text in this browser.</p>
</section>
