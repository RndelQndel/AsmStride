IT_CONDITIONS = {
    0: 'EQ', 1: 'NE', 2: 'CS', 3: 'CC',
    4: 'MI', 5: 'PL', 6: 'VS', 7: 'VC',
    8: 'HI', 9: 'LS', 10: 'GE', 11: 'LT',
    12: 'GT', 13: 'LE', 14: 'AL'
}


def get_itstate(cpsr: int) -> int:
    """Extract ITSTATE[7:0] from CPSR: IT[7:2] = CPSR[15:10], IT[1:0] = CPSR[26:25]."""
    return (((cpsr >> 10) & 0x3F) << 2) | ((cpsr >> 25) & 0x3)


def set_itstate(cpsr: int, itstate: int) -> int:
    """Pack ITSTATE[7:0] into CPSR."""
    cpsr = cpsr & ~((0x3F << 10) | (0x3 << 25))
    cpsr |= ((itstate >> 2) & 0x3F) << 10
    cpsr |= (itstate & 0x3) << 25
    return cpsr


def evaluate_condition(condition: str | None, cpsr: int) -> bool:
    if condition is None or condition.lower() == 'al':
        return True
    n, z, c, v = (bool(cpsr & (1 << bit)) for bit in (31, 30, 29, 28))
    conditions = dict(eq=z, ne=not z, cs=c, hs=c, cc=not c, lo=not c, mi=n, pl=not n,
                      vs=v, vc=not v, hi=c and not z, ls=not c or z,
                      ge=n == v, lt=n != v, gt=not z and n == v, le=z or n != v)
    return conditions.get(condition.lower(), True)


def operand_value(instruction, operand, registers):
    """Read an ALU target operand; this never executes or updates machine state."""
    if operand.kind == 'immediate':
        value = operand.immediate & 0xFFFFFFFF
    elif operand.kind == 'register':
        value = (instruction.address + (8 if instruction.mode == 'arm' else 4)
                 if operand.register == 'pc' else registers.get(operand.register, 0)) & 0xFFFFFFFF
    else:
        return None
    if operand.shift is None:
        return value
    kind, amount = operand.shift
    # Register-shifted PC forms have additional ISA restrictions; fail closed on fetch errors.
    if kind.endswith('_reg'):
        return None
    if kind == 'lsl':
        return (value << amount) & 0xFFFFFFFF
    if kind == 'lsr':
        return value >> amount
    if kind == 'asr':
        signed = value if value < 0x80000000 else value - (1 << 32)
        return (signed >> amount) & 0xFFFFFFFF
    if kind == 'ror':
        amount %= 32
        return ((value >> amount) | (value << (32 - amount))) & 0xFFFFFFFF
    if kind == 'rrx':
        return ((registers.get('cpsr', 0) & 0x20000000) << 2) | (value >> 1)
    return None


def computed_target(instruction, registers, reads=()):
    """Evidence for common computed destinations, not an instruction allowlist."""
    operation, operands = instruction.decode.operation, instruction.decode.operands
    if operation in ('tbb', 'tbh'):
        width = 1 if operation == 'tbb' else 2
        base, index, displacement = operands[0].memory
        base_value = instruction.address + 4 if base == 'pc' else registers.get(base, 0)
        address = (base_value + registers.get(index, 0) * width + displacement) & 0xFFFFFFFF
        if len(reads) == 1 and reads[0]['address'] == address and reads[0]['size'] == width:
            offset = int.from_bytes(bytes.fromhex(reads[0]['bytes']), 'little')
            return (instruction.address + 4 + 2 * offset) & 0xFFFFFFFF
    if not operands or operands[0].register != 'pc' or instruction.decode.updates_flags:
        return None
    if operation not in ('mov', 'add', 'sub'):
        return None
    values = [operand_value(instruction, operand, registers) for operand in operands[1:]]
    if None in values:
        return None
    if operation == 'mov' and len(values) == 1:
        target = values[0]
    elif operation in ('add', 'sub') and len(values) in (1, 2):
        left, right = values if len(values) == 2 else (instruction.address + 4, values[0])
        target = left + right if operation == 'add' else left - right
    else:
        return None
    return target & 0xFFFFFFFE


