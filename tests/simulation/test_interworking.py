import pytest
from armstride.parser import parse
from armstride.simulation.session import SimulationSession


def test_arm_to_thumb_bx():
    source = """    $a
    0x00008000:    e12fff10    ....    BX       r0
    $t
    0x00008004:    2106                MOVS     r1,#6
    0x00008006:    2207                MOVS     r2,#7
"""
    parsed = parse(source, mode="arm", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("r0", 0x8005)  # Bit 0 set -> Thumb mode at 0x8004
        step1 = session.step()
        assert step1["status"] == "executed"
        assert step1["stop_reason"] is None
        assert step1["pc_after"] == 0x8004
        assert session.runtime.registers["pc"] == 0x8004
        assert (session.runtime.registers["cpsr"] & 0x20) != 0  # Thumb T-bit set
        assert session.step_seq == 1

        step2 = session.step()
        assert step2["status"] == "executed"
        assert session.runtime.registers["r1"] == 6
        assert session.runtime.registers["pc"] == 0x8006
        assert session.step_seq == 2
    finally:
        session.close()


def test_thumb_to_arm_bx():
    source = """    $t
    0x00008000:    4700    ..          BX       r0
    $a
    0x00008004:    e3a0102a    *...    MOV      r1,#42
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("r0", 0x8004)  # Bit 0 clear -> ARM mode at 0x8004
        step1 = session.step()
        assert step1["status"] == "executed"
        assert step1["stop_reason"] is None
        assert step1["pc_after"] == 0x8004
        assert (session.runtime.registers["cpsr"] & 0x20) == 0  # ARM T-bit clear
        assert session.step_seq == 1

        step2 = session.step()
        assert step2["status"] == "executed"
        assert session.runtime.registers["r1"] == 42
        assert session.step_seq == 2
    finally:
        session.close()


def test_thumb_to_arm_pop_pc():
    source = """    $t
    0x00008000:    bd01                POP      {r0,pc}
    $a
    0x00008004:    e3a0100a    ....    MOV      r1,#10
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        # SP defaults to 0x20100000; write [r0_val, target_pc]
        # Target 0x8004 has bit 0 = 0 -> ARM mode
        session.patch_memory(0x20100000, bytes.fromhex("2a000000" + "04800000"))
        step1 = session.step()
        assert step1["status"] == "executed"
        assert session.runtime.registers["r0"] == 42
        assert session.runtime.registers["pc"] == 0x8004
        assert (session.runtime.registers["cpsr"] & 0x20) == 0
        assert session.runtime.registers["sp"] == 0x20100008

        step2 = session.step()
        assert step2["status"] == "executed"
        assert session.runtime.registers["r1"] == 10
    finally:
        session.close()


def test_interworking_target_mode_mismatch_rollback():
    source = """    $a
    0x00008000:    e12fff10    ....    BX       r0
    0x00008004:    e3a01001    ....    MOV      r1,#1
"""
    parsed = parse(source, mode="arm", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("r0", 0x8005)  # T-bit requested, but target 0x8004 is ARM
        before = session.runtime
        step = session.step()
        assert step["status"] == "failed"
        assert step["error"]["code"] in ("unsupported_mode_transition", "mode_mismatch")
        # Full rollback verification per P1-FR-005
        assert session.runtime == before
        assert session.step_seq == 0
    finally:
        session.close()


def test_literal_pool_pc_relative_load_from_data_region():
    # In Thumb, PC is Align(address + 4, 4) = 0x8004
    # ldr r0, [pc, #0] reads 4 bytes from 0x8004
    source = """    $t
    0x00008000:    4800                LDR      r0,[pc,#0]
    0x00008002:    bf00                NOP
    $d
    0x00008004:    12345678    .4Vx    DCD      0x12345678
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        step = session.step()
        assert step["status"] == "executed"
        assert session.runtime.registers["r0"] == 0x12345678
        assert session.step_seq == 1
    finally:
        session.close()


def test_direct_branch_into_data_region_halts():
    source = """    $a
    0x00008000:    e12fff10    ....    BX       r0
    $d
    0x00008004:    12345678    .4Vx    DCD      0x78563412
"""
    parsed = parse(source, mode="arm", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("r0", 0x8004)  # Branch into data region
        step1 = session.step()
        assert step1["status"] == "executed"
        assert step1["pc_after"] == 0x8004
        assert step1["stop_reason"] == "non_executable_target"

        # Attempting to execute data halts with error
        step2 = session.step()
        assert step2["status"] == "failed"
        assert step2["error"]["code"] == "non_executable_target"
    finally:
        session.close()


def test_interworking_memory_fault_atomic_rollback():
    source = """    $t
    0x00008000:    bd01                POP      {r0,pc}
"""
    parsed = parse(source, mode="thumb", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("sp", 0x00000000)  # Unmapped stack address
        before = session.runtime
        step = session.step()
        assert step["status"] == "failed"
        assert step["error"]["code"] == "unmapped_memory_access"
        # Atomic rollback verification per P1-FR-005
        assert session.runtime == before
        assert session.step_seq == 0
    finally:
        session.close()
