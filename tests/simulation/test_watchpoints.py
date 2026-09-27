"""Unit tests for Stage P2-C Memory Watchpoints Engine (P2-AC-11 through P2-AC-16)."""

import pytest

from armstride.domain.models import DomainError, Instruction, ProgramImage, Watchpoint
from armstride.parser import parse
from armstride.simulation.session import SimulationSession


def make_session(listing: str, mode: str = "arm") -> SimulationSession:
    res = parse(listing, mode=mode)
    assert res.load_success
    session = SimulationSession()
    session.load(res.program)
    return session


def test_p2_ac_11_read_watchpoint_step_and_run():
    """P2-AC-11: Active read watchpoint triggers on committed memory read; Step reports hits, Run halts."""
    # Program:
    # 0x1000: ldr r0, [r1]  (reads memory at R1)
    # 0x1004: mov r2, #1
    # 0x1008: bx lr
    listing = (
        "0x1000: E5910000 LDR R0, [R1]\n"
        "0x1004: E3A02001 MOV R2, #1\n"
        "0x1008: E12FFF1E BX LR\n"
    )
    # Step test
    session = make_session(listing)
    session.set_register('r1', 0x20000000)
    session.patch_memory(0x20000000, bytes.fromhex("efbeadde"))  # 0xDEADBEEF
    session.add_watchpoint(0x20000000, length=4, kind='read')

    step_res = session.step()
    assert step_res['status'] == 'executed'
    assert len(step_res['watchpoint_hits']) == 1
    hit = step_res['watchpoint_hits'][0]
    assert hit['access_type'] == 'read'
    assert hit['address'] == 0x20000000
    assert hit['triggering_pc'] == 0x1000
    assert session.runtime.registers['r0'] == 0xDEADBEEF

    # Run test
    session.reset()
    session.set_register('r1', 0x20000000)
    run_res = session.run()
    assert run_res['stop_reason'] == 'watchpoint'
    assert run_res['watchpoint_hit'] is not None
    assert run_res['watchpoint_hit']['address'] == 0x20000000
    assert run_res['steps_committed'] == 1
    assert session.runtime.registers['pc'] == 0x1004


def test_p2_ac_12_write_watchpoint_same_value_write():
    """P2-AC-12: Write watchpoint triggers on memory write even when written value equals existing value."""
    # 0x1000: str r0, [r1]
    # 0x1004: bx lr
    listing = (
        "0x1000: E5810000 STR R0, [R1]\n"
        "0x1004: E12FFF1E BX LR\n"
    )
    session = make_session(listing)
    session.set_register('r0', 0x12345678)
    session.set_register('r1', 0x20000000)
    # Pre-populate memory with the EXACT SAME value
    session.patch_memory(0x20000000, (0x12345678).to_bytes(4, 'little'))
    session.add_watchpoint(0x20000000, length=4, kind='write')

    step_res = session.step()
    assert step_res['status'] == 'executed'
    assert len(step_res['watchpoint_hits']) == 1
    hit = step_res['watchpoint_hits'][0]
    assert hit['access_type'] == 'write'
    assert hit['watchpoint_address'] == 0x20000000


def test_p2_ac_13_multi_access_ordered_hits_and_fault_isolation():
    """P2-AC-13: STM/LDM preserves ordered multiple hits; rolled-back failed accesses never hit."""
    # 0x1000: stm r1, {r2, r3} (stores R2 to [R1], R3 to [R1+4])
    # 0x1004: bx lr
    listing = (
        "0x1000: E881000C STM R1, {R2, R3}\n"
        "0x1004: E12FFF1E BX LR\n"
    )
    session = make_session(listing)
    session.set_register('r1', 0x20000000)
    session.set_register('r2', 0x11111111)
    session.set_register('r3', 0x22222222)
    session.zero_fill(0x20000000, 8)

    session.add_watchpoint(0x20000000, length=4, kind='write')
    session.add_watchpoint(0x20000004, length=4, kind='write')

    step_res = session.step()
    assert step_res['status'] == 'executed'
    assert len(step_res['watchpoint_hits']) == 2
    # Check exact ordering
    assert step_res['watchpoint_hits'][0]['address'] == 0x20000000
    assert step_res['watchpoint_hits'][1]['address'] == 0x20000004

    # Failed step isolation: attempt to access unmapped memory with watchpoint
    session.reset()
    session.set_register('r1', 0x30000000)  # unmapped
    session.add_watchpoint(0x30000000, length=4, kind='write')

    step_fail = session.step()
    assert step_fail['status'] == 'failed'
    assert len(step_fail['watchpoint_hits']) == 0  # Rolled-back, NO hits!


