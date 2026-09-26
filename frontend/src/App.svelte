<script lang="ts">
  import { onMount } from 'svelte';
  import { hex, uint32 } from './api';
  import { PageSession } from './session.svelte';
  import ProgramInput from './ProgramInput.svelte';
  import CodeView from './CodeView.svelte';
  import RegisterPanel from './RegisterPanel.svelte';
  import MemoryPanel from './MemoryPanel.svelte';
  import StatusPanel from './StatusPanel.svelte';

  const session = new PageSession();
  session.memoryEnabled = true;
  if (typeof window !== 'undefined') {
    (window as unknown as { __armstride_session?: PageSession }).__armstride_session = session;
  }
  let pc = $state('');
  let pcError = $state('');
  let stepLimit = $state(10000);
  let timeLimitMs = $state(2000);

  $effect(() => { pc = session.state?.pc === null || session.state?.pc === undefined ? '' : hex(session.state.pc); pcError = ''; });
  onMount(() => { void session.create(); return () => session.dispose(); });

  async function go(event: SubmitEvent) {
    event.preventDefault();
    if (!session.editable) return;
    try { pcError = (await session.edit('pc', uint32(pc))) ?? ''; }
    catch (error) { pcError = (error as Error).message; }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'F5') {
      event.preventDefault();
      if (session.editable && !session.running) session.run(stepLimit, timeLimitMs);
    } else if (event.key === 'F7' || event.key === 'F8') {
      event.preventDefault();
      if (session.editable && !session.running) session.step();
    } else if (event.key === 'F9') {
      event.preventDefault();
      if (session.state && session.state.status !== 'empty' && !session.pending && !session.running) session.reset();
    }
  }
</script>

<svelte:window onpagehide={() => session.dispose()} onpageshow={(event) => { if (event.persisted) location.reload(); }} onkeydown={handleKeydown} />
<header class="app-header toolbar" aria-label="Execution controls">
  <div class="header-brand">
    <h1>⚡ ArmStride</h1>
    <span class="badge">ARMv7-A</span>
  </div>
  <div class="header-controls">
    <div class="action-buttons">
      <button class="step-btn" disabled={!session.editable || session.running} onclick={() => session.step()} title="Step instruction (F7 or F8)">Step</button>
      <button class="primary run-btn" disabled={!session.editable || session.running} onclick={() => session.run(stepLimit, timeLimitMs)} title="Run instructions until breakpoint or limit (F5)">Run</button>
      <button class="stop-btn" disabled={!session.running} onclick={() => session.stop()} title="Stop execution">Stop</button>
      <button class="reset-btn" disabled={session.running || session.pending || session.expired || !session.state || session.state.status === 'empty' || session.uncertainty === 'program'} onclick={() => session.reset()} title="Reset execution to baseline (F9)">Reset</button>
    </div>
    <div class="limit-controls">
      <label title="Step count limit per Run">Limit <input type="number" min="1" max="100000" bind:value={stepLimit} disabled={session.running || !session.editable} style="width: 60px;" /> steps</label>
    </div>
    <form onsubmit={go} class="pc-form">
      <label>Start / current PC<input bind:value={pc} disabled={!session.editable || session.running} aria-invalid={!!pcError} spellcheck="false" placeholder="0x1000" /></label>
      <button disabled={!session.editable || session.running} class="go-btn" title="Jump PC without executing">Go</button>
    </form>
    <div class="status-chips">
      <span class="status-badge status-{session.running ? 'running' : session.state?.status ?? 'empty'}" role="status">{session.running ? 'Running…' : session.pending ? 'Request pending…' : session.state?.status ?? 'Connecting…'}</span>
      <span class="seq-badge">step_seq {session.state?.step_seq ?? 0}</span>
    </div>
  </div>
</header>
{#if pcError}<div class="alert-bar error" role="alert">{pcError}</div>{/if}
{#if session.uncertainty}<div class="alert-bar notice">Outcome uncertain. {session.uncertainty === 'program' ? 'Load again to recover the program listing.' : 'Reset or reload before further execution or edits.'}</div>{/if}
{#if session.state?.status === 'unavailable'}<div class="alert-bar error">Machine state is unavailable. Reset or reload to recover.</div>{/if}
<main aria-busy={session.pending}>
  <div class="workspace">
    <div class="main-content">

      <ProgramInput disabled={session.pending || session.running || !session.id || session.expired} load={(body) => session.load(body)} />
      <CodeView program={session.program} state={session.state?.status === 'unavailable' || session.uncertainty ? null : session.state} disabled={!session.editable || session.running} select={(address) => { pc = hex(address); pcError = ''; }} onToggleBreakpoint={(address, mode) => session.toggleBreakpoint(address, mode)} />
      <StatusPanel diagnostics={session.program?.diagnostics ?? []} error={session.error} step={session.uncertainty ? null : session.state?.last_step ?? null} message={session.message} runResult={session.runResult} />
      {#if session.program}<MemoryPanel {session} />{/if}
    </div>
    <aside class="sidebar-column">
      {#if session.state && session.state.status !== 'empty'}
        <RegisterPanel state={session.uncertainty ? { ...session.state, last_step: null } : session.state} disabled={!session.editable || session.running} edit={(name, value, mask) => session.edit(name, value, mask)} />
      {:else}
        <section class="register-empty" aria-labelledby="register-empty-title">
          <div class="panel-header">
            <h2 id="register-empty-title">Registers</h2>
            <span class="muted">Sidebar</span>
          </div>
          <div class="empty-state-card">
            <p class="empty-icon" style="font-size: 24px; margin: 8px 0;">📊</p>
            <p style="margin: 0 0 4px;"><strong>Register Sidebar</strong></p>
            <p class="muted" style="margin: 0; font-size: 11px;">R0–R12, SP, LR, PC, CPSR and flags will populate here when a program is loaded.</p>
          </div>
        </section>
      {/if}
    </aside>
  </div>
</main>
<footer>Page-local session · Refresh starts a new experiment · Idle sessions expire after 30 minutes</footer>
