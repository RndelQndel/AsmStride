"""Program and parsing contracts. No decoder or execution library types escape here."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

Mode = Literal["arm", "thumb"]
ADDRESS_SPACE = 1 << 32
MAX_TEXT_BYTES = 1 << 20
MAX_INSTRUCTIONS = 10_000
MAX_ELF_FILE_BYTES = 10 * 1024 * 1024
MAX_LOGICAL_MEMORY_BYTES = 16 * 1024 * 1024
MAX_BACKING_PAGES_BYTES = 64 * 1024 * 1024
MAX_ELF_SEGMENTS = 32
MAX_ELF_SECTIONS = 128
MAX_WATCHPOINTS = 32
MAX_HISTORY_STEPS = 100


class DomainError(ValueError):
    def __init__(self, code: str, message: str, **context):
        super().__init__(message)
        self.code = code
        self.context = MappingProxyType(context)


def validate_range(address: int, size: int, code: str = "invalid_input") -> None:
    if (type(address) is not int or type(size) is not int or
            address < 0 or size <= 0 or address + size > ADDRESS_SPACE):
        raise DomainError(code, "Expected a nonempty range within the 32-bit address space.",
                          address=address, size=size)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    line: int | None = None
    source_text: str = ""
    related_lines: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "related_lines", tuple(self.related_lines))


@dataclass(frozen=True, slots=True)
class Breakpoint:
    address: int
    mode: Mode


@dataclass(frozen=True, slots=True)
class Watchpoint:
    address: int
    length: int = 1
    kind: Literal["read", "write", "read_write"] = "read_write"

    def __post_init__(self):
        if type(self.address) is not int or not 0 <= self.address < ADDRESS_SPACE:
            raise DomainError("invalid_watchpoint", "Watchpoint address must be an unsigned 32-bit integer.",
                              address=self.address)
        if type(self.length) is not int or not 1 <= self.length <= 4096:
            raise DomainError("invalid_watchpoint", "Watchpoint length must be between 1 and 4096 bytes.",
                              length=self.length)
        if self.address + self.length > ADDRESS_SPACE:
            raise DomainError("invalid_watchpoint", "Watchpoint range exceeds 32-bit address space.",
                              address=self.address, length=self.length)
        if self.kind not in ("read", "write", "read_write"):
            raise DomainError("invalid_watchpoint", f"Invalid watchpoint kind {self.kind}; expected read, write, or read_write.",
                              kind=self.kind)


@dataclass(frozen=True, slots=True)
class WatchpointHit:
    watchpoint: Watchpoint
    access_type: Literal["read", "write"]
    address: int
    length: int
    triggering_pc: int
    before_bytes: str | None = None
    after_bytes: str | None = None


@dataclass(frozen=True, slots=True)
class Operand:
    kind: str
    register: str | None = None
    immediate: int | None = None
    memory: tuple[str | None, str | None, int] | None = None
    shift: tuple[str, int | str] | None = None
    subtracted: bool = False

    def __post_init__(self):
        if self.memory is not None:
            object.__setattr__(self, "memory", tuple(self.memory))
        if self.shift is not None:
            object.__setattr__(self, "shift", tuple(self.shift))


@dataclass(frozen=True, slots=True)
class DecodeMetadata:
    operation: str
    condition: str | None
    operands: tuple[Operand, ...]
    groups: tuple[str, ...]
    registers_read: tuple[str, ...]
    registers_written: tuple[str, ...]
    updates_flags: bool
    writeback: bool

    def __post_init__(self):
        for name in ("operands", "groups", "registers_read", "registers_written"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class Instruction:
    address: int
    raw_bytes: bytes
    mode: Mode
    source_line: int | None
    source_text: str
    display_text: str
    decoded_text: str
    decode: DecodeMetadata
    profile: str = "armv7-a-le"
    feature_exclusion: str | None = None

    def __post_init__(self):
        if not isinstance(self.raw_bytes, bytes):
            raise TypeError("Instruction bytes must be immutable bytes.")
        validate_range(self.address, self.size, "invalid_encoding")
        if self.source_line is not None and self.source_line < 1:
            raise DomainError("invalid_input", "Source lines are one-based.")

    @property
    def size(self) -> int:
        return len(self.raw_bytes)


@dataclass(frozen=True, slots=True)
class DataRegion:
    address: int
    data: bytes
    source_line: int | None = None
    source_text: str = ""
    writable: bool = False

    def __post_init__(self):
        if not isinstance(self.data, bytes):
            raise TypeError("DataRegion data must be immutable bytes.")
        validate_range(self.address, self.size, "invalid_encoding")
        if self.source_line is not None and self.source_line < 1:
            raise DomainError("invalid_input", "Source lines are one-based.")

    @property
    def size(self) -> int:
        return len(self.data)


def program_conflicts(
    instructions: tuple[Instruction, ...],
    data_regions: tuple[DataRegion, ...] = (),
) -> tuple[Diagnostic, ...]:
    diagnostics = []
    items = []
    for inst in instructions:
        items.append((inst.address, inst.size, True, inst.source_line, inst.source_text))
    for dr in data_regions:
        items.append((dr.address, dr.size, False, dr.source_line, dr.source_text))
    items.sort(key=lambda x: x[0])

    starts = {}
    previous = None
    for addr, size, is_inst, s_line, s_text in items:
        duplicate = starts.get(addr)
        conflict = duplicate or (previous if previous and addr < previous[0] + previous[1] else None)
        if conflict:
            c_addr, c_size, c_is_inst, c_line, c_text = conflict
            if duplicate:
                code = "duplicate_instruction_address" if (is_inst or c_is_inst) else "duplicate_address"
            else:
                code = "overlapping_instructions" if (is_inst or c_is_inst) else "overlapping_data"
            related = tuple(line for line in (c_line, s_line) if line is not None)
            diagnostics.append(Diagnostic(
                "error", code, "Address ranges conflict.", s_line, s_text, related
            ))
        starts.setdefault(addr, (addr, size, is_inst, s_line, s_text))
        if previous is None or addr + size > previous[0] + previous[1]:
            previous = (addr, size, is_inst, s_line, s_text)
    return tuple(diagnostics)


def instruction_conflicts(instructions: tuple[Instruction, ...]) -> tuple[Diagnostic, ...]:
    return program_conflicts(instructions, ())


@dataclass(frozen=True, slots=True)
class ProgramImage:
    instructions: tuple[Instruction, ...]
    mode: Mode
    source_text: str
    format: str
    profile: str = "armv7-a-le"
    data_regions: tuple[DataRegion, ...] = ()
    address_index: Mapping[int, Instruction] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        ordered = tuple(sorted(self.instructions, key=lambda instruction: instruction.address))
        if not ordered:
            raise DomainError("empty_program", "A program needs at least one instruction.")
        if len(ordered) > MAX_INSTRUCTIONS:
            raise DomainError("input_limit", "Too many instructions.", limit=MAX_INSTRUCTIONS)
        if self.mode not in ("arm", "thumb") or any(
                instruction.mode not in ("arm", "thumb") or instruction.profile != self.profile for instruction in ordered):
            raise DomainError("invalid_input", "Instructions must share the program profile and have valid modes.")
        ordered_data = tuple(sorted(self.data_regions, key=lambda region: region.address))
        conflicts = program_conflicts(ordered, ordered_data)
        if conflicts:
            raise DomainError(conflicts[0].code, conflicts[0].message,
                              related_lines=conflicts[0].related_lines)
        object.__setattr__(self, "instructions", ordered)
        object.__setattr__(self, "data_regions", ordered_data)
        object.__setattr__(self, "address_index", MappingProxyType({i.address: i for i in ordered}))

    @property
    def start_pc(self) -> int:
        return self.instructions[0].address


@dataclass(frozen=True, slots=True)
class ParseResult:
    program: ProgramImage | None
    records: tuple[Instruction, ...]
    diagnostics: tuple[Diagnostic, ...]
    selected_format: str
    data_regions: tuple[DataRegion, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "data_regions", tuple(self.data_regions))

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def load_success(self) -> bool:
        return self.program is not None

    @property
    def ignored_lines(self) -> tuple[int, ...]:
        return tuple(d.line for d in self.diagnostics if d.code == "ignored_line" and d.line is not None)

    @property
    def ignored_line_count(self) -> int:
        return len(self.ignored_lines)


@dataclass(frozen=True, slots=True)
class SymbolEntry:
    address: int
    name: str
    size: int = 0
    kind: str = "label"  # "func", "object", "label", etc.
    binding: str = "global"  # "global", "local", "weak"
    section: str | None = None


@dataclass(frozen=True, slots=True)
class SymbolTable:
    by_address: Mapping[int, tuple[SymbolEntry, ...]] = field(default_factory=dict)
    by_name: Mapping[str, SymbolEntry] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "by_address", MappingProxyType(dict(self.by_address)))
        object.__setattr__(self, "by_name", MappingProxyType(dict(self.by_name)))


@dataclass(frozen=True, slots=True)
class LineEntry:
    address: int
    file_path: str
    line_number: int
    column: int = 0


@dataclass(frozen=True, slots=True)
class LineTable:
    entries: tuple[LineEntry, ...] = ()
    by_address: Mapping[int, LineEntry] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "by_address", MappingProxyType(dict(self.by_address)))


@dataclass(frozen=True, slots=True)
class ElfInfo:
    entry_point: int
    initial_mode: Mode
    segment_count: int
    section_count: int
    is_stripped: bool
    has_dwarf: bool


@dataclass(frozen=True, slots=True)
class ProgramMetadata:
    symbols: SymbolTable = field(default_factory=SymbolTable)
    lines: LineTable = field(default_factory=LineTable)
    elf_info: ElfInfo | None = None


@dataclass(frozen=True, slots=True)
class ExecutionHistoryEntry:
    step_seq: int
    registers: Mapping[str, int]
    cpsr: int
    mode: Mode
    pc: int
    register_origins: Mapping[str, str]
    modified_memory: Mapping[int, int]
    last_step: Mapping[str, object] | None = None

