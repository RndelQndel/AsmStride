# ArmStride Software Requirements Specification

Status: behavioral contract for the first usable version (P0). P0 execution, browser workflows, and package checks are fully verified. See ARCHITECTURE.md for the authoritative current roadmap.

## 1. Authority and terminology

[concept.md](concept.md) is the primary source of product intent. [README.md](../README.md) is its public summary. This specification resolves their open behavioral questions; [ARCHITECTURE.md](ARCHITECTURE.md) describes how to satisfy it. ArmStride remains the working name.

**Shall** denotes a P0 requirement. P1 and deferred items are not P0 acceptance obligations. An **instruction address** is the address of its first byte. A **snippet** is an ordered set of addressed instructions, possibly with gaps. **Known memory** means bytes supplied by the user, loaded as code, or explicitly initialized by the tool. **Unknown memory** means no byte value has been established; it does not mean a symbolic value. A **Step** attempts one architectural instruction, including a conditionally skipped instruction.

### Explicit assumptions and decisions

These choices make ambiguous concept behavior implementable; they are not claims that the source documents already specify them.

| ID | Decision | Reason |
| --- | --- | --- |
| A-01 | P0 accepts ARM/Thumb assembly source with an explicit base address, or addressed disassembly/crash-log text with encoded bytes. Both produce the same ProgramImage. | Assemble source before loading; retain supplied import bytes. Execution is always byte-driven. |
| A-02 | ARMv7-A, little-endian, user-mode integer execution is the concrete CPU profile. ARM and Thumb, including 32-bit Thumb encodings, are required. Each load has one execution mode. | “ARMv7” alone does not specify a machine; this is a small CPU-level environment, not a Cortex-M board model. |
| A-03 | Unknown memory access stops execution. No demand-zero mapping occurs. A visible, zero-filled scratch stack is the one tool-created data region. | Missing evidence must not silently become a plausible zero value, while basic PUSH/POP must work immediately. |
| A-04 | Unspecified general registers and LR default to zero; flags default to zero. Defaults are labeled assumptions. | Concrete execution requires concrete values; symbolic state is excluded. |
| A-05 | User Baseline State starts with load defaults and receives every accepted manual register, flag, PC, and memory edit. Runtime State receives the same edits plus execution effects. Reset copies the baseline into runtime. | Evidence discovered during stepping must survive Reset; CPU-generated changes must not become initial evidence. |
| A-06 | Run and breakpoints are P1. Mixed ARM/Thumb execution, Thumb IT blocks, and advanced CPU features are deferred. | A bounded single-step integer workflow is the smallest useful release. |
| A-07 | Atomic Step remains the required product behavior: a failed attempt restores pre-Step runtime registers, flags, and memory. Its mechanism must pass the Phase 0 Unicorn spike before core implementation. | Users can repair missing state and retry without hidden partial effects; engine rollback is not assumed. |
| A-08 | Sessions are local and ephemeral; browser refresh starts a new session. | Persistence and shared sessions are not product requirements. |

## 2. Product definition

ArmStride is a local interactive assembly simulator/debugger for short ARM/Thumb assembly snippets or addressed disassembly fragments and partially supplied machine state. An embedded developer, firmware engineer, or failure analyst pastes a fragment, supplies the register and memory values available in a crash report, chooses an instruction address, and steps through the fragment to inspect concrete effects.

It solves the gap between reading a listing manually and reconstructing a complete debugging environment. The original ELF, firmware image, symbols, board, and attached debugger are not required. It answers questions such as “which branch does this comparison take with R0 = 0?”, “what does this prologue put on the stack?”, and “which missing address prevents this load?”

A conventional target debugger normally needs a live process, board, or sufficiently complete captured environment. A full-system emulator requires a broader machine and image setup. An execution library can run the bytes but does not itself provide this paste/inject/step interface or explain missing state. These tools remain useful; ArmStride specializes in minimizing setup for incomplete evidence. Its output describes the supplied experiment, not proof of what the original device did.

## 3. Goals

- Assemble small ARM/Thumb source snippets or import disassembly without its original binary container.
- Accept partial register and memory evidence and disclose every tool-provided default.
- Start at any valid instruction boundary in the loaded snippet.
- Make register, CPSR/flag, PC, memory, and stack changes observable after each Step.
- Make branch outcomes and missing-state failures explicit in crash-log and embedded debugging workflows.
- Keep the local workflow compact: paste, load, inject state, step, inspect, reset.

## 4. Non-goals

P0 is not a full-system emulator, ELF/binary loader or analyzer, decompiler, GDB replacement, hardware debugger, or complete reverse-engineering suite. It does not model peripherals, MMIO side effects, interrupts, operating systems, timing, caches, MMUs, or exception handlers.

Symbolic registers, symbolic execution, constraint solving, automatic path exploration, branch-target solving, and angr integration are excluded. There is no cloud collaboration, multi-user service, authentication system, database, persistent project storage, or target-board/GDB integration. CFG visualization, watchpoints, advanced breakpoint expressions, and execution history/reverse stepping are excluded. Imported text labels are display information. Source labels and ordinary local branch references are resolved by the selected assembler; ArmStride has no symbol-resolution framework. This is a single-file snippet input path, not a build system: no macros as a product feature, linker scripts, ELF generation, object loading, project/multi-file builds, include paths, or C/C++ compilation. RISC-V is a future extension only after the ARM P0 product is complete; AArch64 and x86/x86-64 are also outside P0.

## 5. User scenarios

### 5.1 Crash-log analysis

1. A developer receives several addressed instruction lines, R1, SP, LR, and possibly a few memory values.
2. They select ARM or Thumb, paste the lines, and load them. Diagnostics identify malformed lines before a program is installed.
3. They choose a loaded instruction as the start PC, enter the known register values, and inject known memory bytes or a 32-bit word.
4. The UI shows other registers as assumed zero and identifies the scratch stack.
5. Each Step either executes one instruction and shows its effects, or stops with a precise missing-memory/unsupported-instruction error.
6. The developer adds missing memory and retries, or resets to the user baseline to repeat the experiment with the newly supplied evidence retained.

