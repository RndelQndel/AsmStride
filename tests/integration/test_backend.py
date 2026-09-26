"""Native transaction boundaries beyond the fixed numeric golden cases."""

import pytest

pytestmark = pytest.mark.native
import unicorn as uc

from armstride.architecture.decode import ArmDecoder
from armstride.domain.models import DomainError, ProgramImage
from armstride.simulation import SimulationSession


def program(*records, mode='arm'):
    decoder = ArmDecoder(mode)
    return ProgramImage(tuple(decoder.decode(address, bytes.fromhex(encoded), line, '', '')
                        for line, (address, encoded) in enumerate(records, 1)), mode, '', 'generic')


@pytest.fixture
def session():
    instance = SimulationSession()
    yield instance
    instance.close()


@pytest.mark.parametrize('address', [0x2800, 0x2FFC], ids=['mapped-hole', 'unmapped-page'])
@pytest.mark.parametrize('encoded,mode,base,push,store', [
    ('0300b4e8', 'arm', 'r4', False, False),
    ('0300a4e8', 'arm', 'r4', False, True),
    ('03002de9', 'arm', 'sp', True, True),
    ('0300bde8', 'arm', 'sp', False, False),
    ('03b4', 'thumb', 'sp', True, True),
    ('03bc', 'thumb', 'sp', False, False),
    ('03cc', 'thumb', 'r4', False, False),
    ('03c4', 'thumb', 'r4', False, True),
])
def test_late_fault_full_native_rollback_and_repair(session, address, encoded, mode, base, push, store):
    image = program((0x1000, encoded), mode=mode)
    session.load(image)
    session.set_register(base, address + 8 if push else address)
    session.set_register('r0', 0xAABBCCDD)
    session.set_register('r1', 0xEEFF0011)
    session.patch_memory(address, bytes.fromhex('11223344'))
    before = session.runtime
    pages = session._backend._pages()
    result = session.step()
    assert result['error']['code'] == 'unmapped_memory_access'
    assert result['error']['restored'] is True
    assert result['memory_reads'] == result['memory_writes'] == []
    assert session.runtime == session.baseline == before
    assert session._backend._pages() == pages
    assert session._backend._registers() == dict(before.registers)
    # Repeating the fault uses the restored backend, without an intervening rebuild.
    assert session.step() == result
    session.patch_memory(address + 4, bytes.fromhex('55667788'))
    repaired = session.baseline
    assert session.step()['status'] == 'executed'
    expected_bytes = 'ddccbbaa1100ffee' if store else '1122334455667788'
    assert bytes(cell.value for cell in session.inspect_memory(address, 8)).hex() == expected_bytes
    assert session.runtime.registers[base] == (address if push else address + 8)
    if not store:
        assert session.runtime.registers['r0'] == 0x44332211
        assert session.runtime.registers['r1'] == 0x88776655
    clean = SimulationSession()
    try:
        clean.load(image)
        for name, value in repaired.registers.items():
            clean.set_register(name, value)
        clean.patch_memory(address, bytes.fromhex('1122334455667788'))
        assert clean.step()['status'] == 'executed'
        assert clean.runtime.registers == session.runtime.registers
        assert clean.runtime.memory == session.runtime.memory
        assert clean._backend._pages() == session._backend._pages()
    finally:
        clean.close()


@pytest.mark.parametrize('mode,records,registers,target', [
    ('arm', [(0x1FFC, '0100a0e3')], {}, 0x2000),
    ('thumb', [(0x1FFE, '0120')], {}, 0x2000),
    ('arm', [(0x1000, '13ff2fe1')], {'r3': 0x9000}, 0x9000),
    ('thumb', [(0x1000, '1847')], {'r3': 0x9001}, 0x9000),
    ('thumb', [(0x1000, '1847'), (0x1002, '01f10201')], {'r3': 0x1005}, 0x1004),
    ('arm', [(0xFFFFFFFC, '0100a0e3')], {}, 0),
])
def test_retired_destination_is_not_executed(session, mode, records, registers, target):
    session.load(program(*records, mode=mode))
    for name, value in registers.items():
        session.set_register(name, value)
    result = session.step()
    assert result['status'] == 'executed', result
    assert result['pc_after'] == target
    assert result['stop_reason'] == 'pc_not_loaded'
    assert session.step_seq == 1
    before = session.runtime
    assert session.step()['error']['code'] == 'invalid_pc'
    assert session.runtime == before
    assert session.step_seq == 1


@pytest.mark.parametrize('fault', ['timeout', 'native-error', 'engine-rejection', 'second-instruction', 'initial-fetch'])
def test_native_failure_is_atomic(session, monkeypatch, fault):
    session.load(program((0x1000, '0100a0e3'), (0x1004, '0200a0e3')))
    backend = session._backend
    engine = backend._engine
    original_start, original_query = engine.emu_start, engine.query

    def start(begin, until, timeout, count):
        if fault == 'initial-fetch':
            return original_start(0x9000, until, timeout=timeout, count=count)
        original_start(begin, until, timeout=timeout, count=0 if fault == 'second-instruction' else count)
        if fault == 'native-error':
            raise uc.UcError(uc.UC_ERR_EXCEPTION)
        if fault == 'engine-rejection':
            raise uc.UcError(uc.UC_ERR_INSN_INVALID)

    monkeypatch.setattr(engine, 'emu_start', start)
    if fault == 'timeout':
        monkeypatch.setattr(engine, 'query', lambda query: 1 if query == uc.UC_QUERY_TIMEOUT else original_query(query))
    before, pages = session.runtime, backend._pages()
    monkeypatch.setattr(engine, 'emu_start', start)
    result = session.step()
    assert result['error']['code'] == ('execution_timeout' if fault == 'timeout' else
                                     'unsupported_instruction' if fault == 'engine-rejection' else 'execution_failure')
    assert result['error']['restored'] is True
    assert session.runtime == before
    assert backend._registers() == dict(before.registers)
    assert backend._pages() == pages
    assert session.step_seq == 0


