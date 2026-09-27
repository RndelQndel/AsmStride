"""Exhaustive tests for RV32I simulation engine covering P3-AC-02 through P3-AC-23."""

import threading
import time
import pytest

from armstride.architecture import riscv
from armstride.backends.keystone import KeystoneAssembler
from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation.session import SimulationSession


def read_reg(session: SimulationSession, name: str) -> int:
    canonical = riscv.canonical_register(name)
    return session.runtime.registers[canonical]


def get_pc(session: SimulationSession) -> int:
    return session.runtime.registers["pc"]


def load_rv32(source: str, base_address: int = 0x1000) -> SimulationSession:
    asm = KeystoneAssembler()
    res = asm.assemble(source, mode="riscv32", base_address=base_address, profile="rv32i-le")
    assert res.program is not None, f"Assembly failed: {res.diagnostics}"
    session = SimulationSession()
    session.load(res.program, initial_pc=base_address, stack_base=0x200F0000, stack_size=0x10000)
    return session


# P3-AC-02: Shared simulation contracts do not require CPSR / flags for RISC-V sessions
def test_p3_ac_02_no_cpsr_or_flags():
    from armstride.simulation.session import flags
    session = load_rv32("nop")
    assert session.status == "ready"
    assert session.program.profile == "rv32i-le"
    assert session.program.mode == "riscv32"
    assert "cpsr" not in session.runtime.registers
    assert flags(session.runtime.registers) == {}


# P3-AC-03: x0 unconditionally returns 0; user edits targeting x0 reject with x0_immutable
def test_p3_ac_03_x0_immutability():
    session = load_rv32("addi x1, x0, 10")
    assert read_reg(session, "x0") == 0
    assert read_reg(session, "zero") == 0

    with pytest.raises(DomainError) as exc_info:
        session.set_register("x0", 42)
    assert exc_info.value.code == "x0_immutable"

    with pytest.raises(DomainError) as exc_info:
        session.set_register("zero", 42)
    assert exc_info.value.code == "x0_immutable"


# P3-AC-04: addi x0, x1, 5 stepped: completes, x0 remains 0, no x0 delta reported in register_changes
def test_p3_ac_04_x0_write_ignored_and_no_delta():
    session = load_rv32("addi x0, x1, 5")
    session.set_register("x1", 100)
    step_res = session.step()
    assert step_res["status"] == "executed"
    assert read_reg(session, "x0") == 0
    assert "x0" not in step_res["register_changes"]
    assert "zero" not in step_res["register_changes"]
    assert step_res["cpsr_change"] is None
    assert step_res["flag_changes"] == {}


# P3-AC-05: User edits to x1..x31 or pc update runtime and baseline; invalid register names reject with 422
def test_p3_ac_05_register_edits():
    session = load_rv32("nop\nnop")
    session.set_register("x1", 0x12345678)
    assert read_reg(session, "x1") == 0x12345678

    session.set_register("x31", 0xCAFEBABE)
    assert read_reg(session, "x31") == 0xCAFEBABE

    session.set_pc(0x1004)
    assert get_pc(session) == 0x1004

    with pytest.raises(DomainError) as exc_info:
        session.set_pc(0x2000)
    assert exc_info.value.code == "invalid_pc"

    with pytest.raises(DomainError) as exc_info:
        session.set_register("x32", 1)
    assert exc_info.value.code == "invalid_register"

    with pytest.raises(DomainError) as exc_info:
        session.set_register("r0", 1)
    assert exc_info.value.code == "invalid_register"


# P3-AC-06: Standard ABI aliases map to and update canonical registers
def test_p3_ac_06_abi_aliases():
    session = load_rv32("nop")
    session.set_register("ra", 0x1004)
    assert read_reg(session, "x1") == 0x1004
    assert read_reg(session, "ra") == 0x1004

    session.set_register("sp", 0x200FFFF0)
    assert read_reg(session, "x2") == 0x200FFFF0
    assert read_reg(session, "sp") == 0x200FFFF0

    session.set_register("a0", 42)
    assert read_reg(session, "x10") == 42
    assert read_reg(session, "a0") == 42


