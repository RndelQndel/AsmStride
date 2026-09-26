"""JSON-compatible public Step records, independent of native and web libraries."""

from typing import Literal, TypedDict


class ValueChange[T](TypedDict):
    before: T
    after: T


class InstructionIdentity(TypedDict):
    address: int
    size: int
    source_line: int | None


class MemoryRead(TypedDict):
    address: int
    size: int
    bytes: str


class MemoryWrite(TypedDict):
    address: int
    size: int
    before_bytes: str
    after_bytes: str


class BranchResult(TypedDict):
    kind: Literal['branch', 'call', 'return', 'pc_write']
    condition: str | None
    taken: bool
    target: int | None
    fallthrough: int


class StepError(TypedDict):
    code: str
    context: dict[str, object]
    restored: bool


class StepResult(TypedDict):
    status: Literal['executed', 'failed']
    step_seq: int
    instruction: InstructionIdentity | None
    pc_before: int
    pc_after: int
    condition_passed: bool | None
    register_changes: dict[str, ValueChange[int]]
    cpsr_change: ValueChange[int] | None
    flag_changes: dict[str, ValueChange[bool]]
    memory_reads: list[MemoryRead]
    memory_writes: list[MemoryWrite]
    branch: BranchResult | None
    stop_reason: Literal['pc_not_loaded', 'invalid_pc', 'unsupported_instruction',
                         'memory_fault', 'unsupported_mode_transition', 'execution_error',
                         'backend_unavailable'] | None
    error: StepError | None
