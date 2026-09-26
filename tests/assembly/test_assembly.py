"""Real assembler encodings against fixed bytes, plus validation boundaries."""

from dataclasses import FrozenInstanceError

import pytest

from armstride.assembly import AssemblerBackend
from armstride.backends.keystone import KeystoneAssembler
from armstride.domain.models import MAX_TEXT_BYTES
from armstride.parser import parse

ASSEMBLER: AssemblerBackend = KeystoneAssembler()


@pytest.mark.parametrize('mode,source,listing,widths', [
    ('arm', 'mov r0,#5\nadd r1,r0,#3\nsub r2,r1,r0',
     '1000: E3A00005 mov r0,#5\n1004: E2801003 add r1,r0,#3\n1008: E0412000 sub r2,r1,r0', (4, 4, 4)),
    ('arm', 'b done\nmov r0,#0\ndone: mov r0,#1',
     '1000: EA000000 b done\n1004: E3A00000 mov r0,#0\n1008: E3A00001 mov r0,#1', (4, 4, 4)),
    ('thumb', 'movs r0,#5\nmovs r1,#0', '1000: 2005 movs r0,#5\n1002: 2100 movs r1,#0', (2, 2)),
    ('thumb', 'movw r1,#8', '1000: F240 0108 movw r1,#8', (4,)),
    ('thumb', 'movs r0,#5\nmovw r1,#8\nadds r0,#1',
     '1000: 2005 movs r0,#5\n1002: F240 0108 movw r1,#8\n1006: 3001 adds r0,#1', (2, 4, 2)),
    ('thumb', 'b done\nmovs r0,#0\ndone: movs r0,#1',
     '1000: E000 b done\n1002: 2000 movs r0,#0\n1004: 2001 movs r0,#1', (2, 2, 2)),
    ('arm', 'ldr r0,[pc,#0]', '1000: E59F0000 ldr r0,[pc,#0]', (4,)),
])
def test_source_and_import_normalize_identically(mode, source, listing, widths):
    result = ASSEMBLER.assemble(source, mode=mode, base_address=0x1000)
    imported = parse(listing, mode=mode, format='objdump')
    assert result.load_success and imported.load_success, result.diagnostics
    signature = lambda program: tuple((i.address, i.raw_bytes, i.size, i.decode) for i in program.instructions)
    assert signature(result.program) == signature(imported.program)
    assert tuple(i.size for i in result.program.instructions) == widths
    assert result.raw_bytes == b''.join(i.raw_bytes for i in imported.program.instructions)
    assert result.source_text == result.program.source_text == source
    assert result.program.format == 'assembly'
    assert all(i.source_line is None and i.source_text == '' and i.display_text == i.decoded_text
               for i in result.program.instructions)
    with pytest.raises(FrozenInstanceError):
        result.program.mode = 'arm'


@pytest.mark.parametrize('mode,base,expected', [
    ('arm', 0x1000, '3e0000ea'), ('arm', 0x1004, '3d0000ea'),
    ('thumb', 0x1000, '7ee0'), ('thumb', 0x1002, '7de0'),
])
def test_origin_is_passed_before_encoding(mode, base, expected):
    result = ASSEMBLER.assemble('b 0x1100', mode=mode, base_address=base)
    assert result.load_success, result.diagnostics
    assert result.base_address == result.program.start_pc == base
    assert result.raw_bytes.hex() == expected
    assert result.program.instructions[0].decode.operands[0].immediate == 0x1100


@pytest.mark.parametrize('source,mode', [
    ('.syntax unified\n.arm\n.code 32\nmov r0,#1', 'arm'),
    ('.syntax unified\n.thumb\n.code 16\nmovs r0,#1', 'thumb'),
    ('/* .thumb */\nmov r0,#1 @ .include "x" 한글\n// .org 0', 'arm'),
    ('start: mov r0,#1; b start', 'arm'),
])
def test_labels_comments_and_matching_mode_directives(source, mode):
    result = ASSEMBLER.assemble(source, mode=mode, base_address=0x1000)
    assert result.load_success, result.diagnostics
    assert result.source_text == source


