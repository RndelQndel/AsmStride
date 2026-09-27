"""Immutable sparse logical memory. Mapped padding is never treated as known bytes."""

from dataclasses import dataclass
from typing import Literal, Mapping

from armstride.architecture.arm import STACK_BASE, STACK_SIZE
from armstride.domain.models import ADDRESS_SPACE, DomainError, ProgramImage, validate_range

MAX_LOGICAL_BYTES = 16 << 20
MAX_BACKING_BYTES = 64 << 20
MAX_PATCH_BYTES = 64 << 10
MAX_INSPECTION_BYTES = 4 << 10
PAGE_SIZE = 4096
Origin = Literal["code", "scratch_stack", "user"]


@dataclass(frozen=True, slots=True)
class MemoryRegion:
    address: int
    raw_bytes: bytes
    origin: Origin

    def __post_init__(self):
        if not isinstance(self.raw_bytes, bytes):
            raise TypeError("Region bytes must be immutable bytes.")
        validate_range(self.address, len(self.raw_bytes), "invalid_memory_patch")
        if self.origin not in ("code", "scratch_stack", "user"):
            raise DomainError("invalid_input", "Unknown memory origin.")

    @property
    def end(self) -> int:
        return self.address + len(self.raw_bytes)

    @property
    def writable(self) -> bool:
        return self.origin != "code"


@dataclass(frozen=True, slots=True)
class MemoryCell:
    address: int
    value: int | None
    origin: Origin | None


def backing_bytes(regions: tuple[MemoryRegion, ...]) -> int:
    total, end = 0, 0
    for region in regions:
        first = region.address // PAGE_SIZE
        last = (region.end + PAGE_SIZE - 1) // PAGE_SIZE
        total += max(0, last - max(first, end)) * PAGE_SIZE
        end = max(last, end)
    return total


