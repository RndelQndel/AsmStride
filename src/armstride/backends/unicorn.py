"""Bounded Unicorn execution with full backing-page rollback."""

import unicorn as uc
from unicorn import arm_const as arm

from armstride.architecture.control_flow import computed_target, condition_passed, direct_target, is_control_flow
from armstride.domain.models import DomainError
from armstride.simulation.memory import MemoryRegion, MemoryState, PAGE_SIZE
from armstride.simulation.state import ExecutionOutcome, MachineState

REGISTER_IDS = {f'r{i}': getattr(arm, f'UC_ARM_REG_R{i}') for i in range(13)}
REGISTER_IDS.update(sp=arm.UC_ARM_REG_SP, lr=arm.UC_ARM_REG_LR,
                    pc=arm.UC_ARM_REG_PC, cpsr=arm.UC_ARM_REG_CPSR)
FETCH_ERRORS = (uc.UC_ERR_FETCH_UNMAPPED, uc.UC_ERR_FETCH_PROT)
FETCH_ACCESSES = (uc.UC_MEM_FETCH_UNMAPPED, uc.UC_MEM_FETCH_PROT)


class UnicornBackend:
    def __init__(self, program, state):
        self.program = program
        self.mode = program.mode
        self.timeout_us = 1_000_000

        self._engine = None
        try:
            engine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB if self.mode == 'thumb' else uc.UC_MODE_ARM)
            self._engine = engine
            engine.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A15)
            pages = sorted({page for region in state.memory.regions
                            for page in range(region.address & -PAGE_SIZE, region.end, PAGE_SIZE)})
            for page in pages:
                engine.mem_map(page, PAGE_SIZE)
            for region in state.memory.regions:
                engine.mem_write(region.address, region.raw_bytes)
            engine.reg_write(arm.UC_ARM_REG_CPSR, state.registers['cpsr'])
            for name, register in REGISTER_IDS.items():
                engine.reg_write(register, state.registers[name])
            if self._registers() != dict(state.registers):
                raise DomainError('backend_unavailable', 'Native initialization changed registers.')
        except uc.UcError as error:
            self.close()
            raise DomainError('backend_unavailable', 'Native initialization failed.') from error

    def close(self):
        # The binding releases the native handle when its last reference is dropped.
        self._engine = None

    def _registers(self):
        return {name: self._engine.reg_read(register) for name, register in REGISTER_IDS.items()}

    def _pages(self):
        return {page: bytes(self._engine.mem_read(page, PAGE_SIZE))
                for start, end, _ in self._engine.mem_regions()
                for page in range(start, end + 1, PAGE_SIZE)}

    def _restore(self, context, pages, registers):
        engine = self._engine
        for page in self._pages().keys() - pages.keys():
            engine.mem_unmap(page, PAGE_SIZE)
        for page, content in pages.items():
            engine.mem_write(page, content)
        engine.context_restore(context)
        if self._registers() != dict(registers) or self._pages() != pages:
            raise DomainError('backend_unavailable', 'Native rollback verification failed.')

    def execute_one(self, instruction, state):
        engine = self._engine
        try:
            # ponytail: copy bounded pages; use a write journal only if profiling justifies it.
            context, pages = engine.context_save(), self._pages()
        except uc.UcError as error:
            raise DomainError('backend_unavailable', 'Cannot checkpoint native state.', restored=False) from error
        try:
            return self._attempt(instruction, state)
        except (DomainError, uc.UcError) as error:
            try:
                self._restore(context, pages, state.registers)
            except (DomainError, uc.UcError) as restore_error:
                raise DomainError('backend_unavailable', 'Native rollback failed.', restored=False) from restore_error
            if isinstance(error, DomainError):
                raise
            raise DomainError('execution_failure', 'Native execution failed.') from error

    def _attempt(self, instruction, state):
        engine = self._engine
        reads, writes, rejected, fetches, handles = [], [], [], [], []
        code_count = 0

        def code_hook(native, address, size, _):
            nonlocal code_count
            code_count += 1
            if code_count != 1 or address != instruction.address or size != instruction.size:
                rejected.append(DomainError('execution_failure', 'Unexpected instruction boundary.'))
                native.emu_stop()

        def memory_hook(native, access, address, size, value, _):
            if access in FETCH_ACCESSES:
                fetches.append(address)
                return False
            if rejected:
                return False
            write = access in (uc.UC_MEM_WRITE, uc.UC_MEM_WRITE_UNMAPPED, uc.UC_MEM_WRITE_PROT)
            try:
                state.memory.validate_access(address, size, write=write)
                content = bytes(native.mem_read(address, size))
                if write:
                    writes.append(dict(address=address, size=size, before_bytes=content.hex(),
                                       after_bytes=(value & ((1 << (size * 8)) - 1)).to_bytes(size, 'little').hex()))
                else:
                    reads.append(dict(address=address, size=size, bytes=content.hex()))
            except DomainError as error:
                rejected.append(error)
                native.emu_stop()
            except uc.UcError:
                rejected.append(DomainError('execution_failure', 'Logical and native memory disagree.'))
                native.emu_stop()
            return False

        in_it = (state.registers['cpsr'] & 0x0000FC00) != 0 or (state.registers['cpsr'] & 0x06000000) != 0
        is_thumb = instruction.mode == 'thumb'
        until = (instruction.address + instruction.size) & 0xFFFFFFFF if (is_thumb and (instruction.decode.operation == 'it' or in_it)) else 0xFFFFFFFF
        native_error = None
        try:
            handles.append(engine.hook_add(uc.UC_HOOK_CODE, code_hook))
            handles.append(engine.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory_hook))
            handles.append(engine.hook_add(uc.UC_HOOK_MEM_INVALID, memory_hook))
            try:
                engine.emu_start(instruction.address | int(is_thumb), until,
                                 timeout=self.timeout_us, count=1)
            except uc.UcError as error:
                native_error = error
        finally:
            for handle in handles:
                engine.hook_del(handle)
        if rejected:
            raise rejected[0]
        if engine.query(uc.UC_QUERY_TIMEOUT):
            raise DomainError('execution_timeout', 'Instruction exceeded the native deadline.')
        after = self._registers()
        after['pc'] = after['pc'] & ~1
        resulting_mode = 'thumb' if after['cpsr'] & 0x20 else 'arm'
        if after['pc'] in self.program.address_index:
            target_inst = self.program.address_index[after['pc']]
            if target_inst.mode != resulting_mode:
                raise DomainError('unsupported_mode_transition',
                                  f'Execution mode {resulting_mode} does not match target instruction mode {target_inst.mode}.')
        if code_count != 1 and not (code_count == 0 and in_it and after['pc'] == (instruction.address + instruction.size) & 0xFFFFFFFF):
            raise DomainError('execution_failure', 'No single instruction completion was observed.')

        if native_error:
            if native_error.errno == uc.UC_ERR_INSN_INVALID:
                raise DomainError('unsupported_instruction', 'Engine rejected the instruction.')
            if native_error.errno not in FETCH_ERRORS or not self._retired_fetch(
                    instruction, state, after, reads, fetches):
                raise DomainError('execution_failure', 'Instruction completion could not be established.')
        memory = MemoryState(tuple(MemoryRegion(region.address,
                    bytes(engine.mem_read(region.address, len(region.raw_bytes))), region.origin)
                    for region in state.memory.regions))
        return ExecutionOutcome(MachineState(after, memory), tuple(reads), tuple(writes))

    @staticmethod
    def _retired_fetch(instruction, state, after, reads, fetches):
        """Accept only a proven destination fetch after the one entry code hook."""
        canonical_fetches = [f & ~1 for f in fetches]
        if not canonical_fetches or canonical_fetches != [after['pc']]:
            return False
        if condition_passed(instruction, state.registers) is False or not is_control_flow(instruction):
            target = (instruction.address + instruction.size) & 0xFFFFFFFF
        else:
            target = direct_target(instruction, state.registers)
            if target is None:
                target = computed_target(instruction, state.registers, reads)
            # PC is the final register transferred by POP/LDM, or the LDR destination.
            if target is None and instruction.decode.operation in ('pop', 'ldm', 'ldmib', 'ldmda', 'ldmdb', 'ldr'):
                if reads and reads[-1]['size'] == 4:
                    target = int.from_bytes(bytes.fromhex(reads[-1]['bytes']), 'little') & ~1
        return target is not None and after['pc'] == target

