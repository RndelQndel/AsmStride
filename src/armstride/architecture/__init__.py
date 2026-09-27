"""Architecture profiles and decoders."""

from armstride.domain.models import DomainError
from armstride.architecture import arm, riscv


def get_architecture(profile: str):
    if profile == "rv32i-le":
        return riscv
    if profile == "armv7-a-le":
        return arm
    raise DomainError("unsupported_architecture", f"Unsupported profile: {profile}")
