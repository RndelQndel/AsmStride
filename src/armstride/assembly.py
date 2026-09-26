"""Application-owned assembly boundary; no assembler library types escape it."""

from dataclasses import dataclass
from typing import Protocol

from armstride.architecture.arm import PROFILE
from armstride.domain.models import Diagnostic, ProgramImage


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    source_text: str
    base_address: int
    raw_bytes: bytes = b""
    program: ProgramImage | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def load_success(self) -> bool:
        return self.program is not None


class AssemblerBackend(Protocol):
    def assemble(self, source: str, *, mode: str, base_address: int,
                 profile: str = PROFILE) -> AssemblyResult: ...
