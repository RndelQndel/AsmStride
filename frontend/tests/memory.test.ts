import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import { byteChanged, patch, range, word } from '../src/memory';
import MemoryTable from '../src/MemoryTable.svelte';
import { PageSession } from '../src/session.svelte';
import type { Program, StepResult } from '../src/api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('validates bounded patches and encodes words without signed truncation', () => {
  expect(patch('0x2000', 'word', '0xFEDCBA98')).toEqual({ address: 8192, bytes: '98badcfe' });
  expect(patch('0xffffffff', 'bytes', 'ff')).toEqual({ address: 4294967295, bytes: 'ff' });
  expect(patch('0x2000', 'bytes', ' 12 34\n56 ')).toEqual({ address: 8192, bytes: '123456' });
  expect(patch('0x2000', 'zero', '65536')).toEqual({ address: 8192, zero_fill_length: 65536 });
  for (const text of ['', '1', '0x12', 'g0', '1 2']) expect(() => patch('0', 'bytes', text)).toThrow();
  expect(() => patch('0xfffffffc', 'bytes', '00'.repeat(5))).toThrow();
  expect(() => patch('1', 'word', '1')).toThrow();
  expect(() => patch('0', 'zero', '65537')).toThrow();
  expect(() => patch('0', 'zero', '0')).toThrow();
  expect(() => range('0', '4097', 4096)).toThrow();
  expect(() => range('0xffffffff', '2', 4096)).toThrow();
});

it('renders partial words as unknown and marks only changed committed bytes', () => {
  const cells = [0x78, 0x56, 0x34, 0x92].map(value => ({ value, origin: 'user' as const }));
  expect(word(cells)).toBe('0x92345678');
  expect(word([{ value: null, origin: 'unknown' }, ...cells.slice(1)])).toBe('??');
  const step = { status: 'executed', memory_writes: [{ address: 8192, size: 4, before_bytes: '00563492', after_bytes: '78563492' }] } as StepResult;
  expect(byteChanged(8192, step)).toBe(true);
  expect(byteChanged(8193, step)).toBe(false);
  expect(byteChanged(8192, { ...step, memory_writes: [...step.memory_writes,
    { address: 8192, size: 1, before_bytes: '78', after_bytes: '00' }] })).toBe(false);
  expect(byteChanged(8192, { ...step, status: 'failed' })).toBe(false);
  const { container } = render(MemoryTable, { window: { address: 8192, length: 4, cells }, step, sp: 8192 });
  expect(container.querySelectorAll('.changed')).toHaveLength(1);
  expect(screen.getByText(/← SP/)).toBeTruthy();
  expect(screen.getByText('user')).toBeTruthy();
});

it('serializes inspection with mutations, clears stale windows, and treats read loss as read failure', async () => {
  const session = new PageSession();
  session.id = 'memory-test';
  session.program = {} as Program;
  session.state = { session_id: 'memory-test', status: 'ready', profile: 'armv7-a-le', mode: 'arm',
    baseline_pc: 4096, step_seq: 0, pc: 4096, cpsr: null, flags: null, stack: null, regions: [], last_step: null,
    registers: { sp: { value: 0x20100000, origin: 'default' } } };
  session.memoryEnabled = true;
  let release!: (response: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise(resolve => { release = resolve; }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ address: 0x200fff80, length: 256, cells: [] })));
  vi.stubGlobal('fetch', fetcher);
  const reading = session.inspect(8192, 4);
  await session.step();
  expect(fetcher).toHaveBeenCalledOnce();
  release(new Response(JSON.stringify({ address: 8192, length: 4, cells: [] })));
  await reading;
  expect(session.memory?.address).toBe(8192);
  expect(fetcher.mock.calls[1][0]).toContain('address=537919360&length=256');
  fetcher.mockRejectedValueOnce(new Error('offline'));
  await session.inspect(8192, 4);
  expect(session.memory).toBeNull();
  expect(session.stackMemory).toBeNull();
  expect(session.memoryError).toContain('offline');
  expect(session.uncertainty).toBeNull();
  expect(session.editable).toBe(true);
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'session_not_found', message: 'Missing', context: {} } }), { status: 404 }));
  await session.inspect(8192, 4);
  expect(session.expired).toBe(true);
});
