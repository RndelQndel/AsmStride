"""Validate fixture integrity and expected-state consistency, not product behavior."""

import copy
import hashlib
import json
from pathlib import Path

from verify_encodings import assembly_source, fixture_programs

ROOT = Path(__file__).resolve().parent
REGISTERS = {f'r{i}' for i in range(13)} | {'sp', 'lr', 'pc', 'cpsr'}


def load(path):
    return json.loads(path.read_text())


def fill(memory, address, encoded):
    memory.update({address + offset: byte for offset, byte in enumerate(bytes.fromhex(encoded))})


def read(memory, address, size):
    return bytes(memory[address + offset] for offset in range(size)).hex()


def initial_state(case):
    contract = load(ROOT / 'golden/contract.json')
    stack = contract['scratch_stack']
    memory = dict.fromkeys(range(stack['base'], stack['base'] + stack['size']), 0)
    for region in case['program'] + case['initial']['memory']:
        fill(memory, region['address'], region['bytes'])
    return {'registers': case['initial']['registers'].copy(), 'memory': memory}


def apply(state, delta):
    for field, entries in [('registers', delta['register_changes']), ('memory', delta['memory_changes'])]:
        for key, change in entries.items():
            key = int(key) if field == 'memory' else key
            assert state[field].get(key) == change['before'], (field, key, change)
            assert change['before'] != change['after'], 'Unchanged values are not deltas'
            if change['after'] is None:
                del state[field][key]
            else:
                state[field][key] = change['after']


def verify_manual(action, before, after):
    predicted = copy.deepcopy(before)
    arguments = action['arguments']
    if action['op'] == 'set_register':
        predicted['registers'][arguments['name']] = arguments['value']
    elif action['op'] == 'set_pc':
        predicted['registers']['pc'] = arguments['value']
    elif action['op'] == 'set_flags':
        mask = arguments['mask']
        assert mask and mask & ~0xF0000000 == 0
        predicted['registers']['cpsr'] = (predicted['registers']['cpsr'] & ~mask) | (arguments['value'] & mask)
    elif action['op'] == 'patch_memory':
        fill(predicted['memory'], arguments['address'], arguments['bytes'])
    else:
        raise AssertionError(action['op'])
    assert predicted == after, action


def verify_step(case, action, before, after):
    result = action['expect']['result']
    assert result['pc_before'] == before['registers']['pc']
    assert result['pc_after'] == after['registers']['pc']
    assert result['register_changes'] == {name: change for name, change in action['expect']['runtime']['register_changes'].items() if name != 'cpsr'}
    assert result['cpsr_change'] == action['expect']['runtime']['register_changes'].get('cpsr')
    flag_changes = {name: {'before': bool(before['registers']['cpsr'] & 1 << bit),
                           'after': bool(after['registers']['cpsr'] & 1 << bit)}
                    for name, bit in [('n', 31), ('z', 30), ('c', 29), ('v', 28)]
                    if (before['registers']['cpsr'] ^ after['registers']['cpsr']) & 1 << bit}
    assert result['flag_changes'] == flag_changes
    if result['status'] == 'failed':
        assert before == after and result['error']['restored']
        assert result['branch'] is None and result['condition_passed'] is None
        assert result['memory_reads'] == result['memory_writes'] == []
        error = result['error']
        if error['code'] == 'unmapped_memory_access':
            context = error['context']
            missing = [byte for byte in range(context['address'], context['address'] + context['size'])
                       if byte not in before['memory']]
            assert missing
            recorded = [byte for span in context['missing_ranges'] for byte in range(span['address'], span['address'] + span['size'])]
            assert recorded == missing
        return
    assert result['error'] is None
    expected_stop = None if after['registers']['pc'] in {i['address'] for i in case['program']} else 'pc_not_loaded'
    assert result['stop_reason'] == expected_stop
    for event in result['memory_reads']:
        assert read(before['memory'], event['address'], event['size']) == event['bytes']
    memory = before['memory'].copy()
    for event in result['memory_writes']:
        assert read(memory, event['address'], event['size']) == event['before_bytes']
        assert len(bytes.fromhex(event['after_bytes'])) == event['size']
        fill(memory, event['address'], event['after_bytes'])
    assert memory == after['memory'], 'Write events and memory delta disagree'
    if result['branch']:
        branch = result['branch']
        assert branch['kind'] in ('branch', 'call', 'return', 'pc_write')
        target = branch['target'] if branch['taken'] else branch['fallthrough']
        assert target == after['registers']['pc']


