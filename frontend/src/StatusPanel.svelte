<script lang="ts">
  import { hex } from './api';
  import type { Diagnostic, ErrorEnvelope, StepResult } from './api';
  let { diagnostics, error, step, message }: { diagnostics: Diagnostic[]; error: ErrorEnvelope | null; step: StepResult | null; message: string } = $props();
</script>
<section aria-labelledby="status-title">
  <div class="panel-header">
    <h2 id="status-title">Status &amp; diagnostics</h2>
    <span class="muted">Execution log</span>
  </div>
  <div aria-live="polite">
    {#if message}<p class="notice">{message}</p>{/if}
    {#if error}
      <div class="error-card" style="padding: 8px 12px; background: var(--error-bg); border: 1px solid var(--error-border); border-radius: 6px; margin-bottom: 8px;">
        <p class="error" style="margin: 0 0 4px;">{error.error.code}: {error.error.message}</p>
        <pre style="margin: 0;">{JSON.stringify(error.error.context, null, 2)}</pre>
      </div>
    {/if}
    {#each error?.diagnostics ?? diagnostics as diagnostic}
      <p class:error={diagnostic.severity === 'error'} style="margin: 4px 0;">
        <strong>{diagnostic.severity.toUpperCase()}</strong> · {diagnostic.code}{diagnostic.line === null ? '' : ` · Line ${diagnostic.line}`}: {diagnostic.message}
      </p>
      {#if diagnostic.source_text}<pre>{diagnostic.source_text}</pre>{/if}
    {/each}
    {#if error?.preview?.length}
      <details style="margin: 6px 0;"><summary>Rejected import preview — not loaded</summary>
        {#each error.preview as instruction}<pre style="margin: 2px 0;">{hex(instruction.address)} {instruction.bytes} {instruction.decoded_text}</pre>{/each}
      </details>
    {/if}
    {#if step}
      <div style="padding: 8px 12px; background: var(--bg-subtle); border: 1px solid var(--border-light); border-radius: 6px; margin-top: 6px;">
        <p style="margin: 0 0 4px;"><strong>{step.status}</strong> · <code>{hex(step.pc_before)}</code> → <code>{hex(step.pc_after)}</code> · step_seq {step.step_seq}</p>
        {#if step.condition_passed !== null}<p style="margin: 2px 0;">Instruction condition: {step.condition_passed ? 'passed' : 'not passed (skipped)'}</p>{/if}
        {#if step.branch}<p style="margin: 2px 0;">{step.branch.kind} · {step.branch.condition ?? 'unconditional'} · {step.branch.taken ? 'taken' : 'not taken'} · target {hex(step.branch.target)} · fallthrough {hex(step.branch.fallthrough)}</p>{/if}
        {#if step.stop_reason}<p class="notice" style="margin: 4px 0;">Stop: {step.stop_reason} at {hex(step.pc_after)}</p>{/if}
        {#if step.error}
          <div style="margin-top: 4px;">
            <p class="error" style="margin: 0 0 2px;">{step.error.code} · {step.error.restored ? 'Previous state restored' : 'State unavailable: Reset or reload required'}</p>
            <pre style="margin: 0;">{JSON.stringify(step.error.context, null, 2)}</pre>
          </div>
        {/if}
        {#if step.memory_reads.length || step.memory_writes.length}
          <details style="margin-top: 6px;"><summary>Latest memory accesses</summary>
            <pre>{JSON.stringify({ reads: step.memory_reads, writes: step.memory_writes }, null, 2)}</pre>
          </details>
        {/if}
      </div>
    {/if}
  </div>
</section>
