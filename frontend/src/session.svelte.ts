import { STACK_WINDOW_BYTES } from './memory';
import type { MemoryPatch, MemoryWindow } from './memory';
import { ApiError, request } from './api';
import type { Breakpoint, ErrorEnvelope, LoadRequest, Mode, Program, RunResponse, RunResult, State, StopResponse } from './api';

/** One page owns one session; all operations, including recovery reads, are serialized. */
export class PageSession {
  id = $state<string | null>(null);
  state = $state.raw<State | null>(null);
  program = $state.raw<Program | null>(null);
  pending = $state(false);
  running = $state(false);
  runResult = $state.raw<RunResult | null>(null);
  expired = $state(false);
  uncertainty = $state<'state' | 'program' | null>(null);
  message = $state('');
  error = $state.raw<ErrorEnvelope | null>(null);
  memoryEnabled = false;
  memory = $state.raw<MemoryWindow | null>(null);
  stackMemory = $state.raw<MemoryWindow | null>(null);
  memoryError = $state('');
  memoryAddress = 0x20000000;
  memoryLength = 64;
  stackOffset = 0;
  private closed = false;

  private async refreshMemory() {
    this.memory = null;
    this.stackMemory = null;
    this.memoryError = '';
    if (!this.memoryEnabled || !this.program || this.uncertainty || this.expired ||
        this.state?.status === 'unavailable' || this.closed) return;
    const sp = this.state?.registers.sp?.value ?? 0;
    const stackAddress = Math.max(0, Math.min(0x100000000 - STACK_WINDOW_BYTES, sp - STACK_WINDOW_BYTES / 2 + this.stackOffset));
    try {
      const memory = await request<MemoryWindow>(`/${this.id}/memory?address=${this.memoryAddress}&length=${this.memoryLength}`);
      const stack = await request<MemoryWindow>(`/${this.id}/memory?address=${stackAddress}&length=${STACK_WINDOW_BYTES}`);
      if (!this.closed) { this.memory = memory; this.stackMemory = stack; }
    } catch (error) {
      this.memoryError = `Memory inspection failed: ${(error as Error).message}`;
      if (error instanceof ApiError && error.detail.error.code === 'session_not_found') {
        this.expired = true;
        this.message = 'Session expired or was deleted. Refresh to create a new empty session.';
      }
    }
  }

  async inspect(address: number, length: number, stackOffset = this.stackOffset) {
    if (!this.editable) return;
    this.memoryAddress = address;
    this.memoryLength = length;
    this.stackOffset = stackOffset;
    this.pending = true;
    try { await this.refreshMemory(); }
    finally { this.pending = false; }
  }

  patchMemory(body: MemoryPatch) { return this.command('edit', '/memory', body); }

  get editable() {
    return !!this.program && !!this.state && this.state.status !== 'unavailable' &&
      !this.pending && !this.running && !this.expired && !this.uncertainty;
  }

  hasBreakpoint(address: number): boolean {
    return (this.state?.breakpoints ?? []).some(b => b.address === address);
  }

  async toggleBreakpoint(address: number, mode: Mode = 'arm'): Promise<string | null> {
    if (this.pending || this.running || !this.id || this.expired || this.closed) return 'Session is not available.';
    if (this.program?.data_regions?.some(d => address >= d.address && address < d.address + d.size)) {
      this.message = 'Cannot set breakpoint on data region.';
      return 'Cannot set breakpoint on data region.';
    }
    const exists = this.hasBreakpoint(address);
    this.pending = true;
    this.error = null;
    this.message = '';
    try {
      if (exists) {
        await request(`/${this.id}/breakpoints/${address}`, 'DELETE');
      } else {
        await request(`/${this.id}/breakpoints`, 'POST', { address, mode });
      }
      const bps = await request<Breakpoint[]>(`/${this.id}/breakpoints`);
      if (this.state) {
        this.state = { ...this.state, breakpoints: bps };
      }
      return null;
    } catch (error) {
      if (error instanceof ApiError) {
        this.error = error.detail;
        this.message = error.message;
        return error.message;
      }
      this.message = String(error);
      return String(error);
    } finally {
      this.pending = false;
    }
  }