def verify_golden():
    cases = load(ROOT / 'golden/cases.json')
    assert {case['id'] for case in cases} == {f'GE-{i:02}' for i in range(1, 29)}
    actions = 0
    for case in cases:
        try:
            assert case['profile'] == 'armv7-a-le'
            assert set(case['initial']['registers']) == REGISTERS
            assert case['initial']['registers']['cpsr'] & 0x3F == (0x30 if case['mode'] == 'thumb' else 0x10)
            assert case['verification']['semantics'] and case['verification']['derivation']
            occupied = set()
            for instruction in case['program']:
                assert instruction['size'] == len(bytes.fromhex(instruction['bytes']))
                assert instruction['size'] in ((2, 4) if case['mode'] == 'thumb' else (4,))
                assert instruction['address'] % (2 if case['mode'] == 'thumb' else 4) == 0
                span = set(range(instruction['address'], instruction['address'] + instruction['size']))
                assert not occupied & span
                occupied |= span
            runtime = initial_state(case)
            baseline = copy.deepcopy(runtime)
            sequence = case['initial']['step_seq']
            for action in case['actions']:
                actions += 1
                before, old_baseline = copy.deepcopy(runtime), copy.deepcopy(baseline)
                expected = action['expect']
                apply(runtime, expected['runtime'])
                apply(baseline, expected['baseline'])
                if action['op'] == 'step':
                    verify_step(case, action, before, runtime)
                    assert baseline == old_baseline
                    sequence += expected['result']['status'] == 'executed'
                    assert expected['result']['step_seq'] == sequence
                elif action['op'] == 'reset':
                    assert runtime == baseline == old_baseline
                    assert expected['result'] is None
                else:
                    verify_manual(action, before, runtime)
                    verify_manual(action, old_baseline, baseline)
                    assert expected['result'] is None
                assert expected['step_seq'] == sequence
        except AssertionError as failure:
            raise AssertionError(f"{case['id']} ({case['name']}): {failure}") from failure
    return len(cases), actions


def verify_parser():
    identifiers = set()
    for path in sorted((ROOT / 'fixtures/parser').glob('*.json')):
        case = load(path)
        identifiers.add(case['id'])
        lines = path.with_name(case['input']).read_text().splitlines()
        expected = case['expected']
        assert expected['ignored_line_count'] == len(expected['ignored_lines'])
        assert expected['load_success'] == (not any(d['severity'] == 'error' for d in expected['diagnostics']))
        for record in expected['records']:
            assert 1 <= record['source_line'] <= len(lines)
            assert record['source_line'] not in expected['ignored_lines']
            assert len(bytes.fromhex(record['bytes'])) == record['size']
        for diagnostic in expected['diagnostics']:
            assert lines[diagnostic['line'] - 1] == diagnostic['source_text']
        source = case['provenance']
        if source['kind'] == 'tool_capture_extract':
            raw = (path.parent / source['raw_capture']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source['capture_sha256']
            assert lines == [raw.decode().splitlines()[line - 1] for line in source['raw_source_lines']]
    assert identifiers == {f'PF-{i:02}' for i in range(1, 10)}
    return len(identifiers)


def main():
    if not __debug__:
        raise SystemExit('Run without -O or PYTHONOPTIMIZE; verification requires assertions.')
    parsers = verify_parser()
    cases, actions = verify_golden()
    captures = {entry['id']: entry for entry in load(ROOT / 'provenance/encoding.json')['programs']}
    captures.update({entry['id']: entry for entry in load(ROOT / 'provenance/phase4-encoding.json')['programs']})
    programs = list(fixture_programs())
    assert set(captures) == {identifier for identifier, _, _ in programs}
    for identifier, mode, program in programs:
        capture = captures[identifier]
        assert capture['source'] == assembly_source(program, mode), identifier
        encoded = bytes.fromhex(capture['bytes'])
        assert hashlib.sha256(encoded).hexdigest() == capture['sha256'], identifier
        for instruction in program:
            offset = instruction['address'] - program[0]['address']
            assert encoded[offset:offset + instruction['size']].hex() == instruction['bytes'], identifier
    print(f'PASS: {parsers} parser contracts; {cases} golden cases; {actions} expected actions')
    print(f'PASS: {len(programs)} independent encoding captures, including Phase 4')
    print('Integrity only: this script does not execute the production parser or CPU backend.')


if __name__ == '__main__':
    main()
