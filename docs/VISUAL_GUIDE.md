# ArmStride Visual Guide & Workflow Tour

Welcome to the visual guide for **ArmStride** — a lightweight, local interactive ARMv7-A assembly and disassembly simulator.

This guide walks through the primary user interfaces, workflow steps, and diagnostics.

---

## 1. Main Workspace Overview

The ArmStride workspace is organized into a clean, focused, light-themed debugging interface designed to eliminate clutter and display all critical CPU state without vertical scrolling.

![Main Workspace](../docs/assets/hero_workspace.png)

### Key Interface Sections:
1. **Execution Toolbar (Top)**:
   - **`Step` (F7/F8)**: Executes the instruction at the current Program Counter (PC).
   - **`Reset` (F9)**: Restores CPU registers, flags, and memory back to the initial baseline state.
   - **`Start / current PC` & `Go`**: Jump or set an arbitrary entry point.
   - **Status Badge (`READY` / `STOPPED`) & Step Sequence Counter**: Displays current engine state and total committed step count.

2. **Program Input (Top-Left)**:
   - Architecture selector: **ARMv7-A** (32-bit LE) or **RISC-V (RV32I)**.
   - Input format selector: **Assembly source**, **Disassembly import**, or **ELF32 Binary (.elf)**.
   - Mode: **ARM**, **Thumb / Thumb-2**, or **RV32I**.
   - Base address configuration (default: `0x1000`).
   - File loader (`.s`, `.txt`, `.elf`) or direct multi-line text input.
   - Quick presets for mixed ARM/Thumb, IT blocks, loops, and RV32I arithmetic & stack operations.
   - Optional **Custom Scratch Stack setup** (Base address & size).

3. **Instructions View (Middle-Left)**:
   - Synchronized instruction table showing:
     - Step indicator (`▶` arrow pointer on current PC).
     - Instruction Hex Address.
     - Raw Opcode Bytes in hex (e.g. `2a 00 a0 e3` or `13 05 a0 02`).
     - Decoded instruction mnemonic and operands.
     - Source line and DWARF/symbol cross-references.

4. **Registers & Flags (Right Column)**:
   - **Profile-Driven Register Grid**:
     - **ARMv7-A**: 2-column layout (`R0`–`R7` and `R8`–`R12`, `SP`, `LR`, `PC`), flags bar (`N`, `Z`, `C`, `V`), and CPSR editor.
     - **RISC-V (RV32I)**: Full 32-register grid (`x0`–`x31` + `PC`) annotated with standard ABI aliases (`zero`, `ra`, `sp`, `gp`, `tp`, `t0`–`t6`, `s0`–`s11`, `a0`–`a7`). CPSR and condition flags are cleanly suppressed. `x0 (zero)` is locked to 0 and immutable.
   - **Delta Highlighting**: Registers modified during the latest step are highlighted with an orange border.
   - **In-place Value Editing**: Modify any register at any time; changes update the baseline for Reset.

5. **Memory & Synthetic Stack Panels (Bottom)**:
   - **Memory Hex Grid**: Address, 4-byte grouped hex view, and 32-bit little-endian word representation.
   - **Synthetic Scratch Stack**: Follows `SP` automatically, marks known stack bytes vs unallocated memory (`??`), and flags write operations with a yellow delta (`Δ`) symbol.

---

## 2. Disassembly Import Workflow

When analyzing firmware crash dumps or compiler outputs, you often don't have the original source files. ArmStride can parse raw disassembly output from tools like GNU `objdump` and ARM `fromelf`.

![Disassembly Import](../docs/assets/feature_disassembly.png)

### Workflow:
1. Switch **Input** to `Disassembly import`.
2. Paste disassembly lines containing addresses, opcodes, and instructions:
   ```text
   1000: E3A0002A  MOV  r0, #42
   1004: E2801008  ADD  r1, r0, #8
   1008: E58D1000  STR  r1, [sp]
   100C: E59D2000  LDR  r2, [sp]
   ```
3. Click **`Load`**: ArmStride parses the addresses, extracts opcode bytes directly, verifies alignment, and binds the starting PC.
4. Step through the disassembly with full register and stack tracking.

---

## 3. Memory Fault Detection & Atomic Rollback

ArmStride enforces **strict memory safety**. Access to uninitialized or unmapped memory does not silently succeed with garbage values or cause a hard crash. Instead, it triggers an atomic rollback.

![Memory Fault and Rollback](../docs/assets/feature_fault_rollback.png)

### Safe Fault Mechanics:
1. In the example above, an instruction attempts to load from unmapped address `0x50000000` (`ldr r0, [r1]`).
2. The simulation engine detects an **`unmapped_memory_access`** violation.
3. The engine **aborts the step** and **rolls back** all CPU registers, flags, and memory to the state immediately preceding the faulty instruction.
4. The **Status & Diagnostics** panel displays:
   - Fault address and access type (`read` / `write`).
   - Exact missing address range.
   - Clear diagnostic message: *"Previous state restored; baseline preserved"*.
5. You can patch the required memory using the **Memory Patch** tool and retry execution safely.

---

## 4. Useful Keyboard Shortcuts

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| **`F7`** or **`F8`** | **Step** | Advance simulation by one instruction |
| **`F9`** | **Reset** | Reset registers and memory to baseline |
| **`Enter`** | **Apply** | Commit edited register or memory value |
