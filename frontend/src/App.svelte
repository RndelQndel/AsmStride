<script lang="ts">
  import { onMount } from 'svelte';
  import { hex, uint32 } from './api';
  import { PageSession } from './session.svelte';
  import WorkbenchTabs from './WorkbenchTabs.svelte';
  import ProgramInput from './ProgramInput.svelte';
  import CodeView from './CodeView.svelte';
  import RegisterPanel from './RegisterPanel.svelte';
  import MemoryPanel from './MemoryPanel.svelte';
  import StatusPanel from './StatusPanel.svelte';
  import WatchpointPanel from './WatchpointPanel.svelte';

  const session = new PageSession();
  session.memoryEnabled = true;
  if (typeof window !== 'undefined') {
    (window as unknown as { __armstride_session?: PageSession }).__armstride_session = session;
  }
  let pc = $state('');
  let pcError = $state('');
  let stepLimit = $state(10000);
  let timeLimitMs = $state(2000);
  let viewMode = $state('Source');
  let source = $state('mov r0, #5\nadd r1, r0, #3\ncmp r1, #8');
  let imported = $state('0x1000: E3A00005 MOV r0,#5\n0x1004: E2801003 ADD r1,r0,#3');
  let kind = $state<'assembly' | 'disassembly' | 'elf'>('assembly');
  let activity = $state('Input');
  let sidebarOpen = $state(true);
  let debugOpen = $state(true);
  let panelOpen = $state(true);
  let panel = $state('Execution');
  const tabs = ['Problems', 'Output', 'Memory', 'Stack', 'Execution'];
  const machineStatus = $derived(session.expired ? 'Expired' : session.uncertainty ? 'Uncertain' : session.running ? 'Running' : session.pending ? 'Pending' : session.state?.status ?? 'Connecting');
  function openPanel(tab: string) { panel = tab; panelOpen = true; }
  $effect(() => { if (session.error) openPanel('Problems'); });
  async function load(body: import('./api').LoadRequest) {
    const error = await session.load(body);
    if (!error) {
      viewMode = 'Disassembly';
      if (window.innerWidth <= 760) sidebarOpen = false;
    }
    return error;
  }

  $effect(() => { pc = session.state?.pc === null || session.state?.pc === undefined ? '' : hex(session.state.pc); pcError = ''; });
  onMount(() => {
    if (window.innerWidth <= 760) debugOpen = false;
    void session.create();
    return () => session.dispose();
  });

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
<header class="command-bar toolbar" aria-label="Execution controls">
  <h1>ArmStride</h1>
  <button class="primary" disabled={!session.editable || session.running} onclick={() => session.run(stepLimit, timeLimitMs)} title="Run (F5)">Run</button>
  <button disabled={!session.editable || session.running} onclick={() => session.step()} title="Step (F7 / F8)">Step</button>
  <button disabled={!session.editable || session.running || session.historyDepth === 0} onclick={() => session.stepBack()}>Step Back ({session.historyDepth})</button>
  <button disabled={!session.running} onclick={() => session.stop()}>Stop</button>
  <button disabled={session.running || session.pending || session.expired || !session.state || session.state.status === 'empty' || session.uncertainty === 'program'} onclick={() => session.reset()} title="Reset (F9)">Reset</button>
  <div class="command-spacer"></div>
  <button aria-label="Toggle debug sidebar" aria-pressed={debugOpen} onclick={() => debugOpen = !debugOpen}>Debug</button>
  <button aria-label="Toggle bottom panel" aria-expanded={panelOpen} onclick={() => panelOpen = !panelOpen}>Panel</button>
