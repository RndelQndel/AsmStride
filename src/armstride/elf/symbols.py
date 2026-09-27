"""Symbol extraction and mapping symbol classification from ELF binaries."""

from typing import Any
from elftools.elf.elffile import ELFFile

from armstride.domain.models import SymbolEntry, SymbolTable


def extract_mapping_symbols(elf: ELFFile) -> list[tuple[int, str]]:
    """Extract ARM mapping symbols ($a, $t, $d) sorted by address."""
    section = elf.get_section_by_name('.symtab')
    if section is None or not hasattr(section, 'iter_symbols'):
        return []

    mapping_symbols: list[tuple[int, str]] = []
    for sym in section.iter_symbols():
        name = sym.name
        if not name:
            continue
        mode = None
        if name == '$a' or name.startswith('$a.'):
            mode = 'arm'
        elif name == '$t' or name.startswith('$t.'):
            mode = 'thumb'
        elif name == '$d' or name.startswith('$d.'):
            mode = 'data'

        if mode is not None:
            addr = sym['st_value']
            canonical_addr = addr & ~1 if mode == 'thumb' else addr
            mapping_symbols.append((canonical_addr, mode))

    mapping_symbols.sort(key=lambda item: item[0])
    deduped: list[tuple[int, str]] = []
    for addr, mode in mapping_symbols:
        if deduped and deduped[-1][0] == addr:
            deduped[-1] = (addr, mode)
        else:
            deduped.append((addr, mode))
    return deduped


def extract_symbols(elf: ELFFile) -> SymbolTable:
    """Extract functions, objects, and labels into a decoupled SymbolTable."""
    section = elf.get_section_by_name('.symtab')
    if section is None or not hasattr(section, 'iter_symbols'):
        section = elf.get_section_by_name('.dynsym')
    if section is None or not hasattr(section, 'iter_symbols'):
        return SymbolTable()

    by_address: dict[int, list[SymbolEntry]] = {}
    by_name: dict[str, SymbolEntry] = {}

    for sym in section.iter_symbols():
        name = sym.name
        if not name:
            continue
        if name.startswith(('$a', '$t', '$d')):
            continue

        st_value = sym['st_value']
        st_size = sym['st_size']
        sym_type = sym['st_info']['type']
        sym_bind = sym['st_info']['bind']

        if sym_type == 'STT_FUNC' and (st_value & 1):
            canonical_addr = st_value & ~1
        else:
            canonical_addr = st_value

        kind = ('func' if sym_type == 'STT_FUNC' else
                'object' if sym_type == 'STT_OBJECT' else
                'section' if sym_type == 'STT_SECTION' else
                'file' if sym_type == 'STT_FILE' else 'label')
        binding = ('global' if sym_bind == 'STB_GLOBAL' else
                   'local' if sym_bind == 'STB_LOCAL' else
                   'weak' if sym_bind == 'STB_WEAK' else 'other')

        sec_name = None
        shndx = sym['st_shndx']
        if isinstance(shndx, int) and shndx < elf.num_sections():
            try:
                sec = elf.get_section(shndx)
                if sec is not None:
                    sec_name = sec.name
            except Exception:
                pass

        entry = SymbolEntry(address=canonical_addr, name=name, size=st_size,
                            kind=kind, binding=binding, section=sec_name)
        by_address.setdefault(canonical_addr, []).append(entry)
        if name not in by_name or binding == 'global':
            by_name[name] = entry

    addr_dict = {addr: tuple(entries) for addr, entries in by_address.items()}
    return SymbolTable(by_address=addr_dict, by_name=by_name)
