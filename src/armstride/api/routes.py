"""Worker-thread routes; each complete operation and projection holds its session lock."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from armstride.api.schemas import (AssemblyRequest, BytesPatch, CreateResponse, EmptyRequest, ErrorEnvelope,
    LoadRequest, LoadResponse, MemoryWindow, RegisterRequest, State, StepResponse, ValueRequest, ZeroPatch)
from armstride.api.sessions import IDLE_SECONDS, MAX_SESSIONS
from armstride.api.views import diagnostic_view, instruction_view, program_view, state_view
from armstride.architecture.arm import STACK_BASE, STACK_SIZE
from armstride.domain.models import MAX_INSTRUCTIONS, MAX_TEXT_BYTES, DomainError
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
    return {'session_not_found': 404, 'session_limit': 429, 'program_not_loaded': 409,
            'resource_limit': 409}.get(error.code, 422)


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
        stack = body.stack.model_dump() if body.stack else dict(base=STACK_BASE, size=STACK_SIZE)
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
