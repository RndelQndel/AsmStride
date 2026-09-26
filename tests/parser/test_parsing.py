from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from armstride.architecture.arm import canonical_register, initial_registers, validate_pc
from armstride.domain.models import DomainError, ParseResult
from armstride.parser import parse, select_format


def errors(result):
    return [diagnostic.code for diagnostic in result.diagnostics if diagnostic.severity == "error"]


def test_sort_gaps_source_and_machine_bytes_authority():
    text = "0x1010: e3a00005 ADD r0,#99\n0x1000: e3a01006 MOV r1,#6\n"
    result = parse(text, mode="arm", format="generic")
    assert result.load_success
    assert result.program.start_pc == 0x1000
    assert list(result.program.address_index) == [0x1000, 0x1010]
    instruction = result.records[0]
    assert instruction.source_line == 1
    assert instruction.display_text == "ADD r0,#99"
    assert instruction.decode.operation == "mov"
    assert instruction.decode.operands[1].immediate == 5
    with pytest.raises(FrozenInstanceError):
        instruction.address = 0
    with pytest.raises(TypeError):
        result.program.address_index[0x1004] = instruction
    for invalid in (0x1001, 0x1002, 0x1004, 0x100000000, True):
        with pytest.raises(DomainError, match="loaded instruction"):
            validate_pc(result.program, invalid)
    validate_pc(result.program, 0x1010)


@pytest.mark.parametrize("source,mode,code", [
    ("0x1002: e3a00005 MOV r0,#5", "arm", "invalid_encoding"),
    ("0x1001: 2005 MOVS r0,#5", "thumb", "invalid_encoding"),
    ("0xfffffffe: f240 0108 MOVW r1,#8", "thumb", "invalid_encoding"),
    ("0x100000000: e3a00005 MOV r0,#5", "arm", "invalid_encoding"),
    ("0x1000: f2400108 MOVW r1,#8", "thumb", "invalid_encoding"),
    ("0x1000: f240 MOVW r1,#8", "thumb", "invalid_encoding"),
    ("0x1000: 2005 2006 MOVS r0,#5", "thumb", "invalid_encoding"),
    ("0x1000: e3a00005 e3a00006 MOV r0,#5", "arm", "invalid_encoding"),
    ("0x1000: MOV r0,#5", "arm", "invalid_encoding"),
    ("0x1000: e3a00005", "arm", "parse_error"),
    ("MOV r0,#5", "arm", "parse_error"),
    ("0x1000: ........ MOV r0,#5", "arm", "invalid_encoding"),
    ("0x1000: e3a00005 DCD 5", "arm", "parse_error"),
    ("0x1000: e3a00005 .word 5", "arm", "parse_error"),
    ("arbitrary prose", "arm", "parse_error"),
    ("DISASM:", "arm", "parse_error"),
    ("DISASM: # not an instruction", "arm", "parse_error"),
    ("[00:00:00.001] OTHER: 0x1000: e3a00005 MOV r0,#5", "arm", "parse_error"),
])
def test_reject_malformed_records(source, mode, code):
    result = parse(source, mode=mode, format="generic")
    assert result.program is None
    assert errors(result) == [code]
    assert result.diagnostics[0].line == 1
    assert result.diagnostics[0].source_text == source


def test_overlaps_include_original_lines_without_partial_program():
    result = parse("0x1002: 2005 MOVS r0,#5\n0x1000: f240 0108 MOVW r1,#8", mode="thumb")
    assert not result.load_success
    assert errors(result) == ["overlapping_instructions"]
    assert result.diagnostics[-1].related_lines == (2, 1)
    assert len(result.records) == 2


def test_collect_multiple_failures_and_keep_preview():
    result = parse("0x1000: e3a00005 MOV r0,#5\ngarbage text\n0x1004: ??? ADD r1,r0,#1", mode="arm")
    assert result.program is None
    assert [d.line for d in result.diagnostics if d.severity == "error"] == [2, 3]
    assert result.records[0].address == 0x1000


@pytest.mark.parametrize("format", ["generic", "objdump", "fromelf", "auto"])
def test_comments_labels_and_immediates(format):
    result = parse("; comment\n# comment\n// comment\n\nexample:\n1000 <example>:\n1000: e3a00005 MOV r0,#5", mode="arm", format=format)
    assert result.load_success
    assert result.ignored_lines == (1, 2, 3, 4, 5, 6)
    assert result.records[0].display_text.endswith("#5")


