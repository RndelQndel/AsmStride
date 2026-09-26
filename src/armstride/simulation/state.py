"""Immutable machine snapshots and the simulation-facing execution boundary."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping, Protocol

from armstride.domain.models import Instruction
from armstride.simulation.memory import MemoryState
from armstride.simulation.results import MemoryRead, MemoryWrite


@dataclass(frozen=True)
class MachineState:
    registers: Mapping[str, int]
    memory: MemoryState
    register_origins: Mapping[str, Literal['default', 'user', 'execution']] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "registers", MappingProxyType(dict(self.registers)))
        origins = {name: self.register_origins.get(name, 'default') for name in self.registers}
        object.__setattr__(self, "register_origins", MappingProxyType(origins))

    def register_view(self):
        """Return detached, JSON-compatible values and source labels, including CPSR."""
        return {name: dict(value=value, origin=self.register_origins[name])
                for name, value in self.registers.items()}


@dataclass(frozen=True)
class ExecutionOutcome:
    state: MachineState
    reads: tuple[MemoryRead, ...]
    writes: tuple[MemoryWrite, ...]


class ExecutionBackend(Protocol):
    def execute_one(self, instruction: Instruction, state: MachineState) -> ExecutionOutcome: ...
    def close(self) -> None: ...
