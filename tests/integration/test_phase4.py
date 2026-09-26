"""Independent numeric expectations for core result and computed-flow coverage.

Encodings are checked by GNU as and Clang in verify_encodings.py. Expectations
are declared in phase4.json, never captured from the engine under test.
"""

import json
from pathlib import Path

import pytest

from armstride.simulation import SimulationSession
from tests.integration.test_golden import program_for, memory_bytes, delta
from tests.integration.test_backend import program

pytestmark = pytest.mark.native
CASES = json.loads((Path(__file__).parents[1] / 'golden/phase4.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_phase4_result(case):
    session = SimulationSession()
    try:
        session.load(program_for(case))
        for name, value in case['initial'].items():
            session.set_register(name, value)
        for patch in case['memory']:
            session.patch_memory(patch['address'], bytes.fromhex(patch['bytes']))
        before = session.runtime
        expected = dict(before.registers) | case['expected']
        result = session.step()
        assert result['status'] == 'executed', result
        assert dict(session.runtime.registers) == expected
        assert session.baseline == before
        assert memory_bytes(session.runtime) == memory_bytes(before)
        differences = delta(dict(before.registers), expected)
        assert result['cpsr_change'] == differences.pop('cpsr', None)
        assert result['register_changes'] == differences
        before_flags = {name: bool(before.registers['cpsr'] & 1 << bit) for name, bit in zip('nzcv', (31, 30, 29, 28))}
        after_flags = {name: bool(expected['cpsr'] & 1 << bit) for name, bit in zip('nzcv', (31, 30, 29, 28))}
        assert result['flag_changes'] == delta(before_flags, after_flags)
        assert result['branch'] == case['branch']
        assert result['condition_passed'] == case['condition_passed']
        assert result['memory_reads'] == case['reads']
        assert result['memory_writes'] == []
        assert result['error'] is None
        assert result['stop_reason'] == 'pc_not_loaded'
        assert result['step_seq'] == session.step_seq == 1
        for name, value in expected.items():
            origin = 'execution' if value != before.registers[name] else before.register_origins[name]
            assert session.runtime.register_origins[name] == origin
        assert json.loads(json.dumps(result)) == session.last_step
        after = session.runtime
        assert session.step()['stop_reason'] == 'invalid_pc'
        assert session.runtime == after
        assert session.step_seq == 1
    finally:
        session.close()


def test_thumb_stack_prologue_and_epilogue_on_user_stack():
    session = SimulationSession()
    try:
        session.load(program((0x1000, '01b5'), (0x1002, '82b0'),
                             (0x1004, '02b0'), (0x1006, '06bc'), mode='thumb'))
        session.set_register('sp', 0x2810)
        session.set_register('r0', 0x44332211)
        session.set_register('lr', 0x88776655)
        session.zero_fill(0x2800, 16)
        baseline = session.baseline
        for sp in (0x2808, 0x2800, 0x2808, 0x2810):
            assert session.step()['status'] == 'executed'
            assert session.runtime.registers['sp'] == sp
        assert session.runtime.registers['r1'] == 0x44332211
        assert session.runtime.registers['r2'] == 0x88776655
        assert session.runtime.memory.read(0x2808, 8).hex() == '1122334455667788'
        assert session.baseline == baseline
        session.reset()
        assert session.runtime == baseline
        assert session.last_step is None
        assert session.step_seq == 4
    finally:
        session.close()


def test_thumb_load_partial_repair_and_retry():
    session = SimulationSession()
    try:
        session.load(program((0x1000, '2068'), mode='thumb'))
        session.set_register('r4', 0x2800)
        for patch in (b'', b'\x11', bytes.fromhex('11223344')):
            if patch:
                session.patch_memory(0x2800, patch)
            before = session.runtime
            result = session.step()
            if len(patch) < 4:
                assert result['error']['code'] == 'unmapped_memory_access'
                assert result['error']['context']['address'] == 0x2800
                assert result['error']['context']['size'] == 4
                assert result['memory_reads'] == []
                assert session.runtime == before
                assert session.step_seq == 0
            else:
                assert result['status'] == 'executed'
                assert session.runtime.registers['r0'] == 0x44332211
                assert session.step_seq == 1
            assert session.inspect_memory(0x2804, 1)[0].value is None
    finally:
        session.close()


@pytest.mark.parametrize('mode,encoded', [('arm', '0300a4e8'), ('thumb', '03c4')])
def test_committed_writes_include_unchanged_values(mode, encoded):
    session = SimulationSession()
    try:
        session.load(program((0x1000, encoded), mode=mode))
        session.set_register('r4', 0x2800)
        session.set_register('r0', 0x44332211)
        session.set_register('r1', 0)
        session.patch_memory(0x2800, bytes(8))
        baseline = session.baseline
        result = session.step()
        assert result['status'] == 'executed'
        assert result['memory_writes'] == [
            dict(address=0x2800, size=4, before_bytes='00000000', after_bytes='11223344'),
            dict(address=0x2804, size=4, before_bytes='00000000', after_bytes='00000000')]
        assert delta(memory_bytes(baseline), memory_bytes(session.runtime)) == {
            str(0x2800 + offset): dict(before=0, after=value)
            for offset, value in enumerate(bytes.fromhex('11223344'))}
        assert session.runtime.register_origins['r1'] == 'user'
        assert session.baseline == baseline
        # Explicit same-value edit clears execution highlights and becomes Reset evidence.
        session.set_register('r4', 0x2808)
        assert session.last_step is None
        session.reset()
        assert session.runtime.registers['r4'] == 0x2808
        assert session.runtime.memory.read(0x2800, 8) == bytes(8)
    finally:
        session.close()