  async run(stepLimit = 10000, timeLimitMs = 2000): Promise<string | null> {
    if (this.pending || this.running || !this.id || this.expired || this.closed) return 'Session is not available.';
    if (!this.editable) return 'Reset or reload before continuing.';
    this.running = true;
    this.pending = true;
    this.error = null;
    this.message = '';
    try {
      const response = await request<RunResponse>(
        `/${this.id}/run`,
        'POST',
        { step_limit: stepLimit, time_limit_ms: timeLimitMs }
      );
      if (this.closed) return null;
      this.state = response.state;
      this.runResult = response.run_result;
      this.message = `Run stopped: ${response.run_result.stop_reason} (${response.run_result.steps_committed} steps committed)`;
      await this.refreshMemory();
      return null;
    } catch (error) {
      if (this.closed) return null;
      if (error instanceof ApiError && error.status < 500) {
        this.error = error.detail;
        this.expired = error.detail.error.code === 'session_not_found';
        this.message = this.expired ? 'Session expired or was deleted. Refresh to create a new empty session.' : error.message;
      } else {
        this.uncertainty = this.uncertainty ?? 'state';
        this.message = 'Run response lost. Outcome is uncertain. Reset or reload explicitly before continuing.';
        try {
          const recovered = await request<State>(`/${this.id}/state`);
          if (!this.closed) this.state = recovered;
        } catch {
          // ignore
        }
      }
      await this.refreshMemory();
      return this.message;
    } finally {
      this.running = false;
      this.pending = false;
    }
  }

  async stop(): Promise<string | null> {
    if (!this.id || this.expired || this.closed || !this.running) return null;
    try {
      await request<StopResponse>(`/${this.id}/stop`, 'POST', {});
      return null;
    } catch (error) {
      return String(error);
    }
  }

  async create() {
    if (this.pending || this.id || this.closed) return;
    this.pending = true;
    try {
      const result = await request<{ session_id: string; state: State }>('', 'POST', {});
      this.id = result.session_id;
      if (this.closed) this.dispose();
      else this.state = result.state;
    } catch (error) {
      this.message = `Session creation failed: ${String(error)} Refresh the page to try again.`;
    } finally { this.pending = false; }
  }

  async command(kind: 'load' | 'step' | 'reset' | 'edit', suffix: string, body: unknown): Promise<string | null> {
    if (this.pending || this.running || !this.id || this.expired || this.closed) return 'Session is not available.';
    if ((kind === 'step' || kind === 'edit') && !this.editable) return 'Reset or reload before continuing.';
    if (kind === 'reset' && this.uncertainty === 'program') return 'Reload to recover the program listing.';
    const before = this.state?.step_seq ?? 0;
    this.pending = true;
    this.error = null;
    this.message = '';
    try {
      const result = await request<State | { state: State; program?: Program }>(
        `/${this.id}${suffix}`, kind === 'edit' ? 'PUT' : 'POST', body);
      if (this.closed) return null;
      this.state = 'state' in result ? result.state : result;
      if ('program' in result && result.program) this.program = result.program;
      this.uncertainty = null;
      if (kind === 'load' || kind === 'reset') {
        this.stackOffset = 0;
        this.runResult = null;
      }
      await this.refreshMemory();
      return null;
    } catch (error) {
      if (this.closed) return null;
      if (error instanceof ApiError && error.status < 500) {
        this.error = error.detail;
        this.expired = error.detail.error.code === 'session_not_found';
        this.message = this.expired ? 'Session expired or was deleted. Refresh to create a new empty session.' : error.message;
        if (error.detail.error.code === 'backend_unavailable') this.uncertainty = 'state';
      } else {
        this.uncertainty = kind === 'load' ? 'program' : (this.uncertainty ?? 'state');
        if (kind === 'load') this.program = null;
        this.message = 'Response lost. Outcome is uncertain. Reset or reload explicitly before continuing.';
        if (kind === 'load') this.message = 'Load response lost. Load again explicitly; replacement discards the prior experiment and restores defaults.';
        try {
          const recovered = await request<State>(`/${this.id}/state`);
          if (this.closed) return null;
          this.state = recovered;
          if (kind === 'step' && recovered.step_seq > before) {
            this.uncertainty = null;
            this.message = `Step completion confirmed by step_seq ${recovered.step_seq}. No Step was retried.`;
          }
        } catch (recoveryError) {
          if (recoveryError instanceof ApiError && recoveryError.detail.error.code === 'session_not_found') {
            this.expired = true;
            this.message = 'Session expired or was deleted. Refresh to create a new empty session.';
          } else this.message += ' State recovery also failed.';
        }
      }
      await this.refreshMemory();
      return this.message;
    } finally { this.pending = false; }
  }

  load(body: LoadRequest) { return this.command('load', '/program', body); }
  step() { return this.command('step', '/step', {}); }
  reset() { return this.command('reset', '/reset', {}); }
  edit(name: string, value: number, mask?: number) {
    return this.command('edit', name === 'pc' ? '/pc' : `/registers/${name}`, { value, ...(mask === undefined ? {} : { mask }) });
  }
  dispose() {
    this.closed = true;
    if (this.id) {
      void fetch(`/api/sessions/${this.id}`, { method: 'DELETE', keepalive: true }).catch(() => {});
      this.id = null;
    }
  }
}
