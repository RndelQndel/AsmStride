import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import App from '../src/App.svelte';
import RegisterPanel from '../src/RegisterPanel.svelte';
import CodeView from '../src/CodeView.svelte';
import StatusPanel from '../src/StatusPanel.svelte';
import { ApiError, request, uint32 } from '../src/api';
import type { Program, State, StepResult } from '../src/api';
import { PageSession } from '../src/session.svelte';

function state(): State {
  return { session_id: 'page-1', status: 'ready', profile: 'armv7-a-le', mode: 'arm', baseline_pc: 4096,
    step_seq: 0, registers: { r0: { value: 0, origin: 'default' }, sp: { value: 0x20100000, origin: 'default' },
      lr: { value: 0, origin: 'default' }, pc: { value: 4096, origin: 'default' } },
    cpsr: { value: 16, origin: 'default' }, flags: { n: false, z: false, c: false, v: false },
    pc: 4096, stack: { base: 0x200f0000, size: 65536 }, regions: [], last_step: null };
}
function stepResult(): StepResult {
  return { status: 'executed', step_seq: 1, instruction: { address: 4096, size: 4, source_line: null },
    pc_before: 4096, pc_after: 4100, condition_passed: null,
    register_changes: { r0: { before: 7, after: 8 } }, cpsr_change: null, flag_changes: {},
    memory_reads: [], memory_writes: [], branch: null, stop_reason: null, error: null };
}
function program(mode: 'arm' | 'thumb' = 'arm'): Program {
  return { profile: 'armv7-a-le', mode, format: 'assembly', source_text: '<script>source stays text</script>',
    diagnostics: [], ignored_line_count: 0, instruction_count: 2,
    instructions: [4096, mode === 'arm' ? 4100 : 4098].map((address, index) => ({
      address, bytes: '00000000', size: mode === 'thumb' && index === 0 ? 2 : 4,
      source_line: null, source_text: '', display_text: 'add r0, #1', decoded_text: 'add r0, #1', feature_exclusion: null,
    })) };
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('validates complete unsigned integers without truncation or coercion', () => {
  for (const value of ['', '-1', '+1', '1.2', '1e3', '0x', '0x100000000', '4294967296', '12xyz'])
    expect(() => uint32(value)).toThrow();
  expect(uint32(' 0xFFFFFFFF ')).toBe(4294967295);
  expect(uint32('0012')).toBe(12);
});

it('preserves API diagnostics and uses same-origin JSON requests without retries', async () => {
  const detail = { error: { code: 'invalid_pc', message: 'Invalid PC', context: {} } };
  const fetcher = vi.fn().mockResolvedValue(json(detail, 422));
  vi.stubGlobal('fetch', fetcher);
  await expect(request('/id/pc', 'PUT', { value: 3 })).rejects.toBeInstanceOf(ApiError);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0][1].body).toBe('{"value":3}');
});

async function loadedSession() {
  const session = new PageSession();
  const fetcher = vi.fn().mockResolvedValueOnce(json({ session_id: 'page-1', state: state() }));
  vi.stubGlobal('fetch', fetcher);
  await session.create();
  session.program = program();
  return { session, fetcher };
}

it('serializes rapid Step requests and retains the authoritative response', async () => {
  const { session, fetcher } = await loadedSession();
  let release!: (response: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { release = resolve; }));
  const first = session.step();
  await session.step();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(session.pending).toBe(true);
  release(json({ state: { ...state(), step_seq: 1 } }));
  await first;
  expect(session.state?.step_seq).toBe(1);
  expect(session.pending).toBe(false);
});

it.each([true, false])('recovers a lost self-branch Step with counter advanced=%s without retry', async (advanced) => {
  const { session, fetcher } = await loadedSession();
  fetcher.mockRejectedValueOnce(new TypeError('lost')).mockResolvedValueOnce(json({ ...state(), step_seq: advanced ? 1 : 0 }));
  await session.step();
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/sessions', '/api/sessions/page-1/step', '/api/sessions/page-1/state']);
  expect(session.editable).toBe(advanced);
  expect(session.message).toContain(advanced ? 'completion confirmed' : 'uncertain');
  if (!advanced) {
    await session.step();
    expect(fetcher).toHaveBeenCalledTimes(3);
    fetcher.mockResolvedValueOnce(json(state()));
    await session.reset();
    expect(session.editable).toBe(true);
  }
});