def merge_regions(regions: tuple[MemoryRegion, ...]) -> tuple[MemoryRegion, ...]:
    merged, chunks = [], []
    start, end, origin = 0, 0, None
    for region in regions:
        if chunks and (region.address != end or region.origin != origin):
            merged.append(MemoryRegion(start, b"".join(chunks), origin))
            chunks = []
        if not chunks:
            start, origin = region.address, region.origin
        chunks.append(region.raw_bytes)
        end = region.end
    if chunks:
        merged.append(MemoryRegion(start, b"".join(chunks), origin))
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class MemoryState:
    regions: tuple[MemoryRegion, ...] = ()

    def __post_init__(self):
        ordered = tuple(sorted(self.regions, key=lambda region: region.address))
        if any(left.end > right.address for left, right in zip(ordered, ordered[1:])):
            raise DomainError("invalid_memory_patch", "Logical memory regions overlap.")
        logical = sum(len(region.raw_bytes) for region in ordered)
        backing = backing_bytes(ordered)
        if logical > MAX_LOGICAL_BYTES or backing > MAX_BACKING_BYTES:
            budget = "logical_bytes" if logical > MAX_LOGICAL_BYTES else "backing_bytes"
            raise DomainError("resource_limit", "Memory budget exceeded.", budget=budget,
                              requested=logical if budget == "logical_bytes" else backing,
                              limit=MAX_LOGICAL_BYTES if budget == "logical_bytes" else MAX_BACKING_BYTES)
        object.__setattr__(self, "regions", merge_regions(ordered))

    @classmethod
    def from_program(cls, program: ProgramImage, *, stack_base: int = STACK_BASE,
                     stack_size: int = STACK_SIZE) -> "MemoryState":
        validate_range(stack_base, stack_size, "invalid_memory_patch")
        if stack_base % 4 or stack_size % 4 or stack_base + stack_size >= ADDRESS_SPACE:
            raise DomainError("invalid_memory_patch", "Stack must be word-aligned with a representable top.")
        program_bytes_len = sum(i.size for i in program.instructions) + sum(d.size for d in program.data_regions)
        if stack_size + program_bytes_len > MAX_LOGICAL_BYTES:
            raise DomainError("resource_limit", "Stack exceeds the logical memory budget.",
                              budget="logical_bytes", limit=MAX_LOGICAL_BYTES)
        code = tuple(MemoryRegion(i.address, i.raw_bytes, "code") for i in program.instructions)
        data = tuple(MemoryRegion(d.address, d.data, "code" if not getattr(d, 'writable', False) else "user") for d in program.data_regions)
        all_program = code + data
        if any(region.address < stack_base + stack_size and region.end > stack_base for region in all_program):
            raise DomainError("stack_conflict", "Scratch stack overlaps code.")
        return cls(all_program + (MemoryRegion(stack_base, bytes(stack_size), "scratch_stack"),))

    def restore_bytes(self, modified_memory: dict[int, int] | Mapping[int, int]) -> "MemoryState":
        if not modified_memory:
            return self
        new_regions = []
        for region in self.regions:
            raw = bytearray(region.raw_bytes)
            changed = False
            for addr, val in modified_memory.items():
                if region.address <= addr < region.end:
                    raw[addr - region.address] = val
                    changed = True
            if changed:
                new_regions.append(MemoryRegion(region.address, bytes(raw), region.origin))
            else:
                new_regions.append(region)
        return MemoryState(tuple(new_regions))


    def patch(self, address: int, raw_bytes: bytes) -> "MemoryState":
        if not isinstance(raw_bytes, bytes):
            raise TypeError("Patches must be immutable bytes.")
        validate_range(address, len(raw_bytes), "invalid_memory_patch")
        if len(raw_bytes) > MAX_PATCH_BYTES:
            raise DomainError("input_limit", "Patch exceeds 64 KiB.", limit=MAX_PATCH_BYTES)
        end = address + len(raw_bytes)
        affected = tuple(region for region in self.regions if region.address < end and region.end > address)
        if any(region.origin == "code" for region in affected):
            raise DomainError("invalid_memory_patch", "A patch cannot overlap code.")
        retained = []
        for region in self.regions:
            if region.end <= address or region.address >= end:
                retained.append(region)
                continue
            if region.address < address:
                retained.append(MemoryRegion(region.address, region.raw_bytes[:address - region.address], region.origin))
            if region.end > end:
                retained.append(MemoryRegion(end, region.raw_bytes[end - region.address:], region.origin))
        return MemoryState(tuple(retained) + (MemoryRegion(address, raw_bytes, "user"),))

    def zero_fill(self, address: int, size: int) -> "MemoryState":
        validate_range(address, size, "invalid_memory_patch")
        if size > MAX_PATCH_BYTES:
            raise DomainError("input_limit", "Zero-fill exceeds 64 KiB.", limit=MAX_PATCH_BYTES)
        return self.patch(address, bytes(size))

    def inspect(self, address: int, size: int) -> tuple[MemoryCell, ...]:
        validate_range(address, size)
        if size > MAX_INSPECTION_BYTES:
            raise DomainError("input_limit", "Inspection exceeds 4 KiB.", limit=MAX_INSPECTION_BYTES)
        cells = [MemoryCell(byte, None, None) for byte in range(address, address + size)]
        for region in self.regions:
            first, last = max(address, region.address), min(address + size, region.end)
            for byte in range(first, last):
                cells[byte - address] = MemoryCell(byte, region.raw_bytes[byte - region.address], region.origin)
        return tuple(cells)

    def validate_access(self, address: int, size: int, *, write: bool = False) -> None:
        validate_range(address, size, "unmapped_memory_access")
        access = "write" if write else "read"
        if size > 1 and address % size:
            raise DomainError("unaligned_memory_access", "Data access requires natural alignment.",
                              address=address, size=size, access=access)
        cursor, missing = address, []
        for region in self.regions:
            if region.end <= address or region.address >= address + size:
                continue
            if write and not region.writable:
                raise DomainError("memory_permission_denied", "Code is not writable.",
                                  address=address, size=size, access=access)
            if region.address > cursor:
                missing.append((cursor, region.address - cursor))
            cursor = max(cursor, min(region.end, address + size))
        if cursor < address + size:
            missing.append((cursor, address + size - cursor))
        if missing:
            raise DomainError("unmapped_memory_access", "Access includes unknown bytes.",
                              address=address, size=size, access=access, missing_ranges=tuple(missing))

    def read(self, address: int, size: int) -> bytes:
        self.validate_access(address, size)
        return b"".join(region.raw_bytes[max(address, region.address) - region.address:
                                        min(address + size, region.end) - region.address]
                        for region in self.regions if region.address < address + size and region.end > address)
