"""Unit tests for standalone pure-Python RV32I assembler (P3-FR-008, P3-FR-010)."""

import pytest

from armstride.backends.riscv_assembler import RiscvAssembler
from armstride.domain.models import DomainError


@pytest.fixture
def asm():
    return RiscvAssembler()


def test_rv32i_r_type_instructions(asm):
    source = """
    add x1, x2, x3
    sub x4, x5, x6
    sll x7, x8, x9
    slt x10, x11, x12
    sltu x13, x14, x15
    xor x16, x17, x18
    srl x19, x20, x21
    sra x22, x23, x24
    or x25, x26, x27
    and x28, x29, x30
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    assert len(res.program.instructions) == 10
    insns = res.program.instructions
    assert insns[0].decoded_text.startswith("add ")
    assert insns[1].decoded_text.startswith("sub ")
    assert insns[2].decoded_text.startswith("sll ")
    assert insns[3].decoded_text.startswith("slt ")
    assert insns[4].decoded_text.startswith("sltu ")
    assert insns[5].decoded_text.startswith("xor ")
    assert insns[6].decoded_text.startswith("srl ")
    assert insns[7].decoded_text.startswith("sra ")
    assert insns[8].decoded_text.startswith("or ")
    assert insns[9].decoded_text.startswith("and ")


def test_rv32i_i_type_instructions(asm):
    source = """
    addi x1, x2, 100
    slti x3, x4, -50
    sltiu x5, x6, 200
    xori x7, x8, 0x1f
    ori x9, x10, 0x55
    andi x11, x12, 0xaa
    slli x13, x14, 4
    srli x15, x16, 5
    srai x17, x18, 6
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    assert len(res.program.instructions) == 9


def test_rv32i_loads_and_stores(asm):
    source = """
    lb x1, 0(x2)
    lh x3, 4(x4)
    lw x5, 8(x6)
    lbu x7, 12(x8)
    lhu x9, 16(x10)
    sb x11, 20(x12)
    sh x13, 24(x14)
    sw x15, 28(x16)
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    assert len(res.program.instructions) == 8


def test_rv32i_branches_and_labels(asm):
    source = """
    start:
        beq a0, a1, forward
        bne a0, a1, backward
        blt a0, a1, forward
        bge a0, a1, backward
        bltu a0, a1, forward
        bgeu a0, a1, start
    backward:
        beq a0, a1, start
    forward:
        ret
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    assert len(res.program.instructions) == 8


def test_rv32i_upper_and_jumps(asm):
    source = """
    lui a0, 0x12345
    auipc a1, 0x1000
    jal ra, 16
    jalr zero, 0(ra)
    jalr a0, a1, 4
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    assert len(res.program.instructions) == 5


def test_rv32i_system_and_traps(asm):
    source = """
    ecall
    ebreak
    fence
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    insns = res.program.instructions
    assert insns[0].raw_bytes == bytes.fromhex("73000000")  # ecall
    assert insns[1].raw_bytes == bytes.fromhex("73001000")  # ebreak
    assert insns[2].raw_bytes == bytes.fromhex("0f000000")  # fence


def test_rv32i_pseudos_and_abi_aliases(asm):
    source = """
    nop
    mv a0, a1
    not a2, a3
    neg a4, a5
    seqz a6, a7
    snez s0, s1
    sltz s2, s3
    sgtz s4, s5
    j target
    jr ra
    ret
    target:
    li t0, 42
    li t1, 0x12345678
    call target
    """
    res = asm.assemble(source, mode="riscv32", base_address=0x1000)
    assert res.program is not None
    assert len(res.program.instructions) >= 13


def test_rv32i_golden_encodings_oracle(asm):
    # Verify bit-for-bit equivalence with golden RISC-V oracle encodings
    golden = [
        ("nop", bytes.fromhex("13000000")),
        ("addi x1, x0, 42", bytes.fromhex("9300a002")),
        ("add x3, x1, x2", bytes.fromhex("b3812000")),
        ("sub x3, x1, x2", bytes.fromhex("b3812040")),
        ("lui x1, 0x12345", bytes.fromhex("b7503412")),
        ("jal x0, 8", bytes.fromhex("6f008000")),
        ("jalr x0, 0(x1)", bytes.fromhex("67800000")),
        ("ecall", bytes.fromhex("73000000")),
        ("ebreak", bytes.fromhex("73001000")),
        ("lw x10, 4(x2)", bytes.fromhex("03254100")),
        ("sw x10, 4(x2)", bytes.fromhex("2322a100")),
        ("beq x1, x2, 8", bytes.fromhex("63842000")),
    ]
    for source, expected_bytes in golden:
        res = asm.assemble(source, mode="riscv32", base_address=0x1000)
        assert res.program is not None
        assert res.program.instructions[0].raw_bytes == expected_bytes, f"Failed for {source}: got {res.program.instructions[0].raw_bytes.hex()}, expected {expected_bytes.hex()}"


def test_rv32i_error_cases(asm):
    # Invalid register
    res = asm.assemble("add x32, x0, x0", mode="riscv32", base_address=0x1000)
    assert res.program is None
    assert res.diagnostics[0].code == "invalid_register"

    # Unrecognized instruction
    res = asm.assemble("fadd.s f0, f1, f2", mode="riscv32", base_address=0x1000)
    assert res.program is None
    assert res.diagnostics[0].code == "unsupported_instruction"

    # Unaligned base address
    res = asm.assemble("nop", mode="riscv32", base_address=0x1001)
    assert res.program is None
    assert res.diagnostics[0].code == "invalid_encoding"
