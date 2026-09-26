"""Session transaction tests independent of native engine availability.

The scripted backend tests orchestration, never ARM instruction semantics.
Real instruction outcomes are verified separately in tests/integration.
"""

from dataclasses import replace

import pytest

from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation import SimulationSession, StepResult
from armstride.simulation.state import ExecutionOutcome, MachineState


class ScriptedBackend:
    def __init__(self, state):
        self.state = state
        self.closed = False
        self.outcome = ExecutionOutcome(state, (), ())
        self.error = None

    def execute_one(self, instruction, state):
        assert not self.closed
        assert state.registers == self.state.registers
        assert state.memory == self.state.memory
        if self.error is not None:
            raise self.error
        self.state = self.outcome.state
        return self.outcome

    def close(self):
        self.closed = True


class BackendFactory:
    def __init__(self):
        self.created = []
        self.fail = False

    def __call__(self, program, state):
        if self.fail:
            raise DomainError('backend_unavailable', 'Injected candidate failure.')
        candidate = ScriptedBackend(state)
        self.created.append(candidate)
        return candidate


@pytest.fixture
def image():
    return parse('0x1000: E1A00000 MOV r0,r0\n0x1004: E1A00000 MOV r0,r0', mode='arm').program


@pytest.fixture
def session(image):
    factory = BackendFactory()
    instance = SimulationSession(factory)
    instance.load(image)
    yield instance, factory
    instance.close()


def checkpoint(session):
    return (session.program, session.runtime, session.baseline, session.last_step, session.step_seq, session.status)


def scripted_step(session, factory, **registers):
    current = session.runtime
    candidate = MachineState(dict(current.registers) | registers, current.memory)
    factory.created[-1].outcome = ExecutionOutcome(candidate, (), ())
    return session.step()


def test_load_defaults_and_empty_session(image):
    factory = BackendFactory()
    session = SimulationSession(factory)
    assert session.status == 'empty'
    assert session.snapshot() is None
    for operation in (session.step, session.reset, lambda: session.set_pc(0x1000)):
        with pytest.raises(DomainError) as caught:
            operation()
        assert caught.value.code == 'program_not_loaded'
    session.load(image)
    assert session.status == 'ready'
    assert session.runtime == session.baseline
    assert session.runtime.registers['pc'] == 0x1000
    assert session.runtime.registers['sp'] == 0x20100000
    assert session.runtime.registers['cpsr'] == 0x10
    assert session.runtime.memory.inspect(0x2800, 1)[0].value is None
    session.close()
    assert factory.created[-1].closed


def test_edits_preserve_baseline_write_set_and_reset(session):
    instance, factory = session
    instance.patch_memory(0x2800, bytes(4))
    initial = instance.baseline
    current = MachineState(dict(instance.runtime.registers) | {'r0': 9, 'pc': 0x1004},
                           instance.runtime.memory.patch(0x2800, bytes.fromhex('11223344')))
    factory.created[-1].outcome = ExecutionOutcome(current, (), ())
    assert instance.step()['status'] == 'executed'
    instance.set_register('r1', 7)
    instance.patch_memory(0x2801, b'\xaa')
    instance.set_pc(0x1004)
    assert instance.baseline.registers['r0'] == initial.registers['r0'] == 0
    assert instance.runtime.registers['r0'] == 9
    assert instance.runtime.memory.read(0x2800, 4).hex() == '11aa3344'
    assert instance.baseline.memory.read(0x2800, 4).hex() == '00aa0000'
    instance.reset()
    assert instance.runtime == instance.baseline
    assert instance.runtime.registers['r1'] == 7
    assert instance.runtime.registers['pc'] == 0x1004
    assert instance.step_seq == 1
    assert instance.last_step is None
    assert all(backend.closed for backend in factory.created[:-1])


def test_masked_flags_apply_independently(session):
    instance, factory = session
    instance.set_register('cpsr', 0x10000010)
    scripted_step(instance, factory, cpsr=0x60000010, r0=3, pc=0x1004)
    instance.set_flags(0x80000000, 0x80000000)
    assert instance.runtime.registers['cpsr'] == 0xE0000010
    assert instance.baseline.registers['cpsr'] == 0x90000010
    instance.reset()
    assert instance.runtime.registers['cpsr'] == 0x90000010
    assert instance.runtime.registers['r0'] == 0


