<script lang="ts">
  import { uint32 } from './api';
  import type { LoadRequest, Mode, Profile } from './api';
  let {
    disabled, load,
    source = $bindable('mov r0, #5\nadd r1, r0, #3\ncmp r1, #8'),
    imported = $bindable('0x1000: E3A00005 MOV r0,#5\n0x1004: E2801003 ADD r1,r0,#3'),
    kind = $bindable('assembly'),
  }: {
    disabled: boolean;
    load: (request: LoadRequest) => Promise<string | null>;
    source?: string;
    imported?: string;
    kind?: 'assembly' | 'disassembly' | 'elf';
  } = $props();
  let profile = $state<Profile>('armv7-a-le');
  let mode = $state<Mode>('arm');
  let elfBase64 = $state('');
  let elfFileName = $state('');
  let base = $state('0x1000');
  let format = $state<'auto' | 'fromelf' | 'objdump' | 'generic'>('auto');
  let encoding = $state<'auto' | 'words' | 'bytes'>('auto');
  let customStack = $state(false);
  let stackBase = $state('0x20000000');
  let stackSize = $state('65536');
  let error = $state('');
  let reading = $state(false);

  function onProfileChange() {
    if (profile === 'rv32i-le') {
      mode = 'riscv32';
      stackBase = '0x200f0000';
    } else {
      mode = 'arm';
      stackBase = '0x20000000';
    }
  }

  function bufferToBase64(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunk = 8192;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunk)));
    }
    return btoa(binary);
  }

  async function readFile(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (!file || disabled) return;
    const selectedKind = kind;
    reading = true;
    try {
      if (selectedKind === 'elf') {
        if (file.size > 10 * 1024 * 1024) throw new Error('ELF file exceeds 10 MiB limit.');
        const buf = await file.arrayBuffer();
        elfBase64 = bufferToBase64(buf);
        elfFileName = file.name;
        error = '';
      } else {
        if (file.size > 1048576) throw new Error('Text file exceeds 1 MiB.');
        const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
        if (selectedKind === 'assembly') source = text; else imported = text;
        error = '';
      }
    } catch (cause) { error = `File could not be read: ${(cause as Error).message}`; }
    finally { reading = false; }
  }

  async function submit(event?: SubmitEvent) {
    event?.preventDefault();
    if (disabled || reading) return;
    try {
      if (kind === 'elf') {
        if (!elfBase64) throw new Error('Select an ELF binary file to load.');
        const common = { profile, ...(customStack ? { stack: { base: uint32(stackBase), size: uint32(stackSize) } } : {}) };
        error = (await load({ ...common, input_kind: 'elf', content_base64: elfBase64, profile })) ?? '';
        return;
      }
      const text = kind === 'assembly' ? source : imported;
      if (!text.trim()) throw new Error('Enter source or disassembly text.');
      if (new TextEncoder().encode(text).length > 1048576) throw new Error('Input exceeds 1 MiB.');
      const common = { text, mode, profile, ...(customStack ? { stack: { base: uint32(stackBase), size: uint32(stackSize) } } : {}) };
      const request: LoadRequest = kind === 'assembly'
        ? { ...common, input_kind: kind, base_address: uint32(base) }
        : { ...common, input_kind: kind, format, encoding };
      error = (await load(request)) ?? '';
    } catch (cause) { error = (cause as Error).message; }
  }
  async function applyPreset(type: 'thumb-it' | 'mixed-arm-thumb' | 'mixed-thumb-arm' | 'thumb-loop' | 'arm-basic' | 'rv32-loop' | 'rv32-mem') {
    if (disabled || reading) return;
    if (type === 'rv32-loop') {
      profile = 'rv32i-le';
      mode = 'riscv32';
      kind = 'assembly';
      base = '0x1000';
      source = 'li a0, 0\nli a1, 10\nloop:\naddi a0, a0, 1\nblt a0, a1, loop\nebreak';
    } else if (type === 'rv32-mem') {
      profile = 'rv32i-le';
      mode = 'riscv32';
      kind = 'assembly';
      base = '0x1000';
      source = 'addi sp, sp, -16\nli t0, 0x42\nsw t0, 0(sp)\nlw a0, 0(sp)\naddi sp, sp, 16\nret';
    } else if (type === 'thumb-it') {
      profile = 'armv7-a-le';
      kind = 'disassembly';
      mode = 'thumb';
      format = 'generic';
      imported = '$t\n0x2000: 2000     MOVS r0, #0\n0x2002: bf18     IT NE\n0x2004: 2101     MOVNE r1, #1\n0x2006: 2202     MOV r2, #2\n0x2008: 2001     MOVS r0, #1\n0x200a: bf08     IT EQ\n0x200c: 2303     MOVEQ r3, #3';
    } else if (type === 'mixed-arm-thumb') {
      profile = 'armv7-a-le';
      kind = 'disassembly';
      mode = 'arm';
      format = 'generic';
      imported = '$a\n0x1000: e3a0002a MOV r0, #42\n0x1004: e28f1001 ADD r1, pc, #1\n0x1008: e12fff11 BX r1\n$t\n0x100c: 2205     MOVS r2, #5\n0x100e: 4b01     LDR r3, [pc, #4]\n0x1010: 4770     BX lr\n$d\n0x1014: 12345678 .word 0x12345678';
    } else if (type === 'mixed-thumb-arm') {
      profile = 'armv7-a-le';
      kind = 'disassembly';
      mode = 'thumb';
      format = 'generic';
      imported = '$t\n0x1000: 2000     MOVS r0, #0\n0x1002: bf18     IT NE\n0x1004: 2101     MOVNE r1, #1\n0x1006: f242 0100 MOVW r1, #0x2000\n0x100a: 4708     BX r1\n$a\n0x2000: e3a0202a MOV r2, #42\n0x2004: e59f3000 LDR r3, [pc, #0]\n0x2008: e12fff1e BX lr\n$d\n0x200c: cafebabe .word 0xcafebabe';
    } else if (type === 'thumb-loop') {
      profile = 'armv7-a-le';
      kind = 'assembly';
      mode = 'thumb';
      base = '0x2000';
      source = 'movs r0, #0\nloop:\nadds r0, r0, #1\ncmp r0, #10\nbne loop\nb .';
    } else {
      profile = 'armv7-a-le';
      kind = 'assembly';
      mode = 'arm';
      base = '0x1000';
      source = 'mov r0, #5\nadd r1, r0, #3\ncmp r1, #8';
    }
    await submit();
  }
