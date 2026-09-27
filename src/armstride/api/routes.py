"""Worker-thread routes; each complete operation and projection holds its session lock."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from armstride.api.schemas import (AssemblyRequest, Breakpoint, BreakpointRequest, BytesPatch,
    CreateResponse, ElfRequest, EmptyRequest, ErrorEnvelope, LoadRequest, LoadResponse, MemoryWindow,
    RegisterRequest, RunRequest, RunResponse, State, StepBackResponse, StepResponse, StopResponse,
    SymbolTableView, ValueRequest, WatchpointRequest, WatchpointView, ZeroPatch)
from armstride.api.sessions import IDLE_SECONDS, MAX_SESSIONS
from armstride.api.views import (diagnostic_view, instruction_view, program_view,
    state_view, symbol_entry_view)
from armstride.architecture import get_architecture
from armstride.domain.models import (MAX_ELF_FILE_BYTES, MAX_INSTRUCTIONS,
    MAX_TEXT_BYTES, DomainError)
from armstride.parser import parse
from armstride.simulation.memory import (MAX_BACKING_BYTES, MAX_INSPECTION_BYTES,
    MAX_LOGICAL_BYTES, MAX_PATCH_BYTES)

router = APIRouter(prefix='/api/sessions', responses={
    status: {'model': ErrorEnvelope} for status in (400, 403, 404, 409, 413, 415, 422, 429, 500, 503)})
LIMITS = dict(text_bytes=MAX_TEXT_BYTES, instructions=MAX_INSTRUCTIONS,
              logical_bytes=MAX_LOGICAL_BYTES, backing_bytes=MAX_BACKING_BYTES,
              patch_bytes=MAX_PATCH_BYTES, inspection_bytes=MAX_INSPECTION_BYTES,
              sessions=MAX_SESSIONS, idle_seconds=IDLE_SECONDS)


def error_response(code, message, status, *, context=None, **extra):
    return JSONResponse(dict(error=dict(code=code, message=message, context=context or {}), **extra),
                        status_code=status)


def error_status(error, request):
    if error.code == 'backend_unavailable':
        return 503 if request.url.path.endswith(('/program', '/reset')) else 409
    if error.code == 'input_limit':
        return 422 if request.method == 'GET' or error.context.get('limit') == MAX_INSTRUCTIONS else 413
    if error.code == 'elf_resource_limit_exceeded':
        return 413 if error.context.get('limit') == MAX_ELF_FILE_BYTES else 422
    if error.code in ('history_empty', 'resource_limit', 'program_not_loaded'):
        return 409
    return {'session_not_found': 404, 'session_limit': 429}.get(error.code, 422)


@router.post('', status_code=201, response_model=CreateResponse)
def create_session(body: EmptyRequest, request: Request):
    registry = request.app.state.registry
    session_id = registry.create()
    with registry.access(session_id) as entry:
        return dict(session_id=session_id, state=state_view(session_id, entry), limits=LIMITS)


@router.delete('/{session_id}', status_code=204)
def delete_session(session_id: str, request: Request):
    request.app.state.registry.delete(session_id)
    return Response(status_code=204)


@router.get('/{session_id}/state', response_model=State)
def get_state(session_id: str, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        return state_view(session_id, entry)


@router.post('/{session_id}/program', response_model=LoadResponse)
def load_program(session_id: str, body: LoadRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        arch = get_architecture(body.profile)
        if isinstance(body, ElfRequest):
            try:
                import base64
                raw_bytes = base64.b64decode(body.content_base64)
            except Exception as e:
                raise DomainError('invalid_input', f'Invalid base64 payload: {e}') from None
            if len(raw_bytes) > MAX_ELF_FILE_BYTES:
                raise DomainError('elf_resource_limit_exceeded', 'ELF file size exceeds 10 MiB limit.',
                                  limit=MAX_ELF_FILE_BYTES, actual=len(raw_bytes))
            from armstride.elf.loader import load_elf
            program, metadata, entry_pc, initial_mode = load_elf(raw_bytes, profile=body.profile)
            stack = body.stack.model_dump() if body.stack else dict(base=arch.STACK_BASE, size=arch.STACK_SIZE)
            entry.session.load(program, initial_pc=entry_pc, metadata=metadata,
                               stack_base=stack['base'], stack_size=stack['size'])
            entry.stack = stack
            from armstride.domain.models import ParseResult
            parse_res = ParseResult(program=program, records=program.instructions, diagnostics=(),
                                    selected_format='elf', data_regions=program.data_regions)
            return dict(program=program_view(parse_res, metadata=metadata), state=state_view(session_id, entry))

        # Check decoded text before parsing/assembly; JSON wire size is bounded separately.
        try:
            too_large = len(body.text) > MAX_TEXT_BYTES or len(body.text.encode('utf-8')) > MAX_TEXT_BYTES
        except UnicodeEncodeError:
            raise DomainError('invalid_input', 'Text must be valid UTF-8.') from None
        if too_large:
            raise DomainError('input_limit', 'Input exceeds 1 MiB.', limit=MAX_TEXT_BYTES)
        if isinstance(body, AssemblyRequest):
            result = request.app.state.assembler.assemble(body.text, mode=body.mode,
                profile=body.profile, base_address=body.base_address)
        else:
            result = parse(body.text, mode=body.mode, profile=body.profile,
                           format=body.format, encoding=body.encoding)
        if result.program is None:
            diagnostic = next(d for d in result.diagnostics if d.severity == 'error')
            extra = dict(diagnostics=[diagnostic_view(d) for d in result.diagnostics])
            if not isinstance(body, AssemblyRequest):
                extra['preview'] = [instruction_view(i) for i in result.records]
            # Text was bounded above; producer input_limit now means instruction count.
            return error_response(diagnostic.code, diagnostic.message,
                                  503 if diagnostic.code == 'backend_unavailable' else 422, **extra)
        stack = body.stack.model_dump() if body.stack else dict(base=arch.STACK_BASE, size=arch.STACK_SIZE)
        entry.session.load(result.program, stack_base=stack['base'], stack_size=stack['size'])
        entry.stack = stack
        return dict(program=program_view(result), state=state_view(session_id, entry))


@router.put('/{session_id}/pc', response_model=State)
def set_pc(session_id: str, body: ValueRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        entry.session.set_pc(body.value)
        return state_view(session_id, entry)


@router.put('/{session_id}/registers/{name}', response_model=State)
def set_register(session_id: str, name: str, body: RegisterRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        entry.session.set_register(name, body.value, mask=body.mask)
        return state_view(session_id, entry)


@router.put('/{session_id}/memory', response_model=State)
def patch_memory(session_id: str, body: BytesPatch | ZeroPatch, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        if isinstance(body, BytesPatch):
            if len(body.bytes) > MAX_PATCH_BYTES * 2:
                raise DomainError('input_limit', 'Patch exceeds 64 KiB.', limit=MAX_PATCH_BYTES)
            entry.session.patch_memory(body.address, bytes.fromhex(body.bytes))
        else:
            entry.session.zero_fill(body.address, body.zero_fill_length)
        return state_view(session_id, entry)


DecimalQuery = Annotated[str, Query(pattern=r'^[0-9]{1,10}$')]


@router.get('/{session_id}/memory', response_model=MemoryWindow)
def get_memory(session_id: str, address: DecimalQuery, length: DecimalQuery, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        address, length = int(address), int(length)
        cells = entry.session.inspect_memory(address, length)
        return dict(address=address, length=length,
                    cells=[dict(value=c.value, origin='stack' if c.origin == 'scratch_stack'
                                else c.origin or 'unknown') for c in cells])


@router.post('/{session_id}/step', response_model=StepResponse)
def step(session_id: str, body: EmptyRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        result = entry.session.step()
        return dict(result=result, state=state_view(session_id, entry))


@router.post('/{session_id}/reset', response_model=State)
def reset(session_id: str, body: EmptyRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        entry.session.reset()
        return state_view(session_id, entry)


@router.get('/{session_id}/breakpoints', response_model=list[Breakpoint])
def list_breakpoints(session_id: str, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        return [dict(address=bp.address, mode=bp.mode) for bp in entry.session.list_breakpoints()]


@router.post('/{session_id}/breakpoints', status_code=201, response_model=Breakpoint)
def add_breakpoint(session_id: str, body: BreakpointRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        bp = entry.session.add_breakpoint(body.address, mode=body.mode)
        return dict(address=bp.address, mode=bp.mode)


@router.delete('/{session_id}/breakpoints/{address}', status_code=204)
def remove_breakpoint(session_id: str, address: int, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        entry.session.remove_breakpoint(address)
        return Response(status_code=204)


@router.post('/{session_id}/run', response_model=RunResponse)
def run_session(session_id: str, body: RunRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        entry.stop_event.clear()
        run_res = entry.session.run(stop_event=entry.stop_event, max_steps=body.step_limit,
                                   timeout_seconds=body.time_limit_ms / 1000.0)
        return dict(run_result=run_res, state=state_view(session_id, entry))


@router.post('/{session_id}/stop', response_model=StopResponse)
def stop_session(session_id: str, body: EmptyRequest, request: Request):
    request.app.state.registry.signal_stop(session_id)
    return dict(signaled=True)


@router.get('/{session_id}/symbols', response_model=SymbolTableView)
def get_symbols(session_id: str, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        symbols = []
        if entry.session.metadata is not None:
            for entries in entry.session.metadata.symbols.by_address.values():
                for s in entries:
                    symbols.append(symbol_entry_view(s))
        return dict(symbols=symbols)


@router.get('/{session_id}/watchpoints', response_model=list[WatchpointView])
def list_watchpoints(session_id: str, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        return [dict(address=wp.address, length=wp.length, kind=wp.kind)
                for wp in entry.session.list_watchpoints()]


@router.post('/{session_id}/watchpoints', status_code=201, response_model=WatchpointView)
def add_watchpoint(session_id: str, body: WatchpointRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        wp = entry.session.add_watchpoint(body.address, length=body.length, kind=body.kind)
        return dict(address=wp.address, length=wp.length, kind=wp.kind)


@router.delete('/{session_id}/watchpoints/{address}', status_code=204)
def remove_watchpoint(session_id: str, address: int, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        entry.session.remove_watchpoint(address)
        return Response(status_code=204)


@router.post('/{session_id}/step-back', response_model=StepBackResponse)
def step_back(session_id: str, body: EmptyRequest, request: Request):
    with request.app.state.registry.access(session_id) as entry:
        res = entry.session.step_back()
        return dict(status=res['status'], restored_step_seq=res['restored_step_seq'],
                    current_step_seq=res['current_step_seq'], state_revision=res['state_revision'],
                    history_depth=res['history_depth'], state=state_view(session_id, entry))

