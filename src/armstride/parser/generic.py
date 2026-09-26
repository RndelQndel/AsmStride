"""Strict addressed words or memory-order bytes, with no tool-specific columns."""

from armstride.parser.records import addressed_record, is_common_metadata

is_metadata = is_common_metadata
parse_record = addressed_record
