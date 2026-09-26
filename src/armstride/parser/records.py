"""Shared addressed-record normalization, without format guessing or assembly."""

import re
from dataclasses import dataclass

from armstride.domain.models import DomainError

ADDRESS_RECORD = re.compile(r"^\s*((?:0[xX])?[0-9a-fA-F]+)(:?)\s+(.+)$")
MNEMONIC = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?(?:\s+.*)?$")
HEX = re.compile(r"[0-9a-fA-F]+$")
LABEL = re.compile(r"(?:(?:0[xX])?[0-9a-fA-F]+\s+<[^>]+>|[A-Za-z_.$][\w.$]*):$")
MAPPING_SYMBOL_LINE = re.compile(
    r"^\s*(?:(?:0[xX])?[0-9a-fA-F]+:?\s+)?(?:<)?\$([atd])(?:\.\d+)?(?:>?:?)\s*$",
    re.IGNORECASE,
)


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


def parse_data_line(text: str, encoding: str = "auto", *, require_colon: bool = False) -> tuple[int, bytes]:
    match = ADDRESS_RECORD.fullmatch(text)
    if match is None or (require_colon and not match[2]):
        raise DomainError("parse_error", "Expected an addressed data record with encoded bytes.")
    address = int(match[1], 16)
    tokens = list(re.finditer(r"\S+", match[3]))
    if not tokens:
        raise DomainError("invalid_encoding", "Data bytes are required.")

    first = tokens[0][0]
    directive = first.lower().rstrip(":")
    if directive in (".word", "dcd", ".long"):
        if len(tokens) < 2:
            raise DomainError("invalid_encoding", "Directive requires a value.")
        val_str = tokens[1][0].rstrip(",")
        val = int(val_str, 16) if val_str.lower().startswith("0x") or not val_str.lstrip("-").isdigit() else int(val_str)
        return address, (val & 0xFFFFFFFF).to_bytes(4, "little")
    elif directive in (".short", ".hword", "dcw"):
        if len(tokens) < 2:
            raise DomainError("invalid_encoding", "Directive requires a value.")
        val_str = tokens[1][0].rstrip(",")
        val = int(val_str, 16) if val_str.lower().startswith("0x") or not val_str.lstrip("-").isdigit() else int(val_str)
        return address, (val & 0xFFFF).to_bytes(2, "little")
    elif directive in (".byte", "dcb"):
        if len(tokens) < 2:
            raise DomainError("invalid_encoding", "Directive requires a value.")
        val_str = tokens[1][0].rstrip(",")
        val = int(val_str, 16) if val_str.lower().startswith("0x") or not val_str.lstrip("-").isdigit() else int(val_str)
        return address, (val & 0xFF).to_bytes(1, "little")

    clean_first = first.lower()
    if clean_first.startswith("0x"):
        clean_first = clean_first[2:]

    byte_form = len(first) == 2 and bool(HEX.fullmatch(first))
    if encoding == "words" and byte_form or encoding == "bytes" and not byte_form:
        raise DomainError("invalid_encoding", "Opcode/data fields do not match the selected encoding.")

    if byte_form:
        count = 0
        while count < len(tokens) and len(tokens[count][0]) == 2 and HEX.fullmatch(tokens[count][0]):
            count += 1
        raw = bytes.fromhex("".join(tokens[i][0] for i in range(count)))
    else:
        if clean_first and HEX.fullmatch(clean_first):
            if len(clean_first) == 8:
                raw = int(clean_first, 16).to_bytes(4, "little")
            elif len(clean_first) == 4:
                raw = int(clean_first, 16).to_bytes(2, "little")
            elif len(clean_first) <= 2:
                raw = int(clean_first, 16).to_bytes(1, "little")
            else:
                raw = int(clean_first, 16).to_bytes((len(clean_first) + 1) // 2, "little")
        else:
            raise DomainError("invalid_encoding", "Expected hex data or valid data directive.")
    return address, raw
