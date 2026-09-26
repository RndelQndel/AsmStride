import { hex, uint32 } from './api';
import type { StepResult } from './api';

export const STACK_WINDOW_BYTES = 256;

export interface MemoryCell { value: number | null; origin: 'code' | 'stack' | 'user' | 'unknown' }
export interface MemoryWindow { address: number; length: number; cells: MemoryCell[] }
export type MemoryPatch = { address: number } & ({ bytes: string } | { zero_fill_length: number });

export function range(address: string, length: string, limit: number) {
  const start = uint32(address), size = uint32(length);
  if (!size || size > limit || start + size > 0x100000000)
    throw new Error(`Enter a non-empty 32-bit address range of at most ${limit} bytes.`);
  return { address: start, length: size };
}

export function patch(address: string, kind: 'bytes' | 'word' | 'zero', input: string): MemoryPatch {
  if (kind === 'zero') {
    const selected = range(address, input, 65536);
    return { address: selected.address, zero_fill_length: selected.length };
  }
  let bytes: string;
  if (kind === 'word') {
    if (uint32(address) % 4) throw new Error('Word address must be four-byte aligned.');
    const value = uint32(input);
    bytes = [0, 8, 16, 24].map(shift => ((value >>> shift) & 255).toString(16).padStart(2, '0')).join('');
  } else {
    if (!/^(?:[\da-f]{2}\s*)+$/i.test(input.trim())) throw new Error('Enter complete hexadecimal byte pairs, for example: 78 56 34 12.');
    bytes = input.replace(/\s/g, '');
  }
  return { address: range(address, String(bytes.length / 2), 65536).address, bytes };
}

export function word(cells: MemoryCell[]) {
  if (cells.length !== 4 || cells.some(cell => cell.value === null)) return '??';
  return hex(cells.reduce((value, cell, index) => value + cell.value! * 2 ** (index * 8), 0));
}

export function byteChanged(address: number, step: StepResult | null) {
  if (step?.status !== 'executed') return false;
  let before: string | undefined, after: string | undefined;
  for (const write of step.memory_writes) {
    const offset = (address - write.address) * 2;
    if (offset < 0 || offset >= write.size * 2) continue;
    before ??= write.before_bytes.slice(offset, offset + 2);
    after = write.after_bytes.slice(offset, offset + 2);
  }
  return before !== after;
}
