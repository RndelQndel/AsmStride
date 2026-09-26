import pytest
from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation.session import SimulationSession


def test_it_single_instruction_true():
    source = """    $t
    0x00001000:    bf08    ..          IT       EQ
    0x00001002:    202a                MOV      r0,#42
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_flags(0x40000000, 0x40000000)  # Z=1 (EQ is True)

        step1 = session.step()
        assert step1["status"] == "executed"
        assert step1["executed"] is True
        assert step1["condition_passed"] is None
        assert step1["it_context"] is None
        assert step1["pc_after"] == 0x1002
        assert session.step_seq == 1

        step2 = session.step()
        assert step2["status"] == "executed"
        assert step2["executed"] is True
        assert step2["condition_passed"] is True
        assert step2["it_context"] == {
            "block_index": 1,
            "block_total": 1,
            "condition": "EQ",
            "passed": True,
        }
        assert session.runtime.registers["r0"] == 42
        assert session.step_seq == 2
    finally:
        session.close()


def test_it_single_instruction_false_skip():
    source = """    $t
    0x00001000:    bf08    ..          IT       EQ
    0x00001002:    202a                MOV      r0,#42
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_flags(0x40000000, 0)  # Z=0 (EQ is False)

        step1 = session.step()
        assert step1["status"] == "executed"
        assert step1["pc_after"] == 0x1002

        step2 = session.step()
        assert step2["status"] == "executed"
        assert step2["executed"] is False
        assert step2["condition_passed"] is False
        assert step2["it_context"] == {
            "block_index": 1,
            "block_total": 1,
            "condition": "EQ",
            "passed": False,
        }
        assert session.runtime.registers["r0"] == 0  # Unchanged
        assert "r0" not in step2["register_changes"]
        assert session.step_seq == 2
    finally:
        session.close()


def test_ite_mixed_then_else():
    source = """    $t
    0x00001000:    bf0c    ..          ITE      EQ
    0x00001002:    210a                MOV      r1,#10
    0x00001004:    2214                MOV      r2,#20
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success

    # Test True path: Then executes (r1=10), Else skips (r2 unchanged)
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_flags(0x40000000, 0x40000000)  # Z=1 -> EQ is True

        session.step()  # ITE EQ

        step1 = session.step()  # Then: MOV r1, #10
        assert step1["executed"] is True
        assert step1["condition_passed"] is True
        assert step1["it_context"] == {
            "block_index": 1,
            "block_total": 2,
            "condition": "EQ",
            "passed": True,
        }
        assert session.runtime.registers["r1"] == 10

        step2 = session.step()  # Else: MOV r2, #20 (skipped)
        assert step2["executed"] is False
        assert step2["condition_passed"] is False
        assert step2["it_context"] == {
            "block_index": 2,
            "block_total": 2,
            "condition": "NE",
            "passed": False,
        }
        assert session.runtime.registers["r2"] == 0
        assert "r2" not in step2["register_changes"]
    finally:
        session.close()

    # Test False path: Then skips (r1 unchanged), Else executes (r2=20)
    session2 = SimulationSession()
    try:
        session2.load(parsed.program)
        session2.set_flags(0x40000000, 0)  # Z=0 -> EQ is False

        session2.step()  # ITE EQ

        step1 = session2.step()  # Then: skipped
        assert step1["executed"] is False
        assert step1["condition_passed"] is False
        assert session2.runtime.registers["r1"] == 0

        step2 = session2.step()  # Else: executed
        assert step2["executed"] is True
        assert step2["condition_passed"] is True
        assert session2.runtime.registers["r2"] == 20
    finally:
        session2.close()


def test_itte_three_instructions():
    source = """    $t
    0x00001000:    bf06    ..          ITTE     EQ
    0x00001002:    2101                MOV      r1,#1
    0x00001004:    2202                MOV      r2,#2
    0x00001006:    2303                MOV      r3,#3
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_flags(0x40000000, 0x40000000)  # Z=1 (EQ is True)

        session.step()  # ITTE EQ

        s1 = session.step()
        assert s1["it_context"]["block_index"] == 1
        assert s1["it_context"]["block_total"] == 3
        assert s1["it_context"]["passed"] is True
        assert session.runtime.registers["r1"] == 1

        s2 = session.step()
        assert s2["it_context"]["block_index"] == 2
        assert s2["it_context"]["block_total"] == 3
        assert s2["it_context"]["passed"] is True
        assert session.runtime.registers["r2"] == 2

        s3 = session.step()
        assert s3["it_context"]["block_index"] == 3
        assert s3["it_context"]["block_total"] == 3
        assert s3["it_context"]["passed"] is False
        assert s3["executed"] is False
        assert session.runtime.registers["r3"] == 0
    finally:
        session.close()


def test_manual_pc_entry_into_it_interior_rejected():
    source = """    $t
    0x00001000:    bf08    ..          IT       EQ
    0x00001002:    202a                MOV      r0,#42
    0x00001004:    bf00    ..          NOP
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        # Attempt to jump directly into interior instruction 0x1002
        with pytest.raises(DomainError) as exc_info:
            session.set_register("pc", 0x1002)
        assert exc_info.value.code == "invalid_it_block_entry"
        assert session.runtime.registers["pc"] == 0x1000

        # Jumping to 0x1004 (after IT block) is valid
        session.set_register("pc", 0x1004)
        assert session.runtime.registers["pc"] == 0x1004
    finally:
        session.close()


def test_executed_without_state_change_vs_conditionally_skipped():
    # orrs r0, r0, r0 in Thumb-2: ea50 0000
    source = """    $t
    0x00001000:    bf08    ..          IT       EQ
    0x00001002:    ea50 0000           ORRS     r0,r0,r0
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_flags(0x40000000, 0x40000000)  # Z=1 (condition passes)
        session.step()  # IT EQ
        step = session.step()

        # Executed with condition passed, even though r0 was 0 and remains 0
        assert step["status"] == "executed"
        assert step["executed"] is True
        assert step["condition_passed"] is True
        assert step["it_context"]["passed"] is True
    finally:
        session.close()
