import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import RegisterPanel from '../src/RegisterPanel.svelte';
import ProgramInput from '../src/ProgramInput.svelte';
import type { State } from '../src/api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mockRiscvState(): State {
  const regs: State['registers'] = {};
  for (let i = 0; i < 32; i++) {
    regs[`x${i}`] = { value: i === 2 ? 0x20100000 : 0, origin: 'default' };
  }
  regs.pc = { value: 0x1000, origin: 'default' };

  return {
    session_id: 'p3-session',
    status: 'ready',
    profile: 'rv32i-le',
    mode: 'riscv32',
    baseline_pc: 0x1000,
    step_seq: 0,
    registers: regs,
    cpsr: null,
    flags: null,
    pc: 0x1000,
    stack: { base: 0x200f0000, size: 65536 },
    regions: [],
    last_step: null,
  };
}

describe('Stage P3 Frontend Features', () => {
  it('renders RV32I RegisterPanel with 32 registers, ABI aliases, locked x0, and no flags/CPSR', () => {
    const state = mockRiscvState();
    const edit = vi.fn().mockResolvedValue(null);

    render(RegisterPanel, {
      props: {
        state,
        disabled: false,
        edit,
      },
    });

    // Check header
    expect(screen.getByText('RV32I')).toBeTruthy();

    // Flags bar and CPSR must be suppressed
    expect(screen.queryByText('Flags')).toBeNull();
    expect(screen.queryByText('CPSR')).toBeNull();

    // Check immutable x0 note
    expect(screen.getByText(/x0 \(zero\) is hardwired to 0 and immutable/)).toBeTruthy();

    // Check register labels with ABI names
    expect(screen.getByText('x0 (zero)')).toBeTruthy();
    expect(screen.getByText('x1 (ra)')).toBeTruthy();
    expect(screen.getByText('x2 (sp)')).toBeTruthy();
    expect(screen.getByText('x10 (a0)')).toBeTruthy();
    expect(screen.getByText('x31 (t6)')).toBeTruthy();
    expect(screen.getByText('PC')).toBeTruthy();

    // Check x0 input is disabled (locked)
    const x0Input = screen.getByLabelText('x0 (zero)') as HTMLInputElement;
    expect(x0Input.disabled).toBe(true);

    // Other registers should be enabled
    const x1Input = screen.getByLabelText('x1 (ra)') as HTMLInputElement;
    expect(x1Input.disabled).toBe(false);
  });

  it('adapts ProgramInput to RV32I profile and quick presets', async () => {
    const load = vi.fn().mockResolvedValue(null);

    render(ProgramInput, {
      props: {
        disabled: false,
        load,
      },
    });

    // Quick presets should include RV32I presets
    const loopBtn = screen.getByRole('button', { name: 'RV32I Loop' });
    expect(loopBtn).toBeTruthy();

    // Click RV32I Loop preset
    await fireEvent.click(loopBtn);

    // Should have updated to RV32I
    expect(load).toHaveBeenCalledWith(
      expect.objectContaining({
        input_kind: 'assembly',
        profile: 'rv32i-le',
        mode: 'riscv32',
        base_address: 0x1000,
        text: expect.stringContaining('li a0, 0'),
      })
    );
  });
});
