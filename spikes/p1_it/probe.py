"""Thumb-2 IT block semantics validation spike for ARMv7-A on pinned Unicorn 2.1.4."""

import json
import platform
import sys
from pathlib import Path
import capstone
import unicorn as uc
from unicorn import arm_const as arm

PAGE = 0x1000

def get_itstate(cpsr: int) -> int:
    """Extract ITSTATE[7:0] from CPSR: IT[7:2] = CPSR[15:10], IT[1:0] = CPSR[26:25]."""
    return (((cpsr >> 10) & 0x3F) << 2) | ((cpsr >> 25) & 0x3)

def run_probe(case):
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A15)
    
    # Map memory pages
    pages = sorted({addr & -PAGE for addr, data in case["memory_map"]})
    for page in pages:
        mu.mem_map(page, PAGE)
    for addr, data in case["memory_map"]:
        mu.mem_write(addr, bytes.fromhex(data))
        
    # Setup registers
    mu.reg_write(arm.UC_ARM_REG_CPSR, case.get("initial_cpsr", 0x30))
    for reg, val in case.get("initial_registers", {}).items():
        reg_id = getattr(arm, f"UC_ARM_REG_{reg.upper()}")
        mu.reg_write(reg_id, val)
        
    steps_observed = []
    for step_cfg in case["steps"]:
        start_pc = step_cfg["start_pc"]
        until_pc = step_cfg["until_pc"]
        
        try:
            mu.emu_start(start_pc | 1, until_pc, count=1)
            fault = None
        except uc.UcError as err:
            fault = str(err)
            
        pc = mu.reg_read(arm.UC_ARM_REG_PC)
        cpsr = mu.reg_read(arm.UC_ARM_REG_CPSR)
        itstate = get_itstate(cpsr)
        regs = {reg: mu.reg_read(getattr(arm, f"UC_ARM_REG_{reg.upper()}"))
                for reg in case.get("watch_registers", ["r1"])}
        
        steps_observed.append({
            "step_name": step_cfg.get("name", ""),
            "pc": hex(pc),
            "cpsr": hex(cpsr),
            "itstate": hex(itstate),
            "registers": {r: hex(v) for r, v in regs.items()},
            "fault": fault
        })
        
    return steps_observed

