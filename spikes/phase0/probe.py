"""Headless, fixed-input Unicorn experiment; not a production execution adapter."""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import capstone
import unicorn as uc
from unicorn import arm_const as arm

PAGE = 0x1000
REGISTERS = {f"r{i}": getattr(arm, f"UC_ARM_REG_R{i}") for i in range(13)}
REGISTERS.update(sp=arm.UC_ARM_REG_SP, lr=arm.UC_ARM_REG_LR,
                 pc=arm.UC_ARM_REG_PC, cpsr=arm.UC_ARM_REG_CPSR)
ACCESS_NAMES = {getattr(uc, name): name for name in dir(uc) if name.startswith("UC_MEM_")}


def build(case, repaired=False):
    engine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB if case.get("thumb") else uc.UC_MODE_ARM)
    engine.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A15)
    regions = [(address, bytes.fromhex(encoded), False) for address, encoded in case["code"]]
    regions += [(address, bytes.fromhex(encoded), True) for address, encoded in case.get("memory", [])]
    if repaired:
        regions += [(address, bytes.fromhex(encoded), True) for address, encoded in case["repair"]]
    pages = sorted({address & -PAGE for start, content, _ in regions
                    for address in range(start, start + len(content))})
    for address in pages:
        engine.mem_map(address, PAGE)
    for address, content, _ in regions:
        engine.mem_write(address, content)
    initial = dict.fromkeys(REGISTERS, 0)
    initial.update(pc=case.get("pc", case["code"][0][0]),
                   cpsr=0x30 if case.get("thumb") else 0x10)
    initial.update(case.get("registers", {}))
    # Select user register banks before writing SP/LR; restore T after canonical PC writes.
    engine.reg_write(arm.UC_ARM_REG_CPSR, initial["cpsr"])
    for name, value in initial.items():
        engine.reg_write(REGISTERS[name], value)
    assert snapshot(engine)["registers"] == initial
    return engine, regions


def snapshot(engine):
    return {
        "registers": {name: engine.reg_read(register) for name, register in REGISTERS.items()},
        "pages": {address: bytes(engine.mem_read(address, PAGE))
                  for start, end, _ in engine.mem_regions()
                  for address in range(start, end + 1, PAGE)},
    }


def visible(state, regions):
    return {
        "registers": state["registers"],
        "page_sha256": {hex(start): hashlib.sha256(content).hexdigest()
                        for start, content in state["pages"].items()},
        "region_bytes": {hex(start): bytes(state["pages"][address & -PAGE][address % PAGE]
                                          for address in range(start, start + len(content))).hex()
                         for start, content, _ in regions},
    }


def restore(engine, context, before):
    # Full mapped-page copies are sufficient for this bounded experiment.
    # Production should snapshot logical intervals or journal writes under its memory limits.
    old_pages = set(before["pages"])
    for start, end, _ in list(engine.mem_regions()):
        for address in range(start, end + 1, PAGE):
            if address not in old_pages:
                engine.mem_unmap(address, PAGE)
    for start, content in before["pages"].items():
        engine.mem_write(start, content)
    engine.context_restore(context)
    assert snapshot(engine) == before, "Rollback did not restore all registers/pages/mappings"


def attempt(engine, regions, guarded=True, timeout=1_000_000, count=1):
    before = snapshot(engine)
    context = engine.context_save()
    events, rejected, handles = [], [], []
    code_count = 0

    def code_hook(native, address, size, _):
        nonlocal code_count
        code_count += 1
        events.append({"kind": "code", "address": address, "size": size})
        if guarded and code_count > 1:
            native.emu_stop()

    def memory_hook(native, access, address, size, value, _):
        event = {"kind": ACCESS_NAMES[access], "address": address, "size": size}
        if access == uc.UC_MEM_WRITE:
            event["value"] = value
        events.append(event)
        if access in (uc.UC_MEM_READ, uc.UC_MEM_WRITE) and guarded:
            write = access == uc.UC_MEM_WRITE
            valid = address + size <= 2**32 and all(
                any(start <= byte < start + len(content) and (writable or not write)
                    for start, content, writable in regions)
                for byte in range(address, address + size))
            if not valid:
                rejected.append(event)
                native.emu_stop()
        return False

    handles.append(engine.hook_add(uc.UC_HOOK_CODE, code_hook))
    handles.append(engine.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory_hook))
    handles.append(engine.hook_add(uc.UC_HOOK_MEM_INVALID, memory_hook))
    error = None
    try:
        pc = before["registers"]["pc"]
        thumb = bool(before["registers"]["cpsr"] & 0x20)
        engine.emu_start(pc | int(thumb), 0xFFFFFFFF, timeout=timeout, count=count)
    except uc.UcError as failure:
        error = {"number": failure.errno, "message": str(failure)}
    finally:
        for handle in handles:
            engine.hook_del(handle)
    timed_out = bool(engine.query(uc.UC_QUERY_TIMEOUT))
    after = snapshot(engine)
    return {
        "before": visible(before, regions), "raw_after": visible(after, regions),
        "events": events, "native_error": error, "timeout": timed_out,
        "logical_rejections": rejected, "code_hook_count": code_count,
    }, before, after, context