### 5.2 Branch inspection

The user loads a CMP followed by a conditional branch. They set the compared register, step CMP, inspect N/Z/C/V and the changed flags, then step the branch. The UI reports its condition, taken/not-taken result, and PC before/after. Reset and a different register value allow a second experiment. Branch outcome must remain correct even when the branch target equals the fall-through address.

### 5.3 Stack inspection

The user starts at a PUSH or a function prologue with SP on the scratch stack, or supplies SP and memory corresponding to the original stack. Stepping PUSH and SP arithmetic shows the changed SP and written words. Stepping POP or a function epilogue shows restored registers and SP. If POP loads PC outside the snippet, that instruction completes and execution stops at the resulting PC. The tool does not invent the missing caller code.

### 5.4 Partial memory state

For `LDR r0, [r1, #4]`, the user knows R1 but not the addressed word. The Step fails with the requested address, width, and read access type, leaving state unchanged. Injecting only one byte does not make an entire word known. After supplying all four bytes, retry succeeds. Adjacent unspecified memory remains unknown even if it shares an internal backing page with supplied bytes. A store into missing memory also stops; the user can explicitly create a zero-filled range before retrying.

## 6. Functional requirements

| ID | P0 requirement |
| --- | --- |
| FR-001 | Accept pasted plain text and the contents of a user-selected local UTF-8 text file without requiring ELF, binary, symbols, or firmware. Loading file content and pasting identical text shall produce identical results for the selected source/import workflow. |
| FR-002 | Parse the supported formats in Section 7 into addressed instructions; retain source line numbers and return line-specific diagnostics. A load with any error shall leave the previous program and state unchanged. |
| FR-003 | Preserve explicit 32-bit addresses, sort instructions by address, permit gaps, and reject duplicate addresses, overlapping instruction byte ranges, address overflow, and invalid alignment. Do not relocate or fill code gaps. |
| FR-004 | Preserve instruction bytes and their actual width. Bytes shall determine execution; pasted mnemonic/operand text shall remain visible but shall not override bytes. Show the decoded instruction alongside preserved source so discrepancies can be inspected. Generated source bytes become authoritative only after assembly and the same decode/image validation used by import. |
| FR-005 | Default PC to the lowest loaded instruction address. Accept another start/current PC only if it is an instruction start in the loaded mode. Reject an interior, unaligned, odd-tagged, missing, or out-of-range address without mutation. |
| FR-006 | Each Step shall attempt exactly one instruction at current PC and return the result defined in Section 8. It shall never execute the next instruction automatically. |
| FR-007 | Display R0–R12, SP/R13, LR/R14, PC/R15, full CPSR, and individual N/Z/C/V flags in hexadecimal or labeled bit form. Display SP/LR/PC aliases as the same registers, not independent values. |
| FR-008 | Permit editing R0–R12, SP, LR, and PC using unsigned 32-bit values. Accept `0x`-prefixed hexadecimal or decimal in UI fields, reject malformed/out-of-range input, and validate PC as in FR-005. Reject misaligned SP (not a multiple of four). |
| FR-009 | Display CPSR after every operation; permit editing N/Z/C/V individually or through a CPSR value that changes only those bits. Reject edits to execution-mode, privilege, or other protected bits. |
| FR-010 | Inject bytes at a chosen address, a little-endian 32-bit word, or an explicitly zero-filled byte range. A valid injection shall make exactly those bytes known/readable/writable, update overlapping data bytes, and leave all other bytes unchanged. Reject any patch overlapping code or wrapping the address space. |
| FR-011 | Inspect a bounded memory range without executing code or allocating memory. Show known bytes, `??` for unknown bytes, and little-endian words only where all four bytes are known. |
| FR-012 | Provide a stack view following current SP, showing addresses, words/unknown bytes, an SP marker, and changes from the latest successful Step. It shall also work when SP is outside the scratch stack and shall not allocate memory merely by viewing it. |
| FR-013 | Mark current PC and highlight the corresponding instruction; bring it into view after load, a valid PC edit, Reset, or Step. If resulting PC is outside the snippet, show its value and stop reason without highlighting a different line. |
| FR-014 | Highlight only values that changed in the latest successful Step: registers, flags, and visible memory bytes. Distinguish a write of the same value from an actual value change in the step details. Clear old execution highlights after load, Reset, a manual edit, or a failed Step. |
| FR-015 | Reset shall restore Runtime State from User Baseline State, including the latest manually selected start PC and all accepted manual edits, and clear step results/errors. CPU-generated register/flag changes and memory writes shall be discarded. |
| FR-016 | Report execution failures with stable categories and relevant PC, instruction, access address/width/type, or backend context. A failed Step shall leave all machine state unchanged. Missing code after a successful instruction is a stop, not a rollback-triggering execution error. |
| FR-017 | Mark instructions known to require excluded features before execution. Otherwise attempt loadable instructions using the selected CPU profile; report engine rejection as an explicit failed Step. Do not skip, approximate, or replace instructions with NOP. Encodings that fail decoding or have incorrect byte widths shall be load errors; engine-only incompatibilities may be discovered at Step. |
| FR-018 | Apply the strict memory policy and the labeled defaults in Sections 9–10. Neither inspection nor an access failure shall silently create bytes. |
| FR-019 | Support the ARM and Thumb instruction scope in Section 11, including both two- and four-byte Thumb instructions. Report attempted execution-mode changes as unsupported and restore the pre-Step state. |
| FR-020 | Each browser page instance shall have its own simulation state. Loading, editing, stepping, resetting, or closing one session shall not change another. |
| FR-021 | Run locally through a browser UI without an account or external service. P0 execution controls shall be Load, Step, Reset, and start/current PC input; disable conflicting controls while a request is pending. |
| FR-022 | Report control-flow effects per Step: condition when applicable, taken/not-taken for a branch, PC before/after, and destination. A non-branch shall not be labeled “branch not taken.” |
| FR-023 | Every accepted manual edit shall update only its explicitly addressed register, flag bits, PC, or memory bytes in both User Baseline State and Runtime State. Show that manual edits survive Reset. Never copy unrelated execution changes into the baseline. Rejected edits change neither state. |
| FR-024 | Expose a session-local `step_seq`, initially zero, increasing by one for each successfully committed Step, including conditional skips and stops at unloaded PC. Failed Steps, manual edits, Reset, and program replacement leave it unchanged. Use it to distinguish completed Steps with identical PC/state; do not promise exactly-once HTTP execution. |

