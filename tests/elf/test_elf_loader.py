"""Unit and integration tests for Stage P2-A and P2-B ELF loading (P2-AC-01 through P2-AC-10)."""

import pytest

from armstride.domain.models import DomainError, MAX_ELF_FILE_BYTES, MAX_ELF_SEGMENTS
from armstride.elf.loader import load_elf
from armstride.simulation.session import SimulationSession
from tests.elf.elf_builder import make_elf

# Minimal ARM instructions:
# 0x8000: mov r0, #42   (E3A0002A)
# 0x8004: bx lr         (E12FFF1E)
ARM_CODE = bytes.fromhex("2a00a0e3 1eff2fe1")

# Minimal Thumb instructions:
# 0x8000: movs r0, #42  (202a)
# 0x8002: bx lr         (4770)
THUMB_CODE = bytes.fromhex("2a20 7047")


def test_p2_ac_01_valid_arm_elf_loading():
    """P2-AC-01: Statically linked 32-bit LE ARM ET_EXEC binary loads into a standard ProgramImage."""
    raw_elf = make_elf(
        code=ARM_CODE,
        entry_point=0x8000,
        mapping_symbols=[(0x8000, 'arm')],
        symbols=[{'name': 'main', 'address': 0x8000, 'size': 8, 'type': 'func', 'bind': 'global'}],
    )
    prog, meta, entry_pc, mode = load_elf(raw_elf)

    assert prog.format == 'elf'
    assert prog.mode == 'arm'
    assert entry_pc == 0x8000
    assert len(prog.instructions) == 2
    assert prog.instructions[0].address == 0x8000
    assert prog.instructions[1].address == 0x8004
    assert meta.symbols.by_name['main'].address == 0x8000

    # Verify execution on standard simulation session
    session = SimulationSession()
    session.load(prog, initial_pc=entry_pc, metadata=meta)
    res = session.step()
    assert res['status'] == 'executed'
    assert session.runtime.registers['r0'] == 42


def test_p2_ac_02_unsupported_formats_rejected():
    """P2-AC-02: Unsupported ELF formats are rejected atomically with actionable diagnostics."""
    # 64-bit ELF class
    raw_elf64 = make_elf(code=ARM_CODE, elf_class=2)
    with pytest.raises(DomainError) as exc:
        load_elf(raw_elf64)
    assert exc.value.code == 'unsupported_elf_class'

    # Big-endian
    raw_be = make_elf(code=ARM_CODE, endianness=2)
    with pytest.raises(DomainError) as exc:
        load_elf(raw_be)
    assert exc.value.code == 'unsupported_elf_type'

    # Non-ARM machine (x86_64 = 62)
    raw_x86 = make_elf(code=ARM_CODE, machine=62)
    with pytest.raises(DomainError) as exc:
        load_elf(raw_x86)
    assert exc.value.code == 'unsupported_elf_machine'

    # ET_DYN (Position-Independent Executable / PIE)
    raw_pie = make_elf(code=ARM_CODE, elf_type=3)
    with pytest.raises(DomainError) as exc:
        load_elf(raw_pie)
    assert exc.value.code == 'elf_pie_unsupported'

    # ET_REL (Relocatable object file)
    raw_rel = make_elf(code=ARM_CODE, elf_type=1)
    with pytest.raises(DomainError) as exc:
        load_elf(raw_rel)
    assert exc.value.code == 'elf_relocation_unsupported'

    # Dynamic linking (PT_INTERP segment)
    interp_seg = {
        'p_type': 3,  # PT_INTERP
        'p_vaddr': 0x7000,
        'p_paddr': 0x7000,
        'p_filesz': 16,
        'p_memsz': 16,
        'p_flags': 4,
        'p_align': 1,
        'data': b'/lib/ld-linux.so',
    }
    raw_interp = make_elf(code=ARM_CODE, extra_segments=[interp_seg])
    with pytest.raises(DomainError) as exc:
        load_elf(raw_interp)
    assert exc.value.code == 'elf_dynamic_linking_unsupported'


