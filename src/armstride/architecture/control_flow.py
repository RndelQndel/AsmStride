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


def condition_passed(instruction, registers):
    if instruction.decode.operation == 'it':
        return None
    if instruction.mode == 'thumb':
        itstate = get_itstate(registers['cpsr'])
        if itstate != 0:
            cond_name = IT_CONDITIONS.get(itstate >> 4, 'AL')
            return evaluate_condition(cond_name, registers['cpsr'])
    condition = instruction.decode.condition
    if instruction.decode.operation in ('cbz', 'cbnz'):
        zero = registers[instruction.decode.operands[0].register] == 0
        return zero if instruction.decode.operation == 'cbz' else not zero
    if condition:
        return evaluate_condition(condition, registers['cpsr'])
    return None


def is_control_flow(instruction):
    return (instruction.decode.operation in ('b', 'bl', 'bx', 'blx', 'cbz', 'cbnz', 'tbb', 'tbh') or
            'pc' in instruction.decode.registers_written)


def direct_target(instruction, registers):
    operands = instruction.decode.operands
    operation = instruction.decode.operation
    if operation in ('b', 'bl', 'blx', 'bx', 'cbz', 'cbnz'):
        operand = operands[-1]
        if operand.kind == 'immediate':
            value = operand.immediate
        elif operand.register == 'pc':
            value = instruction.address + (8 if instruction.mode == 'arm' else 4)
        else:
            value = registers[operand.register]
        return value & 0xFFFFFFFE
    return None


def operand_value(instruction, operand, registers):
    """Read an ALU target operand; this never executes or updates machine state."""
    if operand.kind == 'immediate':
        value = operand.immediate & 0xFFFFFFFF
    elif operand.kind == 'register':
        value = (instruction.address + (8 if instruction.mode == 'arm' else 4)
                 if operand.register == 'pc' else registers[operand.register]) & 0xFFFFFFFF
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
        return ((registers['cpsr'] & 0x20000000) << 2) | (value >> 1)
    return None


def computed_target(instruction, registers, reads=()):
    """Evidence for common computed destinations, not an instruction allowlist."""
    operation, operands = instruction.decode.operation, instruction.decode.operands
    if operation in ('tbb', 'tbh'):
        width = 1 if operation == 'tbb' else 2
        base, index, displacement = operands[0].memory
        base_value = instruction.address + 4 if base == 'pc' else registers[base]
        address = (base_value + registers[index] * width + displacement) & 0xFFFFFFFF
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


def branch_result(instruction, before, after, reads=()):
    if not is_control_flow(instruction):
        return None
    operation = instruction.decode.operation
    operands = instruction.decode.operands
    kind = 'branch' if operation in ('b', 'bx', 'cbz', 'cbnz', 'tbb', 'tbh') else 'pc_write'
    if operation in ('bl', 'blx'):
        kind = 'call'
    elif operation == 'pop' or (operation == 'bx' and operands[0].register == 'lr'):
        kind = 'return'
    target = direct_target(instruction, before)
    if target is None:
        target = computed_target(instruction, before, reads)
    cond_passed = condition_passed(instruction, before)
    taken = cond_passed is not False
    condition = instruction.decode.condition
    if condition is None and instruction.mode == 'thumb':
        itstate = get_itstate(before['cpsr'])
        if itstate != 0:
            condition = IT_CONDITIONS.get(itstate >> 4, 'AL').lower()
    return dict(kind=kind, taken=taken, target=after['pc'] if target is None and taken else target,
                condition=condition, fallthrough=(instruction.address + instruction.size) & 0xFFFFFFFF)