# P3-AC-07: Computational instructions
def test_p3_ac_07_computational_instructions():
    source = """
    add a0, a1, a2
    sub a3, a1, a2
    and a4, a1, a2
    or a5, a1, a2
    xor a6, a1, a2
    addi t0, a1, 5
    andi t1, a1, 0x0f
    ori t2, a1, 0x50
    xori t3, a1, 0xff
    """
    session = load_rv32(source)
    session.set_register("a1", 0x12)
    session.set_register("a2", 0x04)

    session.step()  # add: 0x12 + 0x04 = 0x16
    assert read_reg(session, "a0") == 0x16

    session.step()  # sub: 0x12 - 0x04 = 0x0e
    assert read_reg(session, "a3") == 0x0e

    session.step()  # and: 0x12 & 0x04 = 0x00
    assert read_reg(session, "a4") == 0x00

    session.step()  # or: 0x12 | 0x04 = 0x16
    assert read_reg(session, "a5") == 0x16

    session.step()  # xor: 0x12 ^ 0x04 = 0x16
    assert read_reg(session, "a6") == 0x16

    session.step()  # addi: 0x12 + 5 = 0x17
    assert read_reg(session, "t0") == 0x17

    session.step()  # andi: 0x12 & 0x0f = 0x02
    assert read_reg(session, "t1") == 0x02

    session.step()  # ori: 0x12 | 0x50 = 0x52
    assert read_reg(session, "t2") == 0x52

    session.step()  # xori: 0x12 ^ 0xff = 0xed
    assert read_reg(session, "t3") == 0xed


# P3-AC-08: Shift instructions mask shift amount to lower 5 bits; SRA/SRAI preserve sign
def test_p3_ac_08_shifts():
    source = """
    sll a0, a1, a2
    srl a3, a1, a2
    sra a4, a1, a2
    slli t0, a1, 2
    srli t1, a1, 2
    srai t2, a1, 2
    """
    session = load_rv32(source)
    # Negative number: 0x80000020 (-2147483616)
    session.set_register("a1", 0x80000020)
    # Shift by 34 -> lower 5 bits is 2
    session.set_register("a2", 34)

    session.step()  # sll by 2
    assert read_reg(session, "a0") == (0x80000020 << 2) & 0xFFFFFFFF

    session.step()  # srl by 2 (logical)
    assert read_reg(session, "a3") == (0x80000020 >> 2)

    session.step()  # sra by 2 (arithmetic, preserves sign bit 31)
    assert read_reg(session, "a4") == 0xE0000008

    session.step()  # slli by 2
    assert read_reg(session, "t0") == (0x80000020 << 2) & 0xFFFFFFFF

    session.step()  # srli by 2
    assert read_reg(session, "t1") == (0x80000020 >> 2)

    session.step()  # srai by 2
    assert read_reg(session, "t2") == 0xE0000008


# P3-AC-09: Comparison instructions correctly differentiate signed vs unsigned
def test_p3_ac_09_comparisons():
    source = """
    slt a0, a1, a2
    sltu a3, a1, a2
    slti t0, a1, 0
    sltiu t1, a1, 0
    """
    session = load_rv32(source)
    # a1 = -1 (0xFFFFFFFF), a2 = 1
    session.set_register("a1", 0xFFFFFFFF)
    session.set_register("a2", 1)

    session.step()  # slt: signed (-1 < 1 is True -> 1)
    assert read_reg(session, "a0") == 1

    session.step()  # sltu: unsigned (0xFFFFFFFF < 1 is False -> 0)
    assert read_reg(session, "a3") == 0

    session.step()  # slti: signed (-1 < 0 is True -> 1)
    assert read_reg(session, "t0") == 1

    session.step()  # sltiu: unsigned (0xFFFFFFFF < 0 is False -> 0)
    assert read_reg(session, "t1") == 0


# P3-AC-10: Upper immediate instructions (LUI, AUIPC)
def test_p3_ac_10_upper_immediates():
    source = """
    lui a0, 0x12345
    auipc a1, 0x1000
    """
    session = load_rv32(source, base_address=0x2000)

    session.step()  # lui 0x12345 -> a0 = 0x12345000
    assert read_reg(session, "a0") == 0x12345000

    session.step()  # auipc 0x1000 at PC 0x2004 -> a1 = 0x2004 + 0x1000000 = 0x01002004
    assert read_reg(session, "a1") == 0x01002004


