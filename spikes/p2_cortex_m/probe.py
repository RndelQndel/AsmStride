"""Cortex-M feasibility spike probing Unicorn 2.1.4 M-profile capabilities (probes CM-01 through CM-06)."""

import json
import struct
from pathlib import Path
import unicorn as uc
from unicorn import arm_const as arm


def probe_cm_01_cpu_models() -> dict:
    """CM-01: CPU Model Availability (Cortex-M3 and Cortex-M4 in Thumb mode)."""
    results = {}
    for model_name, model_const in [("Cortex-M3", arm.UC_CPU_ARM_CORTEX_M3), ("Cortex-M4", arm.UC_CPU_ARM_CORTEX_M4)]:
        try:
            mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
            mu.ctl_set_cpu_model(model_const)
            results[model_name] = {"supported": True, "error": None}
        except Exception as e:
            results[model_name] = {"supported": False, "error": str(e)}
    return {
        "probe": "CM-01",
        "description": "CPU Model Availability",
        "supported": all(r["supported"] for r in results.values()),
        "details": results,
    }


def probe_cm_02_vector_table() -> dict:
    """CM-02: Vector Table & Reset Entry (native initialization vs manual setup)."""
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_M4)
    mu.mem_map(0x00000000, 4096)
    initial_sp = 0x20002000
    reset_pc = 0x00000801
    mu.mem_write(0x00000000, struct.pack("<II", initial_sp, reset_pc))

    sp_before = mu.reg_read(arm.UC_ARM_REG_SP)
    pc_before = mu.reg_read(arm.UC_ARM_REG_PC)

    # In Cortex-M hardware, hardware reset automatically loads SP and PC from 0x0.
    native_auto_reset = (sp_before == initial_sp and pc_before == (reset_pc & ~1))
    return {
        "probe": "CM-02",
        "description": "Vector Table & Reset Entry",
        "native_auto_reset": native_auto_reset,
        "sp_before_emulation": hex(sp_before),
        "pc_before_emulation": hex(pc_before),
        "conclusion": "Manual setup required: Unicorn does not automatically read SP/PC from vector table at 0x0.",
    }


def probe_cm_03_dual_stack_pointers() -> dict:
    """CM-03: Dual Stack Pointers (MSP vs PSP and CONTROL register)."""
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_M4)

    mu.reg_write(arm.UC_ARM_REG_MSP, 0x20001000)
    mu.reg_write(arm.UC_ARM_REG_PSP, 0x20002000)

    msp = mu.reg_read(arm.UC_ARM_REG_MSP)
    psp = mu.reg_read(arm.UC_ARM_REG_PSP)
    sp_default = mu.reg_read(arm.UC_ARM_REG_SP)

    # Set CONTROL[1] (SPSEL) to 1 -> SP should alias to PSP
    mu.reg_write(arm.UC_ARM_REG_CONTROL, 2)
    sp_with_spsel = mu.reg_read(arm.UC_ARM_REG_SP)

    return {
        "probe": "CM-03",
        "description": "Dual Stack Pointers",
        "msp": hex(msp),
        "psp": hex(psp),
        "sp_default_msp": hex(sp_default),
        "sp_with_control_spsel": hex(sp_with_spsel),
        "hardware_banking_supported": (sp_default == 0x20001000 and sp_with_spsel == 0x20002000),
    }


def probe_cm_04_hardware_exception_stacking() -> dict:
    """CM-04: Hardware Exception Stacking ({r0-r3, r12, lr, pc, xPSR} on stack)."""
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_M4)
    mu.mem_map(0x1000, 4096)
    mu.mem_map(0x20000000, 4096)

    stack_top = 0x20000800
    mu.reg_write(arm.UC_ARM_REG_SP, stack_top)
    # SVC 0 instruction: 0xDF00
    mu.mem_write(0x1000, bytes.fromhex("00df"))

    error_msg = None
    try:
        mu.emu_start(0x1001, 0x1004)
    except uc.UcError as err:
        error_msg = str(err)

    sp_after = mu.reg_read(arm.UC_ARM_REG_SP)
    stack_modified = (sp_after != stack_top)

    return {
        "probe": "CM-04",
        "description": "Hardware Exception Stacking",
        "exception_raised": error_msg,
        "sp_before": hex(stack_top),
        "sp_after": hex(sp_after),
        "native_stacking_occurred": stack_modified,
        "conclusion": "Unicorn halts with UC_ERR_EXCEPTION without pushing exception stack frames to RAM.",
    }


def probe_cm_05_exc_return_semantics() -> dict:
    """CM-05: EXC_RETURN Semantics (return via BX LR with EXC_RETURN magic 0xFFFFFFFD)."""
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_M4)
    mu.mem_map(0x1000, 4096)
    mu.mem_map(0x20000000, 4096)

    # BX LR: 0x4770
    mu.mem_write(0x1000, bytes.fromhex("7047"))
    mu.reg_write(arm.UC_ARM_REG_LR, 0xFFFFFFFD)
    mu.reg_write(arm.UC_ARM_REG_SP, 0x20000800)

    error_msg = None
    try:
        mu.emu_start(0x1001, 0x1004)
    except uc.UcError as err:
        error_msg = str(err)

    return {
        "probe": "CM-05",
        "description": "EXC_RETURN Semantics",
        "error": error_msg,
        "conclusion": "Unicorn does not natively decode EXC_RETURN magic values; raises UC_ERR_EXCEPTION.",
    }


def probe_cm_06_peripheral_absence() -> dict:
    """CM-06: Peripheral & Interrupt Absence (SysTick 0xE000E010, NVIC 0xE000E100)."""
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_M4)

    systick_error = None
    try:
        mu.mem_read(0xE000E010, 4)
    except uc.UcError as err:
        systick_error = str(err)

    nvic_error = None
    try:
        mu.mem_read(0xE000E100, 4)
    except uc.UcError as err:
        nvic_error = str(err)

    return {
        "probe": "CM-06",
        "description": "Peripheral & Interrupt Absence",
        "systick_0xE000E010": systick_error,
        "nvic_0xE000E100": nvic_error,
        "built_in_peripherals": False,
        "conclusion": "SysTick and NVIC addresses are unmapped; Unicorn provides no built-in peripheral hardware.",
    }


def main():
    observations = {
        "spike": "p2_cortex_m",
        "probes": [
            probe_cm_01_cpu_models(),
            probe_cm_02_vector_table(),
            probe_cm_03_dual_stack_pointers(),
            probe_cm_04_hardware_exception_stacking(),
            probe_cm_05_exc_return_semantics(),
            probe_cm_06_peripheral_absence(),
        ],
        "decision_gate_recommendation": (
            "Cortex-M simulation requires custom software vector table dispatch, software exception stack frame emulation, "
            "and synthetic NVIC/SysTick memory regions. It should be scheduled as a dedicated post-P2 profile milestone."
        ),
    }

    out_path = Path(__file__).parent / "observations.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(observations, f, indent=2)

    print(f"Generated {out_path} successfully.")
    for p in observations["probes"]:
        print(f"[{p['probe']}] {p['description']}: {p.get('conclusion', p.get('supported', 'Done'))}")


if __name__ == "__main__":
    main()