it('lost Load clears the listing and requires explicit replacement even after State recovery', async () => {
  const { session, fetcher } = await loadedSession();
  fetcher.mockRejectedValueOnce(new TypeError('lost')).mockResolvedValueOnce(json(state()));
  await session.load({ input_kind: 'assembly', mode: 'arm', text: 'nop', base_address: 4096 });
  expect(session.program).toBeNull();
  expect(session.uncertainty).toBe('program');
  await session.reset();
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it('expired sessions never recreate themselves and disposal deletes the owned session', async () => {
  const { session, fetcher } = await loadedSession();
  fetcher.mockResolvedValueOnce(json({ error: { code: 'session_not_found', message: 'Missing', context: {} } }, 404));
  await session.step();
  await session.step();
  expect(session.expired).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(2);
  fetcher.mockResolvedValueOnce(new Response(null, { status: 204 }));
  session.dispose();
  expect(fetcher.mock.calls.at(-1)?.[1]).toEqual({ method: 'DELETE', keepalive: true });
});

it('cleans up a session whose creation completes after page close', async () => {
  let release!: (response: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { release = resolve; }))
    .mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal('fetch', fetcher);
  const session = new PageSession();
  const creation = session.create();
  session.dispose();
  release(json({ session_id: 'late', state: state() }));
  await creation;
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe('/api/sessions/late');
  expect(session.state).toBeNull();
});

describe.each(['arm', 'thumb'] as const)('%s browser components', (mode) => {
  it.each(['assembly', 'disassembly'] as const)('%s supports Load, edit, Step, Reset and PC selection', async (kind) => {
    let current = state();
    let baseline = 0;
    let releaseStep!: () => void;
    const image = program(mode);
    const fetcher = vi.fn(async (url: string, options: RequestInit = {}) => {
      const body = options.body ? JSON.parse(String(options.body)) : {};
      if (options.method === 'DELETE') return new Response(null, { status: 204 });
      if (url === '/api/sessions') return json({ session_id: 'page-1', state: { ...current, status: 'empty', registers: {}, cpsr: null, pc: null } });
      if (url.includes('/memory?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        return json({ address: Number(query.get('address')), length: Number(query.get('length')),
          cells: Array.from({ length: Number(query.get('length')) }, () => ({ value: null, origin: 'unknown' })) });
      }
      if (url.endsWith('/program')) {
        expect(body.input_kind).toBe(kind);
        expect(body.mode).toBe(mode);
        expect('base_address' in body).toBe(kind === 'assembly');
        expect('format' in body).toBe(kind === 'disassembly');
        return json({ state: current, program: image });
      }
      if (url.endsWith('/registers/r0')) {
        baseline = body.value;
        current = { ...current, registers: { ...current.registers, r0: { value: baseline, origin: 'user' } }, last_step: null };
        return json(current);
      }
      if (url.endsWith('/step')) {
        await new Promise<void>((resolve) => { releaseStep = resolve; });
        current = { ...current, pc: image.instructions[1].address, step_seq: 1,
          registers: { ...current.registers, r0: { value: 8, origin: 'execution' } }, last_step: stepResult() };
        return json({ state: current, result: current.last_step });
      }
      if (url.endsWith('/reset')) {
        current = { ...state(), step_seq: 1, registers: { ...state().registers, r0: { value: baseline, origin: 'user' } } };
        return json(current);
      }
      throw new Error(`Unexpected ${url}`);
    });
    vi.stubGlobal('fetch', fetcher);
    const { container } = render(App);
    await waitFor(() => expect((screen.getByRole('button', { name: 'Load' }) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.change(screen.getByLabelText('Input'), { target: { value: kind } });
    await fireEvent.change(screen.getByLabelText('Mode'), { target: { value: mode } });
    await fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await screen.findByRole('button', { name: 'Apply R0' });
    await waitFor(() => expect(container.querySelector('main')?.getAttribute('aria-busy')).toBe('false'));
    expect(container.querySelector('[aria-current="step"]')?.getAttribute('data-address')).toBe('4096');
    expect(container.querySelectorAll('script')).toHaveLength(0);
    await fireEvent.input(screen.getByLabelText('R0'), { target: { value: '-1' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply R0' }));
    expect(await screen.findByText(/Enter an unsigned/)).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('R0'), { target: { value: '7' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply R0' }));
    await waitFor(() => expect((screen.getByLabelText('R0') as HTMLInputElement).value).toBe('0x00000007'));
    await waitFor(() => expect(container.querySelector('main')?.getAttribute('aria-busy')).toBe('false'));
    await fireEvent.click(screen.getByRole('button', { name: 'Step' }));
    expect((screen.getByRole('button', { name: 'Reset' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Load' }) as HTMLButtonElement).closest('fieldset')?.disabled).toBe(true);
    releaseStep();
    await waitFor(() => expect(container.querySelector('.register.changed')).not.toBeNull());
    expect(container.querySelector('[aria-current="step"]')?.getAttribute('data-address')).toBe(String(image.instructions[1].address));
    await waitFor(() => expect(container.querySelector('main')?.getAttribute('aria-busy')).toBe('false'));
    await fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    await waitFor(() => expect((screen.getByLabelText('R0') as HTMLInputElement).value).toBe('0x00000007'));
    expect(container.querySelector('.register.changed')).toBeNull();
    await waitFor(() => expect(container.querySelector('main')?.getAttribute('aria-busy')).toBe('false'));
    const calls = fetcher.mock.calls.length;
    await fireEvent.click(screen.getByRole('button', { name: `Select PC 0x${image.instructions[1].address.toString(16).padStart(8, '0')}` }));
    expect(fetcher.mock.calls).toHaveLength(calls);
    expect((screen.getByLabelText('Start / current PC') as HTMLInputElement).value).not.toBe('0x00001000');
  });
});

it('rejected replacement preserves the installed program and diagnostics', async () => {
  const { session, fetcher } = await loadedSession();
  const installed = session.program;
  fetcher.mockResolvedValueOnce(json({ error: { code: 'parse_error', message: 'Bad line', context: {} },
    diagnostics: [{ code: 'parse_error', severity: 'error', message: 'Bad line', line: 2, source_text: 'bad', context: {} }], preview: [] }, 422));
  await session.load({ input_kind: 'disassembly', mode: 'thumb', format: 'auto', encoding: 'auto', text: 'bad' });
  expect(session.program).toBe(installed);
  expect(session.state?.pc).toBe(4096);
  expect(session.error?.diagnostics?.[0].line).toBe(2);
  expect(session.editable).toBe(true);
});

it('a failed Step replaces previous deltas and a committed external stop retains its destination', async () => {
  const { session, fetcher } = await loadedSession();
  const failed = { ...stepResult(), status: 'failed', register_changes: {}, pc_after: 4096, step_seq: 0, stop_reason: 'memory_fault' };
  fetcher.mockResolvedValueOnce(json({ state: { ...state(), last_step: failed, status: 'stopped' } }));
  await session.step();
  expect(session.state?.last_step?.register_changes).toEqual({});
  expect(session.editable).toBe(true);
  const external = { ...stepResult(), pc_after: 8192, stop_reason: 'pc_not_loaded' };
  fetcher.mockResolvedValueOnce(json({ state: { ...state(), pc: 8192, last_step: external, status: 'stopped', step_seq: 1 } }));
  await session.step();
  expect(session.state?.pc).toBe(8192);
  expect(session.program?.instructions.some((instruction) => instruction.address === session.state?.pc)).toBe(false);
});

it('recovery failure keeps Step blocked, and explicit Reset restores editing', async () => {
  const { session, fetcher } = await loadedSession();
  fetcher.mockRejectedValueOnce(new TypeError('lost')).mockRejectedValueOnce(new TypeError('offline'));
  await session.step();
  expect(session.message).toContain('State recovery also failed');
  expect(session.editable).toBe(false);
  fetcher.mockResolvedValueOnce(json(state()));
  await session.reset();
  expect(session.editable).toBe(true);
});

it('flag edits send an unsigned mask and PC edits use the dedicated endpoint', async () => {
  const { session, fetcher } = await loadedSession();
  fetcher.mockResolvedValueOnce(json(state()));
  await session.edit('cpsr', 0x80000000, 0x80000000);
  expect(JSON.parse(fetcher.mock.calls.at(-1)?.[1].body)).toEqual({ value: 2147483648, mask: 2147483648 });
  fetcher.mockResolvedValueOnce(json(state()));
  await session.edit('pc', 4100);
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe('/api/sessions/page-1/pc');
});


it('renders API lowercase flag keys and sends the corresponding unsigned mask', async () => {
  const edit = vi.fn().mockResolvedValue(null);
  const machine = state();
  machine.flags = { n: false, z: true, c: false, v: false };
  machine.last_step = { ...stepResult(), flag_changes: { z: { before: false, after: true } } };
  render(RegisterPanel, { state: machine, disabled: false, edit });
  await fireEvent.click(screen.getByRole('button', { name: 'N 0' }));
  expect(edit).toHaveBeenLastCalledWith('cpsr', 2147483648, 2147483648);
  const zero = screen.getByRole('button', { name: 'Z 1 Δ' });
  expect(zero.classList.contains('changed')).toBe(true);
  await fireEvent.click(zero);
  expect(edit).toHaveBeenLastCalledWith('cpsr', 0, 1073741824);
});

it('supports breakpoint toggle via POST and DELETE and syncs with state', async () => {
  const { session, fetcher } = await loadedSession();
  // Initially no breakpoints
  expect(session.hasBreakpoint(4096)).toBe(false);

  // Toggle on -> calls POST /breakpoints then GET /breakpoints
  fetcher.mockResolvedValueOnce(json({ address: 4096, mode: 'arm' }))
    .mockResolvedValueOnce(json([{ address: 4096, mode: 'arm' }]));
  await session.toggleBreakpoint(4096, 'arm');
  expect(fetcher).toHaveBeenCalledWith('/api/sessions/page-1/breakpoints', expect.objectContaining({ method: 'POST' }));
  expect(session.hasBreakpoint(4096)).toBe(true);

  // Toggle off -> calls DELETE /breakpoints/4096 then GET /breakpoints
  fetcher.mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(json([]));
  await session.toggleBreakpoint(4096, 'arm');
  expect(fetcher).toHaveBeenCalledWith('/api/sessions/page-1/breakpoints/4096', expect.objectContaining({ method: 'DELETE' }));
  expect(session.hasBreakpoint(4096)).toBe(false);
});

it('rejects setting breakpoint on a data region', async () => {
  const { session } = await loadedSession();
  session.program = {
    ...program(),
    data_regions: [{ address: 0x2000, size: 4, bytes: '12345678', source_line: 1 }]
  };
  const err = await session.toggleBreakpoint(0x2000);
  expect(err).toBe('Cannot set breakpoint on data region.');
  expect(session.message).toContain('data region');
});

it('executes Run loop, records runResult, and handles stop', async () => {
  const { session, fetcher } = await loadedSession();
  const runRes = {
    start_step_seq: 0,
    end_step_seq: 5,
    steps_committed: 5,
    steps_executed: 5,
    stop_reason: 'breakpoint',
    elapsed_ms: 12.5,
    breakpoint_hit: 4100,
    last_step: stepResult(),
  };
  fetcher.mockResolvedValueOnce(json({
    run_result: runRes,
    state: { ...state(), step_seq: 5, pc: 4100 }
  }));
  const promise = session.run(100, 1000);
  expect(session.running).toBe(true);
  expect(session.editable).toBe(false);
  await promise;
  expect(session.running).toBe(false);
  expect(session.runResult?.stop_reason).toBe('breakpoint');
  expect(session.state?.step_seq).toBe(5);

  // Test stop
  fetcher.mockResolvedValueOnce(json({ signaled: true }));
  session.running = true;
  await session.stop();
  expect(fetcher).toHaveBeenCalledWith('/api/sessions/page-1/stop', expect.objectContaining({ method: 'POST' }));
});

it('renders CodeView with breakpoint gutter, marker combinations, and data rows', async () => {
  const toggleBp = vi.fn();
  const select = vi.fn();
  const mixedProgram: Program = {
    profile: 'armv7-a-le',
    mode: 'arm',
    format: 'fromelf',
    source_text: 'source',
    instructions: [
      { address: 0x1000, bytes: 'e1a00000', size: 4, source_line: 1, source_text: 'nop', display_text: 'nop', decoded_text: 'nop', feature_exclusion: null, mode: 'arm' },
      { address: 0x1004, bytes: '46c0', size: 2, source_line: 2, source_text: 'nop', display_text: 'nop', decoded_text: 'nop', feature_exclusion: null, mode: 'thumb' },
    ],
    data_regions: [
      { address: 0x1008, size: 4, bytes: '12345678', source_line: 3 }
    ],
    diagnostics: [],
    instruction_count: 2,
    ignored_line_count: 0
  };
  const testState: State = {
    ...state(),
    pc: 0x1000,
    breakpoints: [{ address: 0x1000, mode: 'arm' }]
  };
  render(CodeView, { program: mixedProgram, state: testState, disabled: false, select, onToggleBreakpoint: toggleBp });

  // 0x1000 has both PC and BP -> button shows ▶●
  const pcBtn0 = screen.getByRole('button', { name: 'Select PC 0x00001000' });
  expect(pcBtn0.textContent).toContain('▶●');

  // Toggle breakpoint button for 0x1000 is present and clickable
  const bpBtn0 = screen.getByRole('button', { name: 'Toggle breakpoint at 0x00001000' });
  expect(bpBtn0.textContent).toContain('●');
  await fireEvent.click(bpBtn0);
  expect(toggleBp).toHaveBeenCalledWith(0x1000, 'arm');

  // Data row is rendered with $d badge and DATA label
  expect(screen.getByText('DATA (4 bytes)')).toBeDefined();
  expect(screen.getByText('$d · DATA')).toBeDefined();
});

it('renders StatusPanel with IT block condition details and conditional skip', () => {
  const step: StepResult = {
    ...stepResult(),
    executed: false,
    condition_passed: false,
    it_context: {
      block_index: 2,
      block_total: 2,
      condition: 'EQ',
      passed: false
    }
  };
  render(StatusPanel, { diagnostics: [], error: null, step, message: 'Step completed' });
  expect(screen.getByText(/IT Block \[2\/2\]/)).toBeDefined();
  expect(screen.getByText(/not passed \(conditionally skipped\)/)).toBeDefined();
  expect(screen.getByText(/Instruction conditionally skipped/)).toBeDefined();
});