# P3-AC-11: Loads and stores maintain little-endian layout and sign/zero extension
def test_p3_ac_11_loads_stores():
    source = """
    addi sp, sp, -16
    sb a0, 0(sp)
    lb a1, 0(sp)
    lbu a2, 0(sp)
    sh a0, 4(sp)
    lh a3, 4(sp)
    lhu a4, 4(sp)
    sw a0, 8(sp)
    lw a5, 8(sp)
    """
    session = load_rv32(source)
    # Use value with high bit set in byte and halfword: 0x000080F0
    session.set_register("a0", 0x000080F0)

    session.step()  # addi sp, sp, -16
    session.step()  # sb 0xF0 at sp+0
    session.step()  # lb: sign extends 0xF0 -> 0xFFFFFFF0
    assert read_reg(session, "a1") == 0xFFFFFFF0

    session.step()  # lbu: zero extends 0xF0 -> 0x000000F0
    assert read_reg(session, "a2") == 0x000000F0

    session.step()  # sh 0x80F0 at sp+4
    session.step()  # lh: sign extends 0x80F0 -> 0xFFFF80F0
    assert read_reg(session, "a3") == 0xFFFF80F0

    session.step()  # lhu: zero extends 0x80F0 -> 0x000080F0
    assert read_reg(session, "a4") == 0x000080F0

    session.step()  # sw 0x000080F0 at sp+8
    session.step()  # lw -> 0x000080F0
    assert read_reg(session, "a5") == 0x000080F0


# P3-AC-12: Targeting unmapped memory halts with memory_fault and rolls back state
def test_p3_ac_12_unmapped_memory_rollback():
    source = """
    lw a0, 0(a1)
    """
    session = load_rv32(source)
    session.set_register("a0", 42)
    session.set_register("a1", 0x50000000)  # unmapped memory address
    pc_before = get_pc(session)

    step_res = session.step()
    assert step_res["status"] == "failed"
    assert step_res["error"]["code"] == "unmapped_memory_access"
    assert step_res["error"]["restored"] is True
    # State rolled back
    assert get_pc(session) == pc_before
    assert read_reg(session, "a0") == 42


# P3-AC-13: Conditional branches
def test_p3_ac_13_branches():
    source = """
    beq a0, a1, taken_eq
    addi t0, zero, 1
taken_eq:
    blt a0, a1, taken_lt
    addi t1, zero, 1
taken_lt:
    bltu a0, a1, taken_ltu
    addi t2, zero, 1
taken_ltu:
    ret
    """
    session = load_rv32(source)
    # a0 = -1 (0xFFFFFFFF), a1 = 1
    session.set_register("a0", 0xFFFFFFFF)
    session.set_register("a1", 1)

    # beq: -1 != 1 -> not taken, PC advances to addi t0
    step1 = session.step()
    assert step1["branch"]["taken"] is False
    assert read_reg(session, "t0") == 0
    session.step()  # execute addi t0
    assert read_reg(session, "t0") == 1

    # blt: signed -1 < 1 -> taken!
    step2 = session.step()
    assert step2["branch"]["taken"] is True
    assert read_reg(session, "t1") == 0  # skipped addi t1

    # bltu: unsigned 0xFFFFFFFF < 1 -> not taken!
    step3 = session.step()
    assert step3["branch"]["taken"] is False
    session.step()  # execute addi t2
    assert read_reg(session, "t2") == 1


# P3-AC-14: JAL and JALR
def test_p3_ac_14_jumps_and_return():
    source = """
    jal ra, func
    addi a0, zero, 99
func:
    addi a0, zero, 42
    jalr zero, 0(ra)
    """
    session = load_rv32(source, base_address=0x1000)

    step1 = session.step()  # jal ra, func (PC 0x1000 -> jump to 0x1008)
    assert read_reg(session, "ra") == 0x1004
    assert get_pc(session) == 0x1008

    session.step()  # addi a0, zero, 42
    assert read_reg(session, "a0") == 42

    session.step()  # jalr zero, 0(ra) -> returns to 0x1004
    assert get_pc(session) == 0x1004

    session.step()  # addi a0, zero, 99
    assert read_reg(session, "a0") == 99


# P3-AC-15: ECALL and EBREAK halt cleanly with environment_call and breakpoint_trap
def test_p3_ac_15_traps():
    source = """
    ecall
    ebreak
    """
    session = load_rv32(source, base_address=0x1000)

    step1 = session.step()
    assert step1["status"] == "executed"
    assert step1["stop_reason"] == "environment_call"
    assert get_pc(session) == 0x1004

    step2 = session.step()
    assert step2["status"] == "executed"
    assert step2["stop_reason"] == "breakpoint_trap"
    assert get_pc(session) == 0x1008