def test_p2_ac_03_mapping_symbols_partitioning_and_literal_pools():
    """P2-AC-03: Partitioning via mapping symbols ($a, $t, $d); $d inline data remain non-executable DataRegions."""
    # 0x8000: ARM code: mov r0, #1; bx pc; nop (8 bytes) -> switches to Thumb
    # 0x8008: Thumb code: movs r1, #2; bx lr (4 bytes)
    # 0x800C: Data pool ($d): 0xDEADBEEF (4 bytes)
    arm_part = bytes.fromhex("0100a0e3 1e2ff1e1")  # mov r0, #1; bx pc
    thumb_part = bytes.fromhex("0221 7047")        # movs r1, #2; bx lr
    data_part = bytes.fromhex("efbeadde")         # 0xDEADBEEF

    mixed_code = arm_part + thumb_part + data_part
    raw_elf = make_elf(
        code=mixed_code,
        entry_point=0x8000,
        mapping_symbols=[
            (0x8000, 'arm'),
            (0x8008, 'thumb'),
            (0x800C, 'data'),
        ],
    )
    prog, meta, entry_pc, mode = load_elf(raw_elf)

    assert len(prog.instructions) == 4
    assert prog.instructions[0].address == 0x8000
    assert prog.instructions[0].mode == 'arm'
    assert prog.instructions[2].address == 0x8008
    assert prog.instructions[2].mode == 'thumb'

    # $d range becomes DataRegion
    assert len(prog.data_regions) == 1
    assert prog.data_regions[0].address == 0x800C
    assert prog.data_regions[0].size == 4
    assert prog.data_regions[0].data == data_part

    # Test branching into $d halts with non_executable_target
    session = SimulationSession()
    session.load(prog, initial_pc=0x800C)
    res = session.step()
    assert res['status'] == 'failed'
    assert res['stop_reason'] == 'non_executable_target'


def test_p2_ac_03_ambiguous_mixed_regions_fail_closed():
    """P2-AC-03: Mixed executable segments lacking mapping symbols fail closed with ambiguous_elf_execution_mode."""
    # Code without mapping symbols and not matching entry point mode across whole segment
    raw_elf = make_elf(
        code=ARM_CODE,
        entry_point=0x9000,  # entry point outside this segment
        mapping_symbols=None,
        is_stripped=False,
    )
    with pytest.raises(DomainError) as exc:
        load_elf(raw_elf)
    assert exc.value.code == 'ambiguous_elf_execution_mode'


def test_p2_ac_04_bss_zero_expansion():
    """P2-AC-04: PT_LOAD trailing interval [p_vaddr + p_filesz, p_vaddr + p_memsz) initialized to zeros."""
    # Code is 8 bytes, memsz is 16 bytes (8 bytes of BSS)
    raw_elf = make_elf(
        code=ARM_CODE,
        entry_point=0x8000,
        memsz=16,
        mapping_symbols=[(0x8000, 'arm')],
    )
    prog, meta, entry_pc, mode = load_elf(raw_elf)

    assert any(dr.address == 0x8008 and dr.size == 8 and dr.data == b'\x00' * 8
               for dr in prog.data_regions)

    session = SimulationSession()
    session.load(prog, initial_pc=entry_pc)
    # MemoryState inspect reads trailing zeros
    cells = session.inspect_memory(0x8008, 8)
    assert all(c.value == 0 for c in cells)


def test_p2_ac_05_entry_point_thumb_bit0_resolution():
    """P2-AC-05: e_entry resolves Thumb mode (bit 0 == 1) with canonicalized even PC."""
    raw_elf = make_elf(
        code=THUMB_CODE,
        entry_point=0x8001,  # bit 0 set
        mapping_symbols=[(0x8000, 'thumb')],
    )
    prog, meta, entry_pc, mode = load_elf(raw_elf)

    assert mode == 'thumb'
    assert entry_pc == 0x8000

    session = SimulationSession()
    session.load(prog, initial_pc=entry_pc)
    assert session.runtime.registers['pc'] == 0x8000
    assert (session.runtime.registers['cpsr'] & 0x20) != 0  # Thumb T-bit set


