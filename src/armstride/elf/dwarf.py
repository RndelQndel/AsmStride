"""DWARF .debug_line extraction for instruction address to file:line mapping."""

from elftools.elf.elffile import ELFFile

from armstride.domain.models import LineEntry, LineTable


def extract_dwarf_lines(elf: ELFFile) -> LineTable:
    """Extract DWARF .debug_line mappings into LineTable. Non-fatal on missing or malformed DWARF."""
    if not elf.has_dwarf_info():
        return LineTable()

    try:
        dwarfinfo = elf.get_dwarf_info()
        entries: list[LineEntry] = []
        by_address: dict[int, LineEntry] = {}

        for cu in dwarfinfo.iter_CUs():
            line_prog = dwarfinfo.line_program_for_CU(cu)
            if line_prog is None:
                continue

            file_entries = line_prog.header.get('file_entry', [])
            include_dirs = line_prog.header.get('include_directory', [])

            for entry in line_prog.get_entries():
                if entry.state is None:
                    continue
                if entry.state.end_sequence:
                    continue

                addr = entry.state.address
                f_idx = entry.state.file
                file_name = "unknown"
                if 1 <= f_idx <= len(file_entries):
                    fe = file_entries[f_idx - 1]
                    raw_name = getattr(fe, 'name', b'')
                    fname = raw_name.decode('utf-8', errors='replace') if isinstance(raw_name, bytes) else str(raw_name)
                    d_idx = getattr(fe, 'dir_index', 0)
                    if 1 <= d_idx <= len(include_dirs):
                        raw_dir = include_dirs[d_idx - 1]
                        dname = raw_dir.decode('utf-8', errors='replace') if isinstance(raw_dir, bytes) else str(raw_dir)
                        file_name = f"{dname}/{fname}"
                    else:
                        file_name = fname

                line_num = entry.state.line
                col = entry.state.column
                le = LineEntry(address=addr, file_path=file_name, line_number=line_num, column=col)
                entries.append(le)
                if addr not in by_address:
                    by_address[addr] = le

        return LineTable(entries=tuple(entries), by_address=by_address)
    except Exception:
        # P2-AC-10: Corrupted or missing DWARF sections generate non-fatal diagnostics
        return LineTable()
