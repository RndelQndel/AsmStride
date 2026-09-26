"""Shared addressed-record normalization, without format guessing or assembly."""

import re
from dataclasses import dataclass

from armstride.domain.models import DomainError

ADDRESS_RECORD = re.compile(r"^\s*((?:0[xX])?[0-9a-fA-F]+)(:?)\s+(.+)$")
MNEMONIC = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?(?:\s+.*)?$")
HEX = re.compile(r"[0-9a-fA-F]+$")
LABEL = re.compile(r"(?:(?:0[xX])?[0-9a-fA-F]+\s+<[^>]+>|[A-Za-z_.$][\w.$]*):$")


@dataclass(frozen=True, slots=True)
class SourceLine:
    number: int
    original: str
    payload: str
    metadata: bool = False
    disassembly: bool = False


def is_common_metadata(text: str) -> bool:
    stripped = text.strip()
    return not stripped or stripped.startswith((";", "#", "//")) or bool(LABEL.fullmatch(stripped))


def addressed_record(text: str, mode: str, encoding: str, *, fromelf: bool = False,
                     require_colon: bool = False) -> tuple[int, bytes, str]:
    match = ADDRESS_RECORD.fullmatch(text)
    if match is None or (require_colon and not match[2]):
        raise DomainError("parse_error", "Expected an addressed instruction with encoded bytes.")
    address = int(match[1], 16)
    tokens = list(re.finditer(r"\S+", match[3]))
    if not tokens:
        raise DomainError("invalid_encoding", "Instruction bytes are required.")
    first = tokens[0][0]
    byte_form = len(first) == 2
    if encoding == "words" and byte_form or encoding == "bytes" and not byte_form:
        raise DomainError("invalid_encoding", "Opcode fields do not match the selected encoding.")
    if fromelf and byte_form:
        raise DomainError("invalid_encoding", "Fromelf records require words or halfwords.")
    if byte_form:
        count = 0
        while count < len(tokens) and len(tokens[count][0]) == 2 and HEX.fullmatch(tokens[count][0]):
            count += 1
        if count not in ((4,) if mode == "arm" else (2, 4)):
            raise DomainError("invalid_encoding", "Incorrect number of byte tokens.")
        raw = bytes.fromhex("".join(token[0] for token in tokens[:count]))
    else:
        width = 8 if mode == "arm" else 4
        if len(first) != width or not HEX.fullmatch(first):
            raise DomainError("invalid_encoding", "Use ARM words or separate Thumb halfwords, not compact Thumb words.")
        count = 1
        if mode == "thumb" and len(tokens) > 1 and len(tokens[1][0]) == 4 and HEX.fullmatch(tokens[1][0]):
            count = 2
        raw = b"".join(int(token[0], 16).to_bytes(width // 2, "little") for token in tokens[:count])
    tail = match[3][tokens[count - 1].end():].strip()
    if fromelf:
        ascii_column = re.fullmatch(r"([^\s]{" + str(len(raw)) + r"})[ \t]{2,}(.+)", tail)
        if ascii_column and MNEMONIC.fullmatch(ascii_column[2]):
            if MNEMONIC.fullmatch(tail):
                raise DomainError("ambiguous_format", "ASCII and mnemonic columns are ambiguous; normalize the record.")
            tail = ascii_column[2]
    leading = tail.split(maxsplit=1)[0] if tail else ""
    if len(leading) in (4, 8) and HEX.fullmatch(leading):
        raise DomainError("invalid_encoding", "Extra opcode fields are not an instruction display field.")
    if leading.lower() in ("dcd", "dcb", "dcw", "dci"):
        raise DomainError("parse_error", "Data directives are not instruction records.")
    if not MNEMONIC.fullmatch(tail):
        raise DomainError("parse_error", "A uniquely delimited mnemonic/display field is required.")
    return address, raw, tail
