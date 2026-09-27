"""Execute fixed Phase 1 expectations against the production engine."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.native

from armstride.architecture.decode import ArmDecoder
from armstride.domain.models import ProgramImage
from armstride.simulation.session import SimulationSession

CASES = json.loads((Path(__file__).parents[1] / 'golden/cases.json').read_text())


def program_for(case):
    decoder = ArmDecoder(case['mode'])
    instructions = tuple(decoder.decode(record['address'], bytes.fromhex(record['bytes']),
                        record['source_line'], record['assembly'], record['assembly'])
                         for record in case['program'])
    return ProgramImage(instructions, case['mode'], '', 'generic')


def memory_bytes(state):
    return {str(region.address + offset): value for region in state.memory.regions
            for offset, value in enumerate(region.raw_bytes)}


def delta(before, after):
    return {name: dict(before=before.get(name), after=after.get(name)) for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)}


def subset(expected, actual):
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            subset(value, actual[key])
    else:
        assert actual == expected


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_golden(case):
    session = SimulationSession()
    try:
        session.load(program_for(case))
        for name, value in case['initial']['registers'].items():
            session.set_register(name, value)
        for patch in case['initial']['memory']:
            session.patch_memory(patch['address'], bytes.fromhex(patch['bytes']))
        for action in case['actions']:
            before = [session.runtime, session.baseline]
            arguments = dict(action['arguments'])
            if action['op'] == 'patch_memory':
                arguments['raw_bytes'] = bytes.fromhex(arguments.pop('bytes'))
            result = getattr(session, action['op'])(**arguments)
            expected = action['expect']
            assert session.step_seq == expected['step_seq']
            for key, previous, current in zip(('runtime', 'baseline'), before, (session.runtime, session.baseline)):
                assert delta(dict(previous.registers), dict(current.registers)) == expected[key]['register_changes']
                assert delta(memory_bytes(previous), memory_bytes(current)) == expected[key]['memory_changes']
            if action['op'] == 'step':
                expected_result = expected['result']
                if expected_result['error'] is not None:
                    subset(expected_result['error'], result['error'])
                    result = result | {'error': expected_result['error']}
                compare_result = dict(result)
                if 'executed' not in expected_result:
                    compare_result.pop('executed', None)
                if 'it_context' not in expected_result:
                    compare_result.pop('it_context', None)
                if 'watchpoint_hits' not in expected_result:
                    compare_result.pop('watchpoint_hits', None)
                assert compare_result == expected_result
            else:
                assert session.last_step is None
    finally:
        session.close()