def check_success(case, before, after, observation):
    assert not observation["logical_rejections"], observation
    assert not observation["timeout"], observation
    if observation["native_error"]:
        assert observation["native_error"]["number"] == uc.UC_ERR_FETCH_UNMAPPED, observation
        target = retirement_target(case, before)
        assert observation["code_hook_count"] == 1, observation
        assert after["registers"]["pc"] == target, observation
        assert (after["registers"]["cpsr"] ^ before["registers"]["cpsr"]) & 0x20 == 0
        assert observation["events"][-1]["kind"] == "UC_MEM_FETCH_UNMAPPED"
        assert observation["events"][-1]["address"] == target
        observation["retirement_evidence"] = {"decoded_target": target, "same_mode": True}
    expected = before["registers"] | case["expected"]
    assert after["registers"] == expected, (case["id"], expected, after["registers"])
    expected_pages = {start: bytearray(content) for start, content in before["pages"].items()}
    for start, encoded in case.get("writes", []):
        for offset, value in enumerate(bytes.fromhex(encoded)):
            address = start + offset
            expected_pages[address & -PAGE][address % PAGE] = value
    assert after["pages"] == {start: bytes(content) for start, content in expected_pages.items()}, case["id"]
    assert observation["code_hook_count"] <= 1, observation


def retirement_target(case, before):
    """Evidence for only the fixed probe families, never an arbitrary fetch-error bypass."""
    registers = before["registers"]
    decoder = capstone.Cs(capstone.CS_ARCH_ARM,
                          capstone.CS_MODE_THUMB if case.get("thumb") else capstone.CS_MODE_ARM)
    decoder.detail = True
    pc = registers["pc"]
    encoded = next(bytes.fromhex(encoded) for address, encoded in case["code"] if address == pc)
    instruction = next(decoder.disasm(encoded, pc, count=1))
    if instruction.id in (capstone.arm.ARM_INS_B, capstone.arm.ARM_INS_BL):
        return instruction.operands[0].imm
    if instruction.id == capstone.arm.ARM_INS_BX:
        return registers[instruction.reg_name(instruction.operands[0].reg)] & ~1
    if instruction.id == capstone.arm.ARM_INS_POP:
        address = registers["sp"] + 4 * (len(instruction.operands) - 1)
        assert instruction.reg_name(instruction.operands[-1].reg) == "pc"
        content = bytes(before["pages"][byte & -PAGE][byte % PAGE] for byte in range(address, address + 4))
        return int.from_bytes(content, "little") & ~1
    # The sequential page-end probe is MOV r0, #1, not a generic fall-through assumption.
    assert instruction.bytes == bytes.fromhex("0100a0e3")
    return pc + instruction.size


def decode(case):
    decoder = capstone.Cs(capstone.CS_ARCH_ARM,
                          capstone.CS_MODE_THUMB if case.get("thumb") else capstone.CS_MODE_ARM)
    return [{"address": instruction.address, "size": instruction.size,
             "bytes": instruction.bytes.hex(), "text": f"{instruction.mnemonic} {instruction.op_str}".strip()}
            for address, encoded in case["code"]
            for instruction in decoder.disasm(bytes.fromhex(encoded), address)]


