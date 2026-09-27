"""RV32I little-endian profile values; no native execution state."""

from types import MappingProxyType

from armstride.domain.models import ADDRESS_SPACE, DomainError, ProgramImage

PROFILE = "rv32i-le"
REGISTERS = tuple(f"x{i}" for i in range(32)) + ("pc",)
ALIASES = MappingProxyType({
    "zero": "x0",
    "ra": "x1",
    "sp": "x2",
    "gp": "x3",
    "tp": "x4",
    "t0": "x5",
    "t1": "x6",
    "t2": "x7",
    "s0": "x8",
    "fp": "x8",
    "s1": "x9",
    "a0": "x10",
    "a1": "x11",
    "a2": "x12",
    "a3": "x13",
    "a4": "x14",
    "a5": "x15",
    "a6": "x16",
    "a7": "x17",
    "s2": "x18",
    "s3": "x19",
    "s4": "x20",
    "s5": "x21",
    "s6": "x22",
    "s7": "x23",
    "s8": "x24",
    "s9": "x25",
    "s10": "x26",
    "s11": "x27",
    "t3": "x28",
    "t4": "x29",
    "t5": "x30",
    "t6": "x31",
})
ABI_NAMES = MappingProxyType({
    "x0": "zero", "x1": "ra", "x2": "sp", "x3": "gp", "x4": "tp",
    "x5": "t0", "x6": "t1", "x7": "t2", "x8": "s0", "x9": "s1",
    "x10": "a0", "x11": "a1", "x12": "a2", "x13": "a3", "x14": "a4",
    "x15": "a5", "x16": "a6", "x17": "a7", "x18": "s2", "x19": "s3",
    "x20": "s4", "x21": "s5", "x22": "s6", "x23": "s7", "x24": "s8",
    "x25": "s9", "x26": "s10", "x27": "s11", "x28": "t3", "x29": "t4",
    "x30": "t5", "x31": "t6", "pc": "pc"
})
STACK_BASE = 0x200F0000
STACK_SIZE = 0x10000


def validate_profile(profile: str, mode: str | None = None) -> None:
    if profile != PROFILE:
        raise DomainError("unsupported_architecture", "Only rv32i-le is supported by this profile.")
    if mode is not None and mode not in ("riscv32", "riscv", ""):
        raise DomainError("unsupported_mode", "RISC-V mode must be riscv32.")


def canonical_register(name: str) -> str:
    if not isinstance(name, str):
        raise DomainError("invalid_register", "Register name must be text.")
    normalized = name.lower()
    normalized = ALIASES.get(normalized, normalized)
    if normalized not in REGISTERS:
        raise DomainError("invalid_register", "Unknown RISC-V register.", name=name)
    return normalized


def initial_registers(mode: str | None, pc: int):
    validate_profile(PROFILE, mode)
    if type(pc) is not int or not 0 <= pc < ADDRESS_SPACE or pc % 4 != 0:
        raise DomainError("invalid_pc", "PC must be a 4-byte aligned address.", pc=pc)
    registers = dict.fromkeys(REGISTERS, 0)
    registers.update(x2=STACK_BASE + STACK_SIZE, pc=pc)
    registers["x0"] = 0
    return MappingProxyType(registers)


def validate_pc(program: ProgramImage, pc: int) -> None:
    if type(pc) is not int or pc not in program.address_index:
        raise DomainError("invalid_pc", "PC must identify a loaded instruction start.", pc=pc)
    if pc % 4 != 0:
        raise DomainError("unaligned_pc", "Instruction fetch address must be 4-byte aligned.", pc=pc)
