"""GNU objdump's addressed opcode records, headers and labels."""

import re

from armstride.parser.records import addressed_record, is_common_metadata

HEADERS = re.compile(r"(?:.+:\s+file format\s+\S+|Disassembly of section\s+\S+:)$")


def is_metadata(text: str) -> bool:
    return is_common_metadata(text) or bool(HEADERS.fullmatch(text.strip()))


def parse_record(text: str, mode: str, encoding: str):
    return addressed_record(text, mode, encoding, require_colon=True)
