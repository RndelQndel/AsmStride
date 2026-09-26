"""Pure whole-input parsing; no session installation or native execution."""

import re

from armstride.architecture.arm import PROFILE, validate_profile
from armstride.architecture.decode import ArmDecoder
from armstride.domain.models import (
    MAX_INSTRUCTIONS, MAX_TEXT_BYTES, DataRegion, Diagnostic, DomainError, ParseResult, ProgramImage,
    program_conflicts,
)
from armstride.parser import fromelf, generic, objdump
from armstride.parser.records import MAPPING_SYMBOL_LINE, SourceLine, parse_data_line

ADAPTERS = {"fromelf": fromelf, "objdump": objdump, "generic": generic}
ENVELOPE = re.compile(r"^(?:\[\d{2}:\d{2}:\d{2}\.\d{3}\]\s+)?(DISASM|CRASH|REGS|STACK):\s?(.*)$")


def source_lines(text: str) -> tuple[SourceLine, ...]:
    lines = []
    for number, original in enumerate(text.splitlines(), 1):
        envelope = ENVELOPE.fullmatch(original)
        lines.append(SourceLine(number, original, envelope[2] if envelope else original,
                                bool(envelope and envelope[1] != "DISASM"),
                                bool(envelope and envelope[1] == "DISASM")))
    return tuple(lines)


def parse_format(text: str, lines: tuple[SourceLine, ...], mode: str, format: str,
                 encoding: str) -> ParseResult:
    adapter = ADAPTERS[format]
    symbols = fromelf.symbol_lines(lines) if format == "fromelf" else frozenset()
    current_mode = mode
    records, data_records, diagnostics = [], [], []
    for line in lines:
        stripped = line.payload.strip()
        mapping_match = MAPPING_SYMBOL_LINE.fullmatch(stripped)
        if mapping_match:
            symbol_kind = mapping_match.group(1).lower()
            if symbol_kind == "a":
                current_mode = "arm"
            elif symbol_kind == "t":
                current_mode = "thumb"
            elif symbol_kind == "d":
                current_mode = "data"
            diagnostics.append(Diagnostic("info", "ignored_line", "Recognized metadata.",
                                          line.number, line.original))
            continue
        if line.metadata or (not line.disassembly and
                             (line.number in symbols or adapter.is_metadata(line.payload))):
            diagnostics.append(Diagnostic("info", "ignored_line", "Recognized metadata.",
                                          line.number, line.original))
            continue
        if current_mode == "data":
            try:
                address, raw_data = parse_data_line(line.payload, encoding,
                                                    require_colon=(format == "objdump"))
                data_record = DataRegion(address, raw_data, line.number, line.original)
                if len(records) + len(data_records) == MAX_INSTRUCTIONS:
                    diagnostics.append(Diagnostic("error", "input_limit", "Too many instructions/records.",
                                                  line.number, line.original))
                    break
                data_records.append(data_record)
            except DomainError as error:
                diagnostics.append(Diagnostic("error", error.code, str(error), line.number, line.original))
        else:
            try:
                decoder = ArmDecoder(current_mode)
                address, raw_bytes, display = adapter.parse_record(line.payload, current_mode, encoding)
                instruction = decoder.decode(address, raw_bytes, line.number, line.original, display)
                if len(records) + len(data_records) == MAX_INSTRUCTIONS:
                    diagnostics.append(Diagnostic("error", "input_limit", "Too many instructions/records.",
                                                  line.number, line.original))
                    break
                records.append(instruction)
                if instruction.feature_exclusion:
                    diagnostics.append(Diagnostic("warning", "unsupported_instruction", instruction.feature_exclusion,
                                                  line.number, line.original))
            except DomainError as error:
                diagnostics.append(Diagnostic("error", error.code, str(error), line.number, line.original))
    diagnostics.extend(program_conflicts(tuple(records), tuple(data_records)))
    if not records and not any(d.severity == "error" for d in diagnostics):
        diagnostics.append(Diagnostic("error", "empty_program", "No instruction records found."))
    program = None
    if not any(d.severity == "error" for d in diagnostics):
        program = ProgramImage(tuple(records), mode, text, format, data_regions=tuple(data_records))
    return ParseResult(program, tuple(records), tuple(diagnostics), format, data_regions=tuple(data_records))


def select_format(candidates: tuple[ParseResult, ...]) -> ParseResult:
    ambiguous = next((candidate for candidate in candidates
                      if any(d.code == "ambiguous_format" for d in candidate.diagnostics)), None)
    if ambiguous:
        return ParseResult(None, ambiguous.records, ambiguous.diagnostics, "auto",
                           data_regions=ambiguous.data_regions)
    valid = [candidate for candidate in candidates if candidate.load_success]
    if valid:
        signatures = {tuple((i.address, i.raw_bytes, i.display_text, i.source_line)
                            for i in candidate.program.instructions) +
                      tuple((d.address, d.data, d.source_line)
                            for d in candidate.program.data_regions)
                      for candidate in valid}
        if len(signatures) == 1:
            return valid[0]
        return ParseResult(None, (), (Diagnostic("error", "ambiguous_format",
                           "Supported formats disagree; choose one explicitly."),), "auto")
    # Keep the most informative failure preview; ties retain the documented preference.
    return max(candidates, key=lambda candidate: (len(candidate.records) + len(candidate.data_regions),
               -sum(d.severity == "error" for d in candidate.diagnostics)))



def parse(text: str, *, mode: str, format: str = "auto", encoding: str = "auto",
          profile: str = PROFILE) -> ParseResult:
    try:
        validate_profile(profile, mode)
        if not isinstance(text, str) or format not in (*ADAPTERS, "auto") or encoding not in ("auto", "words", "bytes"):
            raise DomainError("invalid_input", "Invalid text, format or encoding selection.")
        if len(text) > MAX_TEXT_BYTES or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise DomainError("input_limit", "Input exceeds 1 MiB.")
    except (DomainError, UnicodeEncodeError) as error:
        code = error.code if isinstance(error, DomainError) else "invalid_input"
        return ParseResult(None, (), (Diagnostic("error", code, str(error)),), format)
    lines = source_lines(text)
    if format != "auto":
        return parse_format(text, lines, mode, format, encoding)
    return select_format(tuple(parse_format(text, lines, mode, name, encoding) for name in ADAPTERS))