def test_fromelf_symbol_context_and_ambiguous_ascii():
    valid = parse("    $a.0\n    [Anonymous symbol #1]\n    sample\n        0x1000: e3a00005    ....    MOV r0,#5", mode="arm", format="fromelf")
    assert valid.load_success
    assert valid.ignored_lines == (1, 2, 3)
    for source in ("arbitrary", "    sample\n0x1000: e3a00005 MOV r0,#5"):
        assert not parse(source, mode="arm", format="fromelf").load_success
    ambiguous = parse("0x1000: e3a00005    ABCD    MOV r0,#5", mode="arm")
    assert errors(ambiguous) == ["ambiguous_format"]


def test_auto_preference_and_disagreement_requires_selection():
    source = "0x1000: e3a00005 MOV r0,#5"
    assert parse(source, mode="arm").selected_format == "fromelf"
    assert parse("0x1000: 05 00 a0 e3 MOV r0,#5", mode="arm").selected_format == "objdump"
    first = parse(source, mode="arm", format="generic")
    changed = replace(first.records[0], raw_bytes=bytes.fromhex("0600a0e3"))
    second = ParseResult(replace(first.program, instructions=(changed,)), (changed,), (), "objdump")
    assert errors(select_format((first, second))) == ["ambiguous_format"]


def test_selection_and_input_limits():
    for options, code in [({"mode":"mips"}, "unsupported_mode"),
                          ({"mode":"arm", "profile":"riscv"}, "unsupported_architecture"),
                          ({"mode":"arm", "format":"mixed"}, "invalid_input"),
                          ({"mode":"arm", "encoding":"integer"}, "invalid_input")]:
        assert errors(parse("", **options)) == [code]
    assert errors(parse("", mode="arm")) == ["empty_program"]
    assert errors(parse("é" * (1 << 19) + "a", mode="arm")) == ["input_limit"]
    assert errors(parse("\ud800", mode="arm")) == ["invalid_input"]
    source = "\n".join(f"{4096 + i * 4:x}: e3a00005 MOV r0,#5" for i in range(10_001))
    limited = parse(source, mode="arm", format="generic")
    assert limited.program is None and errors(limited) == ["input_limit"]
    assert len(limited.records) == 10_000


@pytest.mark.parametrize("mode,source,encoding,expected", [
    ("arm", "1000 e3a00005 MOV r0,#5", "words", "0500a0e3"),
    ("thumb", "1002 f240 0108 MOVW r1,#8", "words", "40f20801"),
    ("thumb", "1002 40 f2 08 01 MOVW r1,#8", "bytes", "40f20801"),
    ("thumb", "1000 05 20 MOVS r0,#5", "bytes", "0520"),
])
def test_explicit_encoding(mode, source, encoding, expected):
    assert parse(source, mode=mode, format="generic", encoding=encoding).records[0].raw_bytes.hex() == expected
    wrong = "bytes" if encoding == "words" else "words"
    assert errors(parse(source, mode=mode, format="generic", encoding=wrong)) == ["invalid_encoding"]


def test_profile_defaults_and_aliases():
    assert canonical_register("R13") == "sp"
    assert canonical_register("R14") == "lr"
    assert canonical_register("R15") == "pc"
    assert canonical_register("CPSR") == "cpsr"
    with pytest.raises(DomainError):
        canonical_register("r16")
    for mode, cpsr in [("arm", 0x10), ("thumb", 0x30)]:
        registers = initial_registers(mode, 0x1000)
        assert registers["sp"] == 0x20100000
        assert registers["cpsr"] == cpsr
        assert registers["lr"] == registers["r0"] == 0
        with pytest.raises(TypeError):
            registers["r0"] = 5


def test_decode_golden_bytes_without_executing_or_using_display_as_an_oracle():
    cases = json.loads((Path(__file__).resolve().parents[1] / "golden/cases.json").read_text())
    for case in cases:
        source = "\n".join(f"{instruction['address']:x}: {bytes.fromhex(instruction['bytes']).hex(' ')} {instruction['assembly']}"
                           for instruction in case["program"])
        result = parse(source, mode=case["mode"], format="generic", encoding="bytes")
        assert result.load_success, (case["id"], result.diagnostics)
        assert [i.raw_bytes.hex() for i in result.records] == [i["bytes"] for i in case["program"]]
        assert [i.size for i in result.records] == [i["size"] for i in case["program"]]
        assert not result.diagnostics, (case["id"], result.diagnostics)


@pytest.mark.parametrize("name", ["NOP", "MOV", "ADDEQ", "MOVSNE", "B.W"])
def test_mnemonic_only_is_not_fromelf_symbol_metadata(name):
    source = f"    {name}\n        0x1000: e3a00005 MOV r0,#5"
    result = parse(source, mode="arm", format="fromelf")
    assert not result.load_success
    assert result.diagnostics[0].line == 1
    assert result.diagnostics[0].code == "parse_error"


