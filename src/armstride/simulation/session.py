"""Session-owned runtime and user baseline with atomic replacement and Step."""

from copy import deepcopy
from typing import Callable

from armstride.architecture.arm import (EDITABLE_FLAGS, STACK_BASE, STACK_SIZE,
    canonical_register, initial_registers, validate_pc)
from armstride.architecture.control_flow import (IT_CONDITIONS, branch_result,
    condition_passed, evaluate_condition, get_itstate)
from armstride.domain.models import Breakpoint, DomainError, ProgramImage
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
        self._it_blocks = {}
        self._it_interior_addresses = set()
        self.breakpoints: dict[int, Breakpoint] = {}


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
        pc = self.runtime.registers['pc']
        if pc not in self.program.address_index:
            return 'stopped'
        current_mode = 'thumb' if self.runtime.registers['cpsr'] & 0x20 else 'arm'
        if self.program.address_index[pc].mode != current_mode:
            return 'stopped'
        return 'ready'

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
        if program is not None:
            self._it_blocks = {}
            instructions = program.instructions
            for idx, inst in enumerate(instructions):
                if inst.mode == 'thumb' and inst.decode.operation == 'it':
                    mnemonic = inst.display_text.split()[0].lower()
                    count = len(mnemonic) - 1
                    if 1 <= count <= 4:
                        for k in range(1, count + 1):
                            if idx + k < len(instructions):
                                target = instructions[idx + k]
                                if target.mode == 'thumb':
                                    self._it_blocks[target.address] = (k, count, inst.address)
            self._it_interior_addresses = set(self._it_blocks.keys())
        else:
            self._it_blocks = {}
            self._it_interior_addresses = set()
        if previous is not None:
            previous.close()

    def load(self, program, *, stack_base=STACK_BASE, stack_size=STACK_SIZE):
        self.clear_breakpoints()
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
            if value in self._it_interior_addresses and get_itstate(self.runtime.registers['cpsr']) == 0:
                raise DomainError('invalid_it_block_entry',
                                  'Cannot set PC to interior of an IT block without active IT context.')
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
        result = StepResult(status='failed', executed=False, pc_before=pc, pc_after=pc,
                            condition_passed=None, it_context=None,
                            branch=None, stop_reason=None, error=None, memory_reads=[], memory_writes=[],
                            flag_changes={}, step_seq=self.step_seq, register_changes={}, cpsr_change=None,
                            instruction=None if instruction is None else dict(address=pc, size=instruction.size,
                                                                             source_line=instruction.source_line))
        try:
            if pc not in self.program.address_index:
                if any(dr.address <= pc < dr.address + dr.size for dr in self.program.data_regions):
                    raise DomainError('non_executable_target', 'Cannot execute non-executable data.')
                raise DomainError('invalid_pc', 'PC must identify a loaded instruction start.')
            current_mode = 'thumb' if before.registers['cpsr'] & 0x20 else 'arm'
            if instruction.mode != current_mode:
                raise DomainError('mode_mismatch', f'Execution mode {current_mode} does not match instruction mode {instruction.mode}.')
            if pc in self._it_interior_addresses and get_itstate(before.registers['cpsr']) == 0:
                raise DomainError('invalid_it_block_entry',
                                  'Cannot execute instruction inside IT block without valid IT context.')
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
                    'mode_mismatch' if code == 'mode_mismatch' else
                    'non_executable_target' if code == 'non_executable_target' else
                    'invalid_it_block_entry' if code == 'invalid_it_block_entry' else
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
            resulting_mode = 'thumb' if after['cpsr'] & 0x20 else 'arm'
            if after['pc'] in self.program.address_index:
                target_instruction = self.program.address_index[after['pc']]
                if target_instruction.mode != resulting_mode:
                    stop_reason = 'mode_mismatch'
                else:
                    stop_reason = None
            elif any(dr.address <= after['pc'] < dr.address + dr.size for dr in self.program.data_regions):
                stop_reason = 'non_executable_target'
            else:
                stop_reason = 'pc_not_loaded'

            itstate_before = get_itstate(before.registers['cpsr']) if instruction.mode == 'thumb' else 0
            if itstate_before != 0:
                cond_code = itstate_before >> 4
                cond_name = IT_CONDITIONS.get(cond_code, 'AL')
                cond_passed = evaluate_condition(cond_name, before.registers['cpsr'])
                info = self._it_blocks.get(instruction.address)
                b_idx = info[0] if info else 1
                b_tot = info[1] if info else 1
                it_context = {
                    'block_index': b_idx,
                    'block_total': b_tot,
                    'condition': cond_name,
                    'passed': cond_passed
                }
                executed = cond_passed
            else:
                it_context = None
                cond_passed = condition_passed(instruction, before.registers)
                executed = False if cond_passed is False else True

            result.update(status='executed', executed=executed, pc_after=after['pc'],
                          condition_passed=cond_passed, it_context=it_context,
                          branch=branch_result(instruction, before.registers, after, outcome.reads),
                          stop_reason=stop_reason,
                          memory_reads=list(outcome.reads), memory_writes=list(outcome.writes),
                          flag_changes=changes(flags(before.registers), flags(after)),
                          step_seq=self.step_seq, register_changes=register_changes, cpsr_change=cpsr_change)
        self._last_step = result

        return self.last_step

    def add_breakpoint(self, address: int, mode: str | None = None) -> Breakpoint:
        self._require_loaded()
        if type(address) is not int or not 0 <= address < 1 << 32:
            raise DomainError('invalid_breakpoint', 'Breakpoint address must be an unsigned 32-bit integer.')
        if any(dr.address <= address < dr.address + dr.size for dr in self.program.data_regions):
            raise DomainError('invalid_breakpoint', 'Cannot set breakpoint on a data region.')
        if address not in self.program.address_index:
            raise DomainError('invalid_breakpoint', 'Breakpoint address must be a loaded instruction start.')
        inst = self.program.address_index[address]
        if inst.mode == 'arm' and address % 4 != 0:
            raise DomainError('invalid_breakpoint', 'ARM breakpoint address must be 4-byte aligned.')
        if inst.mode == 'thumb' and address % 2 != 0:
            raise DomainError('invalid_breakpoint', 'Thumb breakpoint address must be 2-byte aligned.')
        if mode is not None:
            if mode not in ('arm', 'thumb'):
                raise DomainError('invalid_breakpoint', 'Mode must be arm or thumb.')
            if mode != inst.mode:
                raise DomainError('invalid_breakpoint', f'Breakpoint mode {mode} does not match instruction mode {inst.mode}.')
        else:
            mode = inst.mode
        bp = Breakpoint(address, mode)
        self.breakpoints[address] = bp
        return bp

    def remove_breakpoint(self, address: int) -> bool:
        self._require_loaded()
        if address in self.breakpoints:
            del self.breakpoints[address]
            return True
        return False

    def list_breakpoints(self) -> list[Breakpoint]:
        return sorted(self.breakpoints.values(), key=lambda b: b.address)

    def clear_breakpoints(self) -> None:
        self.breakpoints.clear()

    def _current_breakpoint(self) -> Breakpoint | None:
        if self.runtime is None:
            return None
        pc = self.runtime.registers['pc']
        bp = self.breakpoints.get(pc)
        if bp is None:
            return None
        current_mode = 'thumb' if self.runtime.registers['cpsr'] & 0x20 else 'arm'
        if bp.mode == current_mode:
            return bp
        return None

    def run(self, stop_event=None, max_steps: int = 10_000,
            timeout_seconds: float = 2.0) -> dict[str, object]:
        self._require_loaded()
        if stop_event is None:
            import threading
            stop_event = threading.Event()
        from time import monotonic
        start_seq = self.step_seq
        steps_committed = 0
        start_time = monotonic()
        stop_reason = None
        breakpoint_hit = None

        bypassed_bp = self._current_breakpoint()

        while True:
            if stop_event.is_set():
                stop_reason = 'user_stop'
                break
            curr_bp = self._current_breakpoint()
            if curr_bp is not None and curr_bp != bypassed_bp:
                stop_reason = 'breakpoint'
                breakpoint_hit = curr_bp.address
                break
            bypassed_bp = None

            if steps_committed >= max_steps:
                stop_reason = 'step_limit'
                break
            if (monotonic() - start_time) >= timeout_seconds:
                stop_reason = 'time_limit'
                break

            step_res = self.step()
            if step_res['status'] == 'failed':
                stop_reason = step_res.get('stop_reason') or 'execution_failure'
                break
            steps_committed += 1
            if step_res.get('stop_reason') is not None:
                stop_reason = step_res['stop_reason']
                break

        elapsed_ms = (monotonic() - start_time) * 1000.0
        return {
            'start_step_seq': start_seq,
            'end_step_seq': self.step_seq,
            'steps_committed': steps_committed,
            'steps_executed': steps_committed,
            'stop_reason': stop_reason or 'user_stop',
            'elapsed_ms': elapsed_ms,
            'breakpoint_hit': breakpoint_hit,
            'last_step': self.last_step,
            'last_step_result': self.last_step,
        }

