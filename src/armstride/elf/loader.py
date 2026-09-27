"""ELF32 little-endian loader producing standard ProgramImage and ProgramMetadata."""

import io
from typing import Any
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

from armstride.architecture.decode import ArmDecoder
from armstride.domain.models import (
    DataRegion,
    DomainError,
    ElfInfo,
    Instruction,
    MAX_BACKING_PAGES_BYTES,
    MAX_ELF_FILE_BYTES,
    MAX_ELF_SECTIONS,
    MAX_ELF_SEGMENTS,
    MAX_INSTRUCTIONS,
    MAX_LOGICAL_MEMORY_BYTES,
    Mode,
    ProgramImage,
    ProgramMetadata,
)
from armstride.elf.dwarf import extract_dwarf_lines
from armstride.elf.symbols import extract_mapping_symbols, extract_symbols
from armstride.simulation.memory import PAGE_SIZE


def _backing_bytes_for_ranges(ranges: list[tuple[int, int]]) -> int:
    pages: set[int] = set()
    for addr, size in ranges:
        if size <= 0:
            continue
        first_page = (addr // PAGE_SIZE) * PAGE_SIZE
        last_page = ((addr + size + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
        for p in range(first_page, last_page, PAGE_SIZE):
            pages.add(p)
    return len(pages) * PAGE_SIZE


def validate_elf_header(elf: ELFFile, raw_bytes_len: int) -> None:
    """Validate ELF header strictly per Product P2 specifications."""
    if raw_bytes_len > MAX_ELF_FILE_BYTES:
        raise DomainError(
            'elf_resource_limit_exceeded',
            'ELF file size exceeds 10 MiB limit.',
            limit=MAX_ELF_FILE_BYTES,
            actual=raw_bytes_len,
        )

    # ELF Class
    if elf.elfclass == 64:
        raise DomainError(
            'unsupported_elf_class',
            '64-bit ELF executables are not supported; expected 32-bit ELF.',
            elfclass=64,
        )
    if elf.elfclass != 32:
        raise DomainError(
            'unsupported_elf_class',
            f'Unsupported ELF class {elf.elfclass}; expected 32-bit ELF.',
            elfclass=elf.elfclass,
        )

    # Endianness
    ei_data = elf.header['e_ident'].get('EI_DATA')
    if ei_data == 'ELFDATA2MSB':
        raise DomainError(
            'unsupported_elf_type',
            'Big-endian ELF is not supported; expected little-endian.',
            endianness='big',
        )
    if ei_data != 'ELFDATA2LSB':
        raise DomainError(
            'unsupported_elf_type',
            f'Unsupported ELF data encoding {ei_data}; expected little-endian.',
        )

    # Machine architecture
    machine = elf.header.get('e_machine')
    if machine not in ('EM_ARM', 40):
        raise DomainError(
            'unsupported_elf_machine',
            f'Unsupported machine architecture {machine}; expected EM_ARM.',
            machine=machine,
        )

    # ELF Type
    e_type = elf.header.get('e_type')
    if e_type == 'ET_DYN':
        raise DomainError(
            'elf_pie_unsupported',
            'Position-independent executables (ET_DYN / PIE) are not supported in P2; provide a statically linked ET_EXEC executable.',
            elf_type='ET_DYN',
        )
    if e_type == 'ET_REL':
        raise DomainError(
            'elf_relocation_unsupported',
            'Relocatable object files (ET_REL) are not supported; provide a linked executable.',
            elf_type='ET_REL',
        )
    if e_type != 'ET_EXEC':
        raise DomainError(
            'unsupported_elf_type',
            f'Unsupported ELF type {e_type}; expected ET_EXEC.',
            elf_type=e_type,
        )

    # Segments count limit
    if elf.num_segments() > MAX_ELF_SEGMENTS:
        raise DomainError(
            'elf_resource_limit_exceeded',
            f'ELF segment count {elf.num_segments()} exceeds {MAX_ELF_SEGMENTS}.',
            limit=MAX_ELF_SEGMENTS,
            actual=elf.num_segments(),
        )

    # Sections count limit
    if elf.num_sections() > MAX_ELF_SECTIONS:
        raise DomainError(
            'elf_resource_limit_exceeded',
            f'ELF section count {elf.num_sections()} exceeds {MAX_ELF_SECTIONS}.',
            limit=MAX_ELF_SECTIONS,
            actual=elf.num_sections(),
        )

    # Dynamic linking checks
    for seg in elf.iter_segments():
        if seg['p_type'] in ('PT_INTERP', 'PT_DYNAMIC'):
            raise DomainError(
                'elf_dynamic_linking_unsupported',
                'Dynamic linking and PT_INTERP / PT_DYNAMIC are not supported; provide a statically linked binary.',
            )

    for sec in elf.iter_sections():
        sec_name = sec.name
        if sec_name in ('.rel.dyn', '.rela.dyn', '.rel.plt', '.rela.plt') or sec['sh_type'] in ('SHT_DYNAMIC', 'SHT_REL', 'SHT_RELA'):
            # If section contains dynamic relocations
            if 'dyn' in sec_name or 'plt' in sec_name or sec['sh_type'] == 'SHT_DYNAMIC':
                raise DomainError(
                    'elf_dynamic_linking_unsupported',
                    f'Dynamic section/relocation {sec_name} is not supported; provide a statically linked binary.',
                )


def load_elf(
    raw_bytes: bytes,
    profile: str = "armv7-a-le",
) -> tuple[ProgramImage, ProgramMetadata, int, Mode]:
    """Load an ARM ELF32-LE ET_EXEC binary into ProgramImage and ProgramMetadata."""
    if len(raw_bytes) > MAX_ELF_FILE_BYTES:
        raise DomainError(
            'elf_resource_limit_exceeded',
            'ELF file size exceeds 10 MiB limit.',
            limit=MAX_ELF_FILE_BYTES,
            actual=len(raw_bytes),
        )

    f = io.BytesIO(raw_bytes)
    try:
        elf = ELFFile(f)
    except ELFError as error:
        raise DomainError('invalid_encoding', f'Malformed ELF binary: {error}') from error

    validate_elf_header(elf, len(raw_bytes))

    load_segments = [seg for seg in elf.iter_segments() if seg['p_type'] == 'PT_LOAD']
    if not load_segments:
        raise DomainError('empty_program', 'ELF executable has no PT_LOAD segments.')

    # Resource bounds: total logical loaded memory
    total_logical = sum(seg['p_memsz'] for seg in load_segments)
    if total_logical > MAX_LOGICAL_MEMORY_BYTES:
        raise DomainError(
            'elf_resource_limit_exceeded',
            f'Total logical loaded memory ({total_logical} bytes) exceeds 16 MiB.',
            limit=MAX_LOGICAL_MEMORY_BYTES,
            actual=total_logical,
        )

    # Resource bounds: backing pages
    memory_ranges = [(seg['p_vaddr'], seg['p_memsz']) for seg in load_segments]
    total_backing = _backing_bytes_for_ranges(memory_ranges)
    if total_backing > MAX_BACKING_PAGES_BYTES:
        raise DomainError(
            'elf_resource_limit_exceeded',
            f'Backing page allocation ({total_backing} bytes) exceeds 64 MiB.',
            limit=MAX_BACKING_PAGES_BYTES,
            actual=total_backing,
        )

    # Check segment overlap
    sorted_segs = sorted(load_segments, key=lambda s: s['p_vaddr'])
    for prev, curr in zip(sorted_segs, sorted_segs[1:]):
        if prev['p_vaddr'] + prev['p_memsz'] > curr['p_vaddr']:
            raise DomainError('overlapping_data', 'ELF loadable segments overlap.')

    # Extract symbols & DWARF
    symbols = extract_symbols(elf)
    mapping_symbols = extract_mapping_symbols(elf)
    lines = extract_dwarf_lines(elf)
    is_stripped = elf.get_section_by_name('.symtab') is None

    # Entry point resolution
    raw_entry = elf.header['e_entry']
    if raw_entry & 1 == 1:
        initial_mode: Mode = 'thumb'
        canonical_entry = raw_entry & ~1
    else:
        initial_mode = 'arm'
        canonical_entry = raw_entry

    all_instructions: list[Instruction] = []
    all_data_regions: list[DataRegion] = []

    arm_decoder = ArmDecoder('arm')
    thumb_decoder = ArmDecoder('thumb')

    for seg in sorted_segs:
        vaddr = seg['p_vaddr']
        filesz = seg['p_filesz']
        memsz = seg['p_memsz']
        flags = seg['p_flags']
        is_executable = bool(flags & 1)
        is_writable = bool(flags & 2)

        seg_data = seg.data()[:filesz]

        if not is_executable:
            # Standalone data segment
            if filesz > 0:
                all_data_regions.append(
                    DataRegion(address=vaddr, data=seg_data, writable=is_writable)
                )
            if memsz > filesz:
                bss_size = memsz - filesz
                all_data_regions.append(
                    DataRegion(address=vaddr + filesz, data=b'\x00' * bss_size, writable=is_writable)
                )
            continue

        # Executable segment
        seg_mapping = [ms for ms in mapping_symbols if vaddr <= ms[0] < vaddr + filesz]

        if seg_mapping:
            # Partition using mapping symbols
            # If the first mapping symbol is after vaddr, check if entry point determines mode
            if seg_mapping[0][0] > vaddr:
                if canonical_entry == vaddr or vaddr <= canonical_entry < seg_mapping[0][0]:
                    seg_mapping.insert(0, (vaddr, initial_mode))
                else:
                    raise DomainError(
                        'ambiguous_elf_execution_mode',
                        f'Segment at {hex(vaddr)} lacks mapping symbol at start.',
                    )

            # Build intervals: (start_addr, end_addr, mode)
            for i, (addr, mode) in enumerate(seg_mapping):
                next_addr = seg_mapping[i + 1][0] if i + 1 < len(seg_mapping) else vaddr + filesz
                chunk_len = next_addr - addr
                if chunk_len <= 0:
                    continue
                offset = addr - vaddr
                chunk_bytes = seg_data[offset : offset + chunk_len]

                if mode == 'arm':
                    decoded = arm_decoder.decode_stream(addr, chunk_bytes)
                    all_instructions.extend(decoded)
                elif mode == 'thumb':
                    decoded = thumb_decoder.decode_stream(addr, chunk_bytes)
                    all_instructions.extend(decoded)
                elif mode == 'data':
                    all_data_regions.append(
                        DataRegion(address=addr, data=chunk_bytes, writable=is_writable)
                    )
        else:
            # No mapping symbols in this executable segment
            # Try to decode based on initial mode if entry point is in this segment
            seg_mode: Mode | None = None
            if vaddr <= canonical_entry < vaddr + filesz:
                seg_mode = initial_mode
            elif not is_stripped:
                # If unstripped but missing mapping symbols for executable code
                raise DomainError(
                    'ambiguous_elf_execution_mode',
                    f'Executable segment at {hex(vaddr)} lacks ARM mapping symbols ($a, $t, $d).',
                )
            else:
                # Stripped ELF: fallback to initial mode
                seg_mode = initial_mode

            if seg_mode is None:
                raise DomainError(
                    'ambiguous_elf_execution_mode',
                    f'Cannot determine execution mode for executable segment at {hex(vaddr)}.',
                )

            decoder = thumb_decoder if seg_mode == 'thumb' else arm_decoder
            try:
                decoded = decoder.decode_stream(vaddr, seg_data)
                all_instructions.extend(decoded)
            except Exception as error:
                raise DomainError(
                    'ambiguous_elf_execution_mode',
                    f'Failed to decode executable segment at {hex(vaddr)} with mode {seg_mode}: {error}',
                ) from error

        # Trailing BSS in executable segment
        if memsz > filesz:
            bss_size = memsz - filesz
            all_data_regions.append(
                DataRegion(address=vaddr + filesz, data=b'\x00' * bss_size, writable=is_writable)
            )

    if len(all_instructions) > MAX_INSTRUCTIONS:
        raise DomainError(
            'elf_resource_limit_exceeded',
            f'Instruction count {len(all_instructions)} exceeds {MAX_INSTRUCTIONS}.',
            limit=MAX_INSTRUCTIONS,
            actual=len(all_instructions),
        )

    if not all_instructions:
        raise DomainError('empty_program', 'ELF executable contains no decoded instructions.')

    instructions_by_addr = {i.address: i for i in all_instructions}
    if canonical_entry not in instructions_by_addr:
        raise DomainError(
            'invalid_pc',
            f'Entry point {hex(canonical_entry)} does not match a loaded instruction start.',
            entry_point=canonical_entry,
        )

    program = ProgramImage(
        instructions=tuple(all_instructions),
        mode=initial_mode,
        source_text="[ELF executable]",
        format="elf",
        profile=profile,
        data_regions=tuple(all_data_regions),
    )

    elf_info = ElfInfo(
        entry_point=canonical_entry,
        initial_mode=initial_mode,
        segment_count=len(load_segments),
        section_count=elf.num_sections(),
        is_stripped=is_stripped,
        has_dwarf=elf.has_dwarf_info(),
    )

    metadata = ProgramMetadata(
        symbols=symbols,
        lines=lines,
        elf_info=elf_info,
    )

    return program, metadata, canonical_entry, initial_mode