@pytest.mark.parametrize('source', [
    '.thumb\nmovs r0,#1', 'mov r0,#1; label: .thumb', '.code 16',
    '.include "file.s"', '.incbin "file.bin"', '.macro foo\n.endm', '.rept 1000000',
    '.org 0x9000', '.word 0xe3a00001', '.inst 0xe3a00001', '.arch armv8-a',
    '.section .text', '.end', 'ldr r0,=0x12345678', 'constant = 1', '#include "x"',
    '"x": .thumb', '"x//y": .include "file.s"', 'é: .thumb',
])
def test_unsupported_source_is_rejected_before_assembler(source, monkeypatch):
    def unexpected(*args):
        pytest.fail('Unsupported source reached native assembler')
    monkeypatch.setattr('armstride.backends.keystone.ks.Ks', unexpected)
    result = ASSEMBLER.assemble(source, mode='arm', base_address=0x1000)
    assert result.program is None and result.raw_bytes == b''
    assert result.diagnostics[0].code == 'unsupported_source'
    assert result.diagnostics[0].line is not None


@pytest.mark.parametrize('source,kwargs,code', [
    ('mov r0,#1\nnot_an_instruction r0', {}, 'assembly_error'),
    ('b missing_label', {}, 'assembly_error'),
    ('', {}, 'empty_program'), ('@ only comment', {}, 'empty_program'),
    ('mov r0,#1\0mov r1,#2', {}, 'invalid_input'),
    ('\ud800', {}, 'invalid_input'), (None, {}, 'invalid_input'),
    ('a' * (MAX_TEXT_BYTES + 1), {}, 'input_limit'),
    ('mov r0,#1', {'profile': 'aarch64'}, 'unsupported_architecture'),
    ('mov r0,#1', {'mode': 'mixed'}, 'unsupported_mode'),
    ('mov r0,#1', {'base_address': True}, 'invalid_input'),
    ('mov r0,#1', {'base_address': -4}, 'invalid_input'),
    ('mov r0,#1', {'base_address': 1 << 32}, 'invalid_input'),
    ('mov r0,#1', {'base_address': 0x1002}, 'invalid_encoding'),
    ('movs r0,#1', {'mode': 'thumb', 'base_address': 0x1001}, 'invalid_encoding'),
    ('mov r0,#1\nmov r1,#2', {'base_address': 0xFFFFFFFC}, 'invalid_encoding'),
    ('mov r0,#1\n' * 10001, {}, 'input_limit'),
])
def test_failures_publish_no_executable_bytes(source, kwargs, code):
    result = ASSEMBLER.assemble(source, **(dict(mode='arm', base_address=0x1000) | kwargs))
    assert not result.load_success and result.raw_bytes == b''
    assert result.diagnostics[0].code == code
    if code == 'assembly_error':
        assert result.diagnostics[0].line is None
        assert 'statement count' in result.diagnostics[0].message


@pytest.mark.parametrize('mode,raw', [('arm', b'\x01\x00\xa0\xe3\xff'), ('thumb', b'\x00\xf0')])
def test_incomplete_generated_bytes_fail_normalization(mode, raw, monkeypatch):
    monkeypatch.setattr('armstride.backends.keystone.ks.Ks.asm', lambda *args, **kwargs: (raw, 1))
    result = ASSEMBLER.assemble('mov r0,#1', mode=mode, base_address=0x1000)
    assert result.program is None and result.raw_bytes == b''
    assert result.diagnostics[0].code == 'invalid_encoding'


@pytest.mark.parametrize('mode,source', [('arm', 'svc #0'), ('thumb', 'clrex')])
def test_excluded_execution_features_remain_loadable_with_warnings(mode, source):
    result = ASSEMBLER.assemble(source, mode=mode, base_address=0x1000)
    assert result.load_success
    assert result.program.instructions[0].feature_exclusion
    assert result.diagnostics[0].severity == 'warning'
    assert result.diagnostics[0].code == 'unsupported_instruction'


def test_policy_diagnostics_preserve_crlf_and_cr_line_numbers():
    source = '/* comment\r\ncomment */\rmov r0,#1 @ comment\r.thumb'
    result = ASSEMBLER.assemble(source, mode='arm', base_address=0x1000)
    assert result.diagnostics[0].line == 4
    assert result.diagnostics[0].source_text == '.thumb'