def run_case(case):
    engine, regions = build(case)
    observation, before, after, context = attempt(engine, regions)
    result = {"input": case, "decoded": decode(case), "guarded": observation}
    if "repair" in case:
        assert observation["logical_rejections"] or observation["native_error"], case["id"]
        restore(engine, context, before)
        result["restored"] = visible(snapshot(engine), regions)
        # Repair only after proving rollback; compare the entire retry with a fresh machine.
        for address, encoded in case["repair"]:
            content = bytes.fromhex(encoded)
            mapped = {start for start, end, _ in engine.mem_regions()
                      for start in range(start, end + 1, PAGE)}
            for page in sorted({byte & -PAGE for byte in range(address, address + len(content))} - mapped):
                engine.mem_map(page, PAGE)
            engine.mem_write(address, content)
            regions.append((address, content, True))
        retry, retry_before, retry_after, _ = attempt(engine, regions)
        check_success(case, retry_before, retry_after, retry)
        clean, clean_regions = build(case, repaired=True)
        clean_observation, clean_before, clean_after, _ = attempt(clean, clean_regions)
        check_success(case, clean_before, clean_after, clean_observation)
        assert retry_after == clean_after, case["id"]
        assert retry["events"] == clean_observation["events"], case["id"]
        result.update(retry=retry, clean=clean_observation, retry_matches_clean=True)
        raw_engine, raw_regions = build(case)
        raw, raw_before, _, raw_context = attempt(raw_engine, raw_regions, guarded=False)
        raw_engine.context_restore(raw_context)
        raw["context_only_restores_memory"] = snapshot(raw_engine)["pages"] == raw_before["pages"]
        restore(raw_engine, raw_context, raw_before)
        result.update(unguarded=raw, unguarded_rollback_verified=True)
    elif case.get("failure"):
        assert observation["native_error"] or observation["logical_rejections"], case["id"]
        restore(engine, context, before)
        result["restored"] = visible(snapshot(engine), regions)
    else:
        check_success(case, before, after, observation)
        starts = {instruction["address"] for instruction in result["decoded"]}
        result["stop"] = None if after["registers"]["pc"] in starts else "pc_not_loaded"
    result["passed"] = True
    return result


def cases():
    entries = [
        {"id": "arm_condition_true", "code": [(0x1000, "0100a0030200a0e3")],
         "registers": {"cpsr": 0x40000010}, "expected": {"r0": 1, "pc": 0x1004}},
        {"id": "arm_condition_false", "code": [(0x1000, "0100a0030200a0e3")],
         "expected": {"pc": 0x1004}},
        {"id": "thumb16", "thumb": True, "code": [(0x1000, "012001f10201")],
         "expected": {"r0": 1, "pc": 0x1002}},
        {"id": "thumb32", "thumb": True, "pc": 0x1002, "code": [(0x1000, "012001f10201")],
         "expected": {"r1": 2, "pc": 0x1006}},
        {"id": "arm_self_branch", "code": [(0x1000, "feffffea")], "expected": {}},
        {"id": "thumb_self_branch", "thumb": True, "code": [(0x1000, "fee7")], "expected": {}},
        {"id": "arm_external_bx", "code": [(0x1000, "13ff2fe1")],
         "registers": {"r3": 0x9000}, "expected": {"pc": 0x9000}},
        {"id": "thumb_external_bx", "thumb": True, "code": [(0x1000, "1847")],
         "registers": {"r3": 0x9001}, "expected": {"pc": 0x9000}},
        {"id": "arm_bl", "code": [(0x1000, "000000eb"), (0x1008, "1eff2fe1")],
         "expected": {"pc": 0x1008, "lr": 0x1004}},
        {"id": "arm_return", "pc": 0x1008, "code": [(0x1000, "000000eb"), (0x1008, "1eff2fe1")],
         "registers": {"lr": 0x1004}, "expected": {"pc": 0x1004}},
        {"id": "arm_external_bl", "code": [(0x1000, "fe1f00eb")],
         "expected": {"pc": 0x9000, "lr": 0x1004}},
        {"id": "sequential_page_end", "code": [(0x1ffc, "0100a0e3")],
         "expected": {"r0": 1, "pc": 0x2000}},
        {"id": "thumb_interior_target", "thumb": True,
         "code": [(0x1000, "184701f10201")], "registers": {"r3": 0x1005},
         "expected": {"pc": 0x1004}},
        {"id": "initial_fetch_unmapped", "pc": 0x9000, "code": [(0x1000, "0100a0e3")], "failure": True},
        {"id": "invalid_instruction", "code": [(0x1000, "f000f0e7")], "failure": True},
        {"id": "code_write", "code": [(0x1000, "000084e5")],
         "registers": {"r4": 0x1000, "r0": 0x1234}, "failure": True},
        {"id": "arm_pop_external_pc", "code": [(0x1000, "0180bde8")],
         "registers": {"sp": 0x2800}, "memory": [(0x2800, "1122334400900000")],
         "expected": {"r0": 0x44332211, "pc": 0x9000, "sp": 0x2808}},
        {"id": "thumb_pop_external_pc", "thumb": True, "code": [(0x1000, "01bd")],
         "registers": {"sp": 0x2800}, "memory": [(0x2800, "1122334401900000")],
         "expected": {"r0": 0x44332211, "pc": 0x9000, "sp": 0x2808}},
    ]
    for location, address in [("mapped_hole", 0x2800), ("unmapped_page", 0x2ffc)]:
        for operation, encoded, base_register, write, thumb in [
            ("ldm", "0300b4e8", "r4", False, False),
            ("stm", "0300a4e8", "r4", True, False),
            ("push", "03002de9", "sp", True, False),
            ("pop", "0300bde8", "sp", False, False),
            ("thumb_push", "03b4", "sp", True, True),
            ("thumb_pop", "03bc", "sp", False, True),
        ]:
            push = operation.endswith("push")
            expected = {"pc": 0x1002 if thumb else 0x1004,
                        base_register: address if push else address + 8}
            if not write:
                expected.update(r0=0x44332211, r1=0x88776655)
            entries.append({"id": f"{operation}_{location}", "thumb": thumb,
                            "code": [(0x1000, encoded)],
                            "registers": {base_register: address + 8 if push else address,
                                          "r0": 0xAABBCCDD, "r1": 0xEEFF0011},
                            "memory": [(address, "11223344")],
                            "repair": [(address + 4, "55667788")], "expected": expected,
                            "writes": [(address, "ddccbbaa1100ffee")] if write else []})
    return entries


