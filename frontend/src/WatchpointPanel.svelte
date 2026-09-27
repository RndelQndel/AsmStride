<script lang="ts">
  import { hex, uint32 } from './api';
  import type { PageSession } from './session.svelte';

  let { session }: { session: PageSession } = $props();

  let addressInput = $state('0x20000000');
  let lengthInput = $state(4);
  let kindInput = $state<'read' | 'write' | 'read_write'>('read_write');
  let errorMsg = $state('');

  async function handleAdd(event: SubmitEvent) {
    event.preventDefault();
    errorMsg = '';
    try {
      const addr = uint32(addressInput);
      const res = await session.addWatchpoint(addr, lengthInput, kindInput);
      if (res) errorMsg = res;
    } catch (e) {
      errorMsg = (e as Error).message;
    }
  }

  async function handleDelete(addr: number) {
    errorMsg = '';
    const res = await session.removeWatchpoint(addr);
    if (res) errorMsg = res;
  }
</script>

<div class="watchpoint-panel" aria-label="Memory Watchpoints">
  <div class="panel-header">
    <h3>🔍 Watchpoints ({session.watchpoints.length}/32)</h3>
  </div>

  {#if errorMsg}
    <div class="alert-bar error" role="alert">{errorMsg}</div>
  {/if}

  {#if session.state?.last_step?.watchpoint_hits && session.state.last_step.watchpoint_hits.length > 0}
    <div class="watchpoint-hits-notice">
      <strong>⚡ Watchpoint Hit!</strong>
      <ul>
        {#each session.state.last_step.watchpoint_hits as hit}
          <li>
            [{hit.access_type.toUpperCase()}] at {hex(hit.address)} (size {hit.size}) by PC {hex(hit.triggering_pc)}
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <form class="watchpoint-add-form" onsubmit={handleAdd}>
    <input
      type="text"
      placeholder="Address (0x20000000)"
      bind:value={addressInput}
      disabled={session.running || session.pending}
    />
    <select bind:value={kindInput} disabled={session.running || session.pending}>
      <option value="read_write">Read / Write</option>
      <option value="read">Read Only</option>
      <option value="write">Write Only</option>
    </select>
    <input
      type="number"
      min="1"
      max="64"
      bind:value={lengthInput}
      style="width: 50px;"
      disabled={session.running || session.pending}
    />
    <button type="submit" disabled={session.running || session.pending || session.watchpoints.length >= 32}>
      Add
    </button>
  </form>

  <div class="watchpoint-list">
    {#if session.watchpoints.length === 0}
      <div class="empty-hint">No active memory watchpoints.</div>
    {:else}
      <table>
        <thead>
          <tr>
            <th>Address</th>
            <th>Len</th>
            <th>Kind</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {#each session.watchpoints as wp}
            <tr>
              <td><code>{hex(wp.address)}</code></td>
              <td>{wp.length}B</td>
              <td><span class="badge kind-{wp.kind}">{wp.kind}</span></td>
              <td>
                <button
                  type="button"
                  class="btn-delete"
                  disabled={session.running || session.pending}
                  onclick={() => handleDelete(wp.address)}
                >
                  ✕
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<style>
  .watchpoint-panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px;
    background: var(--surface-bg, #1e1e1e);
    border-radius: 6px;
    font-size: 0.85rem;
  }
  .panel-header h3 {
    margin: 0;
    font-size: 0.95rem;
  }
  .watchpoint-hits-notice {
    background: rgba(255, 165, 0, 0.2);
    border-left: 3px solid orange;
    padding: 6px 10px;
    border-radius: 4px;
  }
  .watchpoint-hits-notice ul {
    margin: 4px 0 0 16px;
    padding: 0;
  }
  .watchpoint-add-form {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .watchpoint-add-form input[type="text"] {
    flex: 1;
    font-family: monospace;
  }
  .watchpoint-list {
    max-height: 140px;
    overflow-y: auto;
  }
  .watchpoint-list table {
    width: 100%;
    border-collapse: collapse;
  }
  .watchpoint-list th, .watchpoint-list td {
    padding: 4px 6px;
    text-align: left;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }
  .btn-delete {
    padding: 2px 6px;
    background: transparent;
    border: 1px solid #ff5555;
    color: #ff5555;
    border-radius: 3px;
    cursor: pointer;
  }
  .empty-hint {
    color: #888;
    font-style: italic;
    padding: 6px 0;
  }
</style>