## 7. Input requirements

### 7.0 Assembly source workflow

The user selects source or disassembly/import input explicitly. Source input shall accept multi-line ARM or Thumb assembly, labels and ordinary branch references supported by the assembler, a selected mode, and an explicit unsigned 32-bit base/load address. The assembler shall receive that origin before encoding. Generated instructions have concrete aligned addresses; the resulting image shall never be relocated after assembly.

A successful assembly shall yield machine bytes, decoded at that base through the existing ARM codec/Capstone boundary. Instruction widths come from those bytes, including adjacent 16-bit and 32-bit Thumb encodings. The resulting immutable Instruction and ProgramImage records enter the existing simulation lifecycle; the core never executes mnemonic strings. MachineState, MemoryState, Step, rollback, baseline, Reset and result semantics are shared with import.

P0 is single-mode per image. Mode is never inferred from directives. The initial source subset permits instructions, labels, assembler comments, `.syntax unified`, and mode declarations matching the explicit selection (`.arm`/`.code 32` or `.thumb`/`.code 16`). Other directives, mode changes, data emission, literal-pool pseudo-instructions such as `ldr r0, =value`, and build facilities are rejected as `unsupported_source`. Use explicit PC-relative instructions and existing memory injection for literal data; implicit pools would otherwise be mistaken for executable instructions. This restriction does not add an instruction allowlist or expand the ARM execution profile. Decodable IT/system and other existing feature exclusions retain load warnings and atomic Step rejection; attempted runtime interworking retains rollback.

Assembly and normalization are atomic: errors return application-owned diagnostics with no installable ProgramImage and no executable partial bytes. Syntax failures use `assembly_error`; origin, limits, decode and profile failures retain existing validation categories. Candidate memory/backend installation also must succeed before replacing the existing experiment. Failed replacement preserves program, runtime, baseline, latest result, counter and backend.

Preserve the complete original source on the result/image. Keystone does not provide reliable source-to-instruction mapping: generated instructions have `source_line = null`, empty per-instruction source text, and decoded display text. Step instruction identities also permit a null source line. Import records retain their existing one-based source lines and original text. The generated decoded listing is the authoritative execution view; exact source-level stepping/debug mapping is deferred. Report native syntax messages and statement counts without presenting counts as line numbers; policy diagnostics can identify the offending source line. The same 1 MiB text and 10,000-instruction limits apply.


### 7.1 Accepted text subset

The disassembly/import path accepts instruction records extracted from ARM `fromelf`, GNU `objdump`, generic address/opcode/mnemonic listings, and manually composed listings following those formats. It does not promise to parse every option/version of either tool or arbitrary prose from a crash log.

Each instruction record needs an explicit address, encoded opcode field, and mnemonic/display text. Addresses use hexadecimal, with optional `0x` and optional trailing colon. Upper/lowercase hex, spaces, and tabs are accepted. Source order may differ from address order. Blank lines, full-line `;`, `#`, or `//` comments, address-and-symbol label lines, `symbol:` labels, and recognized section/file headers are ignored and counted in diagnostics. Recognized headers are GNU `file format` and `Disassembly of section ...:` lines, and fromelf `** Section #...`, `Size : ...`, and `Address: ...` metadata lines. Fromelf symbol blocks may also contain `$a`/`$t` mapping symbols (with numeric suffixes), `[Anonymous symbol #N]`, and bare symbol names at the less-indented symbol column preceding an instruction. They are display metadata, not automatic mode switches. Accept these only in that structural context; arbitrary bare words and mnemonic-only instructions remain errors. Other nonempty lines are errors, including mnemonic-only instructions, data directives, omitted-byte placeholders, and wrapped instruction records. A `#` inside operands is an immediate marker, not a comment delimiter.

| Format | Accepted instruction form | Opcode interpretation |
| --- | --- | --- |
| Fromelf subset | Address, opcode word/halfwords, optional printable ASCII column, mnemonic and operands | ARM word or Thumb halfwords as described below; ASCII columns are ignored only when unambiguously separated by the format grammar. |
| Objdump subset | `address: opcode mnemonic operands`, with optional symbol annotations after operands | ARM word, Thumb halfword(s), or separated bytes; labels/annotations do not supply executable bytes. |
| Generic | `0x08000100: E92D4010 PUSH {r4, lr}` | Explicitly selected `words` or `bytes` encoding when automatic interpretation is ambiguous. |
| Manual | The same addressed forms, such as `08000100: 10 40 2d e9 PUSH {r4, lr}` | The four byte tokens are already in increasing memory-address order. |

Fromelf records with or without an ASCII column after the opcode are supported only when the opcode and mnemonic columns can be identified uniquely. An ambiguous record shall request explicit format/encoding selection or normalization to the generic form; it shall not guess.

### 7.2 Byte normalization

ARM instruction starts must be four-byte aligned; Thumb instruction starts must be two-byte aligned, including four-byte Thumb instructions. All P0 code and data are little-endian. ARM accepts one eight-digit word or four two-digit byte tokens. In word form, `E92D4010` becomes memory bytes `10 40 2D E9`.

