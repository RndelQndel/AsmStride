"""Both input producers run through the unchanged core and fixed golden oracle."""

from copy import deepcopy

import pytest

from armstride.backends.keystone import KeystoneAssembler
from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation import SimulationSession
from tests.integration import test_golden as golden
from tests.integration import test_phase4 as phase4
from tests.simulation.test_session import checkpoint

pytestmark = pytest.mark.native
ASSEMBLER = KeystoneAssembler()
CASES = [case for case in golden.CASES if case['id'] in ('GE-01', 'GE-06', 'GE-10', 'GE-15', 'GE-16')]


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
@pytest.mark.parametrize('path', ['assembly', 'objdump', 'generic'])
def test_input_paths_against_unchanged_golden_cpu_expectations(case, path, monkeypatch):
    source = '\n'.join(i['assembly'] for i in case['program'])
    assembled = ASSEMBLER.assemble(source, mode=case['mode'], base_address=case['program'][0]['address'])
    assert assembled.load_success, assembled.diagnostics
    listing = '\n'.join(f"{i['address']:x}: {bytes.fromhex(i['bytes']).hex(' ')} {i['assembly']}"
                        for i in case['program'])
    imported = parse(listing, mode=case['mode'], format='generic' if path == 'assembly' else path,
                     encoding='bytes')
    assert imported.load_success
    signature = lambda program: tuple((i.address, i.raw_bytes, i.size) for i in program.instructions)
    assert signature(assembled.program) == signature(imported.program)
    selected = assembled.program if path == 'assembly' else imported.program
    # Only location metadata differs; all recorded CPU/memory/results remain the oracle.
    expected_case = deepcopy(case)
    if path == 'assembly':
        for action in expected_case['actions']:
            if action['op'] == 'step':
                action['expect']['result']['instruction']['source_line'] = None
    monkeypatch.setattr(golden, 'program_for', lambda case: selected)
    golden.test_golden(expected_case)


def test_thumb_literal_at_halfword_origin_uses_existing_phase4_oracle(monkeypatch):
    case = next(case for case in phase4.CASES if case['id'] == 'P4-thumb-literal')
    result = ASSEMBLER.assemble('ldr r0,[pc,#0]', mode='thumb', base_address=0x1002)
    assert result.raw_bytes.hex() == case['program'][0]['bytes']
    monkeypatch.setattr(phase4, 'program_for', lambda case: result.program)
    phase4.test_phase4_result(case)


@pytest.mark.parametrize('mode,source,pcs', [
    ('arm', 'b done\nmov r0,#0\ndone: mov r0,#1', (0x1008, 0x100C)),
    ('thumb', 'b done\nmovs r0,#0\ndone: movs r0,#1', (0x1004, 0x1006)),
])
def test_label_branch_uses_same_session(mode, source, pcs):
    result = ASSEMBLER.assemble(source, mode=mode, base_address=0x1000)
    session = SimulationSession()
    try:
        session.load(result.program)
        baseline = session.baseline
        assert session.step()['pc_after'] == pcs[0]
        assert session.runtime.registers['r0'] == 0
        assert session.step()['pc_after'] == pcs[1]
        assert session.runtime.registers['r0'] == 1
        assert session.baseline == baseline
        session.reset()
        assert session.runtime == baseline and session.step_seq == 2
    finally:
        session.close()


@pytest.mark.parametrize('failure', ['syntax', 'mode', 'decode', 'stack', 'backend'])
def test_source_failure_preserves_existing_experiment(failure, monkeypatch):
    session = SimulationSession()
    try:
        session.load(parse('1000: E2800001 add r0,r0,#1', mode='arm').program)
        session.set_register('r0', 5)
        session.patch_memory(0x2800, b'1234')
        assert session.step()['status'] == 'executed'
        before, backend = checkpoint(session), session._backend
        source = {'syntax': 'mov r0,#1\nbad_instruction', 'mode': '.thumb\nmovs r0,#1'}.get(
            failure, 'mov r0,#7')
        if failure == 'decode':
            monkeypatch.setattr('armstride.backends.keystone.ks.Ks.asm',
                                lambda *args, **kwargs: (b'\xff', 1))
        result = ASSEMBLER.assemble(source, mode='arm', base_address=0x200F0000 if failure == 'stack' else 0x4000)
        if failure in ('stack', 'backend'):
            assert result.load_success
            if failure == 'backend':
                def reject_candidate(*args):
                    raise DomainError('backend_unavailable', 'Injected candidate failure.')
                monkeypatch.setattr(session, '_backend_factory', reject_candidate)
            with pytest.raises(DomainError):
                session.load(result.program)
        else:
            assert not result.load_success and result.raw_bytes == b''
            assert result.diagnostics[0].severity == 'error'
        assert checkpoint(session) == before
        assert session._backend is backend
        # The original native engine is still usable after rejected replacement.
        monkeypatch.undo()
        session.reset()
        assert session.step()['status'] == 'executed'
        assert session.runtime.registers['r0'] == 6
    finally:
        session.close()


@pytest.mark.parametrize('mode,source,code', [
    ('arm', 'svc #0', 'unsupported_instruction'),
    ('thumb', 'it eq\nmoveq r0,r1', 'unsupported_instruction'),
    ('arm', 'bx r0', 'unsupported_mode_transition'),
])
def test_existing_feature_and_interworking_rejection(mode, source, code):
    result = ASSEMBLER.assemble(source, mode=mode, base_address=0x1000)
    session = SimulationSession()
    try:
        session.load(result.program)
        session.set_register('r0', 0x1001)
        before = session.runtime
        step = session.step()
        assert step['status'] == 'failed' and step['error']['code'] == code
        assert session.runtime == session.baseline == before
        assert session.step_seq == 0
    finally:
        session.close()
