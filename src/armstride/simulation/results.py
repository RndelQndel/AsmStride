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


class ITContext(TypedDict):
    block_index: int
    block_total: int
    condition: str
    passed: bool


class WatchpointHitView(TypedDict):
    address: int
    size: int
    access_type: Literal['read', 'write']
    triggering_pc: int
    watchpoint_address: int
    watchpoint_length: int
    watchpoint_kind: str
    before_bytes: str | None
    after_bytes: str | None


class StepResult(TypedDict):
    status: Literal['executed', 'failed']
    executed: bool
    step_seq: int
    instruction: InstructionIdentity | None
    pc_before: int
    pc_after: int
    condition_passed: bool | None
    it_context: ITContext | None
    register_changes: dict[str, ValueChange[int]]
    cpsr_change: ValueChange[int] | None
    flag_changes: dict[str, ValueChange[bool]]
    memory_reads: list[MemoryRead]
    memory_writes: list[MemoryWrite]
    branch: BranchResult | None
    watchpoint_hits: list[WatchpointHitView]
    stop_reason: Literal['pc_not_loaded', 'invalid_pc', 'unsupported_instruction',
                         'memory_fault', 'unsupported_mode_transition', 'mode_mismatch',
                         'non_executable_target', 'invalid_it_block_entry',
                         'breakpoint', 'watchpoint', 'user_stop', 'step_limit', 'time_limit',
                         'execution_error', 'backend_unavailable'] | None
    error: StepError | None