@pytest.mark.parametrize("word,operation", [
    ("ee100f10", "mrc"), ("e1900f9f", "ldrex"), ("e10f0000", "mrs"),
])
def test_excluded_features_warn_without_preventing_load(word, operation):
    result = parse(f"1000: {word} MOV r0,#0", mode="arm", format="generic")
    assert result.load_success
    assert result.records[0].decode.operation == operation
    assert result.records[0].feature_exclusion
    assert [d.code for d in result.diagnostics] == ["unsupported_instruction"]


def test_normal_integer_operation_is_not_restricted_to_representative_table():
    result = parse("1000: e0000291 MUL r0,r1,r2", mode="arm", format="generic")
    assert result.load_success
    assert result.records[0].decode.operation == "mul"
    assert not result.diagnostics


def test_decoder_register_shift_uses_domain_register_names():
    result = parse("1000: e0810312 ADD r0,r1,r2,LSL r3", mode="arm", format="generic")
    assert result.load_success
    assert result.records[0].decode.operands[2].shift == ("lsl_reg", "r3")
    assert result.records[0].decode.registers_written == ("r0",)


def test_p1_mapping_symbols_mixed_mode_parsing():
    text = """$a
0x1000: e3a00005 MOV r0, #5
$t
0x1004: 2106 MOVS r1, #6
$d
0x1006: 00000042 .word 0x42
"""
    result = parse(text, mode="arm", format="generic")
    assert result.load_success
    assert len(result.program.instructions) == 2
    assert result.program.instructions[0].address == 0x1000
    assert result.program.instructions[0].mode == "arm"
    assert result.program.instructions[1].address == 0x1004
    assert result.program.instructions[1].mode == "thumb"
    assert len(result.program.data_regions) == 1
    assert result.program.data_regions[0].address == 0x1006
    assert result.program.data_regions[0].data == b"\x42\x00\x00\x00"
    assert result.ignored_lines == (1, 3, 5)


def test_p1_address_overlap_rejection():
    # Instruction vs data overlap
    text_overlap_inst_data = """$a
0x1000: e3a00005 MOV r0, #5
$d
0x1002: 00000042 .word 0x42
"""
    res1 = parse(text_overlap_inst_data, mode="arm", format="generic")
    assert not res1.load_success
    assert errors(res1) == ["overlapping_instructions"]

    # Data vs data overlap
    text_overlap_data = """$a
0x1008: e3a00005 MOV r0, #5
$d
0x1000: 00000042 .word 0x42
0x1002: 00000010 .word 0x10
"""
    res2 = parse(text_overlap_data, mode="arm", format="generic")
    assert not res2.load_success
    assert errors(res2) == ["overlapping_data"]

    # Duplicate instruction & data address
    text_dup = """$a
0x1000: e3a00005 MOV r0, #5
$d
0x1000: 00000042 .word 0x42
"""
    res3 = parse(text_dup, mode="arm", format="generic")
    assert not res3.load_success
    assert errors(res3) == ["duplicate_instruction_address"]


def test_p1_objdump_and_fromelf_mapping_symbols():
    # Objdump style
    objdump_text = """00008000 <$a>:
    8000:\te3a00005 \tmov\tr0, #5
00008004 <$t>:
    8004:\t2106     \tmovs\tr1, #6
00008006 <$d>:
    8006:\t00000042 \t.word\t0x00000042
"""
    res_obj = parse(objdump_text, mode="arm", format="objdump")
    assert res_obj.load_success
    assert res_obj.program.instructions[0].mode == "arm"
    assert res_obj.program.instructions[1].mode == "thumb"
    assert len(res_obj.program.data_regions) == 1
    assert res_obj.program.data_regions[0].data == b"\x42\x00\x00\x00"

    # Fromelf style
    fromelf_text = """    $a
    0x00008000:    e3a00005    ....    MOV      r0,#5
    $t
    0x00008004:    2106                MOVS     r1,#6
    $d
    0x00008006:    00000042    ....    DCD      0x00000042
"""
    res_fe = parse(fromelf_text, mode="arm", format="fromelf")
    assert res_fe.load_success
    assert res_fe.program.instructions[0].mode == "arm"
    assert res_fe.program.instructions[1].mode == "thumb"
    assert len(res_fe.program.data_regions) == 1
    assert res_fe.program.data_regions[0].data == b"\x42\x00\x00\x00"