Thumb accepts one four-digit halfword for a 16-bit instruction, two four-digit halfwords in instruction order for a 32-bit instruction, or two/four byte tokens. For example, `F000 F800` becomes `00 F0 00 F8`; it is not reversed as one 32-bit integer. A single eight-digit token in Thumb mode is rejected as ambiguous; users must split it into halfwords or supply memory-order bytes. The actual decoded width must equal the byte count in the line. The disassembly/import parser never synthesizes bytes from mnemonic text; source assembly is a separate explicitly selected operation.

### 7.3 Format selection and failure

The user chooses `auto`, `fromelf`, `objdump`, or `generic`; generic encoding can be `auto`, `words`, or `bytes`. Auto detection tests the fixed supported grammars. If successful candidates produce identical instructions, use a deterministic preference of fromelf, objdump, generic; if they disagree, require explicit selection. A fixed preprocessing pass may remove the fixture-defined crash-log envelope described below while preserving original line numbers. The remaining instruction records must share one supported format; arbitrary mixtures still require user normalization.

The parse report includes detected/selected format, instruction count, ignored-line count, and diagnostics with severity, one-based line number, message, and offending text. Partially valid text may produce a diagnostic preview, but no partial program is installed. An empty result is an error. Decodable instructions known to require explicitly excluded features produce warnings and remain loadable; absence of a warning does not certify engine support; decode failures produce errors. The displayed source listing is never proof that its mnemonic agrees with its bytes; execution always follows the decoded bytes.

### 7.4 Parser fixture contract

P0 parsing shall be checked against 5–10 small fixtures; the initial set below has eight. These are reviewed input/output contracts within this document, not files created by this design task. The examples are format-representative seeds, not claimed captures from installed tool versions. During implementation, retain source/tool/version or a `synthetic` label with each fixture, and acquire actual fromelf/objdump extracts to confirm the layouts before claiming tool compatibility. Preserve raw whitespace and log prefixes in captured fixtures.

| Fixture | Required coverage and expected result |
| --- | --- |
| PF-01 `fromelf_arm` | Section metadata, mapping/symbol block, ASCII column; instruction on line 4, three ignored lines; bytes `05 00 A0 E3`, size four, no errors. |
| PF-02 `fromelf_thumb` | 16-/32-bit Thumb encodings and optional ASCII column; instructions on lines 3/4, two ignored lines; bytes `05 20` and `40 F2 08 01`, sizes two/four, no errors. |
| PF-03 `objdump_arm` | File/section headers, symbol label, tab/space variations and symbol annotation; instructions on lines 4/5 at `0x08000100`/`0x08000104`, three ignored lines; bytes `05 00 A0 E3`/`FD FF FF EA`, no errors. |
| PF-04 `objdump_thumb` | Adjacent two-/four-byte instructions; instructions on lines 2/3, one ignored line; same addresses/bytes/sizes as PF-02, no errors. |
| PF-05 `noisy_crash_log` | Recognized timestamp/record prefixes and non-code metadata; instruction on original line 2 with bytes `05 00 A0 E3`, two ignored lines, no errors. |
| PF-06 `generic_bytes` | Memory-order byte tokens equivalent to word-form input; line 1 yields `05 00 A0 E3`, size four, zero ignored lines, no errors. |
| PF-07 `malformed_opcode` | Instruction-looking line with malformed/missing opcode among valid lines; error on line 2, one valid preview record from line 1, zero ignored lines, no installation. |
| PF-08 `duplicate_address` | Two valid records with the same address; duplicate-address error identifies lines 1/2, zero ignored lines, no installation and existing state intact. |

Representative accepted inputs:

PF-01, ARM (the ASCII column is display-only):

```text
** Section #1 '.text' (SHT_PROGBITS) [SHF_ALLOC + SHF_EXECINSTR]
    $a.0
    example
        0x08000100:    e3a00005    ....    MOV r0,#5
```

PF-02, Thumb:

```text
    $t.0
    example
        0x08000100:    2005         ..      MOVS r0,#5
        0x08000102:    f240 0108    @...    MOVW r1,#8
```

PF-03, ARM:

```text
sample.elf:     file format elf32-littlearm
Disassembly of section .text:
08000100 <example>:
 8000100: e3a00005  mov r0, #5
 8000104: eafffffd  b 8000100 <example>
```

PF-04, Thumb:

```text
08000100 <example>:
 8000100: 2005       movs r0, #5
 8000102: f240 0108  movw r1, #8
```

PF-05, ARM crash log:

```text
[00:00:01.250] CRASH: captured instruction fragment
[00:00:01.251] DISASM: 0x08000100: E3A00005 MOV r0,#5
[00:00:01.252] REGS: r0=00000000
```

P0 recognizes this optional `[HH:MM:SS.mmm]` prefix followed by `DISASM:`, `CRASH:`, `REGS:`, or `STACK:`. `DISASM:` payloads must parse; malformed payloads are errors. The other three record types are ignored with a visible count and do not inject registers/memory. Unrecognized prose is reported, never silently removed. Additional log wrappers require another concrete fixture, not a generic “ignore anything unparseable” switch.

PF-06, ARM bytes:

```text
0x08000100: 05 00 a0 e3 MOV r0,#5
```

PF-07 rejects line 2 while retaining a preview of line 1:

```text
0x08000100: E3A00005 MOV r0,#5
0x08000104: E28??003 ADD r1,r0,#3
```

PF-08 rejects both conflicting addresses:

```text
0x08000100: E3A00005 MOV r0,#5
0x08000100: E3A00006 MOV r0,#6
```

For PF-01/PF-03/PF-05/PF-06, the instruction at `0x08000100` normalizes to `05 00 A0 E3`, size four. For PF-02/PF-04, the records normalize to `05 20` at `0x08000100` and `40 F2 08 01` at `0x08000102`, sizes two and four. Fixture expectations shall additionally state diagnostic severity, source lines, ignored-line counts, and whether installation is permitted. Format examples specify parser behavior; independent verification of executable bytes is required by the golden-case contract in ARCHITECTURE.md.

## 8. Execution semantics

### 8.1 Load and start PC