</header>
{#if session.uncertainty}<div class="alert-bar notice">Outcome uncertain. {session.uncertainty === 'program' ? 'Load again to recover the program listing.' : 'Reset or reload before further execution or edits.'}</div>{/if}
{#if session.state?.status === 'unavailable'}<div class="alert-bar error">Machine state is unavailable. Reset or reload to recover.</div>{/if}
<main class="workbench" aria-busy={session.pending} class:sidebar-closed={!sidebarOpen} class:debug-closed={!debugOpen}>
  <nav class="activity-bar" aria-label="Activity Bar">
    {#each ['Input', 'Debug', 'Memory'] as tool}
      <button title={tool} aria-label={tool + ' tools'} aria-pressed={sidebarOpen && activity === tool} onclick={() => { sidebarOpen = activity === tool ? !sidebarOpen : true; activity = tool; }}>{tool === 'Input' ? 'IN' : tool === 'Debug' ? 'DB' : 'MEM'}</button>
    {/each}
  </nav>
  <aside class="primary-sidebar" aria-label="Primary Sidebar" hidden={!sidebarOpen}>
    <div hidden={activity !== 'Input'}><ProgramInput disabled={session.pending || session.running || !session.id || session.expired} {load} bind:source bind:imported bind:kind /></div>
    <section hidden={activity !== 'Debug'}>
      <h2>Run configuration</h2>
      <label>Limit steps<input type="number" min="1" max="100000" bind:value={stepLimit} disabled={session.running} /></label>
      <label>Time limit (ms)<input type="number" min="1" max="10000" bind:value={timeLimitMs} disabled={session.running} /></label>
      <p class="muted">F5 Run · F7 / F8 Step · F9 Reset</p>
      <p class="muted">Page-local session. Refresh starts a new experiment. Idle sessions expire after 30 minutes.</p>
    </section>
    <section hidden={activity !== 'Memory'}>
      <h2>Memory tools</h2>
      <button onclick={() => openPanel('Memory')}>Inspect and patch memory</button>
      <button onclick={() => openPanel('Stack')}>Inspect stack</button>
      <p class="muted">Inspect bytes, patch data, or follow SP in the bottom panel.</p>
    </section>
  </aside>
  <section class="editor-group" aria-label="Editor group">
    <WorkbenchTabs label="Editor views" tabs={['Source', 'Disassembly', 'Split']} bind:selected={viewMode} />
    <div class="editor-panes" class:split={viewMode === 'Split'}>
      <div class="source-editor" hidden={viewMode === 'Disassembly'}>
        {#if kind === 'elf'}<p class="muted">ELF source is unavailable. Open Disassembly to inspect the loaded program.</p>
        {:else if kind === 'assembly'}<label>Assembly source<textarea bind:value={source} disabled={session.pending || session.running || !session.id || session.expired} spellcheck="false"></textarea></label>
        {:else}<label>Disassembly text<textarea bind:value={imported} disabled={session.pending || session.running || !session.id || session.expired} spellcheck="false"></textarea></label>{/if}
      </div>
      <div class="listing-editor" hidden={viewMode === 'Source'}>
        <CodeView active={viewMode !== 'Source'} program={session.program} state={session.state?.status === 'unavailable' || session.uncertainty ? null : session.state} disabled={!session.editable || session.running} select={(address) => { pc = hex(address); pcError = ''; debugOpen = true; }} onToggleBreakpoint={(address, mode) => session.toggleBreakpoint(address, mode)} />
      </div>
    </div>
  </section>
  <aside class="debug-sidebar" aria-label="Run and Debug" hidden={!debugOpen}>
    <h2>Run and Debug</h2>
    <form onsubmit={go} class="pc-form">
      <label>Start / current PC<input bind:value={pc} disabled={!session.editable || session.running} aria-invalid={!!pcError} spellcheck="false" /></label>
      <button disabled={!session.editable || session.running}>Go</button>
    </form>
    {#if pcError}<p class="error" role="alert">{pcError}</p>{/if}
    {#if session.state && session.state.status !== 'empty'}
      <RegisterPanel state={session.uncertainty ? { ...session.state, last_step: null } : session.state} disabled={!session.editable || session.running} edit={(name, value, mask) => session.edit(name, value, mask)} />
    {:else}<p class="muted">Load a program to inspect registers and processor state.</p>{/if}
    <details open><summary>Breakpoints ({session.state?.breakpoints?.length ?? 0})</summary>
      {#each session.state?.breakpoints ?? [] as bp}
        <div class="breakpoint-row"><code>{hex(bp.address)} {bp.mode}</code><button aria-label={`Remove breakpoint at ${hex(bp.address)}`} disabled={!session.editable} onclick={() => session.toggleBreakpoint(bp.address, bp.mode)}>Remove</button></div>
      {:else}<p class="muted">Use the disassembly gutter to add breakpoints.</p>{/each}
    </details>
    <details open><summary>Watchpoints</summary><WatchpointPanel {session} /></details>
  </aside>
  <div class="bottom-panel" hidden={!panelOpen}>
    <WorkbenchTabs label="Bottom panel" {tabs} bind:selected={panel}>
      <button class="panel-close" aria-label="Close bottom panel" onclick={() => panelOpen = false}>×</button>
    </WorkbenchTabs>
    <div class="panel-content">
      {#each ['Problems', 'Output', 'Execution'] as tab}
        <div hidden={panel !== tab}><StatusPanel view={tab.toLowerCase() as 'problems' | 'output' | 'execution'} diagnostics={session.program?.diagnostics ?? []} error={session.error} step={session.uncertainty ? null : session.state?.last_step ?? null} message={session.message} runResult={session.runResult} /></div>
      {/each}
      <div hidden={panel !== 'Memory' && panel !== 'Stack'}>{#if session.program}<MemoryPanel {session} view={panel === 'Stack' ? 'stack' : 'memory'} />{:else}<p class="muted">Load a program to inspect memory and stack.</p>{/if}</div>
    </div>
  </div>
</main>
<footer class="status-bar" aria-label="Machine status" role="status">
  <span>{session.state?.profile === 'rv32i-le' ? 'RV32I' : 'ARMv7-A'}</span>
  {#if session.state?.profile !== 'rv32i-le'}<span>{(session.state?.cpsr ? (session.state.cpsr.value & 32) !== 0 : session.state?.mode === 'thumb') ? 'Thumb' : 'ARM'}</span>{/if}
  <span>LE</span><span>{machineStatus}</span><span>PC {hex(session.state?.pc ?? null)}</span>
  <span>step_seq {session.state?.step_seq ?? 0}</span><span>history {session.historyDepth}</span>
</footer>
