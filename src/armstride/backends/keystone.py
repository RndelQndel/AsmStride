"""Bounded ARM/Thumb snippets to the existing byte-driven ProgramImage."""

import re

import keystone as ks

from armstride.architecture.arm import PROFILE, validate_profile
from armstride.architecture.decode import ArmDecoder
from armstride.assembly import AssemblyResult
from armstride.domain.models import MAX_TEXT_BYTES, Diagnostic, DomainError, ProgramImage, validate_range


def source_diagnostics(source: str, mode: str) -> tuple[Diagnostic, ...]:
    """Gate directives, not instructions or source-to-instruction mapping."""
    # Preserve line numbers while ignoring assembler comments for this policy check.
    uncommented = re.sub(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\r\n]*|@[^\r\n]*',
                         lambda match: match[0] if match[0].startswith('"') else
                         re.sub(r"[^\r\n]", " ", match[0]), source, flags=re.S)
    allowed = {".syntax unified", ".arm", ".code 32"} if mode == "arm" else {
        ".syntax unified", ".thumb", ".code 16"}
    diagnostics = []
    original_lines = source.splitlines()
    for number, line in enumerate(uncommented.splitlines(), 1):
        for statement in line.split(";"):
            body = statement.strip()
            while label := re.match(r'(?:"(?:\\.|[^"\\])*"|[^\s:]+)\s*:\s*', body):
                body = body[label.end():]
            normalized = " ".join(body.lower().split())
            if ((body.startswith((".", "#")) and normalized not in allowed) or "=" in body):
                diagnostics.append(Diagnostic("error", "unsupported_source",
                    "Only instructions, labels, comments, .syntax unified and matching mode directives "
                    "are supported; data, literal pools, includes and build directives are excluded.",
                    number, original_lines[number - 1]))
    return tuple(diagnostics)


class KeystoneAssembler:
    def assemble(self, source: str, *, mode: str, base_address: int,
                 profile: str = PROFILE) -> AssemblyResult:
        try:
            validate_profile(profile, mode)
            validate_range(base_address, 4 if mode == "arm" else 2)
            if base_address % (4 if mode == "arm" else 2):
                raise DomainError("invalid_encoding", "Assembly base address must be aligned for the selected mode.")
            if not isinstance(source, str) or "\0" in source:
                raise DomainError("invalid_input", "Assembly source must be text without NUL characters.")
            if len(source) > MAX_TEXT_BYTES or len(source.encode("utf-8")) > MAX_TEXT_BYTES:
                raise DomainError("input_limit", "Input exceeds 1 MiB.")
            diagnostics = source_diagnostics(source, mode)
            if diagnostics:
                return AssemblyResult(source, base_address, diagnostics=diagnostics)
            engine = ks.Ks(ks.KS_ARCH_ARM, ks.KS_MODE_ARM if mode == "arm" else ks.KS_MODE_THUMB)
            raw_bytes, _ = engine.asm(source.encode("utf-8"), addr=base_address, as_bytes=True)
            if not raw_bytes:
                raise DomainError("empty_program", "Assembler produced no instructions.")
            instructions = ArmDecoder(mode).decode_stream(base_address, raw_bytes)
            program = ProgramImage(instructions, mode, source, "assembly", profile)
            warnings = tuple(Diagnostic("warning", "unsupported_instruction", instruction.feature_exclusion)
                             for instruction in instructions if instruction.feature_exclusion)
            return AssemblyResult(source, base_address, raw_bytes, program, warnings)
        except ks.KsError as error:
            # Statement counts include labels/directives and are NOT source line numbers.
            diagnostic = Diagnostic("error", "assembly_error",
                f"{error}; assembler statement count: {error.get_asm_count()}.")
        except (DomainError, UnicodeError) as error:
            diagnostic = Diagnostic("error", error.code if isinstance(error, DomainError) else "invalid_input",
                                    str(error))
        return AssemblyResult(source, base_address, diagnostics=(diagnostic,))