@pytest.mark.parametrize('operation', ['register', 'memory', 'zero', 'reset', 'load'])
def test_failed_candidate_preserves_both_states_and_backend(session, image, operation):
    instance, factory = session
    scripted_step(instance, factory, r0=5, pc=0x1004)
    before = checkpoint(instance)
    backend = factory.created[-1]
    factory.fail = True
    operations = dict(register=lambda: instance.set_register('r1', 7),
                      memory=lambda: instance.patch_memory(0x2800, b'1234'),
                      zero=lambda: instance.zero_fill(0x2800, 4), reset=instance.reset,
                      load=lambda: instance.load(image))
    with pytest.raises(DomainError, match='Injected'):
        operations[operation]()
    assert checkpoint(instance) == before
    assert not backend.closed
    factory.fail = False
    instance.reset()
    assert backend.closed


@pytest.mark.parametrize('name,value,mask', [('r0', -1, None), ('r0', True, None), ('r0', 1 << 32, None),
    ('bad', 0, None), ('sp', 3, None), ('pc', 0x1002, None), ('cpsr', 0x30, None),
    ('cpsr', 0, 0), ('cpsr', 0, 0x20), ('cpsr', 0, True), ('r1', 0, 0x80000000)])
def test_invalid_register_edit_never_constructs_backend(session, name, value, mask):
    instance, factory = session
    before, count = checkpoint(instance), len(factory.created)
    with pytest.raises(DomainError):
        instance.set_register(name, value, mask=mask)
    assert checkpoint(instance) == before
    assert len(factory.created) == count


def test_invalid_memory_and_load_preserve_experiment(session, image):
    instance, factory = session
    before, count = checkpoint(instance), len(factory.created)
    for mutation in (lambda: instance.patch_memory(0x1000, b'1234'),
                     lambda: instance.patch_memory(0xFFFFFFFF, b'12'),
                     lambda: instance.zero_fill(0x2800, 65537),
                     lambda: instance.load(image, stack_base=0x1000)):
        with pytest.raises(DomainError):
            mutation()
        assert checkpoint(instance) == before
        assert len(factory.created) == count


def test_aliases_and_nonallocating_inspection(session):
    instance, _ = session
    instance.set_register('R13', 0x2800)
    instance.set_register('r14', 0x1235)
    instance.set_register('R15', 0x1004)
    assert instance.runtime.registers['sp'] == 0x2800
    assert instance.runtime.registers['lr'] == 0x1235
    assert instance.baseline.registers['pc'] == 0x1004
    before = checkpoint(instance)
    assert all(cell.value is None for cell in instance.inspect_memory(0x2800, 4))
    assert checkpoint(instance) == before
    instance.zero_fill(0x2800, 4)
    assert instance.runtime.memory.read(0x2800, 4) == bytes(4)
    assert instance.baseline.memory.read(0x2800, 4) == bytes(4)
    with pytest.raises(TypeError):
        instance.snapshot().registers['r0'] = 9


def test_sequence_noop_failure_reset_and_reload(session, image):
    instance, factory = session
    # Scripted no-op completion verifies the commit counter independently of PC changes.
    for count in (1, 2):
        result = scripted_step(instance, factory)
        assert result['step_seq'] == count
        assert result['register_changes'] == {}
    factory.created[-1].error = DomainError('execution_failure', 'Injected failure.')
    assert instance.step()['status'] == 'failed'
    assert instance.step_seq == 2
    instance.reset()
    assert instance.step_seq == 2
    instance.load(image)
    assert instance.step_seq == 2
    assert instance.last_step is None


def test_unavailable_backend_blocks_edits_and_allows_recovery(session):
    instance, factory = session
    before = instance.runtime
    factory.created[-1].error = DomainError('backend_unavailable', 'Restore failed.', restored=False)
    result = instance.step()
    assert result['error']['restored'] is False
    assert instance.status == 'unavailable'
    assert instance.runtime == before
    for mutation in (instance.step, lambda: instance.set_register('r0', 7),
                     lambda: instance.patch_memory(0x2800, b'1234')):
        with pytest.raises(DomainError, match='Reset or reload'):
            mutation()
    factory.fail = True
    with pytest.raises(DomainError):
        instance.reset()
    assert instance.status == 'unavailable'
    assert instance.baseline == before
    factory.fail = False
    instance.reset()
    assert instance.status == 'ready'


