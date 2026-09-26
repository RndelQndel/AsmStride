import json
from pathlib import Path

import pytest

from armstride.parser import parse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/parser"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda path: path.stem)
def test_parser_fixture_contract(path):
    fixture = json.loads(path.read_text())
    source = path.with_name(fixture["input"]).read_text()
    result = parse(source, mode=fixture["mode"], format=fixture["format"], encoding=fixture["encoding"])
    expected = fixture["expected"]
    assert result.load_success == expected["load_success"], result.diagnostics
    assert result.selected_format == expected["selected_format"]
    assert result.ignored_lines == tuple(expected["ignored_lines"])
    assert result.ignored_line_count == expected["ignored_line_count"]
    assert len(result.records) == expected["record_count"]
    assert [{"source_line": i.source_line, "address": i.address, "bytes": i.raw_bytes.hex(), "size": i.size}
            for i in result.records] == [
                {key: record[key] for key in ("source_line", "address", "bytes", "size")}
                for record in expected["records"]]
    diagnostics = []
    for diagnostic in result.diagnostics:
        entry = {"severity": diagnostic.severity, "code": diagnostic.code,
                 "line": diagnostic.line, "source_text": diagnostic.source_text}
        if diagnostic.related_lines:
            entry["related_lines"] = list(diagnostic.related_lines)
        diagnostics.append(entry)
    assert diagnostics == expected["diagnostics"]
    assert all(i.source_text == source.splitlines()[i.source_line - 1] for i in result.records)
    if result.load_success:
        assert result.program.source_text == source
        assert result.program.instructions == tuple(sorted(result.records, key=lambda i: i.address))
    else:
        assert result.program is None
