"""The fixture-backed fromelf word/halfword and optional ASCII-column subset."""

import re

from armstride.architecture.decode import is_bare_mnemonic
from armstride.parser.records import ADDRESS_RECORD, SourceLine, addressed_record, is_common_metadata

HEADERS = re.compile(r"(?:\*\* Section #\d+\b.*|Size\s*:\s*\d+ bytes.*|Address:\s*0[xX][0-9a-fA-F]+)\s*$")
SYMBOL = re.compile(r"(?:\$[atd](?:\.\d+)?|\[Anonymous symbol #\d+\]|[A-Za-z_.$][\w.$]*)$")


def symbol_lines(lines: tuple[SourceLine, ...]) -> frozenset[int]:
    """Only a contiguous, less-indented block directly before an instruction is metadata."""
    ignored = set()
    block = []
    for line in lines:
        if (not line.metadata and not line.disassembly and SYMBOL.fullmatch(line.payload.strip())
                and not is_bare_mnemonic(line.payload.strip())):
            block.append(line)
            continue
        if ADDRESS_RECORD.fullmatch(line.payload):
            indent = len(line.payload) - len(line.payload.lstrip())
            if block and all(len(entry.payload) - len(entry.payload.lstrip()) < indent for entry in block):
                ignored.update(entry.number for entry in block)
        block = []
    return frozenset(ignored)


def is_metadata(text: str) -> bool:
    return is_common_metadata(text) or bool(HEADERS.fullmatch(text.strip()))


def parse_record(text: str, mode: str, encoding: str):
    return addressed_record(text, mode, encoding, fromelf=True)