def test_p2_ac_14_stop_precedence_matrix():
    """P2-AC-14: Watchpoint halts Run while preserving architectural stop (pc_not_loaded) in last_step."""
    # 0x1000: str r0, [r1]
    # 0x1004: bx r2  (R2 points to unloaded address 0x9000)
    listing = (
        "0x1000: E5810000 STR R0, [R1]\n"
        "0x1004: E12FFF12 BX R2\n"
    )
    session = make_session(listing)
    session.set_register('r0', 0x42)
    session.set_register('r1', 0x20000000)
    session.set_register('r2', 0x9000)
    session.zero_fill(0x20000000, 4)

    # Watchpoint on the second instruction? No, watchpoint on STR and let it run to BX R2
    # Or an instruction that both writes and branches to unloaded: e.g. LDR PC, [R1] where [R1] = 0x9000!
    # 0x1000: LDR PC, [R1]
    single_inst_listing = "0x1000: E591F000 LDR PC, [R1]\n"
    session2 = make_session(single_inst_listing)
    session2.set_register('r1', 0x20000000)
    session2.patch_memory(0x20000000, (0x9000).to_bytes(4, 'little'))
    session2.add_watchpoint(0x20000000, length=4, kind='read')

    run_res = session2.run()
    # Run halts with watchpoint
    assert run_res['stop_reason'] == 'watchpoint'
    # But last_step_result simultaneously retains pc_not_loaded!
    assert run_res['last_step_result']['stop_reason'] == 'pc_not_loaded'
    assert len(run_res['last_step_result']['watchpoint_hits']) == 1


def test_p2_ac_15_breakpoint_and_watchpoint_coexistence():
    """P2-AC-15: Instruction with breakpoint and watchpoint stops at breakpoint first, then watchpoint on resume."""
    listing = (
        "0x1000: E1A00000 NOP\n"
        "0x1004: E5910000 LDR R0, [R1]\n"
    )
    session = make_session(listing)
    session.set_register('r1', 0x20000000)
    session.zero_fill(0x20000000, 4)

    session.add_breakpoint(0x1004, 'arm')
    session.add_watchpoint(0x20000000, length=4, kind='read')

    # First run executes NOP and halts at 0x1004 breakpoint before execution
    run1 = session.run()
    assert run1['stop_reason'] == 'breakpoint'
    assert run1['breakpoint_hit'] == 0x1004
    assert run1['steps_committed'] == 1
    assert session.runtime.registers['pc'] == 0x1004

    # Resuming bypasses breakpoint and halts at watchpoint after executing 0x1004
    run2 = session.run()
    assert run2['stop_reason'] == 'watchpoint'
    assert run2['steps_committed'] == 1
    assert session.runtime.registers['pc'] == 0x1008


def test_p2_ac_16_watchpoint_lifecycle_and_capacity():
    """P2-AC-16: Watchpoints persist across steps, runs, edits, reset; cleared on reload; capacity is 32."""
    listing = "0x1000: E1A00000 NOP\n"
    session = make_session(listing)

    # Capacity limit 32
    for i in range(32):
        session.add_watchpoint(0x20000000 + i * 4, length=4, kind='read_write')
    assert len(session.list_watchpoints()) == 32

    # 33rd watchpoint raises DomainError
    with pytest.raises(DomainError) as exc:
        session.add_watchpoint(0x20001000, length=4, kind='read')
    assert exc.value.code == 'invalid_watchpoint'

    # Removing a watchpoint
    assert session.remove_watchpoint(0x20000000) is True
    assert len(session.list_watchpoints()) == 31

    # Persists across step, manual edits, and reset
    session.step()
    assert len(session.list_watchpoints()) == 31
    session.set_register('r0', 10)
    assert len(session.list_watchpoints()) == 31
    session.reset()
    assert len(session.list_watchpoints()) == 31

    # Cleared only on replacement Load
    session.load(session.program)
    assert len(session.list_watchpoints()) == 0