Loading valid text creates a fresh experiment: initialized machine state, scratch stack, and code bytes. A successful replacement load discards the old experiment and baseline. Failed loads change neither. Default PC is the lowest instruction address, even if source lines were unsorted. The user can select any loaded instruction start before or between Steps; “Go” changes PC and does not execute.

PC is displayed as the address of the next instruction to execute. For Thumb, addresses are even; the mode is a separate property, not encoded into the user-visible address. A CPU instruction reading PC observes the architecture's pipeline/alignment semantics, not necessarily the displayed instruction address. Users entering a PC captured from hardware must choose the corresponding instruction address; the tool does not automatically subtract a pipeline offset.

### 8.2 One Step

1. Validate that current PC identifies a loaded instruction in the active mode and reject known excluded features. Engine compatibility is determined by the execution attempt, not an exhaustive application-maintained instruction allowlist.
2. Attempt that instruction using the current concrete state. A condition-failed ARM instruction still consumes one Step, ordinarily advances to fall-through, and does not apply its conditional effects.
3. On success, commit the instruction's architectural register, CPSR, and memory effects to Runtime State only and increment `step_seq` once. Read the resulting PC from execution. Use instruction width to identify fall-through for reporting; never implement a universal `PC += 4` rule.
4. Return the executed instruction, before/after PC, register and flag changes, data memory reads/writes, branch outcome if applicable, and any stop reason. Instruction fetches are not listed as data reads.
5. Remain paused. Another instruction requires another Step request.

For ordinary sequential execution, fall-through is `address + size` in the profile's 32-bit address space. A 32-bit Thumb instruction is one Step, not two. Branch/call/return and allowed PC-writing instructions determine their own next PC. LR updates from calls are preserved, including the architecture's Thumb return-address convention.

### 8.3 Branches and stopping

A taken branch transfers to its computed target; a condition-failed branch falls through. The result identifies whether the branch executed, not merely whether next PC differs from fall-through. Direct branches use the offset encoded in the bytes at their preserved address; pasted target labels do not relocate them.

After a successful instruction:

- If next PC is a loaded instruction start in the same mode, the session is ready for the next Step.
- If it is outside the loaded starts, stop with `pc_not_loaded`, preserving the completed instruction's changes and the resulting PC. This includes reaching the end, a code gap, an external function/caller, or the middle of another instruction. Report whether the target was outside the image or inside a non-boundary byte range.
- If it changes execution mode, fail with `unsupported_mode_transition` and restore the pre-Step state. There is no partially switched session.

No sentinel LR, host call stub, automatic return, implicit NOP, or page padding acts as program termination/code. An LR of zero can naturally produce `pc_not_loaded` when used by a valid same-mode return. An additional Step with no loaded instruction at PC executes nothing and reports `invalid_pc`.

### 8.4 Failure and recovery

Invalid/unsupported instructions, unknown memory reads/writes, writes to code, unsupported mode changes, and execution-engine failures stop the attempted Step without committed CPU or memory changes. The error includes sufficient context to locate the problem. Attempted memory access details may be shown as diagnostic events but must not be presented as committed writes.

A user can repair registers/memory, select another valid PC, reload, or Reset and try again. There is no automatic skipping. A backend failure that prevents reliable restoration makes the session unavailable for further Step until Reset or successful reload; the UI shall not present partially recovered state as valid.

## 9. Machine state and Reset

### 9.1 Initial state

| State | Default | User control and interpretation |
| --- | --- | --- |
| R0–R12 | `0x00000000` | Editable; marked default/assumed until supplied or modified by execution. |
| SP/R13 | `0x20100000` | Top (exclusive upper bound) of the default downward-growing scratch stack; editable, four-byte aligned. Editing SP does not relocate or allocate memory. |
| LR/R14 | `0x00000000` | Editable; not a synthesized caller or termination hook. |
| PC/R15 | Lowest loaded instruction address | Editable only to a loaded boundary; zero/empty before a program exists is not an executable state. |
| CPSR | `0x00000010` for ARM; `0x00000030` for Thumb | User mode; T corresponds to selected mode; N/Z/C/V initially zero. Only N/Z/C/V are editable in P0. All other bits are displayed and controlled by the profile/execution. |
| Code bytes | Loaded bytes at their explicit addresses | Known, readable and executable only at loaded instruction starts; not user-writable. |
| Scratch stack | `[0x200F0000, 0x20100000)` filled with zero | Tool-created, readable/writable, non-executable; visibly labeled synthetic. |
| Supplied memory | Only the exact supplied bytes | Known, readable/writable data; no implicit neighboring bytes. |
| All other memory | Unknown/unmapped | Inspected as `??`; CPU access fails. |

A load may specify a different scratch-stack base and size to avoid collisions or match a scenario. Base and size must be positive-range valid with four-byte alignment, size greater than zero, and no overlap with code. Initial SP equals its exclusive upper bound, which must be representable as a 32-bit value. A conflicting default stack causes a load diagnostic requiring a different stack range; it is never silently moved. Changing stack configuration requires reload.

Register origin labels distinguish defaults, explicit inputs, and execution updates. Memory views distinguish code, synthetic stack, user-supplied data, and unknown addresses. These are initialization/source labels, not taint tracking or an assertion that a computed value is historically true. An execution-unchanged register retains its prior label; an explicit edit is labeled user-supplied even if its numeric value stays the same. Execution writes are marked in the latest Step without propagating evidence labels through calculations.

### 9.2 User baseline and runtime lifecycle

There are two concrete states, not two editing modes:

- **User Baseline State:** load defaults plus every accepted explicit user edit. It owns the restart PC, user register/flag values, synthetic stack defaults, and supplied memory.
- **Runtime State:** initially a copy of the baseline; CPU execution changes this state only. Manual edits also apply here immediately so a failed instruction can be retried.

