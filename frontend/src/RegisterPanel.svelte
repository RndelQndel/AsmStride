<script lang="ts">
  import type { Flag, State } from './api';
  import ValueEditor from './ValueEditor.svelte';
  let { state, disabled, edit }: { state: State; disabled: boolean; edit: (name: string, value: number, mask?: number) => Promise<string | null> } = $props();
  const aliases: Record<string, string> = { sp: 'SP / R13', lr: 'LR / R14', pc: 'PC / R15' };
  const flags: Flag[] = ['n', 'z', 'c', 'v'];
  const masks: Record<Flag, number> = { n: 0x80000000, z: 0x40000000, c: 0x20000000, v: 0x10000000 };

  const leftKeys = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7'];
  const rightKeys = ['r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc'];
</script>
<section aria-labelledby="register-title" class="register-sidebar-panel">
  <div class="panel-header">
    <h2 id="register-title">Registers</h2>
    <span class="muted">ARMv7-A</span>
  </div>
  <div class="flags-bar">
    <span class="flags-label">Flags</span>
    <div class="flags">
      {#each flags as name}
        {@const value = state.flags?.[name] ?? false}
        <button {disabled} aria-pressed={value} class:changed={!!state.last_step?.flag_changes[name]} onclick={() => edit('cpsr', value ? 0 : masks[name], masks[name])}>
          {name.toUpperCase()} {Number(value)}{state.last_step?.flag_changes[name] ? ' Δ' : ''}
        </button>
      {/each}
    </div>
  </div>
  <div class="compact-reg-table">
    <div class="reg-column">
      {#each leftKeys as name (name)}
        {@const reg = state.registers[name]}
        {#if reg}
          <div class="register" class:changed={!!state.last_step?.register_changes[name]}>
            <ValueEditor label={aliases[name] ?? name.toUpperCase()} value={reg.value} {disabled} save={(value) => edit(name, value)} />
          </div>
        {/if}
      {/each}
    </div>
    <div class="reg-column">
      {#each rightKeys as name (name)}
        {@const reg = state.registers[name]}
        {#if reg}
          <div class="register" class:changed={!!state.last_step?.register_changes[name]}>
            <ValueEditor label={aliases[name] ?? name.toUpperCase()} value={reg.value} {disabled} save={(value) => edit(name, value)} />
          </div>
        {/if}
      {/each}
    </div>
  </div>
  {#if state.cpsr}
    <div class="register cpsr-register" class:changed={!!state.last_step?.cpsr_change}>
      <ValueEditor label="CPSR" value={state.cpsr.value} {disabled} save={(value) => edit('cpsr', value)} />
    </div>
  {/if}
  <p class="muted sidebar-hint">Only N/Z/C/V editable in CPSR. Mode/privilege protected.</p>
</section>
