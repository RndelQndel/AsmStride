"""Session-owned runtime and user baseline with atomic replacement and Step."""

from copy import deepcopy
from typing import Callable

from armstride.architecture.arm import (EDITABLE_FLAGS, STACK_BASE, STACK_SIZE,
    canonical_register, initial_registers, validate_pc)
from armstride.architecture.control_flow import branch_result, condition_passed
from armstride.domain.models import DomainError, ProgramImage
from armstride.simulation.memory import MemoryState
from armstride.simulation.results import StepResult
from armstride.simulation.state import ExecutionBackend, MachineState


def changes(before, after):
    return {name: dict(before=value, after=after[name]) for name, value in before.items()
            if value != after[name]}


def flags(registers):
    return {name: bool(registers['cpsr'] & (1 << bit)) for name, bit in zip('nzcv', (31, 30, 29, 28))}


class SimulationSession:
    def __init__(self, backend_factory: Callable[[ProgramImage, MachineState], ExecutionBackend] | None = None):
        if backend_factory is None:
            from armstride.backends.unicorn import UnicornBackend
            backend_factory = UnicornBackend
        self._backend_factory = backend_factory
        self._backend = None
        self.program = None
        self.runtime = None
        self.baseline = None
        self.step_seq = 0
        self._last_step: StepResult | None = None
        self.unavailable = False

    @property
    def last_step(self) -> StepResult | None:
        return deepcopy(self._last_step)

    @property
    def status(self):
        if self.unavailable:
            return 'unavailable'
        if self.program is None:
            return 'empty'
        if self._last_step is not None and self._last_step['status'] == 'failed':
            return 'stopped'
        return 'ready' if self.runtime.registers['pc'] in self.program.address_index else 'stopped'

    def snapshot(self):
        return self.runtime

    def _require_loaded(self, *, recovery=False):
        if self.program is None:
            raise DomainError('program_not_loaded', 'Load a program first.')
        if self.unavailable and not recovery:
            raise DomainError('backend_unavailable', 'Reset or reload to recover the session.')

    def _replace(self, program, runtime, baseline):
        # ponytail: rebuild per edit; optimize synchronization only if editing latency warrants it.
        candidate = self._backend_factory(program, runtime)
        previous = self._backend
        self._backend, self.program = candidate, program
        self.runtime, self.baseline = runtime, baseline
        self.unavailable, self._last_step = False, None
        if previous is not None:
            previous.close()

    def load(self, program, *, stack_base=STACK_BASE, stack_size=STACK_SIZE):
        memory = MemoryState.from_program(program, stack_base=stack_base, stack_size=stack_size)
        registers = dict(initial_registers(program.mode, program.start_pc))
        registers['sp'] = stack_base + stack_size
        state = MachineState(registers, memory)
        self._replace(program, state, state)

    def set_register(self, name, value, *, mask=None):
        self._require_loaded()
        name = canonical_register(name)
        if type(value) is not int or not 0 <= value < 1 << 32:
            raise DomainError('invalid_register', 'Register values must be unsigned 32-bit integers.')
        if mask is not None and name != 'cpsr':
            raise DomainError('invalid_register', 'Only CPSR accepts a mask.')
        if name == 'pc':
            validate_pc(self.program, value)
        if name == 'sp' and value % 4:
            raise DomainError('invalid_register', 'SP must be word-aligned.')
        if name == 'cpsr':
            if mask is None:
                if (value ^ self.runtime.registers['cpsr']) & ~EDITABLE_FLAGS:
                    raise DomainError('invalid_register', 'Protected CPSR bits cannot be changed.')
                mask = EDITABLE_FLAGS
            elif type(mask) is not int or mask <= 0 or mask & ~EDITABLE_FLAGS:
                raise DomainError('invalid_register', 'CPSR mask must select only N/Z/C/V.')
        candidates = []
        for state in (self.runtime, self.baseline):
            registers = dict(state.registers)
            registers[name] = (registers[name] & ~mask) | (value & mask) if mask is not None else value
            candidates.append(MachineState(registers, state.memory, dict(state.register_origins) | {name: 'user'}))
        self._replace(self.program, *candidates)

    def set_pc(self, value):
        self.set_register('pc', value)

    def set_flags(self, mask, value):
        self.set_register('cpsr', value, mask=mask)

    def patch_memory(self, address, raw_bytes):
        self._require_loaded()
        candidates = [MachineState(state.registers, state.memory.patch(address, raw_bytes), state.register_origins)
                      for state in (self.runtime, self.baseline)]
        self._replace(self.program, *candidates)

    def zero_fill(self, address, size):
        self._require_loaded()
        candidates = [MachineState(state.registers, state.memory.zero_fill(address, size), state.register_origins)
                      for state in (self.runtime, self.baseline)]
        self._replace(self.program, *candidates)

    def inspect_memory(self, address, size):
        self._require_loaded(recovery=True)
        return self.runtime.memory.inspect(address, size)

    def reset(self):
        self._require_loaded(recovery=True)
        self._replace(self.program, self.baseline, self.baseline)

    def close(self):
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self.unavailable = self.program is not None

    def step(self) -> StepResult:
        self._require_loaded()
        before = self.runtime
        pc = before.registers['pc']
        instruction = self.program.address_index.get(pc)
        result = StepResult(status='failed', pc_before=pc, pc_after=pc, condition_passed=None,
                      branch=None, stop_reason=None, error=None, memory_reads=[], memory_writes=[],
                      flag_changes={}, step_seq=self.step_seq, register_changes={}, cpsr_change=None,
                      instruction=None if instruction is None else dict(address=pc, size=instruction.size,
                                                                       source_line=instruction.source_line))
        try:
            validate_pc(self.program, pc)
            if instruction.feature_exclusion:
                raise DomainError('unsupported_instruction', instruction.feature_exclusion)
            outcome = self._backend.execute_one(instruction, before)
        except DomainError as error:
            context = dict(error.context)
            restored = context.pop('restored', True)
            context.update(pc=pc, source_line=instruction.source_line if instruction else None)
            if 'missing_ranges' in context:
                context['missing_ranges'] = [dict(address=start, size=size) for start, size in context['missing_ranges']]
            code = error.code
            self.unavailable = code == 'backend_unavailable'
            stop = ('memory_fault' if code in ('unmapped_memory_access', 'unaligned_memory_access',
                                               'memory_permission_denied') else
                    'unsupported_instruction' if code == 'unsupported_instruction' else
                    'unsupported_mode_transition' if code == 'unsupported_mode_transition' else
                    'invalid_pc' if code == 'invalid_pc' else
                    'backend_unavailable' if code == 'backend_unavailable' else 'execution_error')
            result.update(error=dict(code=code, context=context, restored=restored), stop_reason=stop)
        else:
            after = outcome.state.registers
            register_changes = changes(before.registers, after)
            origins = dict(before.register_origins) | dict.fromkeys(register_changes, 'execution')
            self.runtime = MachineState(after, outcome.state.memory, origins)
            self.step_seq += 1
            cpsr_change = register_changes.pop('cpsr', None)
            result.update(status='executed', pc_after=after['pc'],
                          condition_passed=condition_passed(instruction, before.registers),
                          branch=branch_result(instruction, before.registers, after, outcome.reads),
                          stop_reason=None if after['pc'] in self.program.address_index else 'pc_not_loaded',
                          memory_reads=list(outcome.reads), memory_writes=list(outcome.writes),
                          flag_changes=changes(flags(before.registers), flags(after)),
                          step_seq=self.step_seq, register_changes=register_changes, cpsr_change=cpsr_change)
        self._last_step = result
        return self.last_step