def test_error_result_is_detached_and_empty_of_attempted_changes(session):
    instance, factory = session
    factory.created[-1].error = DomainError('unmapped_memory_access', 'Unknown byte.',
        address=0x2800, size=4, access='read', missing_ranges=((0x2800, 4),))
    before = instance.runtime
    result = instance.step()
    assert result['stop_reason'] == 'memory_fault'
    assert result['register_changes'] == {}
    assert result['memory_reads'] == result['memory_writes'] == []
    assert instance.runtime == instance.baseline == before
    result['error']['context']['missing_ranges'].clear()
    assert instance.last_step['error']['context']['missing_ranges'] == [{'address': 0x2800, 'size': 4}]


def test_known_exclusion_rejected_before_backend_execution(session, image):
    instance, factory = session
    excluded = replace(image.instructions[0], feature_exclusion='Excluded for this test.')
    instance.load(replace(image, instructions=(excluded,)))
    factory.created[-1].error = AssertionError('Backend must not execute excluded instructions.')
    assert instance.step()['error']['code'] == 'unsupported_instruction'


def test_sessions_do_not_share_runtime_or_baseline(session, image):
    instance, factory = session
    other = SimulationSession(factory)
    try:
        other.load(image)
        instance.set_register('r0', 7)
        instance.patch_memory(0x2800, b'1234')
        assert other.runtime.registers['r0'] == other.baseline.registers['r0'] == 0
        assert other.inspect_memory(0x2800, 1)[0].value is None
        assert other.step_seq == 0
    finally:
        other.close()


def test_register_origins_follow_explicit_edits_changes_and_reset(session, image):
    import json

    instance, factory = session
    assert set(instance.runtime.register_origins.values()) == {'default'}
    instance.set_register('r1', 0)  # Same-value evidence is still user input.
    instance.set_register('R13', instance.runtime.registers['sp'])
    instance.set_flags(0x40000000, 0)
    baseline = instance.baseline
    assert baseline.register_origins['r1'] == baseline.register_origins['sp'] == 'user'
    assert baseline.register_origins['cpsr'] == 'user'
    result = scripted_step(instance, factory, r0=7, pc=0x1004, cpsr=0x40000010)
    assert {name for name, origin in instance.runtime.register_origins.items() if origin == 'execution'} == {'r0', 'pc', 'cpsr'}
    assert instance.runtime.register_origins['r1'] == 'user'
    assert instance.baseline == baseline
    assert json.loads(json.dumps(result)) == result
    assert result.keys() == StepResult.__required_keys__
    view = instance.snapshot().register_view()
    assert json.loads(json.dumps(view)) == view
    view['r0']['origin'] = 'user'
    assert instance.runtime.register_origins['r0'] == 'execution'
    with pytest.raises(TypeError):
        instance.runtime.register_origins['r0'] = 'user'
    # A later unchanged execution and memory edit preserve labels.
    scripted_step(instance, factory)
    instance.patch_memory(0x2800, b'1')
    instance.zero_fill(0x2801, 1)
    assert instance.runtime.register_origins['r0'] == 'execution'
    instance.set_register('r0', 7)
    assert instance.runtime.register_origins['r0'] == 'user'
    instance.reset()
    assert instance.runtime.register_origins == instance.baseline.register_origins
    assert instance.runtime.register_origins['pc'] == 'default'
    instance.load(image)
    assert set(instance.runtime.register_origins.values()) == {'default'}


def test_failed_step_clears_highlights_but_preserves_origins(session):
    instance, factory = session
    scripted_step(instance, factory, r0=1, cpsr=0x40000010)
    before = instance.runtime
    factory.created[-1].error = DomainError('backend_unavailable', 'Restore failed.', restored=False)
    result = instance.step()
    assert instance.runtime == before
    assert result['stop_reason'] == 'backend_unavailable'
    assert result['register_changes'] == result['flag_changes'] == {}
    assert result['memory_writes'] == []
