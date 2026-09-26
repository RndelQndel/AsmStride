"""Strict HTTP inputs and the browser's OpenAPI response contract."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from armstride.simulation.results import StepResult

UInt32 = Annotated[int, Field(strict=True, ge=0, lt=1 << 32)]
PositiveSize = Annotated[int, Field(strict=True, gt=0, le=1 << 32)]


class Schema(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class EmptyRequest(Schema):
    pass


class Stack(Schema):
    base: UInt32
    size: PositiveSize


class ProgramRequest(Schema):
    text: str
    profile: str = 'armv7-a-le'
    mode: str
    stack: Stack | None = None


class AssemblyRequest(ProgramRequest):
    input_kind: Literal['assembly']
    base_address: UInt32


class DisassemblyRequest(ProgramRequest):
    input_kind: Literal['disassembly']
    format: Literal['auto', 'fromelf', 'objdump', 'generic'] = 'auto'
    encoding: Literal['auto', 'words', 'bytes'] = 'auto'


LoadRequest = Annotated[AssemblyRequest | DisassemblyRequest, Field(discriminator='input_kind')]


class ValueRequest(Schema):
    value: UInt32


class RegisterRequest(ValueRequest):
    mask: UInt32 | None = None


class BytesPatch(Schema):
    address: UInt32
    bytes: Annotated[str, Field(min_length=2, pattern=r'^(?:[0-9a-fA-F]{2})+$')]


class ZeroPatch(Schema):
    address: UInt32
    zero_fill_length: PositiveSize


class RegisterValue(Schema):
    value: UInt32
    origin: Literal['default', 'user', 'execution']


class Region(Schema):
    base: UInt32
    size: PositiveSize
    kind: Literal['code', 'scratch_stack', 'user']
    permissions: Literal['rx', 'rw']


class Breakpoint(Schema):
    address: UInt32
    mode: Literal['arm', 'thumb']


class BreakpointRequest(Schema):
    address: UInt32
    mode: Literal['arm', 'thumb'] | None = None


class State(Schema):
    session_id: str
    status: Literal['empty', 'ready', 'stopped', 'unavailable']
    profile: str | None
    mode: Literal['arm', 'thumb'] | None
    baseline_pc: UInt32 | None
    step_seq: int
    registers: dict[str, RegisterValue]
    cpsr: RegisterValue | None
    flags: dict[str, bool] | None
    pc: UInt32 | None
    stack: Stack | None
    regions: list[Region]
    last_step: StepResult | None
    breakpoints: list[Breakpoint] = []


class DiagnosticView(Schema):
    code: str
    severity: Literal['info', 'warning', 'error']
    message: str
    line: int | None
    source_text: str
    context: dict[str, object]


class InstructionView(Schema):
    address: UInt32
    bytes: str
    size: int
    source_line: int | None
    source_text: str
    display_text: str
    decoded_text: str
    feature_exclusion: str | None
    mode: Literal['arm', 'thumb'] | None = None


class DataRegionView(Schema):
    address: UInt32
    size: PositiveSize
    bytes: str
    source_line: int | None


class Program(Schema):
    profile: str
    mode: Literal['arm', 'thumb']
    format: str
    source_text: str
    instructions: list[InstructionView]
    data_regions: list[DataRegionView] = []
    diagnostics: list[DiagnosticView]
    instruction_count: int
    ignored_line_count: int


class ErrorDetail(Schema):
    code: str
    message: str
    context: dict[str, object]


class ErrorEnvelope(Schema):
    error: ErrorDetail
    diagnostics: list[DiagnosticView] | None = None
    preview: list[InstructionView] | None = None


class LoadResponse(Schema):
    program: Program
    state: State


class CreateResponse(Schema):
    session_id: str
    state: State
    limits: dict[str, int]


class StepResponse(Schema):
    result: StepResult
    state: State


class RunRequest(Schema):
    step_limit: Annotated[int, Field(ge=1, le=100_000)] = 10_000
    time_limit_ms: Annotated[int, Field(ge=1, le=10_000)] = 2000


class RunResultView(Schema):
    start_step_seq: int
    end_step_seq: int
    steps_committed: int
    steps_executed: int
    stop_reason: str
    elapsed_ms: float
    breakpoint_hit: UInt32 | None
    last_step: StepResult | None = None
    last_step_result: StepResult | None = None


class RunResponse(Schema):
    run_result: RunResultView
    state: State


class StopResponse(Schema):
    signaled: bool


class MemoryCellView(Schema):
    value: int | None
    origin: Literal['code', 'stack', 'user', 'unknown']


class MemoryWindow(Schema):
    address: UInt32
    length: int
    cells: list[MemoryCellView]