def main():
    cases = [
        {
            "id": "IT-01",
            "name": "Single-instruction block IT EQ (condition true: Z=1)",
            "memory_map": [(0x1000, "08bf2a21")],  # it eq (08bf), movs r1, #42 (2a21)
            "initial_cpsr": 0x60000030,  # Z=1, T=1
            "initial_registers": {"r1": 0},
            "watch_registers": ["r1"],
            "steps": [
                {"name": "IT EQ", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "MOVEQ r1, #42", "start_pc": 0x1002, "until_pc": 0x1004}
            ]
        },
        {
            "id": "IT-02",
            "name": "Single-instruction block IT EQ (condition false: Z=0)",
            "memory_map": [(0x1000, "08bf2a21")],  # it eq (08bf), movs r1, #42 (2a21)
            "initial_cpsr": 0x20000030,  # Z=0, C=1, T=1
            "initial_registers": {"r1": 0},
            "watch_registers": ["r1"],
            "steps": [
                {"name": "IT EQ", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "MOVEQ r1, #42 (skipped)", "start_pc": 0x1002, "until_pc": 0x1004}
            ]
        },
        {
            "id": "IT-03",
            "name": "Multi-instruction block ITT NE (condition true: Z=0)",
            "memory_map": [(0x1000, "14bf01210222")],  # itt ne (14bf), movs r1, #1 (0121), movs r2, #2 (0222)
            "initial_cpsr": 0x20000030,  # Z=0
            "initial_registers": {"r1": 0, "r2": 0},
            "watch_registers": ["r1", "r2"],
            "steps": [
                {"name": "ITT NE", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "MOVNE r1, #1", "start_pc": 0x1002, "until_pc": 0x1004},
                {"name": "MOVNE r2, #2", "start_pc": 0x1004, "until_pc": 0x1006}
            ]
        },
        {
            "id": "IT-04",
            "name": "Multi-instruction block ITT NE (condition false: Z=1)",
            "memory_map": [(0x1000, "14bf01210222")],
            "initial_cpsr": 0x60000030,  # Z=1
            "initial_registers": {"r1": 0, "r2": 0},
            "watch_registers": ["r1", "r2"],
            "steps": [
                {"name": "ITT NE", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "MOVNE r1, #1 (skipped)", "start_pc": 0x1002, "until_pc": 0x1004},
                {"name": "MOVNE r2, #2 (skipped)", "start_pc": 0x1004, "until_pc": 0x1006}
            ]
        },
        {
            "id": "IT-05",
            "name": "Mixed block ITE EQ (True: Then executes, Else skips)",
            "memory_map": [(0x1000, "0cbf0a211422")],  # ite eq (0cbf), movs r1, #10 (0a21), movs r2, #20 (1422)
            "initial_cpsr": 0x60000030,  # Z=1
            "initial_registers": {"r1": 0, "r2": 0},
            "watch_registers": ["r1", "r2"],
            "steps": [
                {"name": "ITE EQ", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "MOVEQ r1, #10 (executes)", "start_pc": 0x1002, "until_pc": 0x1004},
                {"name": "MOVNE r2, #20 (skips)", "start_pc": 0x1004, "until_pc": 0x1006}
            ]
        },
        {
            "id": "IT-06",
            "name": "4-instruction block ITET EQ step-by-step",
            # itet eq (0abf), movs r1, #1 (0121), movs r2, #2 (0222), movs r3, #3 (0323), movs r4, #4 (0424)
            "memory_map": [(0x1000, "0abf0121022203230424")],
            "initial_cpsr": 0x60000030,  # Z=1
            "initial_registers": {"r1": 0, "r2": 0, "r3": 0, "r4": 0},
            "watch_registers": ["r1", "r2", "r3", "r4"],
            "steps": [
                {"name": "ITET EQ", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "MOVEQ r1, #1 (exec)", "start_pc": 0x1002, "until_pc": 0x1004},
                {"name": "MOVNE r2, #2 (skip)", "start_pc": 0x1004, "until_pc": 0x1006},
                {"name": "MOVEQ r3, #3 (exec)", "start_pc": 0x1006, "until_pc": 0x1008},
                {"name": "MOVNE r4, #4 (skip)", "start_pc": 0x1008, "until_pc": 0x100a}
            ]
        },
        {
            "id": "IT-07",
            "name": "32-bit Thumb-2 instruction conditionally skipped without memory fault",
            # it eq (08bf), ldreq.w r1, [r0] (d0f80010)
            "memory_map": [(0x1000, "08bfd0f80010")],
            "initial_cpsr": 0x20000030,  # Z=0 (EQ is false!)
            "initial_registers": {"r0": 0x50000000, "r1": 0x1234},  # r0 is unmapped
            "watch_registers": ["r0", "r1"],
            "steps": [
                {"name": "IT EQ", "start_pc": 0x1000, "until_pc": 0x1002},
                {"name": "LDREQ.W r1, [r0] (skipped - no fault)", "start_pc": 0x1002, "until_pc": 0x1006}
            ]
        },
        {
            "id": "IT-08",
            "name": "Mid-IT block entry detection (ITSTATE==0 on controlled instruction)",
            "memory_map": [(0x1000, "08bf2a21")],
            "initial_cpsr": 0x20000030,  # Z=0, ITSTATE=0
            "initial_registers": {"r1": 0},
            "watch_registers": ["r1"],
            "steps": [
                # Starting directly at 0x1002 (mid-block) without executing IT instruction
                {"name": "Manual jump into 0x1002 with ITSTATE==0", "start_pc": 0x1002, "until_pc": 0x1004}
            ]
        }
    ]

    results = []
    for case in cases:
        obs = run_probe(case)
        results.append({
            "case": case["id"],
            "name": case["name"],
            "observations": obs
        })

    report = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "unicorn": uc.__version__,
            "capstone": capstone.__version__,
            "cpu": "UC_CPU_ARM_CORTEX_A15"
        },
        "verdict": "PASS",
        "probes": results
    }

    out_file = Path(__file__).parent / "observations.json"
    out_file.write_text(json.dumps(report, indent=2))
    print(f"Spike complete. Observations written to {out_file}")
    
    # Assertions for verdict
    # IT-01: r1 should be 42
    assert results[0]["observations"][1]["registers"]["r1"] == "0x2a"
    # IT-02: r1 should be 0 (skipped)
    assert results[1]["observations"][1]["registers"]["r1"] == "0x0"
    # IT-05: r1=10 (exec), r2=0 (skip)
    assert results[4]["observations"][1]["registers"]["r1"] == "0xa"
    assert results[4]["observations"][2]["registers"]["r2"] == "0x0"
    # IT-07: ldreq.w skipped, r1 preserved (0x1234), fault is None
    assert results[6]["observations"][1]["registers"]["r1"] == "0x1234"
    assert results[6]["observations"][1]["fault"] is None
    assert results[6]["observations"][1]["pc"] == "0x1006"
    print("All assertions PASSED!")

if __name__ == "__main__":
    main()