def test_rollback_failure_requires_reset(session, monkeypatch):
    session.load(program((0x1000, '000094e5')))
    session.set_register('r4', 0x2800)
    before = session.runtime

    def fail_restore(*args):
        raise uc.UcError(uc.UC_ERR_RESOURCE)

    monkeypatch.setattr(session._backend, '_restore', fail_restore)
    result = session.step()
    assert result['error']['code'] == 'backend_unavailable'
    assert result['error']['restored'] is False
    assert session.status == 'unavailable'
    assert session.runtime == before
    for mutation in (session.step, lambda: session.set_register('r0', 7), lambda: session.patch_memory(0x2800, b'1234')):
        with pytest.raises(DomainError, match='Reset or reload'):
            mutation()
    session.reset()
    assert session.status == 'ready'
    session.patch_memory(0x2800, b'1234')
    assert session.step()['status'] == 'executed'



def test_real_native_timeout_restores_all_state(session, monkeypatch):
    session.load(program((0x1000, '010090e2'), (0x1004, 'fdffffea')))
    backend = session._backend
    engine = backend._engine
    original_add, original_start = engine.hook_add, engine.emu_start
    backend.timeout_us = 10_000

    def add_hook(kind, callback, *args, **kwargs):
        if kind == uc.UC_HOOK_CODE:
            entered = False

            def first_entry(*callback_args):
                nonlocal entered
                if not entered:
                    entered = True
                    callback(*callback_args)

            return original_add(kind, first_entry, *args, **kwargs)
        return original_add(kind, callback, *args, **kwargs)

    # Deliberately disable the two instruction limits to reach the real deadline.
    monkeypatch.setattr(engine, 'hook_add', add_hook)
    monkeypatch.setattr(engine, 'emu_start', lambda begin, until, timeout, count:
                        original_start(begin, until, timeout=timeout, count=0))
    before, pages = session.runtime, backend._pages()
    result = session.step()
    assert result['error']['code'] == 'execution_timeout'
    assert session.runtime == before
    assert backend._registers() == dict(before.registers)
    assert backend._pages() == pages


def test_rollback_removes_tentative_mapping(session, monkeypatch):
    session.load(program((0x1000, '0100a0e3')))
    backend = session._backend
    attempt = backend._attempt

    def failing_attempt(*args):
        attempt(*args)
        backend._engine.mem_map(0x9000, 4096)
        backend._engine.mem_write(0x9000, b'changed')
        raise DomainError('execution_failure', 'Injected fault after mapping.')

    before, pages = session.runtime, backend._pages()
    monkeypatch.setattr(backend, '_attempt', failing_attempt)
    assert session.step()['error']['restored'] is True
    assert session.runtime == before
    assert backend._pages() == pages
    assert backend._registers() == dict(before.registers)


@pytest.mark.parametrize('encoded,mode,base,contents', [
    ('0180bde8', 'arm', 'sp', '1122334400900000'),  # POP {r0, pc}
    ('0080b4e8', 'arm', 'r4', '00900000'),          # LDM r4!, {pc}
    ('00f094e5', 'arm', 'r4', '00900000'),          # LDR pc, [r4]
])
def test_external_pc_load_retirement(session, encoded, mode, base, contents):
    session.load(program((0x1000, encoded), mode=mode))
    session.set_register(base, 0x2800)
    session.patch_memory(0x2800, bytes.fromhex(contents))
    result = session.step()
    assert result['status'] == 'executed', result
    assert result['pc_after'] == 0x9000
    assert result['stop_reason'] == 'pc_not_loaded'
    assert result['memory_reads'][-1]['bytes'] == '00900000'


def test_bx_pc_reports_pipeline_target_and_detached_result(session):
    session.load(program((0x1000, '1fff2fe1'), (0x1008, '0100a0e3')))
    result = session.step()
    assert result['status'] == 'executed'
    assert result['branch']['target'] == result['pc_after'] == 0x1008
    assert session.runtime.registers['r0'] == 0
    result['branch']['target'] = 0
    assert session.last_step['branch']['target'] == 0x1008


@pytest.mark.parametrize('method', ['mem_map', 'mem_write', 'reg_write'])
def test_native_initialization_failure_preserves_existing_engine(session, monkeypatch, method):
    session.load(program((0x1000, '0100a0e3')))
    before, baseline, backend = session.runtime, session.baseline, session._backend
    original = getattr(uc.Uc, method)

    def fail_candidate(engine, *args, **kwargs):
        if engine is not backend._engine:
            raise uc.UcError(uc.UC_ERR_RESOURCE)
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(uc.Uc, method, fail_candidate)
    with pytest.raises(DomainError) as caught:
        session.set_register('r1', 7)
    assert caught.value.code == 'backend_unavailable'
    assert session.runtime == before
    assert session.baseline == baseline
    assert session._backend is backend
    assert session.step()['status'] == 'executed'