# P3-AC-16: RV32I assembly source with local labels and ABI aliases
def test_p3_ac_16_labels_and_abi_aliases():
    source = """
    li a0, 0
    li a1, 5
loop:
    addi a0, a0, 1
    blt a0, a1, loop
    ret
    """
    session = load_rv32(source)
    while get_pc(session) != session.program.instructions[-1].address:
        session.step()
    assert read_reg(session, "a0") == 5


# P3-AC-17: Addressed RV32 disassembly text with hex bytes
def test_p3_ac_17_disassembly_import():
    listing = (
        "0x1000: 02a00513 addi a0, zero, 42\n"
        "0x1004: 00a505b3 add a1, a0, a0\n"
    )
    res = parse(listing, mode="riscv32", profile="rv32i-le", format="generic", encoding="words")
    assert res.program is not None
    assert len(res.program.instructions) == 2
    session = SimulationSession()
    session.load(res.program, initial_pc=0x1000)
    session.step()
    assert read_reg(session, "a0") == 42
    session.step()
    assert read_reg(session, "a1") == 84


# P3-AC-19: Bounded Run and concurrent Stop
def test_p3_ac_19_run_and_stop():
    source = """
loop:
    addi a0, a0, 1
    j loop
    """
    session = load_rv32(source)
    # Bounded run terminates at step limit
    res = session.run(max_steps=50)
    assert res["steps_executed"] == 50
    assert res["stop_reason"] == "step_limit"
    assert read_reg(session, "a0") == 25  # loop is 2 instructions

    # Stop signaled concurrently
    stop_event = threading.Event()
    def async_stop():
        time.sleep(0.005)
        stop_event.set()

    threading.Thread(target=async_stop, daemon=True).start()
    res2 = session.run(stop_event=stop_event, max_steps=100000)
    stop_event.wait(timeout=1.0)
    assert res2["stop_reason"] == "user_stop"


# P3-AC-20: Pre-execution breakpoint
def test_p3_ac_20_breakpoints():
    source = """
    addi a0, zero, 1
    addi a0, a0, 2
    addi a0, a0, 3
    """
    session = load_rv32(source, base_address=0x1000)
    session.add_breakpoint(0x1004)

    run1 = session.run(max_steps=10)
    assert run1["stop_reason"] == "breakpoint"
    assert run1["breakpoint_hit"] == 0x1004
    assert get_pc(session) == 0x1004
    assert read_reg(session, "a0") == 1

    # Resuming bypasses breakpoint for one step
    run2 = session.run(max_steps=10)
    assert read_reg(session, "a0") == 6


# P3-AC-21: Memory watchpoints
def test_p3_ac_21_watchpoints():
    source = """
    addi sp, sp, -16
    sw a0, 0(sp)
    lw a1, 0(sp)
    """
    session = load_rv32(source)
    session.step()  # addi sp, sp, -16
    sp_val = read_reg(session, "sp")
    session.add_watchpoint(sp_val, 4, "write")

    step1 = session.step()
    assert len(step1["watchpoint_hits"]) == 1
    assert step1["watchpoint_hits"][0]["access_type"] == "write"

    run_res = session.run(max_steps=10)
    # lw should not trigger write watchpoint
    assert run_res["watchpoint_hit"] is None


# P3-AC-22: Step Back
def test_p3_ac_22_step_back():
    source = """
    addi a0, zero, 10
    addi a0, a0, 20
    """
    session = load_rv32(source)
    session.step()
    assert read_reg(session, "a0") == 10

    session.step()
    assert read_reg(session, "a0") == 30

    back_res = session.step_back()
    assert back_res["status"] == "ok"
    assert read_reg(session, "a0") == 10
    # step_seq is invariant
    assert session.step_seq == 2


# P3-AC-23: Reset cleanly restores state from User Baseline State
def test_p3_ac_23_reset():
    source = """
    addi a0, a0, 10
    """
    session = load_rv32(source)
    session.set_register("a0", 50)  # User edit establishing baseline
    session.step()
    assert read_reg(session, "a0") == 60

    session.reset()
    assert read_reg(session, "a0") == 50  # Restored to baseline
    assert get_pc(session) == 0x1000
