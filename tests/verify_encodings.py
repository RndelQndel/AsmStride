"""Reassemble fixture inputs with two independent assemblers; never execute a CPU."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def command(arguments, cwd=None):
    return subprocess.run(arguments, cwd=cwd, check=True, capture_output=True, text=True).stdout


def assembly_source(program, mode):
    base = program[0]['address']
    lines = ['.syntax unified', '.cpu cortex-a15', '.' + mode, '.text', '.global _start', '_start:']
    for instruction in program:
        lines += [f".org {instruction['address'] - base}", instruction['assembly']]
    return '\n'.join(lines) + '\n'


def assemble(program, mode, prefix, clang, directory):
    base = program[0]['address']
    source = assembly_source(program, mode)
    (directory / 'input.s').write_text(source)
    # Thumb32 may begin at address % 4 == 2; override object-section alignment.
    alignment = 2 if mode == 'thumb' else 4
    (directory / 'link.ld').write_text(
        f'SECTIONS {{ .text {base} : SUBALIGN({alignment}) {{ *(.text) }} }}\n')
    command([prefix + 'as', '-mcpu=cortex-a15', '-o', 'gnu.o', 'input.s'], directory)
    command([clang, '--target=armv7-none-eabi', '-mcpu=cortex-a15', '-c', 'input.s', '-o', 'clang.o'], directory)
    outputs = []
    for name in ('gnu', 'clang'):
        command([prefix + 'ld', '-T', 'link.ld', '-e', '_start', '-o', name + '.elf', name + '.o'], directory)
        command([prefix + 'objcopy', '-O', 'binary', '--only-section=.text', name + '.elf', name + '.bin'], directory)
        outputs.append((directory / (name + '.bin')).read_bytes())
    assert outputs[0] == outputs[1], ('GNU as and Clang disagree', source, [value.hex() for value in outputs])
    disassembly = command([prefix + 'objdump', '-d', 'gnu.elf'], directory)
    return outputs[0], source, disassembly


def fixture_programs():
    for case in json.loads((ROOT / 'golden/cases.json').read_text()):
        yield case['id'], case['mode'], case['program']
    for case in json.loads((ROOT / 'golden/phase4.json').read_text()):
        yield case['id'], case['mode'], case['program']
    for path in sorted((ROOT / 'fixtures/parser').glob('*.json')):
        case = json.loads(path.read_text())
        # Invalid duplicate records are checked independently at their original addresses.
        for number, instruction in enumerate(case['expected']['records']):
            yield f"{case['id']}-{number}", case['mode'], [instruction]


def main():
    if not __debug__:
        raise SystemExit('Run without -O or PYTHONOPTIMIZE; verification requires assertions.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-prefix', default='arm-none-eabi-')
    parser.add_argument('--clang', default='clang')
    parser.add_argument('--capture', type=Path)
    args = parser.parse_args()
    versions = {tool: command([args.tool_prefix + tool, '--version']).splitlines()[0]
                for tool in ('as', 'ld', 'objcopy', 'objdump')}
    versions['clang'] = command([args.clang, '--version']).splitlines()[0]
    captures = []
    with tempfile.TemporaryDirectory(prefix='armstride-encoding-') as temporary:
        for identifier, mode, program in fixture_programs():
            try:
                encoded, source, disassembly = assemble(program, mode, args.tool_prefix, args.clang, Path(temporary))
            except (AssertionError, subprocess.CalledProcessError) as failure:
                detail = failure.stderr if isinstance(failure, subprocess.CalledProcessError) else str(failure)
                raise RuntimeError(f'{identifier}: {detail}') from failure
            expected = bytearray(program[-1]['address'] - program[0]['address'] + program[-1]['size'])
            for instruction in program:
                offset = instruction['address'] - program[0]['address']
                expected[offset:offset + instruction['size']] = bytes.fromhex(instruction['bytes'])
            assert encoded == expected, identifier
            captures.append({'id': identifier, 'source': source, 'bytes': encoded.hex(),
                             'sha256': hashlib.sha256(encoded).hexdigest(), 'gnu_objdump': disassembly})
    if args.capture:
        args.capture.write_text(json.dumps({'tools': versions, 'programs': captures}, indent=2) + '\n')
    print(f'PASS: {len(captures)} programs match GNU as, Clang, and recorded bytes')


if __name__ == '__main__':
    main()