</script>
<section aria-label="Program configuration">
  <h2 id="input-title">Input</h2>
  <form onsubmit={submit}>
    <fieldset disabled={disabled || reading}>
      <div class="fields-grid">
        <label>Architecture<select bind:value={profile} onchange={onProfileChange}>
          <option value="armv7-a-le">ARMv7-A</option>
          <option value="rv32i-le">RISC-V (RV32I)</option>
        </select></label>
        <label>Input<select bind:value={kind}>
          <option value="assembly">Assembly source</option>
          <option value="disassembly">Disassembly import</option>
          <option value="elf">ELF32 Binary (.elf)</option>
        </select></label>
        {#if kind !== 'elf'}
          <label>Mode<select bind:value={mode}>
            {#if profile === 'rv32i-le'}
              <option value="riscv32">RV32I</option>
            {:else}
              <option value="arm">ARM</option>
              <option value="thumb">Thumb / Thumb-2</option>
            {/if}
          </select></label>
        {/if}
        {#if kind === 'assembly'}
          <label>Base address<input bind:value={base} spellcheck="false" /></label>
        {:else if kind === 'disassembly'}
          <label>Format<select bind:value={format}>{#each ['auto', 'fromelf', 'objdump', 'generic'] as option}<option>{option}</option>{/each}</select></label>
          <label>Encoding<select bind:value={encoding}>{#each ['auto', 'words', 'bytes'] as option}<option>{option}</option>{/each}</select></label>
        {/if}
      </div>
      <div class="file-load-row">
        {#if kind === 'elf'}
          <label class="file-label">Select ELF binary<input type="file" accept=".elf,.axf,.o,application/octet-stream" onchange={readFile} /></label>
        {:else}
          <label class="file-label">Read local text file<input type="file" accept="text/*,.s,.asm,.lst,.log" onchange={readFile} /></label>
        {/if}
        <button type="submit" class="primary load-btn">Load</button>
      </div>
      <details class="stack-setup"><summary>Scratch stack setup</summary>
        <label class="inline"><input type="checkbox" bind:checked={customStack} />Use custom scratch stack</label>
        {#if customStack}<div class="fields" style="margin-top: 6px;"><label>Stack base<input bind:value={stackBase} /></label><label>Stack size (bytes)<input bind:value={stackSize} /></label></div>{/if}
        <p class="muted" style="margin: 4px 0 0;">Default: 64 KiB initialized zero at 0x200f0000. SP starts at top (0x20100000).</p>
      </details>
      {#if kind === 'elf'}<p class="muted">{elfFileName || 'Choose an ELF32-LE file (max 10 MiB).'}</p>{/if}
    </fieldset>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </form>
  <details class="presets-bar"><summary>Example presets</summary>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('rv32-loop')}>RV32I Loop</button>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('rv32-mem')}>RV32I Load/Store</button>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('mixed-thumb-arm')}>Mixed (Thumb ➔ ARM + Data)</button>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('mixed-arm-thumb')}>Mixed (ARM ➔ Thumb + Data)</button>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('thumb-it')}>Thumb-2 IT Blocks</button>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('thumb-loop')}>Thumb Loop & Run</button>
    <button type="button" class="preset-pill" disabled={disabled || reading} onclick={() => applyPreset('arm-basic')}>ARM Basic</button>

  </details>
  <p class="muted">Load replaces the experiment with fresh defaults.</p>
</section>
