<script lang="ts">
  import { hex } from './api';
  import type { Diagnostic, ErrorEnvelope, RunResult, StepResult } from './api';

  let {
    view = 'all',
    diagnostics,
    error,
    step,
    message,
    runResult = null
  }: {
    view?: 'all' | 'problems' | 'output' | 'execution';
    diagnostics: Diagnostic[];
    error: ErrorEnvelope | null;
    step: StepResult | null;
    message: string;
    runResult?: RunResult | null;
  } = $props();
</script>

<section aria-label={view === 'all' ? 'Status & diagnostics' : view}>
  <div class="panel-header">
    <h2>{view === 'all' ? 'Status & diagnostics' : view}</h2>
    <span class="muted">Execution log</span>
  </div>
  <div aria-live="polite">
    {#if view === 'problems' && !error && diagnostics.length === 0}<p class="muted">No problems reported.</p>{/if}
    {#if view === 'output' && !message}<p class="muted">No operation messages.</p>{/if}
    {#if view === 'execution' && !step && !runResult}<p class="muted">Step or Run a loaded program to inspect execution.</p>{/if}
    {#if (view === 'all' || view === 'output') && message}<p class="notice">{message}</p>{/if}
    {#if view === 'all' || view === 'problems'}
    {#if error}
      <div role="alert" class="error-card" style="padding: 8px 12px; background: var(--error-bg); border: 1px solid var(--error-border); border-radius: 0; margin-bottom: 8px;">
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
    {/if}
    {#if view === 'all' || view === 'execution'}
    {#if runResult}
      <div class="execution-summary">
        <p style="margin: 0 0 4px;">
          <strong>Run result:</strong> Stop reason: <span class="badge">{runResult.stop_reason}</span>
          · {runResult.steps_committed} steps committed
          · {runResult.elapsed_ms.toFixed(1)} ms
          {#if runResult.breakpoint_hit !== null}
            · Breakpoint hit at <code>{hex(runResult.breakpoint_hit)}</code>
          {/if}
        </p>
      </div>
    {/if}
    {#if step}
      <div class="execution-summary">
        <p style="margin: 0 0 4px;"><strong>{step.status}</strong> · <code>{hex(step.pc_before)}</code> → <code>{hex(step.pc_after)}</code> · step_seq {step.step_seq}</p>
        {#if step.it_context}
          <p class="it-context" style="margin: 2px 0;">
            <strong>IT Block [{step.it_context.block_index}/{step.it_context.block_total}]:</strong>
            Condition {step.it_context.condition} — {step.it_context.passed ? 'passed (executed)' : 'not passed (conditionally skipped)'}
          </p>
        {/if}
        {#if step.condition_passed !== null && !step.it_context}
          <p style="margin: 2px 0;">Instruction condition: {step.condition_passed ? 'passed' : 'not passed (skipped)'}</p>
        {/if}
        {#if step.executed === false && step.condition_passed === false}
          <p class="notice" style="margin: 2px 0;">Instruction conditionally skipped: no state mutated.</p>
        {/if}
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
    {/if}
  </div>
</section>