def test_p2_ac_05_entry_point_at_address_zero():
    """P2-AC-05: Address 0x00000000 is valid if mapped."""
    raw_elf = make_elf(
        code=ARM_CODE,
        vaddr=0x00000000,
        entry_point=0x00000000,
        mapping_symbols=[(0x00000000, 'arm')],
    )
    prog, meta, entry_pc, mode = load_elf(raw_elf)

    assert entry_pc == 0x00000000
    session = SimulationSession()
    session.load(prog, initial_pc=entry_pc)
    assert session.runtime.registers['pc'] == 0x00000000
    res = session.step()
    assert res['status'] == 'executed'


def test_p2_ac_06_resource_bounds_enforced():
    """P2-AC-06: Independent operational bounds enforced; violations rejected with elf_resource_limit_exceeded."""
    # Too many segments (> 32)
    extra_segs = [{
        'p_type': 1,
        'p_vaddr': 0x10000 + i * 0x1000,
        'p_paddr': 0x10000 + i * 0x1000,
        'p_filesz': 4,
        'p_memsz': 4,
        'p_flags': 6,
        'p_align': 4,
        'data': b'\x00\x00\x00\x00',
    } for i in range(35)]

    raw_too_many_segs = make_elf(code=ARM_CODE, extra_segments=extra_segs)
    with pytest.raises(DomainError) as exc:
        load_elf(raw_too_many_segs)
    assert exc.value.code == 'elf_resource_limit_exceeded'

    # File size limit (> 10 MiB)
    with pytest.raises(DomainError) as exc:
        load_elf(b'\x7fELF' + b'\x00' * (MAX_ELF_FILE_BYTES + 1))
    assert exc.value.code == 'elf_resource_limit_exceeded'


def test_p2_ac_07_stripped_and_unstripped_equivalence():
    """P2-AC-07: Unstripped symbols resolve; stripped ELF executes identically."""
    raw_unstripped = make_elf(
        code=ARM_CODE,
        entry_point=0x8000,
        mapping_symbols=[(0x8000, 'arm')],
        symbols=[{'name': 'main', 'address': 0x8000, 'size': 8, 'type': 'func', 'bind': 'global'}],
        is_stripped=False,
    )
    prog_u, meta_u, entry_u, mode_u = load_elf(raw_unstripped)
    assert 'main' in meta_u.symbols.by_name

    raw_stripped = make_elf(
        code=ARM_CODE,
        entry_point=0x8000,
        is_stripped=True,
    )
    prog_s, meta_s, entry_s, mode_s = load_elf(raw_stripped)
    assert len(meta_s.symbols.by_name) == 0

    # Step both and verify identical machine state
    session_u = SimulationSession()
    session_u.load(prog_u, initial_pc=entry_u)
    res_u = session_u.step()

    session_s = SimulationSession()
    session_s.load(prog_s, initial_pc=entry_s)
    res_s = session_s.step()

    assert res_u['status'] == res_s['status'] == 'executed'
    assert session_u.runtime.registers == session_s.runtime.registers


def test_p2_ac_08_multiple_symbols_at_same_address():
    """P2-AC-08: Multiple symbols at same address resolve deterministically."""
    raw_elf = make_elf(
        code=ARM_CODE,
        entry_point=0x8000,
        mapping_symbols=[(0x8000, 'arm')],
        symbols=[
            {'name': '_start', 'address': 0x8000, 'size': 8, 'type': 'func', 'bind': 'global'},
            {'name': 'entry_label', 'address': 0x8000, 'size': 0, 'type': 'label', 'bind': 'local'},
        ],
    )
    prog, meta, entry_pc, mode = load_elf(raw_elf)
    entries = meta.symbols.by_address[0x8000]
    assert len(entries) == 2
    names = [e.name for e in entries]
    assert '_start' in names and 'entry_label' in names