Every manual edit applies its exact write set to both states, before or after any Step. Editing R1 does not copy runtime R0 or SP into the baseline. A flag toggle updates only that flag in each state; an explicit full CPSR edit supplies all editable N/Z/C/V bits. A memory patch updates only the supplied bytes in each state, preserving unrelated baseline bytes even if runtime stores changed neighboring bytes. Explicit zero-fill follows the same rule. Editing PC/Go also updates the restart PC; merely highlighting or selecting a line does not. Invalid edits change neither state.

Reset copies the baseline into runtime, including its PC and complete logical memory mappings, and clears the latest Step/error/highlights. Every accepted manual edit survives; CPU-generated changes disappear. Reset never copies current runtime back into baseline. A successful program replacement creates fresh defaults and discards both prior states. There is no baseline freeze, temporary-patch mode, “save baseline” action, or history UI.

For example, after two successful Steps, a load fails on missing memory. The user supplies that word and retries. Reset then preserves that word and restarts at the baseline PC, while discarding computed registers and stores. If the user manually changes PC during inspection, that new address becomes the next Reset destination. The UI shall state `Manual edits update the reset baseline` and show the baseline start PC alongside the current PC.

### 9.3 Step sequence

`step_seq` belongs to the session, not to either CPU state. It starts at zero when the session is created and increments only after a successful Step commit. A conditionally skipped instruction and a completed branch outside the snippet count as success. Rollback/failure does not increment it. Reset, edits, and replacement loads preserve the counter so it remains monotonic for that session; a new session starts over. This is a lightweight completion indicator, not a request ID, event log, or exactly-once delivery guarantee.

## 10. Memory behavior

P0 uses **strict missing-memory behavior**, with no policy toggle. This avoids presenting unknown firmware state as discovered facts and keeps one testable execution policy.

- Code occupies exactly supplied instruction byte ranges. Gaps are unknown. Code may be read as data, but cannot be overwritten; self-modifying code is excluded.
- The scratch stack is the explicit zero-initialization exception. Its label shall remain visible in stack inspection.
- A user memory injection creates or updates exactly its data byte interval; adjacent intervals may be combined without making gaps known. Overwriting part of the scratch stack is allowed. Any code overlap rejects the entire patch.
- A four-byte word injection expands into four little-endian bytes. Zero-fill is an explicit user action over a specified length, not a response to a CPU fault.
- Reads and writes must cover entirely known, permitted bytes, including accesses crossing region boundaries. An access with one missing byte fails as a whole. An instruction with multiple accesses commits none of its effects if any access fails.
- P0 requires natural alignment for multi-byte data accesses; an unaligned access fails with its address and width. Byte accesses can use any byte address. This deliberately excludes CPU-dependent unaligned-access behavior.
- Code is executable; stack and user memory are not executable. Injecting bytes at a branch target does not add instructions to the loaded program.
- Inspection is non-faulting: it reports byte availability and never changes state. A word containing unknown bytes is unknown, not a zero word.
- No memory dump import, peripheral callbacks, virtual-to-physical translation, or lazy firmware image reconstruction is required.

## 11. Architecture support

### Required P0 profile

`armv7-a-le`, with load mode `arm` or `thumb`, 32-bit addresses and general registers, user-mode CPSR, and little-endian code/data. Thumb includes both 16-bit and 32-bit (Thumb-2) instruction encodings. The tool does not claim all of ARMv7 or a particular board's behavior.

Execution capability is delegated to the selected Unicorn version, ARM/Thumb mode, and CPU model, within this product's explicit state and feature boundaries. ArmStride executes loadable machine bytes; it does not implement an ARM ISA or execute mnemonic strings. The separate source producer assembles mnemonics using an existing assembler before decode validation and loading. An ordinary integer instruction is not rejected merely because it is absent from the validation table below. Backend rejection produces an explicit failed Step with rollback.

### P0 validation instruction classes

These are release-verification targets, not an exhaustive instruction/operand/alias support matrix.

| Class | Representative P0 validation |
| --- | --- |
| Data processing | MOV, ADD, SUB, including register/immediate forms |
| Flags and conditions | CMP, TST and a conditionally skipped ARM instruction |
| Branch and call/return | B, BEQ, BNE, BL and a same-mode return; include equal-to-fall-through and external targets |
| Memory | LDR, STR, known/missing bytes and a PC-relative literal load |
| Stack | PUSH, POP and prologue/epilogue SP changes |
| Multiple memory accesses | LDM, STM with successful execution and late-access faults |
| Thumb 16-bit | Representative two-byte instructions and sequential PC changes |
| Thumb-2 32-bit | Representative four-byte instructions, such as MOVW, adjacent to 16-bit instructions |

All these classes require concrete golden cases. Aliases such as PUSH versus STM do not require a custom assembler or alias semantics table: bytes drive execution, while decoder metadata serves display and branch reporting.

Engine support does not add absent machine facilities to the product. Privileged/system execution, exceptions/interrupt handlers, SIMD/VFP/NEON state, coprocessor facilities, exclusive-access monitor state, Thumb IT blocks, and mixed-mode execution remain explicitly deferred. Known feature exclusions may be rejected by a small decoder-based guard; do not build an exhaustive ARM operand-validity checker. Undefined/unpredictable encodings have no promised result; detected decode/engine failures are reported, and they are never used as golden success cases. Normal integer operations outside the representative table may run when the configured engine accepts them, without a separate application allowlist.

A mode-changing BX/BLX or PC load is not supported in P0; same-mode transfers are supported. Thumb return targets may contain bit 0 as required by the ISA, but the displayed resulting PC is canonical/even. Explicit PC edits use canonical addresses only. An IT instruction is marked unsupported; because entry ITSTATE is zero, users must not treat a fragment cut from the middle of an omitted IT block as a faithful replay.

### P1 and deferred architecture scope

P1 candidates are Run with bounded execution and Stop, and basic address breakpoints. Thumb IT-state execution and mixed-mode/interworking support are later work requiring dedicated semantics and tests; they are not a hidden P0 dependency. Big-endian ARM, Cortex-M exception state, privileged/system execution, AArch64, RISC-V, and MIPS are deferred. The instruction model must preserve widths/modes without adding implementations for those architectures.

