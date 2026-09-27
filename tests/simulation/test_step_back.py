"""Tests for Step Back / Execution History (P2-AC-17 ~ P2-AC-20)."""

import pytest
from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation.session import SimulationSession


def make_session(listing: str) -> SimulationSession:
    parsed = parse(listing, mode="arm")
    assert parsed.load_success
    session = SimulationSession()
    session.load(parsed.program)
    return session


def test_p2_ac_17_single_and_multi_step_rewind():
    """P2-AC-17: Step back restores registers, PC, flags, and memory to exact pre-step state."""
    listing = (
        "0x1000: E3A0002A MOV R0, #42\n"       # R0 = 42
        "0x1004: E3A01007 MOV R1, #7\n"        # R1 = 7
        "0x1008: E5820000 STR R0, [R2]\n"      # [R2] = 42
        "0x100C: E0803001 ADD R3, R0, R1\n"    # R3 = 49
    )
    session = make_session(listing)
    session.set_register('r2', 0x20000000)
    session.zero_fill(0x20000000, 4)

    # Step 1: MOV R0, #42
    s1 = session.step()
    assert s1['status'] == 'executed'
    assert session.runtime.registers['r0'] == 42
    assert session.runtime.registers['pc'] == 0x1004

    # Step 2: MOV R1, #7
    s2 = session.step()
    assert s2['status'] == 'executed'
    assert session.runtime.registers['r1'] == 7
    assert session.runtime.registers['pc'] == 0x1008

    # Step 3: STR R0, [R2]
    s3 = session.step()
    assert s3['status'] == 'executed'
    assert bytes(c.value for c in session.inspect_memory(0x20000000, 4)) == b'\x2a\x00\x00\x00'
    assert session.runtime.registers['pc'] == 0x100C

    # Step 4: ADD R3, R0, R1
    s4 = session.step()
    assert s4['status'] == 'executed'
    assert session.runtime.registers['r3'] == 49
    assert session.runtime.registers['pc'] == 0x1010

    # Rewind step 4 -> R3 restored, PC restored to 0x100C
    b1 = session.step_back()
    assert b1['status'] == 'ok'
    assert b1['history_depth'] == 3
    assert session.runtime.registers['r3'] == 0
    assert session.runtime.registers['pc'] == 0x100C

    # Rewind step 3 -> memory at 0x20000000 restored to 0, PC restored to 0x1008
    b2 = session.step_back()
    assert b2['status'] == 'ok'
    assert b2['history_depth'] == 2
    assert bytes(c.value for c in session.inspect_memory(0x20000000, 4)) == b'\x00\x00\x00\x00'
    assert session.runtime.registers['pc'] == 0x1008
    assert session.runtime.registers['r1'] == 7

    # Rewind step 2 -> R1 restored to 0, PC restored to 0x1004
    b3 = session.step_back()
    assert b3['status'] == 'ok'
    assert b3['history_depth'] == 1
    assert session.runtime.registers['r1'] == 0
    assert session.runtime.registers['r0'] == 42
    assert session.runtime.registers['pc'] == 0x1004

    # Rewind step 1 -> R0 restored to 0, PC restored to 0x1000
    b4 = session.step_back()
    assert b4['status'] == 'ok'
    assert b4['history_depth'] == 0
    assert session.runtime.registers['r0'] == 0
    assert session.runtime.registers['pc'] == 0x1000

    # Stepping back with empty history raises DomainError
    with pytest.raises(DomainError) as exc:
        session.step_back()
    assert exc.value.code == 'history_empty'


def test_p2_ac_18_monotonic_step_seq_invariance():
    """P2-AC-18: Step back does NOT change step_seq; forward steps continue from max_step_seq + 1."""
    listing = (
        "0x1000: E3A00001 MOV R0, #1\n"
        "0x1004: E3A01002 MOV R1, #2\n"
    )
    session = make_session(listing)
    assert session.step_seq == 0

    session.step()  # step_seq becomes 1
    assert session.step_seq == 1

    session.step()  # step_seq becomes 2
    assert session.step_seq == 2

    # Step back once
    res_b = session.step_back()
    # step_seq remains invariant (2), not decremented
    assert session.step_seq == 2
    assert res_b['current_step_seq'] == 2
    assert res_b['restored_step_seq'] == 1
    assert session.runtime.registers['pc'] == 0x1004

    # Subsequent forward step advances to max_step_seq + 1 = 3
    s_fwd = session.step()
    assert session.step_seq == 3
    assert s_fwd['step_seq'] == 3


def test_p2_ac_19_state_revision_and_baseline_isolation():
    """P2-AC-19: Step back increments state_revision; UserBaselineState is intact and reset() works cleanly."""
    listing = "0x1000: E3A00005 MOV R0, #5\n"
    session = make_session(listing)
    init_rev = session.state_revision

    session.step()
    assert session.state_revision == init_rev  # normal step does not necessarily bump revision unless specified, or session tracks it

    rev_before = session.state_revision
    b = session.step_back()
    assert b['state_revision'] == rev_before + 1
    assert session.state_revision == rev_before + 1

    # Baseline is still intact (R0 = 0)
    assert session.baseline.registers['r0'] == 0
    # Reset restores cleanly from baseline
    session.reset()
    assert session.runtime.registers['r0'] == 0
    assert session.state_revision == rev_before + 2


def test_p2_ac_20_history_invalidation_rules():
    """P2-AC-20: Manual edit (registers, memory) or reset/load invalidates and clears history journal."""
    listing = (
        "0x1000: E3A00001 MOV R0, #1\n"
        "0x1004: E3A01002 MOV R1, #2\n"
        "0x1008: E3A02003 MOV R2, #3\n"
        "0x100C: E3A03004 MOV R3, #4\n"
    )
    session = make_session(listing)
    session.zero_fill(0x20000000, 4)

    # 1. Step to accumulate history
    session.step()
    assert len(session._history) == 1

    # Manual register edit clears history
    session.set_register('r4', 100)
    assert len(session._history) == 0
    with pytest.raises(DomainError) as exc:
        session.step_back()
    assert exc.value.code == 'history_empty'

    # Step again
    session.step()
    assert len(session._history) == 1

    # Memory patch clears history
    session.patch_memory(0x20000000, b'\x01\x02\x03\x04')
    assert len(session._history) == 0

    # Step again
    session.step()
    assert len(session._history) == 1

    # Reset clears history
    session.reset()
    assert len(session._history) == 0


def test_history_capacity_bound():
    """Execution history deque is capped at MAX_HISTORY_STEPS (100)."""
    # Create a small 2-instruction loop
    listing = (
        "0x1000: E2800001 ADD R0, R0, #1\n"
        "0x1004: EAFFFFFE B 0x1000\n"
    )
    session = make_session(listing)

    # Execute 120 steps
    for _ in range(120):
        session.step()

    assert len(session._history) == 100
