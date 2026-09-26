import pytest

from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation.memory import MemoryRegion, MemoryState


def program(address=0x1000):
    return parse(f"{address:x}: e3a00005 MOV r0,#5", mode="arm").program


def test_defaults_known_code_scratch_and_unknown_inspection():
    state = MemoryState.from_program(program())
    assert state.read(0x1000, 4) == bytes.fromhex("0500a0e3")
    assert state.inspect(0x1000, 1)[0].origin == "code"
    assert state.inspect(0x200FFFFC, 4)[0].origin == "scratch_stack"
    assert state.read(0x200FFFFC, 4) == bytes(4)
    previous = state.regions
    assert state.inspect(0x20100000, 1)[0].value is None
    assert state.inspect(0x1004, 1)[0].value is None
    assert state.regions is previous
    with pytest.raises(DomainError) as failure:
        state.read(0x1004, 4)
    assert failure.value.code == "unmapped_memory_access"
    assert failure.value.context["missing_ranges"] == ((0x1004, 4),)


def test_partial_repair_is_exact_and_immutable():
    initial = MemoryState.from_program(program())
    partial = initial.patch(0x2800, b"\x11\x22")
    with pytest.raises(DomainError) as failure:
        partial.read(0x2800, 4)
    assert failure.value.context["missing_ranges"] == ((0x2802, 2),)
    complete = partial.patch(0x2802, b"\x33\x44")
    assert complete.read(0x2800, 4) == bytes.fromhex("11223344")
    assert initial.inspect(0x2800, 1)[0].value is None
    assert partial.inspect(0x2802, 1)[0].value is None
    assert complete.inspect(0x2804, 1)[0].value is None


def test_patch_splits_and_merges_without_losing_origin_or_neighbors():
    state = MemoryState((MemoryRegion(0x2000, b"abcdef", "scratch_stack"),))
    patched = state.patch(0x2002, b"XY")
    assert [(r.address, r.raw_bytes, r.origin) for r in patched.regions] == [
        (0x2000, b"ab", "scratch_stack"), (0x2002, b"XY", "user"), (0x2004, b"ef", "scratch_stack")]
    assert patched.read(0x2000, 4) == b"abXY"
    assert state.read(0x2000, 4) == b"abcd"
    assert patched.patch(0x2000, b"123456").regions == (MemoryRegion(0x2000, b"123456", "user"),)


def test_code_overlap_rejects_entire_patch_and_store():
    state = MemoryState.from_program(program())
    for address, content in [(0x0FFE, b"1234"), (0x1002, b"1234")]:
        with pytest.raises(DomainError) as failure:
            state.patch(address, content)
        assert failure.value.code == "invalid_memory_patch"
    with pytest.raises(DomainError) as failure:
        state.validate_access(0x1000, 4, write=True)
    assert failure.value.code == "memory_permission_denied"
    assert state.read(0x1000, 4).hex() == "0500a0e3"
    assert state.inspect(0xFFE, 1)[0].value is None


def test_cross_region_access_and_missing_ranges():
    state = MemoryState((MemoryRegion(0x2000, b"ab", "scratch_stack"), MemoryRegion(0x2002, b"cd", "user")))
    assert state.read(0x2000, 4) == b"abcd"
    state.validate_access(0x2000, 4, write=True)
    holes = MemoryState((MemoryRegion(0x2001, b"a", "user"), MemoryRegion(0x2003, b"b", "user")))
    with pytest.raises(DomainError) as failure:
        holes.validate_access(0x2000, 4)
    assert failure.value.context["missing_ranges"] == ((0x2000, 1), (0x2002, 1))


def test_cross_page_access_and_alignment():
    state = MemoryState().patch(0x2FFC, b"abcdefgh")
    assert state.read(0x3000, 4) == b"efgh"
    assert state.inspect(0x2FFF, 2)[0].value == ord("d")
    with pytest.raises(DomainError) as failure:
        state.read(0x2FFF, 4)
    assert failure.value.code == "unaligned_memory_access"
    assert state.read(0x2FFF, 1) == b"d"


@pytest.mark.parametrize("address,size", [(-1, 1), (0, 0), (0xFFFFFFFF, 2), (0, 65537), (True, 1)])
def test_invalid_patch_ranges(address, size):
    with pytest.raises(DomainError):
        MemoryState().zero_fill(address, size)


def test_patch_inspection_and_address_limits():
    state = MemoryState().zero_fill(0xFFFF0000, 65536)
    assert state.inspect(0xFFFFFFFF, 1)[0].value == 0
    assert len(state.inspect(0xFFFF0000, 4096)) == 4096
    with pytest.raises(DomainError):
        state.inspect(0xFFFF0000, 4097)
    with pytest.raises(DomainError):
        state.patch(0, bytes(65537))


def test_memory_budget_includes_page_padding():
    regions = tuple(MemoryRegion(i * 8192, b"x", "user") for i in range(16384))
    at_limit = MemoryState(regions)
    with pytest.raises(DomainError) as failure:
        at_limit.patch(16384 * 8192, b"y")
    assert failure.value.context["budget"] == "backing_bytes"
    assert len(at_limit.regions) == 16384
    logical = MemoryState((MemoryRegion(0, bytes(16 << 20), "user"),))
    with pytest.raises(DomainError) as failure:
        logical.patch(16 << 20, b"x")
    assert failure.value.context["budget"] == "logical_bytes"


def test_stack_constraints_and_code_gap():
    with pytest.raises(DomainError) as failure:
        MemoryState.from_program(program(0x200F0000))
    assert failure.value.code == "stack_conflict"
    for base, size in [(0x2001, 4), (0x2000, 3), (0xFFFFFFFC, 4), (0x2000, 0), (0x2000, 1 << 30)]:
        with pytest.raises(DomainError):
            MemoryState.from_program(program(), stack_base=base, stack_size=size)
    image = parse("1000: e3a00005 MOV r0,#5\n1008: e3a00005 MOV r0,#5", mode="arm").program
    state = MemoryState.from_program(image, stack_base=0x3000, stack_size=4)
    assert state.inspect(0x1004, 1)[0].value is None
    assert state.inspect(0x3000, 1)[0].origin == "scratch_stack"
