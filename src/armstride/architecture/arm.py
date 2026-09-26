"""ARMv7-A little-endian profile values; no native execution state."""

from types import MappingProxyType

from armstride.domain.models import ADDRESS_SPACE, DomainError, Mode, ProgramImage

PROFILE = "armv7-a-le"
REGISTERS = tuple(f"r{i}" for i in range(13)) + ("sp", "lr", "pc", "cpsr")
ALIASES = MappingProxyType({"r13": "sp", "r14": "lr", "r15": "pc"})
STACK_BASE = 0x200F0000
STACK_SIZE = 0x10000
EDITABLE_FLAGS = 0xF0000000


def validate_profile(profile: str, mode: str) -> None:
    if profile != PROFILE:
        raise DomainError("unsupported_architecture", "Only armv7-a-le is supported.")
    if mode not in ("arm", "thumb"):
        raise DomainError("unsupported_mode", "Choose arm or thumb.")


def canonical_register(name: str) -> str:
    if not isinstance(name, str):
        raise DomainError("invalid_register", "Register name must be text.")
    normalized = name.lower()
    normalized = ALIASES.get(normalized, normalized)
    if normalized not in REGISTERS:
        raise DomainError("invalid_register", "Unknown ARM register.", name=name)
    return normalized


def initial_registers(mode: Mode, pc: int):
    validate_profile(PROFILE, mode)
    if type(pc) is not int or not 0 <= pc < ADDRESS_SPACE or pc % (4 if mode == "arm" else 2):
        raise DomainError("invalid_pc", "PC must be a canonical aligned address.", pc=pc)
    registers = dict.fromkeys(REGISTERS, 0)
    registers.update(sp=STACK_BASE + STACK_SIZE, pc=pc, cpsr=0x10 if mode == "arm" else 0x30)
    return MappingProxyType(registers)


def validate_pc(program: ProgramImage, pc: int) -> None:
    if type(pc) is not int or pc not in program.address_index:
        raise DomainError("invalid_pc", "PC must identify a loaded instruction start.", pc=pc)