## 12. UI requirements

The local page shall resemble a compact debugger/code viewer: a dominant monospaced instruction pane with a gutter, adjacent registers, and memory/stack inspection below or beside it. A spreadsheet-style editable instruction table is not required.

- **Input/load:** source/import selector, text area, local text file selection, ARM/Thumb choice, Load, and assembly/parse diagnostics. Source requires a base/load address; import has format/encoding controls. Link diagnostics to source lines only when known. Preserve source separately from the generated execution listing. Optional scratch-stack fields can be grouped under setup. Loading a file only reads its text in the browser.
- **Code view:** address, byte representation, source mnemonic/operands, decoded instruction, current-PC gutter marker, current-line highlight, and automatic scrolling to current PC. Unsupported instructions have a distinct marker. Selecting a line can fill the PC input; it does not execute.
- **Registers:** R0–R12, SP, LR, PC, CPSR and N/Z/C/V; in-place value editing, range errors next to inputs, origin labels, and changed-register/flag highlighting. Full CPSR is visible with protected bits explained.
- **Memory:** address/range input, bytes and aligned little-endian words, `??` cells, source-region labels, byte/word patch input, explicit zero-fill action, and latest writes/changes.
- **Stack:** follows SP, shows words and an SP marker, and supports scrolling around SP. At the initial top-of-stack SP, display words below the top so the empty scratch stack is visible. Out-of-range cells remain `??`.
- **Controls:** Load, Step, Reset, and start/current PC with Go. Step and edits require a loaded program. Pending operations disable conflicting controls; no double Step from one click. No Run, Stop, or breakpoint gutter controls are shown in P0.
- **Feedback:** parse warnings/errors, condition and branch result, stopped PC, missing-memory details, the manual-edit/baseline rule, `step_seq`, and transport failure feedback. Do not automatically retry Step after a lost response. Highlighting must also use markers/text so meaning does not depend on color alone. Inputs and buttons are keyboard accessible.

## 13. P0, P1, and deferred scope

| Release boundary | Features |
| --- | --- |
| Mandatory P0 | ARM/Thumb source assembly with explicit origin; supported addressed text formats; atomic assembly/parse/load; ARM and Thumb/Thumb-2 execution within the selected profile; arbitrary loaded start PC; exactly-one-instruction Step; register and N/Z/C/V edits; CPSR display; strict partial memory and explicit patches/zero-fill; scratch stack and stack inspection; current-PC and change highlights; branch results; deterministic Reset; isolated ephemeral local sessions; actionable errors. |
| P1 | Bounded Run/Stop and basic address breakpoints, only after Step correctness is established. No commitment to a streaming transport is implied. |
| Deferred | Exact source-level debug mapping, assembly build-system features, mixed-mode images/interworking, IT blocks, further ARM families/profiles, persistent experiments, binary/dump/ELF loaders, other ISAs, advanced debugger/analysis/integration features listed in Section 4. |

### Operational bounds (explicit P0 assumptions)

The intended workload is tens to hundreds of instructions. To bound a local process, P0 accepts at most 1 MiB of input text, 10,000 instructions, 16 MiB of total logical code/stack/data memory per session, 64 MiB of backing pages per session (including padding for sparse ranges), a 64 KiB patch/zero-fill per request, and a 4 KiB inspection window per request. Excess input is rejected before mutation; memory-budget errors identify whether logical bytes or backing pages exceeded the limit. At most eight live sessions are retained; a ninth creation is rejected. Sessions expire after 30 minutes without a request and are destroyed when the server exits. Expired sessions produce an explicit message and a new-session action; state is not silently replaced. These limits are initial engineering defaults, not firmware address-space limits or performance claims. No background/cloud execution is required.

## 14. Repository and Project Structure Requirements

The production repository shall use a single canonical Python project rooted at the repository root.

ArmStride is a Python application with a local Web UI, not a separately packaged backend service. The production package name is `armstride`; Python 3.12+, uv dependency management, and pytest are required. Phase 6 exposes `uv run armstride` for the local API and static serving contract; the Phase 2 scope did not include that launcher or a Web server.

The production Python package shall use a standard `src` layout and live under:

```text
src/armstride/
```

Production Python tests shall live under:

```text
tests/
```

The production project shall use the root-level:

```text
pyproject.toml
uv.lock
```

as its canonical Python dependency and build configuration.

A separate production Python project under `backend/` shall not be created.

The Phase 1 assets originally placed in `backend/tests/` shall move to root `tests/` without changing their expectations, captured provenance, or independent verification semantics. Only relocation-required references may change. Remove the obsolete `backend/` directory when empty.

Experimental validation environments may remain isolated under `spikes/` with their own dependency manifests when reproducibility requires it.

In particular, preserve `spikes/phase0/pyproject.toml`, `uv.lock`, `probe.py`, and `observations.json` as isolated evidence. Its environment and dependency graph shall not be merged into the root production project. Production dependencies shall be added only when used by the active implementation phase.

The frontend may exist as a separate Node/Vite project under:

```text
frontend/
```

Documentation shall live under:

```text
docs/
```

The detailed repository layout, module boundaries, and directory responsibilities shall be defined in `ARCHITECTURE.md`.

The repository structure must distinguish clearly between:

* production source code
* production tests
* frontend code
* documentation
* experimental spikes
* generated artifacts

Generated files such as `__pycache__`, `.pyc`, virtual environments, test caches, frontend dependencies, and build outputs shall not be tracked as source artifacts.

Create only directories used by the current phase. Phase 2 includes domain records, ARM parsing metadata, parser adapters, logical memory, and their tests; production Unicorn execution, API/server code, and frontend implementation remain later phases.


## 15. Acceptance criteria

These criteria derive tests; the architecture adds mechanism-specific verification without expanding product scope.

