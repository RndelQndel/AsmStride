"""Destination evidence must fail closed without executing a native CPU."""

from dataclasses import replace

import pytest

from armstride.architecture.arm import initial_registers
from armstride.architecture.control_flow import computed_target
from armstride.architecture.decode import ArmDecoder
from armstride.backends.unicorn import UnicornBackend
from armstride.domain.models import Operand
from armstride.simulation.memory import MemoryState
from armstride.simulation.state import MachineState


@pytest.mark.parametrize('fetches,pc', [([], 0x9000), ([0x1000], 0x9000),
                                      ([0x9000, 0x9000], 0x9000), ([0x8000], 0x8000)])
def test_computed_fetch_requires_matching_unique_destination(fetches, pc):
    instruction = ArmDecoder('arm').decode(0x1000, bytes.fromhex('02f183e0'), 1, '', '')
    registers = dict(initial_registers('arm', 0x1000)) | {'r3': 0x8000, 'r2': 0x400}
    state = MachineState(registers, MemoryState())
    assert not UnicornBackend._retired_fetch(instruction, state, registers | {'pc': pc}, [], fetches)
    assert UnicornBackend._retired_fetch(instruction, state, registers | {'pc': 0x9000}, [], [0x9000])


@pytest.mark.parametrize('reads', [[], [{'address': 0x2801, 'size': 2, 'bytes': 'fe3f'}],
                                  [{'address': 0x2800, 'size': 1, 'bytes': 'fe'}]])
def test_table_branch_requires_correct_read_evidence(reads):
    instruction = ArmDecoder('thumb').decode(0x1000, bytes.fromhex('d4e812f0'), 1, '', '')
    registers = dict(initial_registers('thumb', 0x1000)) | {'r4': 0x2800}
    assert computed_target(instruction, registers, reads) is None
    valid = [{'address': 0x2800, 'size': 2, 'bytes': 'fe3f'}]
    assert computed_target(instruction, registers, valid) == 0x9000


def test_unknown_computed_form_has_no_fabricated_evidence():
    instruction = ArmDecoder('arm').decode(0x1000, bytes.fromhex('02f183e0'), 1, '', '')
    registers = dict(initial_registers('arm', 0x1000))
    metadata = replace(instruction.decode, operation='unrecognized')
    assert computed_target(replace(instruction, decode=metadata), registers) is None
    metadata = replace(instruction.decode, operands=(Operand('register', register='pc'),
        Operand('register', register='r3'), Operand('register', register='r2', shift=('lsl_reg', 'r1'))))
    assert computed_target(replace(instruction, decode=metadata), registers) is None


@pytest.mark.parametrize('encoded', ['0ef0b0e1', '04f05ee2'])
def test_exception_return_forms_are_explicitly_excluded(encoded):
    instruction = ArmDecoder('arm').decode(0x1000, bytes.fromhex(encoded), 1, '', '')
    assert instruction.feature_exclusion == 'Exception-return state is outside P0.'
