import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import WatchpointPanel from '../src/WatchpointPanel.svelte';
import CodeView from '../src/CodeView.svelte';
import { PageSession } from '../src/session.svelte';
import type { Program, State } from '../src/api';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mockState(): State {
  return {
    session_id: 'p2-session',
    status: 'ready',
    profile: 'armv7-a-le',
    mode: 'arm',
    baseline_pc: 0x8000,
    step_seq: 2,
    registers: {
      r0: { value: 42, origin: 'execution' },
      sp: { value: 0x20100000, origin: 'default' },
      lr: { value: 0, origin: 'default' },
      pc: { value: 0x8004, origin: 'execution' },
    },
    cpsr: { value: 16, origin: 'default' },
    flags: { n: false, z: false, c: false, v: false },
    pc: 0x8004,
    stack: { base: 0x200f0000, size: 65536 },
    regions: [],
    last_step: {
      status: 'executed',
      step_seq: 2,
      instruction: { address: 0x8000, size: 4, source_line: 1 },
      pc_before: 0x8000,
      pc_after: 0x8004,
      condition_passed: null,
      register_changes: { r0: { before: 0, after: 42 } },
      cpsr_change: null,
      flag_changes: {},
      memory_reads: [],
      memory_writes: [],
      branch: null,
      stop_reason: null,
      watchpoint_hits: [
        {
          address: 0x20000000,
          size: 4,
          access_type: 'read',
          triggering_pc: 0x8000,
          watchpoint_address: 0x20000000,
          watchpoint_length: 4,
          watchpoint_kind: 'read',
        },
      ],
      error: null,
    },
    watchpoints: [
      { address: 0x20000000, length: 4, kind: 'read' },
    ],
  };
}

describe('Stage P2 Frontend Features', () => {
  it('supports Step Back action in session', async () => {
    const session = new PageSession();
    session.id = 'p2-session';
    session.state = mockState();
    session.program = {
      profile: 'armv7-a-le',
      mode: 'arm',
      format: 'elf',
      source_text: '',
      diagnostics: [],
      instruction_count: 1,
      ignored_line_count: 0,
      instructions: [
        {
          address: 0x8000,
          bytes: '2a00a0e3',
          size: 4,
          source_line: 1,
          source_text: '',
          display_text: 'MOV R0, #42',
          decoded_text: 'mov r0, #0x2a',
          feature_exclusion: null,
        },
      ],
    };

    const restoredState = {
      ...mockState(),
      step_seq: 2, // invariant
      pc: 0x8000,
      registers: {
        ...mockState().registers,
        r0: { value: 0, origin: 'default' },
        pc: { value: 0x8000, origin: 'default' },
      },
    };

    const fetcher = vi.fn().mockResolvedValue(
      json({
        status: 'ok',
        restored_step_seq: 1,
        current_step_seq: 2,
        state_revision: 5,
        history_depth: 0,
        state: restoredState,
      })
    );
    vi.stubGlobal('fetch', fetcher);

    const result = await session.stepBack();
    expect(result).toBeNull();
    expect(fetcher).toHaveBeenCalledWith(
      '/api/sessions/p2-session/step-back',
      expect.objectContaining({ method: 'POST' })
    );
    expect(session.state?.registers.r0.value).toBe(0);
    expect(session.historyDepth).toBe(0);
  });

  it('supports Watchpoint CRUD in session', async () => {
    const session = new PageSession();
    session.id = 'p2-session';
    session.state = mockState();

    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ address: 0x20000000, length: 4, kind: 'read' }, 201))
      .mockResolvedValueOnce(json([{ address: 0x20000000, length: 4, kind: 'read' }]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json([]));
    vi.stubGlobal('fetch', fetcher);

    // Add watchpoint
    await session.addWatchpoint(0x20000000, 4, 'read');
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      '/api/sessions/p2-session/watchpoints',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ address: 0x20000000, length: 4, kind: 'read' }) })
    );
    expect(session.watchpoints).toHaveLength(1);

    // Remove watchpoint
    await session.removeWatchpoint(0x20000000);
    expect(fetcher).toHaveBeenNthCalledWith(
      3,
      '/api/sessions/p2-session/watchpoints/536870912',
      expect.objectContaining({ method: 'DELETE' })
    );
    expect(session.watchpoints).toHaveLength(0);
  });

  it('renders WatchpointPanel and reports hit highlights', () => {
    const session = new PageSession();
    session.id = 'p2-session';
    session.state = mockState();
    session.watchpoints = [{ address: 0x20000000, length: 4, kind: 'read' }];

    render(WatchpointPanel, { props: { session } });
    expect(screen.getByText(/Watchpoints \(1\/32\)/)).toBeTruthy();
    expect(screen.getByText('0x20000000')).toBeTruthy();
    expect(screen.getByText(/Watchpoint Hit!/)).toBeTruthy();
  });

  it('renders CodeView with symbols and DWARF line tags', () => {
    const prg: Program = {
      profile: 'armv7-a-le',
      mode: 'arm',
      format: 'elf',
      source_text: '',
      diagnostics: [],
      instruction_count: 1,
      ignored_line_count: 0,
      instructions: [
        {
          address: 0x8000,
          bytes: '2a00a0e3',
          size: 4,
          source_line: null,
          source_text: '',
          display_text: 'MOV R0, #42',
          decoded_text: 'mov r0, #0x2a',
          feature_exclusion: null,
        },
      ],
      metadata: {
        symbols: [
          { address: 0x8000, name: 'main', size: 4, type: 'func', binding: 'global' },
        ],
        lines: [
          { address: 0x8000, file: 'main.c', line: 42, column: 0 },
        ],
      },
    };

    render(CodeView, {
      props: {
        program: prg,
        state: mockState(),
        disabled: false,
        select: vi.fn(),
      },
    });

    expect(screen.getByText(/main:/)).toBeTruthy();
    expect(screen.getByText(/main.c:42/)).toBeTruthy();
  });
});