| ID | Given / When / Then | Requirements |
| --- | --- | --- |
| AC-01 | Given equivalent fromelf, objdump, generic word, and generic byte listings, when loaded under the same profile, then addresses, memory-order bytes, widths, and execution results agree. File selection and paste behave identically. | FR-001–004 |
| AC-02 | Given an existing experiment and input with one malformed line among valid lines, when Load is requested, then the offending line and message are returned, valid lines may be previewed, and the existing experiment is unchanged. Empty input, duplicate addresses, overlaps, and wrong widths likewise reject atomically. | FR-002–004, FR-017 |
| AC-03 | Given unsorted valid ARM instructions, when loaded, then PC is the lowest address; when a different loaded start is selected and Step is pressed, exactly that instruction executes. Selecting an interior/gap/odd address rejects without changing PC. | FR-003, FR-005–006 |
| AC-04 | Given ARM sequential instructions and a Thumb snippet with consecutive 16-bit and 32-bit instructions, when stepping, then each request executes one instruction and the observed sequential advances are respectively four, two, and four bytes. PC-relative loads use architectural PC semantics. | FR-004, FR-006, FR-019 |
| AC-05 | Given CMP and a conditional B with known operands, when stepping both, then flags match the comparison and the branch reports its condition, correct taken/not-taken result, and correct PC. Repeat for both outcomes and a target equal to fall-through. | FR-009, FR-022 |
| AC-06 | Given only R1 is supplied, when inspecting state, then other default registers and the synthetic stack are identified as assumptions. Editing R13 changes SP and vice versa; invalid numbers or protected CPSR bits are rejected without mutation. | FR-007–009, FR-018 |
| AC-07 | Given a word load whose address has no bytes, when stepping, then a read error identifies its address/width and state is unchanged. Inject one byte and retry: it still fails. Inject all four and retry: the loaded value matches little-endian bytes; neighboring addresses remain unknown. | FR-010–011, FR-016, FR-018 |
| AC-08 | Given an unmapped store target, when stepping, then no memory is created. After explicit zero-fill, the same store succeeds. A code-overlapping patch or CPU code write fails without altering code. Inspection never allocates bytes. | FR-010–011, FR-016, FR-018 |
| AC-09 | Given known registers and SP at the scratch-stack top, when PUSH, a prologue SP adjustment, the inverse adjustment, and POP are stepped, then SP, word order, restored registers, and memory highlights match execution. A custom injected stack works the same way. | FR-008, FR-012, FR-014 |
| AC-10 | Given a multi-register transfer whose final access crosses into unknown memory, when Step fails, then earlier writes, register updates, flags, and SP changes from that instruction are all absent. An unaligned word access similarly fails atomically. | FR-016, FR-018 |
| AC-11 | Given initial register/memory/PC edits and executed changes, when the user adds missing memory, edits a register/flag or PC, and presses Reset, then every manual edit remains, unrelated CPU-generated changes disappear, PC equals the latest manually selected start, and highlights clear. Patching one byte shall not copy neighboring runtime stores into baseline; toggling one flag shall not copy other runtime flags. | FR-015, FR-023 |
| AC-12 | Given a same-mode branch or POP to an unloaded address, when Step succeeds, then its register/memory effects commit, PC shows the destination, and `pc_not_loaded` is displayed without a misleading code marker. Another Step executes nothing. | FR-006, FR-013, FR-016, FR-022 |
| AC-13 | Given a decoded instruction requiring a known excluded feature, when loaded, then it is marked and Step fails without changes. An engine-rejected instruction or mode-changing transfer also fails atomically with an explicit category. An ordinary integer instruction is not rejected solely because it is absent from the representative validation table. | FR-016–019 |
| AC-14 | Given a Step that changes R0, Z, and one stack word but rewrites another byte to its existing value, then only changed values highlight and both writes are listed. A subsequent manual edit or failed Step clears old execution highlights. | FR-012–014 |
| AC-15 | Given two browser sessions, when one loads/edits/steps/resets or is destroyed, then the other retains its state. After expiry, requests return an expired/missing-session error, not another session's state. | FR-020–021 |
| AC-16 | Given a loaded page, when controls are used with the keyboard and a Step request is pending, then the PC marker, register/flag results, memory view, and errors remain usable and no second conflicting operation is sent. Go never executes. | FR-005, FR-013, FR-021 |
| AC-17 | Given BL followed by a same-mode return and a conditional non-branch instruction, when stepped with both flag outcomes, then LR/PC follow the ISA, and a skipped instruction consumes one Step without its conditional effects. | FR-006, FR-019, FR-022 |
| AC-18 | Given a request exceeding a stated text, instruction, memory, inspection, or session bound, when submitted, then it is rejected with a limit diagnostic and existing state remains unchanged. | FR-002, FR-010–011, FR-020–021 |
| AC-19 | Given a session whose successful Step count is N, when another Step completes with the same PC/state (for example a self-branch), then `step_seq` becomes N+1. Failed Steps, edits, Reset, and reload leave it unchanged. A lost response never triggers an automatic Step retry. | FR-024 |
| AC-20 | Given PF-01–PF-08, when the appropriate mode/format is selected, then normalized bytes, sizes, original source lines and diagnostics match the fixture contract; recognized noise is visible as ignored lines and malformed instruction records are never silently discarded. | FR-001–004, FR-017 |
| AC-21 | Given equivalent ARM/Thumb source and fixed imported bytes, when assembled at the same origin, then normalized addresses/bytes/widths and Step results agree with independent golden expectations. Cover labels, PC-relative encoding, origin changes, adjacent Thumb widths, syntax/decode/profile failures and atomic preservation of an existing experiment. Preserve source without fabricating line mappings. | FR-001–004, FR-017, FR-019, Section 7.0 |

P0 is accepted only when these capabilities and representative ARM/Thumb golden cases pass. Passing them is not a claim of exhaustive ARM ISA conformance. Atomic execution remains a release requirement whose feasibility must first be demonstrated in Phase 0.
