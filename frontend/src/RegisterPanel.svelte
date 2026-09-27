<script lang="ts">
  import type { Flag, State } from './api';
  import ValueEditor from './ValueEditor.svelte';
  let { state, disabled, edit }: { state: State; disabled: boolean; edit: (name: string, value: number, mask?: number) => Promise<string | null> } = $props();

  const isRiscv = $derived(state.profile === 'rv32i-le');

  const armAliases: Record<string, string> = { sp: 'SP / R13', lr: 'LR / R14', pc: 'PC / R15' };
  const riscvAliases: Record<string, string> = {
    x0: 'zero', x1: 'ra', x2: 'sp', x3: 'gp', x4: 'tp',
    x5: 't0', x6: 't1', x7: 't2', x8: 's0/fp', x9: 's1',
    x10: 'a0', x11: 'a1', x12: 'a2', x13: 'a3', x14: 'a4',
    x15: 'a5', x16: 'a6', x17: 'a7', x18: 's2', x19: 's3',
    x20: 's4', x21: 's5', x22: 's6', x23: 's7', x24: 's8',
    x25: 's9', x26: 's10', x27: 's11', x28: 't3', x29: 't4',
    x30: 't5', x31: 't6', pc: 'pc'
  };

  const flags: Flag[] = ['n', 'z', 'c', 'v'];
  const masks: Record<Flag, number> = { n: 0x80000000, z: 0x40000000, c: 0x20000000, v: 0x10000000 };

  const armLeftKeys = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7'];
  const armRightKeys = ['r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc'];

  const riscvLeftKeys = [
    'x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7',
    'x8', 'x9', 'x10', 'x11', 'x12', 'x13', 'x14', 'x15', 'pc'
  ];
  const riscvRightKeys = [
    'x16', 'x17', 'x18', 'x19', 'x20', 'x21', 'x22', 'x23',
    'x24', 'x25', 'x26', 'x27', 'x28', 'x29', 'x30', 'x31'
  ];

  const leftKeys = $derived(isRiscv ? riscvLeftKeys : armLeftKeys);
  const rightKeys = $derived(isRiscv ? riscvRightKeys : armRightKeys);

  function getLabel(name: string): string {
    if (isRiscv) {
      const alias = riscvAliases[name];
      return alias && alias !== name ? `${name} (${alias})` : name.toUpperCase();
    }
    return armAliases[name] ?? name.toUpperCase();
  }
</script>
<section aria-labelledby="register-title" class="register-sidebar-panel">
  <div class="panel-header">
    <h2 id="register-title">Registers</h2>
    <span class="muted">{isRiscv ? 'RV32I' : 'ARMv7-A'}</span>
  </div>
  {#if !isRiscv && state.flags}
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
  {/if}
  <div class="compact-reg-table">
    <div class="reg-column">
      {#each leftKeys as name (name)}
        {@const reg = state.registers[name]}
        {#if reg}
          <div class="register" class:changed={!!state.last_step?.register_changes[name]}>
            <ValueEditor label={getLabel(name)} value={reg.value} disabled={disabled || (isRiscv && name === 'x0')} save={(value) => edit(name, value)} />
          </div>
        {/if}
      {/each}
    </div>
    <div class="reg-column">
      {#each rightKeys as name (name)}
        {@const reg = state.registers[name]}
        {#if reg}
          <div class="register" class:changed={!!state.last_step?.register_changes[name]}>
            <ValueEditor label={getLabel(name)} value={reg.value} disabled={disabled || (isRiscv && name === 'x0')} save={(value) => edit(name, value)} />
          </div>
        {/if}
      {/each}
    </div>
  </div>
  {#if !isRiscv && state.cpsr}
    <div class="register cpsr-register" class:changed={!!state.last_step?.cpsr_change}>
      <ValueEditor label="CPSR" value={state.cpsr.value} {disabled} save={(value) => edit('cpsr', value)} />
    </div>
    <p class="muted sidebar-hint">Only N/Z/C/V editable in CPSR. Mode/privilege protected.</p>
  {/if}
  {#if isRiscv}
    <p class="muted sidebar-hint">x0 (zero) is hardwired to 0 and immutable.</p>
  {/if}
</section>
