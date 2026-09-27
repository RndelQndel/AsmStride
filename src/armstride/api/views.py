"""Explicit public projections, without native handles or full memory dumps."""

from armstride.simulation.session import flags


def state_view(session_id, entry):
    session = entry.session
    machine = session.snapshot()
    registers = machine.register_view() if machine else {}
    return dict(session_id=session_id, status=session.status,
                profile=session.program.profile if session.program else None,
                mode=session.program.mode if session.program else None,
                baseline_pc=session.baseline.registers['pc'] if machine else None,
                step_seq=session.step_seq,
                state_revision=session.state_revision,
                history_depth=session.history_depth,
                cpsr=registers.pop('cpsr', None), registers=registers,
                flags=flags(machine.registers) if machine else None,
                pc=machine.registers['pc'] if machine else None,
                stack=entry.stack, last_step=session.last_step,
                regions=[dict(base=r.address, size=len(r.raw_bytes), kind=r.origin,
                              permissions='rw' if r.writable else 'rx')
                         for r in machine.memory.regions] if machine else [],
                breakpoints=[dict(address=bp.address, mode=bp.mode)
                             for bp in session.list_breakpoints()],
                watchpoints=[dict(address=wp.address, length=wp.length, kind=wp.kind)
                             for wp in session.list_watchpoints()])


def diagnostic_view(diagnostic):
    return dict(code=diagnostic.code, severity=diagnostic.severity, message=diagnostic.message,
                line=diagnostic.line, source_text=diagnostic.source_text,
                context=dict(related_lines=list(diagnostic.related_lines)))


def instruction_view(instruction):
    return dict(address=instruction.address, bytes=instruction.raw_bytes.hex(), size=instruction.size,
                source_line=instruction.source_line, source_text=instruction.source_text,
                display_text=instruction.display_text, decoded_text=instruction.decoded_text,
                feature_exclusion=instruction.feature_exclusion, mode=instruction.mode)


def symbol_entry_view(symbol):
    return dict(address=symbol.address, name=symbol.name, size=symbol.size,
                kind=symbol.kind, binding=symbol.binding, section=symbol.section)


def line_entry_view(line):
    return dict(address=line.address, file_path=line.file_path,
                line_number=line.line_number, column=line.column)


def program_view(result, metadata=None):
    program = result.program
    symbols = []
    lines = []
    if metadata is not None:
        for entries in metadata.symbols.by_address.values():
            for s in entries:
                symbols.append(symbol_entry_view(s))
        for line in metadata.lines.entries:
            lines.append(line_entry_view(line))

    return dict(profile=program.profile, mode=program.mode, format=program.format,
                source_text=program.source_text,
                instructions=[instruction_view(i) for i in program.instructions],
                data_regions=[dict(address=d.address, size=d.size, bytes=d.data.hex(), source_line=d.source_line)
                              for d in program.data_regions],
                symbols=symbols,
                lines=lines,
                diagnostics=[diagnostic_view(d) for d in result.diagnostics],
                instruction_count=len(program.instructions),
                ignored_line_count=sum(d.code == 'ignored_line' for d in result.diagnostics))