def boundary_checks():
    results = []
    by_id = {case["id"]: case for case in cases()}
    for sequence in [("thumb16", "thumb32"), ("arm_bl", "arm_return")]:
        engine, regions = build(by_id[sequence[0]])
        observations = []
        for name in sequence:
            observation, before, after, _ = attempt(engine, regions)
            check_success(by_id[name], before, after, observation)
            observations.append(observation)
        results.append({"id": "consecutive_" + sequence[0], "steps": observations, "passed": True})

    case = {"id": "second_code_hook_guard", "code": [(0x1000, "0100a0e30200a0e3")]}
    engine, regions = build(case)
    observation, before, after, _ = attempt(engine, regions, count=0)
    assert observation["code_hook_count"] == 2
    assert not observation["timeout"] and not observation["native_error"]
    assert after["registers"] == before["registers"] | {"r0": 1, "pc": 0x1004}
    assert after["pages"] == before["pages"]
    results.append({"input": case, "count": 0, "observation": observation, "passed": True})

    case = {"id": "native_timeout_rollback", "code": [(0x1000, "010090e2fdffffea")],
            "registers": {"r0": 0xFFFFFFFF, "cpsr": 0xF0000010}}
    engine, regions = build(case)
    observation, before, _, context = attempt(engine, regions, guarded=False, count=0, timeout=1_000)
    assert observation["timeout"] and not observation["native_error"], observation
    restore(engine, context, before)
    observation["event_count"] = len(observation["events"])
    observation["events"] = observation["events"][:8] + observation["events"][-8:]
    observation["event_capture"] = "First and last eight events; timeout iteration count varies by host"
    results.append({"input": case, "synthetic": "Disable count/guard to exercise native timeout",
                    "count": 0, "timeout_microseconds": 1_000, "observation": observation,
                    "restored": visible(snapshot(engine), regions), "passed": True})

    engine, regions = build(by_id["stm_unmapped_page"])
    before, context = snapshot(engine), engine.context_save()
    engine.mem_map(0x9000, PAGE)
    engine.mem_write(0x9000, b"new mapping")
    engine.mem_write(0x2ffc, b"edit")
    engine.reg_write(arm.UC_ARM_REG_R0, 99)
    mutated = snapshot(engine)
    restore(engine, context, before)
    results.append({"id": "mapping_rollback", "synthetic": "Inject an allocation and state mutation",
                    "before": visible(before, regions), "mutated": visible(mutated, regions),
                    "restored": visible(snapshot(engine), regions), "passed": True})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    results = [run_case(case) for case in cases()]
    boundaries = boundary_checks()
    report = {"environment": {"python": platform.python_version(), "platform": platform.platform(),
                               "unicorn_binding": uc.__version__, "unicorn_native": uc.uc_version(),
                               "capstone": capstone.__version__, "cpu": "UC_CPU_ARM_CORTEX_A15",
                               "timeout_microseconds": 1_000_000, "instruction_count": 1},
              "cases": results, "boundary_checks": boundaries}
    arguments.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {len(results)} cases + {len(boundaries)} boundary checks; observations: {arguments.output}")


if __name__ == "__main__":
    main()
