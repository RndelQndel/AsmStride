"""Helper to build test ARM ELF32-LE binaries for unit and integration testing."""

import struct


def build_strtab(strings: list[str]) -> tuple[bytes, dict[str, int]]:
    table = b'\x00'
    offsets: dict[str, int] = {}
    for s in strings:
        offsets[s] = len(table)
        table += s.encode('utf-8') + b'\x00'
    return table, offsets


def make_elf(
    *,
    code: bytes,
    entry_point: int = 0x8000,
    vaddr: int = 0x8000,
    memsz: int | None = None,
    p_flags: int = 5,  # PF_R | PF_X
    elf_class: int = 1,  # 1 = 32-bit, 2 = 64-bit
    endianness: int = 1,  # 1 = little-endian, 2 = big-endian
    machine: int = 40,  # 40 = EM_ARM
    elf_type: int = 2,  # 2 = ET_EXEC, 1 = ET_REL, 3 = ET_DYN
    data_segments: list[dict] | None = None,
    symbols: list[dict] | None = None,  # list of {name, address, size, type, bind}
    mapping_symbols: list[tuple[int, str]] | None = None,  # list of (address, mode: 'arm'|'thumb'|'data')
    extra_segments: list[dict] | None = None,
    extra_sections: list[dict] | None = None,
    is_stripped: bool = False,
) -> bytes:
    if memsz is None:
        memsz = len(code)

    all_segments = []
    # Primary code segment
    all_segments.append({
        'p_type': 1,  # PT_LOAD
        'p_vaddr': vaddr,
        'p_paddr': vaddr,
        'p_filesz': len(code),
        'p_memsz': memsz,
        'p_flags': p_flags,
        'p_align': 4,
        'data': code,
    })

    if data_segments:
        for ds in data_segments:
            d_data = ds.get('data', b'')
            all_segments.append({
                'p_type': 1,
                'p_vaddr': ds['vaddr'],
                'p_paddr': ds['vaddr'],
                'p_filesz': len(d_data),
                'p_memsz': ds.get('memsz', len(d_data)),
                'p_flags': ds.get('flags', 6),  # PF_R | PF_W
                'p_align': 4,
                'data': d_data,
            })

    if extra_segments:
        all_segments.extend(extra_segments)

    # 32-bit ELF header: 52 bytes
    # Program header: 32 bytes each
    ph_count = len(all_segments)
    ph_off = 52
    ph_size = 32
    body_offset = ph_off + ph_count * ph_size

    # Assign file offsets to segments
    curr_offset = body_offset
    for seg in all_segments:
        seg['p_offset'] = curr_offset
        curr_offset += len(seg.get('data', b''))

    # Sections & Symbols (if not stripped)
    sections = []
    shstr_names = ['.shstrtab']
    str_names: list[str] = []

    if not is_stripped:
        shstr_names.extend(['.text', '.symtab', '.strtab'])
        if symbols:
            str_names.extend(s['name'] for s in symbols)
        if mapping_symbols:
            for _, mode in mapping_symbols:
                tag = '$a' if mode == 'arm' else '$t' if mode == 'thumb' else '$d'
                if tag not in str_names:
                    str_names.append(tag)

    shstrtab, shstr_offs = build_strtab(shstr_names)
    strtab, str_offs = build_strtab(str_names)

    symtab_bytes = b''
    if not is_stripped:
        # Symbol 0: STN_UNDEF
        sym_entries = [struct.pack('<IIIBBH', 0, 0, 0, 0, 0, 0)]
        if mapping_symbols:
            for addr, mode in mapping_symbols:
                tag = '$a' if mode == 'arm' else '$t' if mode == 'thumb' else '$d'
                sym_entries.append(struct.pack('<IIIBBH', str_offs[tag], addr, 0, 0, 0, 1))
        if symbols:
            for s in symbols:
                st_type = 2 if s.get('type') == 'func' else 1 if s.get('type') == 'object' else 0
                st_bind = 1 if s.get('bind') == 'global' else 0
                info = (st_bind << 4) | (st_type & 0xf)
                s_addr = s['address']
                if s.get('type') == 'func' and s.get('mode') == 'thumb':
                    s_addr |= 1
                sym_entries.append(struct.pack('<IIIBBH', str_offs[s['name']], s_addr, s.get('size', 0), info, 0, 1))
        symtab_bytes = b''.join(sym_entries)

    sh_offset = curr_offset
    # Section headers:
    # 0: NULL
    # 1: .text
    # 2: .symtab
    # 3: .strtab
    # 4: .shstrtab
    sec_headers = []
    if not is_stripped:
        sec_data_offset = sh_offset
        shstrtab_offset = sec_data_offset
        strtab_offset = shstrtab_offset + len(shstrtab)
        symtab_offset = strtab_offset + len(strtab)
        final_sh_offset = symtab_offset + len(symtab_bytes)

        # 0: NULL
        sec_headers.append(struct.pack('<IIIIIIIIII', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        # 1: .text
        sec_headers.append(struct.pack('<IIIIIIIIII', shstr_offs['.text'], 1, 6, vaddr, all_segments[0]['p_offset'], len(code), 0, 0, 4, 0))
        # 2: .symtab (type 2, link to .strtab index 3)
        sec_headers.append(struct.pack('<IIIIIIIIII', shstr_offs['.symtab'], 2, 0, 0, symtab_offset, len(symtab_bytes), 3, 1, 4, 16))
        # 3: .strtab (type 3)
        sec_headers.append(struct.pack('<IIIIIIIIII', shstr_offs['.strtab'], 3, 0, 0, strtab_offset, len(strtab), 0, 0, 1, 0))
        # 4: .shstrtab (type 3)
        sec_headers.append(struct.pack('<IIIIIIIIII', shstr_offs['.shstrtab'], 3, 0, 0, shstrtab_offset, len(shstrtab), 0, 0, 1, 0))

        sh_num = len(sec_headers)
        sh_str_idx = 4
        sh_table_offset = final_sh_offset
    else:
        sh_num = 0
        sh_str_idx = 0
        sh_table_offset = 0

    # Build ELF header
    e_ident = bytearray(16)
    e_ident[0:4] = b'\x7fELF'
    e_ident[4] = elf_class
    e_ident[5] = endianness
    e_ident[6] = 1  # version
    fmt = '<' if endianness == 1 else '>'

    e_version = 1
    e_flags = 0x05000000 if machine == 40 else 0
    e_ehsize = 52
    e_phentsize = 32
    e_phnum = ph_count
    e_shentsize = 40
    e_shnum = sh_num
    e_shstrndx = sh_str_idx

    elf_hdr = struct.pack(
        f'{fmt}16sHHIIIIIHHHHHH',
        bytes(e_ident),
        elf_type,
        machine,
        e_version,
        entry_point,
        ph_off,
        sh_table_offset,
        e_flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    )

    # Pack program headers
    ph_bytes = []
    for seg in all_segments:
        ph_bytes.append(struct.pack(
            f'{fmt}IIIIIIII',
            seg['p_type'],
            seg['p_offset'],
            seg['p_vaddr'],
            seg['p_paddr'],
            seg['p_filesz'],
            seg['p_memsz'],
            seg['p_flags'],
            seg['p_align'],
        ))

    parts = [elf_hdr, b''.join(ph_bytes)]
    for seg in all_segments:
        parts.append(seg.get('data', b''))

    if not is_stripped:
        parts.append(shstrtab)
        parts.append(strtab)
        parts.append(symtab_bytes)
        parts.append(b''.join(sec_headers))

    return b''.join(parts)