class ArmControlFlowInterpreter:
    def is_control_flow(self, instruction):
        return (instruction.decode.operation in ('b', 'bl', 'bx', 'blx', 'cbz', 'cbnz', 'tbb', 'tbh') or
                'pc' in instruction.decode.registers_written)

    def condition_passed(self, instruction, registers):
        if instruction.decode.operation == 'it':
            return None
        if instruction.mode == 'thumb':
            itstate = get_itstate(registers.get('cpsr', 0))
            if itstate != 0:
                cond_name = IT_CONDITIONS.get(itstate >> 4, 'AL')
                return evaluate_condition(cond_name, registers.get('cpsr', 0))
        condition = instruction.decode.condition
        if instruction.decode.operation in ('cbz', 'cbnz'):
            zero = registers.get(instruction.decode.operands[0].register, 0) == 0
            return zero if instruction.decode.operation == 'cbz' else not zero
        if condition:
            return evaluate_condition(condition, registers.get('cpsr', 0))
        return None

    def direct_target(self, instruction, registers):
        operands = instruction.decode.operands
        operation = instruction.decode.operation
        if operation in ('b', 'bl', 'blx', 'bx', 'cbz', 'cbnz'):
            operand = operands[-1]
            if operand.kind == 'immediate':
                value = operand.immediate
            elif operand.register == 'pc':
                value = instruction.address + (8 if instruction.mode == 'arm' else 4)
            else:
                value = registers.get(operand.register, 0)
            return value & 0xFFFFFFFE
        return None

    def branch_result(self, instruction, before, after, reads=()):
        if not self.is_control_flow(instruction):
            return None
        operation = instruction.decode.operation
        operands = instruction.decode.operands
        kind = 'branch' if operation in ('b', 'bx', 'cbz', 'cbnz', 'tbb', 'tbh') else 'pc_write'
        if operation in ('bl', 'blx'):
            kind = 'call'
        elif operation == 'pop' or (operation == 'bx' and operands[0].register == 'lr'):
            kind = 'return'
        target = self.direct_target(instruction, before)
        if target is None:
            target = computed_target(instruction, before, reads)
        cond_passed = self.condition_passed(instruction, before)
        taken = cond_passed is not False
        condition = instruction.decode.condition
        if condition is None and instruction.mode == 'thumb':
            itstate = get_itstate(before.get('cpsr', 0))
            if itstate != 0:
                condition = IT_CONDITIONS.get(itstate >> 4, 'AL').lower()
        return dict(kind=kind, taken=taken, target=after['pc'] if target is None and taken else target,
                    condition=condition, fallthrough=(instruction.address + instruction.size) & 0xFFFFFFFF)


