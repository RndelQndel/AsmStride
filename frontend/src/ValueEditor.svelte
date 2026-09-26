<script lang="ts">
  import { hex, uint32 } from './api';
  let { label, value, disabled = false, save }: {
    label: string; value: number; disabled?: boolean; save: (value: number) => Promise<string | null>;
  } = $props();
  let draft = $state('');
  let error = $state('');
  $effect(() => { draft = hex(value); error = ''; });
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (disabled) return;
    try { error = (await save(uint32(draft))) ?? ''; }
    catch (cause) { error = (cause as Error).message; }
  }
</script>
<form onsubmit={submit} class="value-editor">
  <div class="reg-label-row">
    <label for={`reg-input-${label}`} class="reg-name">{label}</label>
  </div>
  <div class="reg-input-row">
    <input id={`reg-input-${label}`} aria-label={label} bind:value={draft} {disabled} spellcheck="false" aria-invalid={!!error} />
    <button {disabled} type="submit" aria-label={`Apply ${label}`} class="apply-btn">Apply</button>
  </div>
  {#if error}<small class="error" role="alert">{error}</small>{/if}
</form>