class RiscvControlFlowInterpreter:
    def is_control_flow(self, instruction) -> bool:
        op = instruction.decode.operation
        return op in (
            'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu',
            'beqz', 'bnez', 'blez', 'bgez', 'bltz', 'bgtz',
            'bgt', 'ble', 'bgtu', 'bleu',
            'jal', 'j', 'jalr', 'jr', 'ret',
            'ecall', 'ebreak'
        )

    def condition_passed(self, instruction, registers) -> bool | None:
        op = instruction.decode.operation
        operands = instruction.decode.operands
        if op in ('beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu'):
            if len(operands) < 2 or not operands[0].register or not operands[1].register:
                return None
            val1 = registers.get(operands[0].register, 0)
            val2 = registers.get(operands[1].register, 0)
            s1 = val1 if val1 < 0x80000000 else val1 - 0x100000000
            s2 = val2 if val2 < 0x80000000 else val2 - 0x100000000
            if op == 'beq': return val1 == val2
            if op == 'bne': return val1 != val2
            if op == 'blt': return s1 < s2
            if op == 'bge': return s1 >= s2
            if op == 'bltu': return (val1 & 0xFFFFFFFF) < (val2 & 0xFFFFFFFF)
            if op == 'bgeu': return (val1 & 0xFFFFFFFF) >= (val2 & 0xFFFFFFFF)
        elif op in ('beqz', 'bnez', 'blez', 'bgez', 'bltz', 'bgtz'):
            if not operands or not operands[0].register:
                return None
            val1 = registers.get(operands[0].register, 0)
            s1 = val1 if val1 < 0x80000000 else val1 - 0x100000000
            if op == 'beqz': return val1 == 0
            if op == 'bnez': return val1 != 0
            if op == 'blez': return s1 <= 0
            if op == 'bgez': return s1 >= 0
            if op == 'bltz': return s1 < 0
            if op == 'bgtz': return s1 > 0
        return None

    def direct_target(self, instruction, registers) -> int | None:
        op = instruction.decode.operation
        operands = instruction.decode.operands
        if op in ('beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu'):
            if len(operands) >= 3 and operands[2].immediate is not None:
                return (instruction.address + operands[2].immediate) & 0xFFFFFFFF
        elif op in ('beqz', 'bnez', 'blez', 'bgez', 'bltz', 'bgtz'):
            if len(operands) >= 2 and operands[1].immediate is not None:
                return (instruction.address + operands[1].immediate) & 0xFFFFFFFF
        elif op == 'jal':
            if len(operands) == 2 and operands[1].immediate is not None:
                return (instruction.address + operands[1].immediate) & 0xFFFFFFFF
            elif len(operands) == 1 and operands[0].immediate is not None:
                return (instruction.address + operands[0].immediate) & 0xFFFFFFFF
        elif op == 'j':
            if len(operands) >= 1 and operands[0].immediate is not None:
                return (instruction.address + operands[0].immediate) & 0xFFFFFFFF
        elif op == 'jalr':
            if len(operands) == 3:
                rs1 = operands[1].register
                imm = operands[2].immediate or 0
                return ((registers.get(rs1, 0) + imm) & ~1) & 0xFFFFFFFF
            elif len(operands) == 2:
                if operands[1].kind == 'memory' and operands[1].memory:
                    rs1, _, imm = operands[1].memory
                    return ((registers.get(rs1, 0) + (imm or 0)) & ~1) & 0xFFFFFFFF
                else:
                    rs1 = operands[1].register
                    return (registers.get(rs1, 0) & ~1) & 0xFFFFFFFF
            elif len(operands) == 1:
                rs1 = operands[0].register
                return (registers.get(rs1, 0) & ~1) & 0xFFFFFFFF
        elif op == 'jr':
            if operands and operands[0].register:
                return (registers.get(operands[0].register, 0) & ~1) & 0xFFFFFFFF
        elif op == 'ret':
            return (registers.get('x1', 0) & ~1) & 0xFFFFFFFF
        return None

    def branch_result(self, instruction, before, after, reads=()) -> dict | None:
        if not self.is_control_flow(instruction):
            return None
        op = instruction.decode.operation
        operands = instruction.decode.operands
        fallthrough = (instruction.address + 4) & 0xFFFFFFFF

        if op in ('ecall', 'ebreak'):
            return dict(
                kind='trap',
                condition=None,
                taken=False,
                target=None,
                fallthrough=fallthrough
            )

        cond_pass = self.condition_passed(instruction, before)
        target = self.direct_target(instruction, before)

        if op in ('jal', 'j'):
            taken = True
            rd = operands[0].register if (op == 'jal' and len(operands) == 2) else ('x1' if op == 'jal' else 'x0')
            kind = 'call' if rd in ('x1', 'ra') else 'branch'
        elif op == 'jalr':
            taken = True
            rd = operands[0].register if len(operands) in (2, 3) else 'x1'
            rs1 = operands[1].register if len(operands) == 3 else (operands[1].memory[0] if (len(operands) == 2 and operands[1].kind == 'memory') else operands[0].register)
            if rs1 in ('x1', 'ra') and rd in ('x0', 'zero'):
                kind = 'return'
            elif rd in ('x1', 'ra'):
                kind = 'call'
            else:
                kind = 'branch'
        elif op == 'jr':
            taken = True
            rs1 = operands[0].register if operands else 'x1'
            kind = 'return' if rs1 in ('x1', 'ra') else 'branch'
        elif op == 'ret':
            taken = True
            kind = 'return'
        else:
            taken = bool(cond_pass)
            kind = 'branch'

        return dict(
            kind=kind,
            taken=taken,
            target=target if target is not None else after.get('pc'),
            condition=None,
            fallthrough=fallthrough
        )


_ARM_INTERPRETER = ArmControlFlowInterpreter()
_RISCV_INTERPRETER = RiscvControlFlowInterpreter()


def get_control_flow_interpreter(profile: str):
    if profile == 'rv32i-le':
        return _RISCV_INTERPRETER
    return _ARM_INTERPRETER


def is_control_flow(instruction):
    return get_control_flow_interpreter(getattr(instruction, 'profile', 'armv7-a-le')).is_control_flow(instruction)


def condition_passed(instruction, registers):
    return get_control_flow_interpreter(getattr(instruction, 'profile', 'armv7-a-le')).condition_passed(instruction, registers)


def direct_target(instruction, registers):
    return get_control_flow_interpreter(getattr(instruction, 'profile', 'armv7-a-le')).direct_target(instruction, registers)


def branch_result(instruction, before, after, reads=()):
    return get_control_flow_interpreter(getattr(instruction, 'profile', 'armv7-a-le')).branch_result(instruction, before, after, reads)
