# ArmStride Software Requirements Specification

Status: Product P0 and Product P1 baselines are fully verified and accepted as the stable foundation. This specification defines the completed P0/P1 baselines, formal Product P2 requirements and acceptance criteria, and deferred post-P2 / research scope. See ARCHITECTURE.md, milestones/P1.md, and milestones/P2.md for implementation roadmaps.

## 1. Authority and terminology

[concept.md](concept.md) is the primary source of product intent. [README.md](../README.md) is its public summary. This specification resolves their open behavioral questions; [ARCHITECTURE.md](ARCHITECTURE.md) describes how to satisfy it, and [milestones/P2.md](milestones/P2.md) defines the Product P2 milestone. ArmStride remains the working name.

**Shall** denotes an active product requirement. P0 and P1 requirements represent the completed and immutable baseline. P2 requirements are prefixed with `P2-` and define the current development milestone. Deferred items are post-P2 obligations. An **instruction address** is the address of its first byte. An **execution location** is the tuple `(address, mode)` where mode is `arm` or `thumb`. A **snippet** is an ordered set of addressed instructions, possibly with gaps. A **DataRegion** is an addressed sequence of concrete, readable, non-executable data bytes (such as a literal pool). **Known memory** means bytes supplied by the user, loaded as code/data, or explicitly initialized by the tool. **Unknown memory** means no byte value has been established; it does not mean a symbolic value. A **Step** attempts one architectural instruction, including a conditionally skipped instruction. A **Run** is a sequence of atomic Steps bounded by step and wall-clock limits or interrupted by a breakpoint, watchpoint, or user stop. A **Watchpoint** is a debugger capability identifying an address range and access type (`read`, `write`, `read_write`) that halts execution at a committed Step boundary when actual CPU execution accesses memory in that range. A **Step Back** is a debugger operation that restores Runtime State to the immediately preceding committed Step boundary within a bounded history window without modifying User Baseline State. **ProgramMetadata** encapsulates presentation and debug metadata (symbols, DWARF line mappings) decoupled from execution-truth machine instructions.

### 1.1 Product P0 baseline assumptions and decisions

These choices established the accepted P0 release:

| ID | Decision | Reason |
| --- | --- | --- |
| A-01 | P0 accepts ARM/Thumb assembly source with an explicit base address, or addressed disassembly/crash-log text with encoded bytes. Both produce the same ProgramImage. | Assemble source before loading; retain supplied import bytes. Execution is always byte-driven. |
| A-02 | ARMv7-A, little-endian, user-mode integer execution is the concrete CPU profile. ARM and Thumb, including 32-bit Thumb encodings, are required. Each load has one execution mode. | “ARMv7” alone does not specify a machine; this is a small CPU-level environment, not a Cortex-M board model. |
| A-03 | Unknown memory access stops execution. No demand-zero mapping occurs. A visible, zero-filled scratch stack is the one tool-created data region. | Missing evidence must not silently become a plausible zero value, while basic PUSH/POP must work immediately. |
| A-04 | Unspecified general registers and LR default to zero; flags default to zero. Defaults are labeled assumptions. | Concrete execution requires concrete values; symbolic state is excluded. |
| A-05 | User Baseline State starts with load defaults and receives every accepted manual register, flag, PC, and memory edit. Runtime State receives the same edits plus execution effects. Reset copies the baseline into runtime. | Evidence discovered during stepping must survive Reset; CPU-generated changes must not become initial evidence. |
| A-06 | Single-step execution is the initial release boundary. Run, breakpoints, mixed-mode images, and Thumb IT blocks were deferred to P1. | A bounded single-step integer workflow was the smallest useful initial release. |
| A-07 | Atomic Step remains the required product behavior: a failed attempt restores pre-Step runtime registers, flags, and memory. Its mechanism passed the Phase 0 Unicorn spike before core implementation. | Users can repair missing state and retry without hidden partial effects; engine rollback is not assumed. |
| A-08 | Sessions are local and ephemeral; browser refresh starts a new session. | Persistence and shared sessions are not product requirements. |

### 1.2 Completed Product P1 baseline assumptions and decisions

These choices formalized the completed and verified Product P1 milestone:

| ID | Decision | Reason |
| --- | --- | --- |
| P1-A-01 | Disassembly import accepts ARM mapping symbols `$a`, `$t`, `$d` as parser state transitions. ProgramImage supports mixed ARM and Thumb instructions alongside non-executable DataRegions. | Real disassembly listings (fromelf, objdump) transition between ARM, Thumb, and embedded literal data pools using mapping symbols. |
| P1-A-02 | Concrete data bytes represented by `$d` are loaded into known logical memory as non-executable data. They participate in range/overlap checks and are accessible to PC-relative literal loads (LDR), but reject direct execution. | Literal pools must be readable without user memory patching, while retaining strict memory and code execution boundaries. |
| P1-A-03 | Execution location is conceptually `(address, mode)` where mode is `arm` or `thumb`. Numeric PC alone does not determine whether an executable instruction is valid. | In mixed-mode execution, the CPU execution state (CPSR T bit) must match the instruction encoding at that address. |
| P1-A-04 | Runtime ARM/Thumb interworking is supported across all PC-writing instructions (BX, BLX, POP to PC, LDM to PC, etc.) via native CPSR T-bit resolution, committing exactly one architectural instruction atomically. | Eliminates the P0 `unsupported_mode_transition` error for valid architectural state switches while preserving all atomic rollback guarantees. |
| P1-A-05 | Thumb-2 IT blocks (IT, ITT, ITE, etc.) are supported for 1–4 controlled instructions, requiring a dedicated validation spike on the pinned Unicorn engine before production support is committed. | Step-by-step IT execution requires verifying native ITSTATE/CPSR persistence across single-step boundaries on the pinned engine. |
| P1-A-06 | Manual entry into the interior of an IT block without executing the preceding IT instruction is prohibited and yields an explicit validation error. | ArmStride executes verified architectural state and will not synthesize arbitrary unestablished ITSTATE. |
| P1-A-07 | Bounded Run is implemented strictly by composing existing atomic Steps, subject to configurable maximum step and wall-clock execution limits. Correctness and rollback fidelity take precedence over execution speed. | Prevents introducing an unverified high-speed emulation bypass that could compromise strict memory checking, rollback, and `step_seq` isolation. |
| P1-A-08 | Stop is concurrent and non-blocking via a thread-safe cancellation primitive evaluated between Steps. Breakpoints identify `(address, mode)` locations, halt pre-execution, and support a one-time resume bypass. | Guarantees machine state is always paused at a clean, complete Step boundary without deadlocking active Run requests. |

### 1.3 Product P2 assumptions and decisions

These choices formalize the Product P2 milestone (Debugger and Input Expansion):

| ID | Decision | Reason |
| --- | --- | --- |
| P2-A-01 | Direct linked ARM ELF loading serves as a third input producer alongside source assembly and disassembly import, compiling into the unified ProgramImage domain representation. | Enables loading compiled binaries without manually dumping disassembly text, preserving the single execution stack invariant. |
| P2-A-02 | P2 ELF support is strictly bounded to statically linked ELF32 little-endian ARM executables (`ET_EXEC`) with `PT_LOAD` segments. `ET_DYN` (PIE) is deferred to post-P2 until load-bias and relocation semantics are explicitly designed. Relocations (`ET_REL`), dynamic linking (`PT_INTERP`), and shared libraries are rejected. | Prevents turning ArmStride into an operating-system loader, linker, or dynamic relocation engine. |
| P2-A-03 | PT_LOAD defines memory placement and permissions. ARM mapping symbols (`$a`, `$t`, `$d`) partition executable segments into ARM code, Thumb code, and non-executable DataRegions (inline literal pools). Ambiguous executable regions without reliable mapping symbols fail closed. BSS expansions (`p_memsz > p_filesz`) become known zero bytes. Mapped padding between sparse segments remains unknown memory (`??`). | Reuses P1 mixed-mode ProgramImage semantics and avoids guessing code/data boundaries or CPU modes. |
| P2-A-04 | Independent resource bounds govern ELF loading: raw input bytes (10 MiB), total logical memory including BSS (16 MiB), backing pages (64 MiB), decoded instructions (10,000), and segment/section counts (32 segments, 128 sections). All executable segments within bounds are eagerly decoded. | Simple and deterministic; replaces speculative lazy disassembly while enforcing explicit multi-dimensional safety boundaries. |
| P2-A-05 | ELF symbols and DWARF line table entries are extracted into decoupled `ProgramMetadata`. Symbols and line numbers are presentation aids only and shall never override machine bytes or execution truth. | Keeps execution-domain records lightweight and prevents native ELF/DWARF library objects from leaking into SimulationSession, HTTP schemas, or StepResult. |
| P2-A-06 | DWARF address-to-line records provide `(file, line)` references. If source files are not provided to ArmStride, display metadata identifiers (e.g. `main.c:42`) without fabricating source text. Host filesystem browsing is excluded. | Avoids guessing source code or creating unrequested file-access requirements from browser sandbox environments. |
| P2-A-07 | Memory Watchpoints are defined as debugger triggers on address range + access type (`read`, `write`, `read_write`). Watchpoints are observable on both Step (via `watchpoint_hits` list) and Run (halts Run). Ordered multiple hits from multi-access instructions are preserved. | Keeps machine state paused at valid architectural Step boundaries; instructions are not rolled back merely because they hit a watchpoint. |
| P2-A-08 | Execution stop state is strictly separated from debugger observations: an instruction can simultaneously produce an architectural stop (`pc_not_loaded`) and committed Watchpoint hits without discarding either fact. Pre-execution Breakpoint prevents instruction execution; failed/rolled-back steps never trigger watchpoints; same-value writes trigger write watchpoints. | Eliminates ambiguous stop-reason overwrites and enforces deterministic debugger precedence. |
| P2-A-09 | Step Back restores Runtime State from a bounded history journal (capturing pre-step registers and lazily capturing pre-write memory bytes, keeping the first pre-value for multiple writes) without mutating User Baseline State. `step_seq` counts committed Steps only and is NEVER incremented or decremented on Step Back. Subsequent forward Steps advance from the monotonic maximum. A separate `state_revision` tracks state mutations. | Provides robust reverse-stepping without corrupting forward sequence counters or conflating step counts with state mutation revisions. |
| P2-A-10 | Cortex-M support is defined as an isolated feasibility research gate (`P2-R`), not a P2 release commitment. Behavioral MMIO simulation is decoupled from Watchpoints and deferred beyond P2. | Protects P2 delivery velocity from the deep architectural shifts of Cortex-M exception hardware and prevents premature peripheral emulation bloat. |

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

ArmStride is not a full-system emulator, OS kernel simulator, decompiler, GDB replacement, hardware debugger, or complete reverse-engineering suite. It does not model peripherals, behavioral MMIO side effects, interrupt controllers (NVIC), operating systems, timing, caches, MMUs, or exception dispatch hardware.

Symbolic registers, symbolic execution, constraint solving, automatic path exploration, branch-target solving, and angr integration are excluded. There is no cloud collaboration, multi-user service, authentication system, database, persistent project storage, or target-board/GDB remote protocol integration. CFG visualization, complex conditional breakpoint expressions, and branching reverse-execution trees are excluded.

In Product P2:
- Direct ELF loading is strictly bounded to already-linked ARM ELF32 executables; it is not a general object linker, dynamic loader, shared-library runtime, or firmware flasher.
- Symbol support is presentation metadata (`address -> name`); it is not a symbolic execution engine.
- DWARF support is bounded to address-to-source-line mapping; variable inspection, lexical scopes, type reconstruction, and CFI call-frame unwinding are excluded.
- Watchpoints are basic memory-range access triggers (`read`, `write`, `read_write`); conditional expressions and script callbacks are excluded.
- Step Back is bounded linear history restoration; branching time-travel trees and unlimited trace logging are excluded.
- Cortex-M exception handling, behavioral MMIO, VFP/NEON SIMD, and RISC-V remain explicitly deferred beyond Product P2.

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

### 6.1 Completed Product P0 baseline requirements

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
| FR-019 | Support the ARM and Thumb instruction scope in Section 11, including both two- and four-byte Thumb instructions. In P0 single-mode images, report attempted execution-mode changes as unsupported and restore the pre-Step state. |
| FR-020 | Each browser page instance shall have its own simulation state. Loading, editing, stepping, resetting, or closing one session shall not change another. |
| FR-021 | Run locally through a browser UI without an account or external service. P0 execution controls shall be Load, Step, Reset, and start/current PC input; disable conflicting controls while a request is pending. |
| FR-022 | Report control-flow effects per Step: condition when applicable, taken/not-taken for a branch, PC before/after, and destination. A non-branch shall not be labeled “branch not taken.” |
| FR-023 | Every accepted manual edit shall update only its explicitly addressed register, flag bits, PC, or memory bytes in both User Baseline State and Runtime State. Show that manual edits survive Reset. Never copy unrelated execution changes into the baseline. Rejected edits change neither state. |
| FR-024 | Expose a session-local `step_seq`, initially zero, increasing by one for each successfully committed Step, including conditional skips and stops at unloaded PC. Failed Steps, manual edits, Reset, and program replacement leave it unchanged. Use it to distinguish completed Steps with identical PC/state; do not promise exactly-once HTTP execution. |

### 6.2 Completed Product P1 baseline requirements

| ID | Product P1 requirement |
| --- | --- |
| P1-FR-001 | Accept ARM mapping symbols `$a` (or `$a.N`), `$t` (or `$t.N`), and `$d` (or `$d.N`) in disassembly listings as parser state transitions between ARM code, Thumb code, and non-executable data. Transition state shall determine opcode interpretation and record emission without requiring a single global mode per image. |
| P1-FR-002 | Model data regions represented by `$d` as non-executable `DataRegion` records in ProgramImage and as known logical memory in MemoryState. Data regions shall retain their exact concrete addresses and bytes, participate in overlap/range validation, be available to PC-relative literal loads (LDR), and reject direct CPU execution attempts. Data regions shall never be converted into fake instructions or silently zero-filled. |
| P1-FR-003 | Model executable location as the tuple `(address, mode)` where mode is `arm` or `thumb`. When validating whether an execution location is valid, the current CPU architectural mode (CPSR T bit) must match the mode of the instruction at that address. Reject execution attempts where address exists but mode mismatches. |
| P1-FR-004 | Support architectural runtime ARM/Thumb interworking on all PC-writing instructions capable of changing execution state, including BX, BLX, POP to PC, LDM to PC, returns, and ALU operations writing PC. Authoritative execution mode shall be read directly from post-execution CPSR T bit (bit 5) and canonicalized PC (bit 0 cleared). |
| P1-FR-005 | Preserve strict transactional rollback during interworking instructions. A successful interworking instruction shall commit exactly one architectural instruction. If an interworking instruction fails due to unmapped memory, permission fault, backend error, or execution location mismatch at the target, all register, flag, and memory state shall be restored to the pre-Step state. |
| P1-FR-006 | Support Thumb-2 IT blocks (IT, ITT, ITE, and all 1–4 instruction variants) across successive single-Step operations, gated by the successful completion of the P1 IT validation spike. Execution shall preserve architectural ITSTATE in CPSR across Step boundaries and advance through the block until all controlled instructions retire. |
| P1-FR-007 | Report IT block execution outcomes distinguishing an instruction that executed with condition passed (even if producing no numeric register/memory changes) from an instruction that was conditionally skipped. StepResult shall report `condition`, `condition_passed`, and IT execution metadata. |
| P1-FR-008 | Reject manual PC entry (via Go or PC edit) into the interior of an IT block when valid ITSTATE was not established by stepping the corresponding IT instruction. Manual ITSTATE injection is excluded in P1. |
| P1-FR-009 | Provide a bounded Run operation composed strictly of sequential atomic Steps. Run shall execute a loop that checks cancellation, breakpoints, and limits, performs one existing atomic Step, inspects the result, and halts when a boundary or failure is encountered. No bypass execution path that circumvents Step rollback or memory checks shall exist. |
| P1-FR-010 | Bound every Run by two independent limits: a maximum committed Step count (`step_limit`, default 10,000 steps) and a wall-clock execution duration (`time_limit`, default 2.0 seconds). Reaching either bound shall stop Run cleanly at the last committed Step boundary with the corresponding stop reason. |
| P1-FR-011 | Support concurrent, non-blocking Stop signaling while a Run operation is active. The session's primary mutation lock shall not block Stop delivery. Stop shall be signaled via a thread-safe primitive (`stop_event`); in-flight Steps shall complete or roll back atomically, after which Run shall halt before beginning the next Step with stop reason `user_stop`. |
| P1-FR-012 | Aggregate Run termination results reporting `start_step_seq`, `end_step_seq`, `steps_committed`, `stop_reason`, and final `State`. Monotonic `step_seq` shall increase by exactly one for every committed Step during Run. No cumulative step history storage is maintained. |
| P1-FR-013 | Manage breakpoints identified by `(address, mode)`. Validate breakpoint locations against loaded instruction starts; reject breakpoints on DATA records, code gaps, interior instruction bytes, unaligned addresses, or mode mismatches. |
| P1-FR-014 | Halt Run immediately before executing an instruction at an active breakpoint (pre-execution semantics) with stop reason `breakpoint`. The machine state displayed at a breakpoint shall represent state immediately prior to executing that instruction. Manual Step shall ignore breakpoints, allowing single-stepping through them. |
| P1-FR-015 | Implement a one-time resume bypass rule: when Run is initiated with PC currently paused at an active breakpoint, that specific breakpoint shall be bypassed for exactly one Step; normal breakpoint checking shall immediately resume for subsequent steps. Breakpoints shall remain enabled and shall not be deleted or globally suppressed. |
| P1-FR-016 | Preserve breakpoints across single-step execution, manual register/flag/memory edits, and session Reset. Clear all breakpoints on a successful replacement Load. New sessions shall start with an empty breakpoint set. |
| P1-FR-017 | Extend the browser workspace to support Run, Stop, breakpoint gutter toggling, Run stop reason badges, mixed ARM/Thumb/DATA listing rendering, and visual distinction between current PC markers, breakpoints, and combined PC+breakpoint locations. DATA rows shall not expose breakpoint interaction. |
| P1-FR-018 | Assembly source input workflow shall remain single-mode per snippet in P1 (matching P0). Mixed ARM/Thumb/Data images are supported via the disassembly/import workflow. Arbitrary assembler mode-switching directives remain deferred post-P1. |

### 6.3 Product P2 functional requirements

| ID | Product P2 requirement |
| --- | --- |
| P2-FR-001 | Accept statically linked ARM ELF32-LE executables (`ET_EXEC`) as a third `ProgramImage` producer alongside assembly source and disassembly import, without creating a parallel execution stack (`ElfSimulationSession`, `ElfExecutionBackend`, etc.). ELF-derived programs shall share the identical `ProgramImage`, `MachineState`, `MemoryState`, `Step`, `Run`, `Breakpoint`, rollback, `Reset`, and result contracts. |
| P2-FR-002 | Restrict initial ELF input validation to ELF32 little-endian (`ELFDATA2LSB`), machine architecture `EM_ARM` (code 40), and ELF type `ET_EXEC`. Reject 64-bit ELF (`ELFCLASS64`), big-endian ELF (`ELFDATA2MSB`), non-ARM machine types, `ET_DYN` (PIE, deferred post-P2), relocatable object files (`ET_REL`), core dumps (`ET_CORE`), or images requiring dynamic linking (`PT_INTERP` or unresolved dynamic relocations) atomically with an explicit diagnostic without modifying existing session state. |
| P2-FR-003 | Map loadable ELF segments (`PT_LOAD`) into explicit known logical memory. Executable segments (`PF_X`) shall be partitioned into ARM code, Thumb code, and non-executable `DataRegion`s (e.g. inline literal pools) using ARM mapping symbols (`$a`, `$t`, `$d`). `$d` ranges inside executable segments shall remain non-executable `DataRegion` records. Ambiguous mixed executable regions lacking reliable mapping symbols shall fail closed with actionable diagnostics. Non-executable readable/writable segments (`PF_R`, `PF_W` without `PF_X`) shall normalize into `DataRegion` records. |
| P2-FR-004 | Establish explicit zero-initialized memory for PT_LOAD segments where memory size exceeds file size (`p_memsz > p_filesz`). The trailing byte range `[p_vaddr + p_filesz, p_vaddr + p_memsz)` (e.g. `.bss`) shall become known zero bytes in `MemoryState` and be recorded as non-executable `DataRegion` entries. Unmapped gaps between segments and physical page padding shall remain unknown memory (`??`). |
| P2-FR-005 | Default session initial start PC to the ELF entry point (`e_entry`) if it addresses a valid instruction start in `ProgramImage`. Bit 0 selects Thumb entry (`e_entry & 1 == 1`) with canonicalized PC (`e_entry & ~1`); bit 0 clear selects ARM mode with PC `e_entry`. Entry address `0x00000000` is valid if loaded with an instruction. If `e_entry` does not address a loaded instruction start, default start PC to the lowest loaded instruction address. |
| P2-FR-006 | Enforce independent operational resource bounds on ELF input: maximum raw file size 10 MiB, maximum 16 MiB logical memory including BSS, maximum 64 MiB backing-page allocation, maximum 10,000 decoded instructions, and maximum 32 PT_LOAD segments and 128 sections. Binary inputs exceeding any limit shall reject atomically with an actionable diagnostic. All executable segments within bounds shall be eagerly decoded during load. |
| P2-FR-007 | Extract symbol metadata from `.symtab` / `.strtab` (or `.dynsym` / `.dynstr` if `.symtab` is absent), indexing mapping `address -> symbol name` for function (`STT_FUNC`), object (`STT_OBJECT`), and mapping symbols (`$a`, `$t`, `$d`). Store symbol records in decoupled `ProgramMetadata`. Symbols shall serve as display and navigation aids and shall never override machine bytes or become a second source of execution truth. |
| P2-FR-008 | Support stripped ELF files and files without symbol tables without degradation of execution capabilities. Stripped files shall load, step, run, and halt identically to unstripped equivalents. Symbols without executable code shall be preserved as display labels at their address. Duplicate or local symbols at identical addresses shall resolve deterministically without execution ambiguity. |
| P2-FR-009 | Extract DWARF `.debug_line` line tables when present, providing bidirectional mapping between instruction addresses and `(source_file, source_line)` pairs. DWARF metadata shall reside in `ProgramMetadata`. Malformed, unsupported, or absent DWARF sections shall be reported as warnings and shall not prevent ELF program installation or execution. |
| P2-FR-010 | Display source file and line metadata (e.g. `main.c:137`) for instruction lines when DWARF line mapping exists, without requiring the host source file contents or pretending the source text is present. Arbitrary host filesystem access from the browser shall not be required. |
| P2-FR-011 | Manage memory watchpoints identified by an address range `[start_address, end_address)` and access type (`read`, `write`, `read_write`). Validate that ranges are non-empty and reside within the 32-bit address space. Maximum 32 active watchpoints per session. |
| P2-FR-012 | Evaluate active watchpoints on both single Step and multi-step Run using actual committed CPU memory events (`memory_reads`, `memory_writes`). Ordered multiple hits from multi-access instructions shall be preserved. On single Step, report `watchpoint_hits` while remaining paused; on multi-step Run, halt execution immediately after committing that Step with stop reason `watchpoint`. The instruction's architectural effects remain committed (no rollback of successful execution). |
| P2-FR-013 | Strictly separate execution stop state from debugger observations: an instruction that successfully commits may simultaneously have `pc_not_loaded` (if resulting PC is unmapped) and committed `watchpoint_hits` without discarding either fact. Attempted memory accesses from an atomic Step that fails and rolls back shall never trigger a watchpoint hit. Pre-execution Breakpoint halts Run prior to instruction execution and prevents watchpoint evaluation. |
| P2-FR-014 | Trigger write watchpoints on any committed store access within the watched range, regardless of whether the written byte value equals the pre-existing byte value (`before == after`). Watchpoint triggers are driven strictly by CPU memory access events, not UI highlight deltas. |
| P2-FR-015 | Maintain watchpoint lifecycle: active watchpoints shall survive single Step, bounded Run, session Reset, and manual register/flag/memory/PC edits. All watchpoints shall be cleared upon a successful replacement Load. New sessions start with an empty watchpoint set. |
| P2-FR-016 | Provide a bounded Step Back operation that reverts Runtime State to the immediately preceding committed Step boundary within a retained execution history window (default 100 steps). Capture pre-step registers, CPSR (including N/Z/C/V, mode, and ITSTATE), and lazily capture pre-write memory bytes (retaining the first pre-value for multiple writes to the same byte) to restore exact previous machine state. |
| P2-FR-017 | Isolate User Baseline State from Step Back: Step Back shall mutate only Runtime State. User Baseline State, baseline start PC, and user-supplied edits shall remain completely unchanged. The restored Runtime State shall be a valid architectural state from which subsequent Step or Run can continue. |
| P2-FR-018 | Step Back sequence semantics: `step_seq` counts committed forward execution Steps only and shall NEVER be incremented or decremented on Step Back. Subsequent forward Steps continue from the session's monotonic maximum (`max_step_seq + 1`). A separate `state_revision` counter tracks all state mutations (Step, Step Back, manual edit, Reset, Load) for client synchronization. |
| P2-FR-019 | Maintain linear execution history: if a user steps back one or more steps and then executes a forward Step or Run, all discarded forward history states are purged (no branching history trees). |
| P2-FR-020 | Invalidate and clear all retained Step Back history upon any operation that mutates baseline or establishes a new execution origin: manual register edit, flag edit, PC edit, memory patch, zero-fill, session Reset, or program replacement Load. Breakpoint and watchpoint edits shall not clear history. |
| P2-FR-021 | Bound execution history retention by a configurable maximum step capacity (default 100 steps). When capacity is reached during forward execution, the oldest historical state entries shall be discarded in FIFO order. Step Back is permitted only within the retained history window. |
| P2-FR-022 | Extend the browser workspace to support ELF file upload and parsing diagnostics; symbol gutter badges, context labels, and Go-to-symbol navigation; DWARF `file:line` indicators; a Watchpoint management panel with address range, access type, and hit indicators; and a Step Back button with active history depth indication. |

### 6.3 Product P3 functional requirements (Planned Milestone — RISC-V Introduction: RV32I)

| ID | Description |
| --- | --- |
| P3-FR-001 | Execute little-endian RV32I integer instructions (`ADD`, `ADDI`, `SUB`, `AND`, `OR`, `XOR`, `SLL`, `SRL`, `SRA`, `SLT`, `SLTU`, `LUI`, `AUIPC`, `LB`, `LBU`, `LH`, `LHU`, `LW`, `SB`, `SH`, `SW`, `BEQ`, `BNE`, `BLT`, `BGE`, `BLTU`, `BGEU`, `JAL`, `JALR`, `FENCE`) under native engine execution with transactional single-step rollback on faults. |
| P3-FR-002 | Enforce strict architectural immutability of register `x0` (`zero`): `x0` shall permanently evaluate to `0`. Any user edit targeting `x0` or `zero` shall be rejected atomically with HTTP 422 `x0_immutable`. Instructions writing to `x0` shall execute normally without altering `x0` or reporting a delta. |
| P3-FR-003 | Model the RV32I register set as `x0`–`x31` and `pc`, supporting standard ABI aliases (`zero`, `ra`, `sp`, `gp`, `tp`, `t0`–`t6`, `s0`–`s11`, `a0`–`a7`) for user input, state editing, and UI presentation without storing aliases as independent registers. |
| P3-FR-004 | Separate architecture profile identity (`"armv7-a-le"`, `"rv32i-le"`) from dynamic execution mode (`arm`/`thumb` for ARM; fixed/None for RV32I). Shared domain contracts shall not require fake CPSR or N/Z/C/V flags for RISC-V sessions. |
| P3-FR-005 | Preserve `ProgramImage` as the single executable-image abstraction across all architectures. `ProgramImage.profile` shall identify the profile identity without creating an architecture-specific image subtype. |
| P3-FR-006 | Define an architecture-owned control-flow boundary producing normalized `BranchAnalysis` records (`is_control_flow`, `kind`, `taken`, `target`, `fallthrough`) without hard-coding multi-architecture conditionals in shared simulation code. |
| P3-FR-007 | Implement dedicated architecture execution backends (`ArmUnicornBackend`, `RiscvUnicornBackend`) sharing generic page mapping, memory access hooks, timeout enforcement, and transactional rollback helpers while isolating CPU model setup and register IDs. |
| P3-FR-008 | Ingest RV32I assembly source with local labels, numeric offsets, and ABI register aliases into authoritative machine bytes via a standalone, zero-dependency embedded RV32I assembler. |
| P3-FR-009 | Ingest addressed RV32 disassembly listings into `ProgramImage` with machine bytes authoritative, excluding ARM-specific mapping symbols (`$a`, `$t`, `$d`). |
| P3-FR-010 | Verify RV32I test encodings and golden fixtures against an independent external assembler oracle (`llvm-mc` or GNU binutils) with provenance recorded. |
| P3-FR-011 | Integrate RV32I execution with `MemoryState`, enforcing strict partial memory tracking (known vs unmapped `??` bytes), synthetic scratch stack, memory patches, zero-fill, and transactional rollback. |
| P3-FR-012 | Initialize a synthetic scratch stack for RV32I at `0x200F0000` (size 64 KiB), initializing `x2`/`sp` to stack top (`0x20100000`) without synthesizing OS or libc runtime state. |
| P3-FR-013 | Reuse debugger features (Bounded Run, concurrent Stop, pre-execution Breakpoints, Memory Watchpoints, Bounded Step Back, Reset, User Baseline State) seamlessly on RV32I sessions via shared session logic. |
| P3-FR-014 | Treat environment instructions `ECALL` and `EBREAK` as explicit debugger trap stops (`environment_call`, `breakpoint_trap`) with actionable stop reasons rather than crashing native execution. |
| P3-FR-015 | Dynamically adapt the browser UI from architecture profile metadata: render the 32 integer registers with ABI labels, hide ARM status bars (CPSR and flags) on RISC-V sessions, and provide RISC-V preset programs. |
| P3-FR-016 | Guarantee complete preservation of existing ARMv7-A / Thumb-2 capabilities with zero regressions across all automated test suites. |

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

### 7.5 Product P1 mixed-mode and data mapping syntax

P1 disassembly parsers implement an explicit state machine for mixed ARM/Thumb/Data listings:

- **State machine states:** `ARM_CODE`, `THUMB_CODE`, and `DATA`.
- **Initial state:** Determined by the load request mode or the first mapping symbol encountered in the listing.
- **`$a` / `$a.N` transition:** Switches the active parser state to `ARM_CODE`. Subsequent lines decode as ARM instructions (4-byte aligned, 4-byte width).
- **`$t` / `$t.N` transition:** Switches the active parser state to `THUMB_CODE`. Subsequent lines decode as Thumb instructions (2-byte aligned, 2-byte or 4-byte width).
- **`$d` / `$d.N` transition:** Switches the active parser state to `DATA`. Subsequent lines parse as concrete data byte records (e.g. `.word`, `.byte`, `DCD`, or raw hex byte sequences).

#### DataRegion semantics

Data lines are normalized into `DataRegion` instances rather than fake instructions:
- Each `DataRegion` retains its concrete address and bytes.
- Data regions appear in the normalized listing alongside instructions.
- Data regions are mapped to `MemoryState` as known, readable, non-executable logical memory (e.g. for literal pools).
- Data regions participate in address range and overlap validation.
- Direct CPU execution attempts or branch transfers to addresses within a DataRegion are rejected as invalid execution locations.
- Data regions shall not be silently zero-filled; absent bytes remain unknown.

#### Source assembly scope in P1

The assembly source input path (Keystone-based) remains strictly single-mode per snippet in P1 (matching P0). Assembler directives that create arbitrary mixed ARM/Thumb/Data source images are deferred post-P1. Mixed ARM/Thumb/Data images in P1 are produced via the disassembly/import pipeline.

### 7.6 Product P2 direct ARM ELF loading workflow

Product P2 introduces direct linked ARM ELF binary loading as a third `ProgramImage` producer. It accepts compiled ELF binaries without requiring users to manually run `objdump` or `fromelf` and paste text listings.

#### 7.6.1 Supported ELF subset and validation contract

The ELF loader is strictly bounded to already-linked executable images suitable for the existing ARMv7-A execution profile:

1. **Header validation:**
   - **Magic:** Must match standard ELF magic (`\x7fELF`).
   - **Class:** Must be `ELFCLASS32` (32-bit). `ELFCLASS64` is rejected with `unsupported_elf_class`.
   - **Data encoding:** Must be `ELFDATA2LSB` (little-endian). `ELFDATA2MSB` (big-endian) is rejected with `unsupported_elf_endianness`.
   - **Machine:** Must be `EM_ARM` (machine type 40). Non-ARM machines (e.g. x86, RISC-V, MIPS) are rejected with `unsupported_elf_machine`.
   - **Type:** Strictly `ET_EXEC` (executable). Position-independent executables (`ET_DYN` / PIE) are deferred to post-P2 until load-bias and relocation semantics are explicitly designed (absence of `PT_INTERP` does not prove `ET_DYN` needs no runtime relocation). Relocatable object files (`ET_REL`), core files (`ET_CORE`), and shared libraries are rejected with `unsupported_elf_type`.
   - **Dynamic linking:** Binaries containing `PT_INTERP` (dynamic interpreter request) or unresolved dynamic relocations are rejected with `unsupported_dynamic_elf`. ArmStride does not emulate an OS dynamic linker (`ld.so`) or load shared libraries.

2. **Segment extraction and logical memory population:**
   - `PT_LOAD` headers define memory placement and permissions. Headers such as `PT_NOTE`, `PT_DYNAMIC`, or `PT_GNU_STACK` are ignored for memory allocation.
   - Validates that segment virtual addresses and sizes do not wrap the 32-bit address space (`p_vaddr + p_memsz <= 0x100000000`).
   - **Executable segments (`PF_X`):** Raw file bytes are NOT blindly decoded entirely as instructions. Reusing the mixed ARM/Thumb/Data `ProgramImage` model from P1, ARM mapping symbols (`$a`, `$t`, `$d`) partition executable segments:
     - `$a` spans decode as ARM instructions (4-byte aligned).
     - `$t` spans decode as Thumb instructions (2-byte aligned, 2-byte or 4-byte width).
     - `$d` spans inside executable segments remain non-executable `DataRegion` records (e.g. inline literal pools, jump tables), loaded as known, readable, non-executable logical memory. Direct execution into `$d` ranges halts with `non_executable_target`.
     - **Fail-closed policy for ambiguous executable regions:** If an executable segment lacks mapping symbols, the loader requires an explicit uniform mode or verifies uniform decoding from entry point without ambiguity; if mixed or ambiguous without reliable mapping symbols, the loader fails closed and rejects with `ambiguous_elf_execution_mode`.
   - **Non-executable data segments (`PF_R`, `PF_W` without `PF_X`):** Raw file bytes are extracted into immutable `DataRegion` records in `ProgramImage` and loaded into `MemoryState` as known, readable (and writable if `PF_W`) logical data memory. Direct execution attempts halt with `non_executable_target`.
   - **Zero-initialized regions (`.bss`):** For segments where memory size exceeds file size (`p_memsz > p_filesz`), the delta range `[p_vaddr + p_filesz, p_vaddr + p_memsz)` is explicitly established as known zero bytes in `MemoryState` and recorded as non-executable `DataRegion` entries.
   - **Strict memory boundaries:** Gaps between segments and page padding remain strictly unknown memory (`??`). Unmapped accesses halt immediately.

3. **Entry point and initial PC:**
   - Default initial start PC is the ELF header entry point (`e_entry`), validated against loaded instruction starts in `ProgramImage`.
   - If `e_entry` has bit 0 set (Thumb entry indicator), visible PC is canonicalized (`e_entry & ~1`) and initial execution mode is set to `thumb`. If bit 0 is clear, initial mode is `arm` and visible PC is `e_entry`.
   - Entry address `0x00000000` is NOT assumed to be inherently invalid; it is valid whenever an executable instruction is loaded at that address.
   - If `e_entry` does not address any loaded instruction start, initial PC falls back to the lowest loaded instruction address.

4. **Independent resource bounds and eager decoding:**
   Independent limits are enforced to prevent unconstrained resource consumption:
   - Maximum raw ELF file size: 10 MiB (`MAX_ELF_FILE_BYTES = 10 * 1024 * 1024`).
   - Maximum logical memory including BSS: 16 MiB (`MAX_LOGICAL_MEMORY_BYTES = 16 * 1024 * 1024`).
   - Maximum backing-page allocation: 64 MiB (`MAX_BACKING_PAGES_BYTES = 64 * 1024 * 1024`, reusing `MemoryState`).
   - Maximum decoded instructions: 10,000 instructions (`MAX_INSTRUCTIONS`).
   - Maximum PT_LOAD segments: 32 (`MAX_ELF_SEGMENTS = 32`).
   - Maximum ELF sections: 128 (`MAX_ELF_SECTIONS = 128`).
   All executable `PT_LOAD` segments within these bounds are eagerly decoded upon load. Binaries exceeding any bound are rejected atomically with actionable diagnostics. Speculative lazy-disassembly infrastructure is deliberately excluded.

#### 7.6.2 Decoupled ProgramMetadata (Symbols & DWARF)

Debug information is extracted in parallel into a decoupled `ProgramMetadata` structure, preventing native ELF/DWARF library objects from polluting simulation core or execution backends:

- **Symbol metadata:** Extracted from `.symtab` / `.strtab` (or `.dynsym` / `.dynstr`). Function symbols (`STT_FUNC`), data object symbols (`STT_OBJECT`), and ARM mapping symbols (`$a`, `$t`, `$d`) are indexed by address. Symbols provide labels in the UI, PC context badges, branch target tooltips, and Go-to-symbol navigation. Symbols are display metadata and never override machine bytes. Stripped ELF files remain 100% executable without symbols.
- **DWARF line mapping:** Extracted from `.debug_line`. Maps instruction addresses to `(source_file, source_line)`. If the original source files are not provided to ArmStride, the UI displays `file:line` identifiers (e.g. `main.c:137`) without fabricating source text. Missing or malformed DWARF tables produce warnings and do not block execution.

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

### 8.5 Product P1 execution semantics

#### 8.5.1 Runtime ARM/Thumb interworking

In Product P1, runtime mode switching between ARM and Thumb is an architectural feature rather than an error:

1. **Native execution:** The CPU backend executes the instruction natively. Any PC-writing instruction (such as `BX`, `BLX`, `POP {..., pc}`, `LDM ..., {..., pc}`, `LDR pc, [sp]`, etc.) updates architectural PC and CPSR.
2. **State extraction:** Post-execution PC and CPSR are read from the backend. The resulting execution mode is determined directly from the architectural CPSR T bit (bit 5, `0x20`): `thumb` if set, `arm` if clear. The visible PC is canonicalized by clearing bit 0.
3. **Execution location resolution:** The tuple `(resulting_pc, resulting_mode)` is resolved against `ProgramImage`:
   - If an instruction exists at `resulting_pc` and its `mode == resulting_mode`, execution is ready for the next Step.
   - If no instruction exists at `resulting_pc` (e.g. branch to an unloaded target or external address), the instruction completes successfully, its effects commit to Runtime State, `step_seq` increments by 1, and the session pauses with stop reason `pc_not_loaded`.
   - If an instruction exists at `resulting_pc` but its mode does not match `resulting_mode` (mode mismatch), execution halts with an explicit mode mismatch diagnostic.
   - If `resulting_pc` points inside a `DataRegion`, execution halts immediately as data is non-executable.
4. **Rollback preservation:** If an interworking instruction fails during execution (due to memory fault, alignment fault, or backend error), atomic rollback restores pre-Step registers, CPSR (including original T bit), and memory completely. Exactly one architectural instruction is committed per successful Step.

#### 8.5.2 Thumb-2 IT block stepping and skip reporting

In Product P1, Thumb-2 IT blocks (IT, ITT, ITE, and all 1–4 instruction variants) are supported across successive single-Step operations, gated by the P1 IT validation spike:

1. **IT instruction execution:** Stepping the `IT <cond>` instruction itself commits the initial `ITSTATE` field into CPSR (`CPSR[15:10, 26:25]`), updates PC to the first controlled instruction, and increments `step_seq`.
2. **Controlled instruction execution:** Each subsequent Step attempts exactly one IT-controlled instruction using the current architectural CPSR (carrying active ITSTATE):
   - **Condition passed:** The instruction executes its architectural effects, updates registers/memory, advances ITSTATE to the next instruction in the block, advances PC by instruction width, and reports `condition_passed: true` with `executed: true`.
   - **Condition failed (skipped):** The instruction does not apply its conditional register/memory effects. The engine advances ITSTATE to the next instruction in the block, advances PC past the instruction, and reports `condition_passed: false` with `executed: false`.
   - **Distinguishing skipped from no-op:** An instruction that executed with condition passed but produced no numeric changes (e.g. `MOV r0, r0` or `AND r1, r1, #0` when R1 was 0) shall report `condition_passed: true` and `executed: true`, distinguishing it from a conditionally skipped instruction (`condition_passed: false`, `executed: false`).
3. **Manual entry restriction:** Setting PC manually into the interior of an IT block when valid ITSTATE was not established by stepping the IT instruction is rejected as `invalid_it_block_entry`. Manual ITSTATE injection is not supported in P1.
4. **Breakpoints inside IT blocks:** A breakpoint may be placed on an IT-controlled instruction. Stopping at the breakpoint halts immediately before that instruction executes and preserves current ITSTATE in CPSR, allowing subsequent Step or Run continuation without losing IT block context.

#### 8.5.3 Bounded Run loop and execution limits

Product P1 provides bounded multi-step execution (Run) implemented strictly by composing existing atomic Steps:

```text
while running:
    if stop_requested:
        stop with user_stop
        break
    if at_breakpoint and not resume_bypass:
        stop with breakpoint
        break
    if steps_committed >= max_steps:
        stop with step_limit
        break
    if wall_clock_elapsed >= max_time:
        stop with time_limit
        break

    clear resume_bypass
    result = perform_one_atomic_step()

    if result.status == "failed" or result.stop_reason is not null:
        stop with (result.stop_reason or "execution_failure")
        break
```

1. **No emulation bypass:** Run shall never bypass logical memory validation, rollback journals, interworking checks, `step_seq` increments, or UserBaseline isolation. Correctness and rollback fidelity take precedence over throughput.
2. **Independent bounds:** Every Run is bounded by both:
   - `step_limit`: maximum committed Step count (default 10,000 steps).
   - `time_limit`: wall-clock execution duration (default 2.0 seconds).
3. **Clean stopping:** Reaching any limit stops Run cleanly at a committed Step boundary. Session state represents the exact state after the last committed Step.
4. **Monotonic sequence accounting:** `step_seq` increments by 1 for each successfully committed architectural Step during Run. Run returns `start_step_seq`, `end_step_seq`, `steps_committed`, `stop_reason`, and final `State`.

#### 8.5.4 Concurrent Stop semantics

1. **Non-blocking Stop:** A `Stop` request may be submitted concurrently while a `Run` request is actively executing.
2. **Locking architecture:** The session registry and `SessionEntry` shall decouple Stop signaling from the session's primary mutation lock. Stop is signaled via a thread-safe primitive (`stop_event`) without waiting for the Run loop to terminate.
3. **Step boundary invariant:** Stop never aborts native CPU execution midway through an instruction. The in-flight atomic Step completes or rolls back cleanly. The Run loop observes `stop_event` between Steps, exits cleanly, and returns with `stop_reason: user_stop`.

#### 8.5.5 Breakpoint identity, pre-execution halting, and resume bypass

1. **Identity:** A breakpoint is identified by the tuple `(address, mode)` where mode is `arm` or `thumb`.
2. **Validation:** Setting a breakpoint validates that `(address, mode)` matches an existing instruction start in `ProgramImage`. Breakpoints on DATA records, code gaps, interior instruction bytes, or mismatched modes are rejected.
3. **Pre-execution stop:** During Run, if current executable location matches an enabled breakpoint, Run halts immediately before attempting that instruction. Machine state reflects the pre-execution state.
4. **Single-step bypass:** Manual single Step ignores breakpoints, allowing users to step through a breakpointed instruction.
5. **One-time resume bypass:** When Run is initiated while PC is currently paused at an active breakpoint, that specific breakpoint is bypassed for exactly one Step. Normal breakpoint checking immediately resumes for subsequent steps. Breakpoints are never automatically deleted or globally disabled.
6. **Lifecycle:** Breakpoints survive single Step, manual edits, and Reset. Breakpoints are cleared upon a successful replacement Load. New sessions start with an empty breakpoint set. Breakpoints are ephemeral and held in session memory.

### 8.6 Product P2 execution and debugger semantics

#### 8.6.1 Memory Watchpoint committed-boundary semantics

Product P2 introduces memory Watchpoints as a non-intrusive debugging capability for observing memory reads and writes:

1. **Identity and configuration:**
   - A Watchpoint is identified by an address range `[start_address, end_address)` and access type: `read`, `write`, or `read_write`.
   - Start address and length are validated within the 32-bit address space. Maximum 32 active watchpoints per session.
2. **Post-instruction committed-boundary evaluation & dual observability:**
   - Watchpoints discover accesses through actual CPU memory bus operations performed during an atomic Step.
   - Evaluation sequence:
     1. One atomic Step executes and completes successfully.
     2. All architectural effects (registers, CPSR, PC, and memory writes) commit to Runtime State, and `step_seq` increments by 1.
     3. The successfully committed `memory_reads` and `memory_writes` are evaluated against active watchpoints. Ordered multiple hits from multi-access instructions (e.g. `STM`, `PUSH`, `LDRD`) are preserved.
     4. Dual observability on Step and Run:
        - During single Step: The instruction completes normally, and `StepResult` reports all committed hits in `watchpoint_hits: list[WatchpointHitView]` while remaining paused.
        - During bounded Run: Run terminates immediately after that Step with `RunResult.stop_reason = "watchpoint"` and populates `RunResult.watchpoint_hit`.
   - **No step rollback:** A successfully executed instruction is never rolled back merely because it triggered a watchpoint. Machine state remains at a valid, consistent architectural Step boundary.
3. **Isolation from failed Steps:**
   - Attempted memory accesses from an atomic Step that fails and rolls back (e.g. `unmapped_memory_access`, `unaligned_memory_access`) shall never trigger a watchpoint hit.
   - Run halts with the underlying execution fault (e.g. `memory_fault`), leaving all machine state restored to the pre-Step state.
4. **Same-value writes:**
   - A write watchpoint shall trigger on any executed memory store access within the watched range, even when the newly written byte value is identical to the existing byte value (`before == after`). Watchpoint triggers reflect CPU memory operations, not UI highlight deltas.
5. **Strict separation of execution stop state and debugger observations:**
   - A Step may simultaneously produce a normal architectural stop such as `pc_not_loaded` (when the resulting PC is outside loaded code) and one or more committed Watchpoint hits. Neither fact shall be discarded.
   - `StepResult` captures both facts: `stop_reason: "pc_not_loaded"` and `watchpoint_hits: [...]`.
   - Run loop evaluates stopping conditions in deterministic order of precedence:
     1. *Pre-execution Breakpoint:* halts Run before instruction executes (`stop_reason: "breakpoint"`). Prevents that instruction from generating memory access or watchpoint events.
     2. *Execution Fault:* instruction execution fails and rolls back (`stop_reason: <fault_reason>`), leaving `watchpoint_hits` empty.
     3. *Post-execution Watchpoint Hit:* if committed memory accesses hit active watchpoints, Run halts with `stop_reason: "watchpoint"`. If `pc_not_loaded` also occurred, `last_step_result.stop_reason = "pc_not_loaded"` is preserved.
     4. *Post-execution Architectural Stop (`pc_not_loaded`):* if no watchpoints hit but resulting PC is not loaded, Run halts with `stop_reason: "pc_not_loaded"`.
     5. *User Stop:* concurrent stop event halts Run (`stop_reason: "user_stop"`).
     6. *Run Bounds:* `step_limit` or `time_limit` reached.
6. **Lifecycle:**
   - Watchpoints survive single Step, bounded Run, session Reset, and manual register/flag/PC/memory edits.
   - All watchpoints are cleared upon a successful replacement Load. New sessions start with an empty watchpoint set.

#### 8.6.2 Bounded execution history and Step Back semantics

Product P2 introduces a bounded **Step Back** capability to reverse execution without requiring full-program replay:

1. **Exact state restoration and lazy memory capture:**
   - Step Back restores Runtime State to the immediately preceding committed Step boundary within a retained execution history window (default 100 steps).
   - History entries capture register state (R0–R12, SP, LR, PC), CPSR (flags N/Z/C/V, mode, ITSTATE), and lazily captured original memory bytes.
   - **Lazy original byte capture:** Pre-step memory bytes are recorded lazily from committed write events / write hooks. For multiple writes to the same memory byte during a single instruction, the history entry retains the pre-Step original byte once (first pre-value observed) for exact reverse restoration.
   - The restored state is an authentic, valid architectural state from which subsequent forward `step()` or `run()` can continue.
2. **User Baseline State isolation:**
   - Step Back mutates **only** Runtime State.
   - User Baseline State, restart PC, and user-supplied edits remain completely untouched.
   - Reset continues to restore Runtime State from User Baseline State, discarding execution history.
3. **Step sequence and revision semantics:**
   - Session `step_seq` strictly counts committed forward architectural Steps. Step Back shall **NEVER increment or decrement `step_seq`**.
   - After stepping backward, a newly committed forward Step continues from the session's monotonic maximum (`max_step_seq + 1`), not the historical restored sequence number.
   - A separate `state_revision` integer counter increments on every state mutation (committed Step, Step Back, manual register/flag/PC edit, memory patch, Reset, Load) to provide unambiguous client-side cache and synchronization tracking without overloading `step_seq`.
4. **Linear history and forward invalidation (branching):**
   - Execution history is strictly linear (no branching time-travel trees).
   - When a user steps back $N$ steps (e.g. $A \to B \to C \to D$, stepped back to $B$) and executes a new forward Step or Run ($B \to E$), all discarded forward history states ($C \to D$) are permanently purged.
5. **History invalidation policy:**
   - Any operation that establishes a new experiment state or mutates the baseline invalidates and purges all retained execution history:
     - Manual register edit
     - Manual flag / CPSR edit
     - Manual PC edit (Go)
     - Memory patch or zero-fill
     - Session Reset
     - Program replacement Load
   - Breakpoint and watchpoint additions, deletions, or toggles do not mutate CPU or memory state and therefore do not clear execution history.
6. **Bounded retention bounds:**
   - Execution history is retained in a FIFO bounded journal or ring buffer capped at a configurable maximum step capacity (default 100 steps).
   - When forward execution exceeds the capacity, the oldest reversible historical states are discarded. Step Back operates strictly within the retained window.

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

### Completed Product P1 architecture additions

Product P1 formalized and verified the following execution capabilities:

1. **Runtime ARM/Thumb interworking:** Enabled for all PC-writing instructions (BX, BLX, POP to PC, LDM to PC, etc.) via native CPSR T-bit resolution, committing exactly one architectural instruction atomically.
2. **Thumb-2 IT block execution:** Multi-step IT block support (IT, ITT, ITE, etc.) preserving ITSTATE in CPSR across Steps, verified via the P1 IT validation spike.
3. **Bounded Run and concurrent Stop:** Composed of sequential atomic Steps bounded by configurable step and time limits.
4. **Address/mode breakpoints:** Pre-execution halting at `(address, mode)` with single-step bypass and one-time resume bypass.
5. **Mixed ARM/Thumb/Data listings:** Disassembly import driven by `$a`, `$t`, and `$d` mapping symbols.

### Product P2 architecture additions

Product P2 formalizes the following debugger and input capabilities:

1. **Direct linked ARM ELF loading:** ELF32 little-endian (`ET_EXEC`) container parsing as a third `ProgramImage` producer. PT_LOAD executable segments partitioned into ARM code, Thumb code, and non-executable `DataRegion`s via ARM mapping symbols (`$a`, `$t`, `$d`); non-executable data segments map to `DataRegion` and known memory; trailing BSS spans expand to explicit known zero bytes; initial PC and mode initialize from `e_entry` (including valid address 0); fail-closed on ambiguous segments lacking mapping symbols.
2. **Decoupled ProgramMetadata (Symbols & DWARF):** ELF symbol table extraction (`address -> symbol name`) and DWARF `.debug_line` line table mapping (`address -> file:line`). Clean separation of presentation metadata from execution-truth machine instructions.
3. **Memory Watchpoints:** Range-based memory access monitoring (`read`, `write`, `read_write`) evaluated at post-instruction committed Step boundaries on actual CPU memory bus events. Observable on both Step (`watchpoint_hits` list) and Run (`stop_reason: watchpoint`). Preserves ordered multiple hits from multi-access instructions; triggers write watchpoints on same-value stores (`before == after`); strictly separates execution stop state (`pc_not_loaded`, faults) from debugger observations.
4. **Bounded Step Back & Execution History:** Reversible execution restoring exact previous Runtime State (registers, CPSR, PC, lazily captured original memory bytes) within a bounded linear journal (default 100 steps) without modifying User Baseline State. `step_seq` counts committed forward Steps only and is NEVER incremented or decremented on Step Back; subsequent forward Steps continue from monotonic maximum (`max_step_seq + 1`). Separate `state_revision` tracks state mutations. Discards forward history on branching; clears history on manual mutations, Reset, or reload.
5. **Cortex-M Feasibility Research Gate (P2-R):** Dedicated non-blocking experimental spike investigating Unicorn Cortex-M CPU models, Thumb stepping, MSP/PSP, exception stacking, EXC_RETURN, and HardFault behavior to inform a future product milestone.

### Deferred architecture scope (post-P2)

The following capabilities are explicitly deferred beyond Product P2:
- Position-independent executables (`ET_DYN` / PIE) and dynamic load-bias/relocation resolution.
- Production Cortex-M execution and exception model (gated by P2-R feasibility spike outcome).
- Behavioral MMIO and peripheral simulation (evaluated in distinct post-P2 layers from named metadata to behavioral devices).
- VFP / NEON floating-point and SIMD vector register state.
- RISC-V source/disassembly/execution profile.
- Arbitrary branching reverse-execution trees or non-linear time-travel debugging.
- Full DWARF variable debugging, lexical scopes, type reconstruction, expression evaluation, or CFI stack unwinding.
- General object-file linking (`ET_REL`), dynamic loading (`PT_INTERP`), or shared-library runtime.

## 12. UI requirements

The local page shall resemble a compact debugger/code viewer: a dominant monospaced instruction pane with a gutter, adjacent registers, and memory/stack inspection below or beside it. A spreadsheet-style editable instruction table is not required.

- **Input/load:** source/import selector, text area, local text file selection, ARM/Thumb choice, Load, and assembly/parse diagnostics. Source requires a base/load address; import has format/encoding controls. Link diagnostics to source lines only when known. Preserve source separately from the generated execution listing. Optional scratch-stack fields can be grouped under setup. Loading a file only reads its text in the browser.
  - *P2 extension:* Support direct ELF binary upload via file picker or drag-and-drop. Display ELF container metadata (entry point, loadable segments, symbol count, DWARF availability).
- **Code view:** address, byte representation, source mnemonic/operands, decoded instruction, current-PC gutter marker, current-line highlight, and automatic scrolling to current PC. Unsupported instructions have a distinct marker. Selecting a line can fill the PC input; it does not execute.
  - *P1 extension:* Mixed-mode listing displaying ARM code, Thumb code, and non-executable DATA records in address order with clear tags. Breakpoint gutter allows toggling breakpoints on instruction lines; DATA rows reject breakpoint clicks. Visually distinguish current-PC marker, breakpoint marker, and combined PC+breakpoint marker.
  - *P2 extension:* Display symbol labels at function and label addresses; show current symbol context badge; provide Go-to-symbol navigation. Display DWARF `file:line` metadata (e.g. `main.c:137`) alongside decoded instructions without requiring host source contents. Display active watchpoint gutter markers or highlights when memory accesses touch visible data rows.
- **Registers:** R0–R12, SP, LR, PC, CPSR and N/Z/C/V; in-place value editing, range errors next to inputs, origin labels, and changed-register/flag highlighting. Full CPSR is visible with protected bits explained.
- **Memory:** address/range input, bytes and aligned little-endian words, `??` cells, source-region labels, byte/word patch input, explicit zero-fill action, and latest writes/changes.
  - *P2 extension:* Watchpoints panel: list active watchpoints with address range, access type (`read`, `write`, `read_write`), and hit counts; add/remove watchpoints directly from memory view or address input.
- **Stack:** follows SP, shows words and an SP marker, and supports scrolling around SP. At the initial top-of-stack SP, display words below the top so the empty scratch stack is visible. Out-of-range cells remain `??`.
- **Controls:** Load, Step, Reset, and start/current PC with Go. Step and edits require a loaded program. Pending operations disable conflicting controls; no double Step from one click.
  - *P1 extension:* Add Run and Stop controls to the toolbar. Run initiates bounded execution; Stop halts an active Run at the next Step boundary. Disable conflicting inputs while Run is active; ensure Stop remains enabled and clickable during Run.
  - *P2 extension:* Add **Step Back** button to toolbar with history depth counter (e.g. `Step Back (12)`). Disabled when history is empty or invalidated.
- **Feedback:** parse warnings/errors, condition and branch result, stopped PC, missing-memory details, the manual-edit/baseline rule, `step_seq`, and transport failure feedback. Do not automatically retry Step after a lost response. Highlighting must also use markers/text so meaning does not depend on color alone. Inputs and buttons are keyboard accessible.
  - *P1 extension:* StatusPanel displays Run stop reasons (`breakpoint`, `user_stop`, `step_limit`, `time_limit`, `pc_not_loaded`, etc.) and IT block execution/skip feedback.
  - *P2 extension:* StatusPanel displays `watchpoint` stop reason with triggering address, access type, and byte values.
  - *P2 extension:* State and response headers include `state_revision` for reliable mutation tracking.

## 13. P0, P1, P2, P3, and deferred scope

| Release boundary | Features |
| --- | --- |
| Mandatory P0 (Completed Baseline) | ARM/Thumb source assembly with explicit origin; supported addressed text formats; atomic assembly/parse/load; ARM and Thumb/Thumb-2 execution within the selected profile; arbitrary loaded start PC; exactly-one-instruction Step; register and N/Z/C/V edits; CPSR display; strict partial memory and explicit patches/zero-fill; scratch stack and stack inspection; current-PC and change highlights; branch results; deterministic Reset; isolated ephemeral local sessions; actionable errors. |
| Product P1 (Completed Baseline) | 1. Mixed ARM / Thumb / Data disassembly ProgramImages (`$a`, `$t`, `$d`).<br/>2. Non-executable DataRegions in ProgramImage and logical memory.<br/>3. Runtime ARM/Thumb interworking on all PC-writing instructions.<br/>4. Thumb-2 IT blocks (IT, ITT, ITE) with CPSR ITSTATE preservation and skip reporting.<br/>5. Bounded Run (composed of atomic Steps) bounded by step limit and wall-clock time limit.<br/>6. Concurrent, non-blocking Stop signaling.<br/>7. Address/mode breakpoints `(address, mode)` with pre-execution halting and one-time resume bypass.<br/>8. Browser UI integration for mixed listings, Run/Stop controls, and breakpoint gutter. |
| Product P2 (Completed Baseline — Debugger and Input Expansion) | 1. Direct ARM ELF32-LE binary loading (`ET_EXEC`) as third ProgramImage producer.<br/>2. PT_LOAD segment extraction, mapping symbol partitioning (`$a`, `$t`, `$d`), non-executable data regions, BSS zero-expansion, and `e_entry` initialization.<br/>3. Decoupled symbol metadata (`SymbolTable`) for labels, branch context, and Go-to-symbol navigation.<br/>4. Decoupled DWARF line mapping (`LineTable`) for address-to-file:line display without source fabrication.<br/>5. Memory Watchpoints (`read`, `write`, `read_write`) observable on Step and Run with ordered multi-hits.<br/>6. Bounded Step Back restoring exact Runtime State within a 100-step linear journal, capturing lazy memory changes.<br/>7. Monotonic `step_seq` invariance (neither incremented nor decremented on Step Back) and separate `state_revision`.<br/>8. Browser UI integration for ELF upload, symbols, watchpoint panel, and Step Back control.<br/>9. Non-blocking Cortex-M feasibility research spike (`P2-R`). |
| Product P3 (Planned Milestone — RISC-V Introduction: RV32I) | 1. Native RV32I little-endian integer execution on Unicorn 2.1.4.<br/>2. RV32I assembly source and addressed disassembly/import input producers.<br/>3. Architectural immutability of register `x0` (`zero`), rejecting user edits and suppressing execution deltas.<br/>4. Multi-ISA domain contracts decoupling profile identity (`"armv7-a-le"`, `"rv32i-le"`) from dynamic execution mode.<br/>5. Architecture-owned control-flow interpreter (`RiscvControlFlowInterpreter`).<br/>6. Dedicated RISC-V execution backend (`RiscvUnicornBackend`).<br/>7. Full reuse of debugger features: Run / Stop, Breakpoints, Watchpoints, Bounded Step Back, Reset.<br/>8. Synthetic scratch stack at `0x200F0000` with `x2`/`sp` initialization.<br/>9. Profile-driven UI dynamically rendering RV32I registers and hiding ARM-specific CPSR/flags.<br/>10. Full ARM regression preservation. |
| Post-P3 RISC-V Extensions | P3.1: RV32M (Integer Multiply/Divide); P3.2: RV32C (Compressed 16-bit instructions with mixed-width alignment); P3.3: RV64I (64-bit base integer with XLEN=64 expansion); P3.4: Direct RISC-V ELF32 loading. |
| Deferred (Research / Future Scope) | Position-independent executables (`ET_DYN` / PIE), production Cortex-M execution, behavioral MMIO / peripheral simulation, VFP/NEON SIMD, RV32A atomics, RV32F/D floating-point, Vector, Bitmanip, privileged architecture / MMU / CSRs, OS/SBI emulation, branching reverse-execution trees, full DWARF variable debugging / CFI stack unwinding, relocatable object-file linking, dynamic loading. |

### Operational bounds (explicit P0/P1/P2 assumptions)

The intended workload is tens to hundreds of instructions. To bound a local process:
- Maximum input text: 1 MiB.
- Maximum raw ELF binary file: 10 MiB (`MAX_ELF_FILE_BYTES`).
- Maximum logical loaded memory including BSS: 16 MiB per session (`MAX_LOGICAL_MEMORY_BYTES`).
- Maximum backing pages: 64 MiB per session (`MAX_BACKING_PAGES_BYTES`, including padding for sparse ranges).
- Maximum decoded instructions: 10,000 instructions per ProgramImage (`MAX_INSTRUCTIONS`).
- Maximum PT_LOAD segments: 32 per ELF (`MAX_ELF_SEGMENTS`).
- Maximum ELF sections: 128 per ELF (`MAX_ELF_SECTIONS`).
- Maximum memory patch / zero-fill: 64 KiB per request.
- Maximum memory inspection window: 4 KiB per request.
- Maximum live sessions: 8 concurrent sessions; 30-minute idle TTL.
- Maximum active watchpoints: 32 per session.
- Maximum retained execution history: 100 steps per session.
Excess input is rejected before mutation; memory-budget errors identify whether logical bytes or backing pages exceeded the limit. No background/cloud execution is required.

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

### 15.1 Completed Product P0 baseline acceptance criteria

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
| AC-13 | Given a decoded instruction requiring a known excluded feature, when loaded, then it is marked and Step fails without changes. An engine-rejected instruction or mode-changing transfer in P0 single-mode images also fails atomically with an explicit category. An ordinary integer instruction is not rejected solely because it is absent from the representative validation table. | FR-016–019 |
| AC-14 | Given a Step that changes R0, Z, and one stack word but rewrites another byte to its existing value, then only changed values highlight and both writes are listed. A subsequent manual edit or failed Step clears old execution highlights. | FR-012–014 |
| AC-15 | Given two browser sessions, when one loads/edits/steps/resets or is destroyed, then the other retains its state. After expiry, requests return an expired/missing-session error, not another session's state. | FR-020–021 |
| AC-16 | Given a loaded page, when controls are used with the keyboard and a Step request is pending, then the PC marker, register/flag results, memory view, and errors remain usable and no second conflicting operation is sent. Go never executes. | FR-005, FR-013, FR-021 |
| AC-17 | Given BL followed by a same-mode return and a conditional non-branch instruction, when stepped with both flag outcomes, then LR/PC follow the ISA, and a skipped instruction consumes one Step without its conditional effects. | FR-006, FR-019, FR-022 |
| AC-18 | Given a request exceeding a stated text, instruction, memory, inspection, or session bound, when submitted, then it is rejected with a limit diagnostic and existing state remains unchanged. | FR-002, FR-010–011, FR-020–021 |
| AC-19 | Given a session whose successful Step count is N, when another Step completes with the same PC/state (for example a self-branch), then `step_seq` becomes N+1. Failed Steps, edits, Reset, and reload leave it unchanged. A lost response never triggers an automatic Step retry. | FR-024 |
| AC-20 | Given PF-01–PF-08, when the appropriate mode/format is selected, then normalized bytes, sizes, original source lines and diagnostics match the fixture contract; recognized noise is visible as ignored lines and malformed instruction records are never silently discarded. | FR-001–004, FR-017 |
| AC-21 | Given equivalent ARM/Thumb source and fixed imported bytes, when assembled at the same origin, then normalized addresses/bytes/widths and Step results agree with independent golden expectations. Cover labels, PC-relative encoding, origin changes, adjacent Thumb widths, syntax/decode/profile failures and atomic preservation of an existing experiment. Preserve source without fabricating line mappings. | FR-001–004, FR-017, FR-019, Section 7.0 |

P0 is accepted and fully verified across all AC-01 through AC-21 acceptance criteria and the 388 test suite baseline.

### 15.2 Completed Product P1 baseline acceptance criteria

| ID | Given / When / Then | Requirements |
| --- | --- | --- |
| P1-AC-01 | Given a disassembly listing containing `$a`, `$t`, and `$d` mapping symbols, when parsed and loaded, then instructions are classified with their respective `arm` and `thumb` modes and data lines normalize into `DataRegion` records with concrete addresses and bytes. | P1-FR-001, P1-FR-002 |
| P1-AC-02 | Given a `DataRegion` representing an embedded literal pool, when an instruction performs a valid PC-relative literal read (`LDR r0, [pc, #offset]`), then the access succeeds, returning the expected data bytes; when execution branches directly into a `DataRegion` address, execution halts immediately with a non-executable target stop reason. | P1-FR-002 |
| P1-AC-03 | Given an ARM instruction performing a mode-switching branch to Thumb (e.g. `BX r0` with bit 0 set to 1), when stepped, then CPSR T-bit updates to 1, visible PC is canonicalized (even address), the resulting `(pc, thumb)` location is verified against `ProgramImage`, and exactly one architectural Step commits with `step_seq` incremented by 1. | P1-FR-003, P1-FR-004, P1-FR-005 |
| P1-AC-04 | Given a Thumb instruction performing a mode-switching return to ARM (e.g. `POP {..., pc}` or `BX lr` where LR bit 0 is 0), when stepped, then CPSR T-bit updates to 0, visible PC is canonicalized, and the resulting `(pc, arm)` location is verified against `ProgramImage`, committing atomically. | P1-FR-003, P1-FR-004, P1-FR-005 |
| P1-AC-05 | Given an interworking instruction whose destination or memory access encounters an unmapped address or execution fault, when executed, then full atomic rollback restores pre-Step registers, original CPSR mode/T-bit, and memory state completely without partial state commitment. | P1-FR-005 |
| P1-AC-06 | Given an interworking instruction that targets an address loaded in `ProgramImage` with the opposite mode (e.g. PC at address possessing an ARM instruction while CPU mode is Thumb), then execution halts with an explicit mode mismatch diagnostic. | P1-FR-003, P1-FR-004 |
| P1-AC-07 | Given a Thumb-2 IT block (IT, ITT, ITE) with flags satisfying or failing the condition, when stepped sequentially, then ITSTATE in CPSR correctly governs execution: matching conditions execute their effects, failing conditions conditionally skip without modifying registers/memory, and PC advances appropriately across each Step. | P1-FR-006 |
| P1-AC-08 | Given an IT-controlled instruction, when executed, StepResult distinguishes an instruction that executed with condition passed but produced no register/memory change from an instruction that was conditionally skipped (`executed: false`, `condition_passed: false`). | P1-FR-007 |
| P1-AC-09 | Given a session with loaded Thumb-2 code, when a user attempts to manually set PC to an instruction in the interior of an IT block without active ITSTATE established by the preceding IT instruction, then the operation is rejected with `invalid_it_block_entry`. | P1-FR-008 |
| P1-AC-10 | Given a program with sequential instructions and loops, when Run is initiated, then it executes consecutive atomic Steps until hitting the configured `step_limit`, halting cleanly at a Step boundary with stop reason `step_limit` and exact `step_seq` accounting. | P1-FR-009, P1-FR-010, P1-FR-012 |
| P1-AC-11 | Given a tight self-branch loop or infinite execution loop, when Run is initiated, then it halts cleanly upon reaching the wall-clock execution deadline with stop reason `time_limit` and valid committed machine state. | P1-FR-009, P1-FR-010, P1-FR-012 |
| P1-AC-12 | Given an active Run in progress, when a concurrent Stop request is received, then the in-flight atomic Step finishes or rolls back completely, Run terminates before starting the subsequent Step, and the session returns stop reason `user_stop` with machine state paused at that Step boundary. | P1-FR-011, P1-FR-012 |
| P1-AC-13 | Given Run encountering an unmapped memory access or CPU execution error, then Run halts immediately at that Step; the failed Step rolls back to its pre-step state, and the Run result reports the corresponding fault stop reason. | P1-FR-009, P1-FR-012 |
| P1-AC-14 | Given an active breakpoint at `(address, mode)`, when Run reaches that instruction, then Run halts immediately before attempting execution with stop reason `breakpoint` and pre-execution state preserved; when manual Step is subsequently pressed, the breakpointed instruction executes normally. | P1-FR-013, P1-FR-014 |
| P1-AC-15 | Given a session halted at an active breakpoint, when Run is initiated again, then the current breakpoint is bypassed for exactly one Step, execution continues, and if execution branches back to that breakpoint location later in the Run, execution halts again. | P1-FR-014, P1-FR-015 |
| P1-AC-16 | Given registered breakpoints, when Step, manual edits, or Reset are performed, then breakpoints remain unchanged; when a replacement Load succeeds, all breakpoints are cleared; attempting to set a breakpoint on a DATA address or unaligned address is rejected. | P1-FR-013, P1-FR-016 |

Product P1 is accepted and fully verified across all P1-AC-01 through P1-AC-16 acceptance criteria and the 410 automated test suite baseline.

### 15.3 Product P2 acceptance criteria

| ID | Given / When / Then | Requirements |
| --- | --- | --- |
| P2-AC-01 | Given a valid compiled ARM ELF32-LE executable (`ET_EXEC`) and equivalent assembly source / disassembly import snippets, when loaded, then normalized instruction bytes, addresses, widths, initial mode, and subsequent Step/Run architectural execution results agree across all three producers. | P2-FR-001, P2-FR-002, P2-FR-003 |
| P2-AC-02 | Given an invalid or unsupported ELF file (ELF64 class, big-endian `ELFDATA2MSB`, non-ARM machine architecture, `ET_DYN` / PIE, relocatable `ET_REL` object, or binary requiring `PT_INTERP` dynamic linking), when Load is requested, then the loader rejects atomically with an explicit diagnostic (`unsupported_elf_*`) and existing session state remains completely intact. | P2-FR-002 |
| P2-AC-03 | Given an ELF file with distinct executable (`PF_X`) segments containing ARM mapping symbols (`$a`, `$t`, `$d`) and readable/writable data segments (`PF_R`, `PF_W`), when loaded, then mapping symbols partition executable segments such that `$a`/`$t` ranges populate instructions in `ProgramImage`, `$d` inline data ranges inside executable segments and standalone data segments normalize into `DataRegion` entries and known logical memory, data reads via `LDR` succeed, and branching into any data range halts with `non_executable_target`. If mapping symbols are absent and execution mode is ambiguous, load rejects with `ambiguous_elf_execution_mode`. | P2-FR-003, P2-FR-006 |
| P2-AC-04 | Given an ELF file with a `PT_LOAD` segment where `p_memsz > p_filesz` (representing `.bss`), when loaded, then the trailing memory range `[p_vaddr + p_filesz, p_vaddr + p_memsz)` is explicitly established as known zero bytes in `MemoryState`; reads from that range return zeros; unmapped memory outside the segment remains unknown (`??`). | P2-FR-004 |
| P2-AC-05 | Given an ELF file with entry point `e_entry` matching an instruction start (including address `0x00000000` when mapped to executable code; e.g. `0x08000101` for Thumb or `0x08000100` for ARM), when loaded, then initial PC canonicalizes to even address (`e_entry & ~1`), execution mode initializes to `thumb` (if bit 0 is 1) or `arm` (if bit 0 is 0), and initial CPSR reflects the corresponding mode. | P2-FR-005 |
| P2-AC-06 | Given an ELF file violating independent operational bounds (raw file > 10 MiB, segment count > 32, section count > 128, decoded instructions > 10,000, total logical loaded memory including BSS > 16 MiB, or backing pages > 64 MiB), when load is attempted, then it is rejected atomically with an actionable limit diagnostic (`input_limit` or `resource_limit`) with existing session state untouched. | P2-FR-006 |
| P2-AC-07 | Given an unstripped ELF file with function (`STT_FUNC`) and object (`STT_OBJECT`) symbols, when loaded, then valid symbols resolve in `ProgramMetadata` and display as labels in the UI; when an identical binary stripped of symbol tables is loaded, execution behavior, stepping, and results remain identical. | P2-FR-007, P2-FR-008 |
| P2-AC-08 | Given an ELF file with multiple symbols at the same address (e.g. local and global labels) or symbols without executable instructions, then symbols resolve deterministically without crashing or altering machine execution bytes. | P2-FR-007, P2-FR-008 |
| P2-AC-09 | Given an ELF binary compiled with DWARF line tables (`.debug_line`), when loaded, instruction addresses map to corresponding `(file, line)` metadata records; when a binary lacking DWARF information is loaded, it loads and executes normally without errors. | P2-FR-009 |
| P2-AC-10 | Given DWARF line records referencing source files absent from the local host or browser sandbox, the UI displays `file:line` metadata (e.g. `foo.c:42`) without fabricating source text or demanding arbitrary local filesystem access. | P2-FR-010 |
| P2-AC-11 | Given an active read watchpoint on memory range `[0x20000000, 0x20000004)`, when an instruction reads memory within that range (e.g. `LDR r0, [r1]` where R1 is in range) during single Step or bounded Run, then the instruction commits its architectural effects, Step reports committed `watchpoint_hits`, Run halts immediately after committing that Step with stop reason `watchpoint`, and triggering access details are reported. | P2-FR-011, P2-FR-012 |
| P2-AC-12 | Given an active write watchpoint on memory range `[0x20000000, 0x20000004)`, when an instruction writes to that range during single Step or bounded Run (including a store where written byte values equal the existing byte values), then the instruction commits its architectural effects, Step reports committed `watchpoint_hits`, Run halts at that Step boundary with stop reason `watchpoint`, and triggering access details are reported. | P2-FR-012, P2-FR-014 |
| P2-AC-13 | Given an active watchpoint and a multi-access instruction (e.g. `LDM` or `STM`) whose second or subsequent register transfer touches the watched range, when stepped or run, the watchpoint triggers upon successful completion of the instruction, preserving ordered multiple hits from that single instruction. | P2-FR-011, P2-FR-012 |
| P2-AC-14 | Given an active watchpoint on an unmapped address range, when an instruction attempts to access that range and fails (triggering `memory_fault` rollback), then the failed Step does not trigger a watchpoint hit; Run halts with stop reason `memory_fault` and machine state remains restored to the pre-Step state. If an instruction commits an architectural stop condition (e.g. `pc_not_loaded`) and simultaneously touches a watchpoint, Run reports stop reason `watchpoint` while `last_step_result` deterministically retains both `pc_not_loaded` and `watchpoint_hits`. | P2-FR-012, P2-FR-013 |
| P2-AC-15 | Given an instruction that has an active breakpoint and also performs a memory access to an active watchpoint, when Run is initiated, then Run halts before executing the instruction with stop reason `breakpoint`; upon resuming, the instruction executes, commits, and Run halts with stop reason `watchpoint`. | P2-FR-012, P2-FR-015 |
| P2-AC-16 | Given registered watchpoints, when single Step, bounded Run, manual register/flag/memory edits, or session Reset are performed, then watchpoints remain active; when a replacement Load succeeds, all watchpoints are cleared. | P2-FR-015 |
| P2-AC-17 | Given execution of 3 consecutive atomic Steps modifying registers and memory (advancing `step_seq` from 0 to 3), when Step Back is invoked, then Runtime State (registers, CPSR flags/mode/ITSTATE, PC, memory bytes) is restored exactly to the state after Step 2; `step_seq` remains 3 (never decremented or incremented on Step Back); `state_revision` increments; a second Step Back restores state to after Step 1 (`step_seq` still 3); a subsequent forward Step executes instruction 2 correctly and commits with `step_seq` advancing from monotonic maximum (3 -> 4). | P2-FR-016, P2-FR-017, P2-FR-018 |
| P2-AC-18 | Given a session where user manual edits were applied and several Steps were executed, when Step Back is performed, then User Baseline State and restart PC remain completely unchanged, and reverse memory restoration uses lazily captured pre-Step original bytes (retaining the first pre-value once for multiple writes to the same byte within a single instruction). | P2-FR-017, P2-FR-018 |
| P2-AC-19 | Given a session stepped from state A to B to C, then stepped back to B, when a new forward Step or Run is executed producing state D, then previous forward state C is purged from history (linear history preserved). When forward steps exceed capacity (100), oldest history entries are discarded without error. | P2-FR-019, P2-FR-021 |
| P2-AC-20 | Given an active execution history, when a manual register edit, flag edit, PC edit, memory patch, zero-fill, session Reset, or replacement Load is performed, then all retained execution history is cleared and Step Back is disabled until new steps commit. Breakpoint and watchpoint edits do not clear history. | P2-FR-020 |

### 15.4 Product P3 acceptance criteria (Planned Milestone — RISC-V Introduction: RV32I)

| ID | Given / When / Then | Requirements |
| --- | --- | --- |
| P3-AC-01 | Given existing ARMv7-A / Thumb-2 test fixtures and Playwright suites, when executed under the refactored multi-ISA domain boundary, then all tests remain 100% green with zero regressions. | P3-FR-016 |
| P3-AC-02 | Given a multi-ISA codebase, when inspecting shared simulation contracts (`domain/models.py`, `simulation/state.py`), then shared models do not require ARM CPSR, Thumb IT context, or ARM condition flags for RISC-V sessions. | P3-FR-004, P3-FR-005 |
| P3-AC-03 | Given an RV32I session, when reading register `x0` or `zero`, then it unconditionally returns value 0; when a user edit targeting `x0` or `zero` is attempted via API or UI, then the request rejects with HTTP 422 `x0_immutable`. | P3-FR-002, P3-FR-003 |
| P3-AC-04 | Given an RV32I program containing `addi x0, x1, 5`, when stepped, then execution completes successfully, `x0` remains 0, and no register delta for `x0` is reported in `StepResult.register_changes`. | P3-FR-001, P3-FR-002 |
| P3-AC-05 | Given an RV32I session, when user edits are applied to registers `x1` through `x31` or `pc`, then runtime and user baseline state reflect the updated values; edits with invalid register names reject with 422. | P3-FR-003 |
| P3-AC-06 | Given an RV32I session, when registers are edited or referenced using standard ABI aliases (`ra`, `sp`, `gp`, `tp`, `t0`–`t6`, `s0`–`s11`, `a0`–`a7`), then they map to and update the underlying canonical registers (`x1`, `x2`, etc.). | P3-FR-003 |
| P3-AC-07 | Given RV32I computational instructions (`ADD`, `SUB`, `ADDI`), when stepped, then 32-bit arithmetic produces exact wrapping overflow and signed immediate adjustment results. | P3-FR-001 |
| P3-AC-08 | Given RV32I bitwise and shift instructions (`AND`, `OR`, `XOR`, `SLL`, `SRL`, `SRA`), when stepped, then exact bitwise masking, logical zero-fill shift (`SRL`), and sign-replicating arithmetic shift (`SRA`) are observed. | P3-FR-001 |
| P3-AC-09 | Given comparison instructions (`SLT`, `SLTI`, `SLTU`, `SLTIU`), when stepped with operands `0xFFFFFFFF` (-1 signed) and `1`, then signed comparisons yield 1 and unsigned comparisons yield 0. | P3-FR-001 |
| P3-AC-10 | Given upper immediate instructions (`LUI`, `AUIPC`), when stepped, then `LUI` sets upper 20 bits directly and `AUIPC` adds upper immediate to the instruction's own PC. | P3-FR-001 |
| P3-AC-11 | Given memory load and store instructions (`LB`, `LBU`, `LH`, `LHU`, `LW`, `SB`, `SH`, `SW`), when stepped, then little-endian byte layout is maintained in memory; signed loads (`LB`, `LH`) sign-extend and unsigned loads (`LBU`, `LHU`) zero-extend into destination registers. | P3-FR-001, P3-FR-011 |
| P3-AC-12 | Given an RV32I load or store instruction targeting unmapped memory (`??`), when stepped, then execution halts with `memory_fault` and native machine state completely rolls back to the pre-step snapshot. | P3-FR-001, P3-FR-011 |
| P3-AC-13 | Given conditional branch instructions (`BEQ`, `BNE`, `BLT`, `BGE`, `BLTU`, `BGEU`), when stepped, then taken branches update PC to target and untaken branches advance PC by 4; signed vs unsigned branches observe correct predicate comparisons. | P3-FR-001, P3-FR-006 |
| P3-AC-14 | Given jump instructions (`JAL`, `JALR`), when stepped, then `JAL` writes link address `PC + 4` to `rd` and updates PC; `JALR` masks bit 0 (`target & ~1`), updates PC, and writes link address if `rd != zero`. Return via `jalr zero, 0(ra)` executes cleanly. | P3-FR-001, P3-FR-006 |
| P3-AC-15 | Given environment instructions `ECALL` and `EBREAK`, when stepped, then execution halts cleanly with explicit stop reasons `environment_call` or `breakpoint_trap` without crashing the session or engine. | P3-FR-014 |
| P3-AC-16 | Given valid RV32I assembly source with local labels and ABI aliases, when loaded, then the assembler generates exact machine bytes and produces a valid `ProgramImage`. | P3-FR-008 |
| P3-AC-17 | Given addressed RV32 disassembly text with hex bytes, when loaded, then machine bytes are authoritative and disassemble into valid `ProgramImage` instruction records without requiring ARM mapping symbols. | P3-FR-009 |
| P3-AC-18 | Given representative RV32I test snippets, when compared against an independent `llvm-mc` or GNU binutils oracle, then assembled machine bytes match the oracle outputs byte-for-byte. | P3-FR-010 |
| P3-AC-19 | Given an RV32I program loaded in a session, when bounded Run is triggered, consecutive Steps execute up to the limit; when Stop is signaled concurrently, Run halts cleanly at the next Step boundary. | P3-FR-013 |
| P3-AC-20 | Given a pre-execution breakpoint on an RV32I instruction address, when Run is triggered, execution halts before executing the target instruction; resuming bypasses the breakpoint for one step. | P3-FR-013 |
| P3-AC-21 | Given an active memory watchpoint on a memory range, when an RV32I load or store accesses that range, then committed `watchpoint_hits` are reported on single Step, and Run terminates with stop reason `watchpoint`. Rolled-back failed steps never trigger watchpoints. | P3-FR-013 |
| P3-AC-22 | Given several executed RV32I steps, when Step Back is invoked, Runtime State is rewound to the preceding step boundary, preserving `step_seq` invariance and incrementing `state_revision`. | P3-FR-013 |
| P3-AC-23 | Given an RV32I session with manual edits, when Reset is invoked, the session cleanly restores state from the User Baseline State. | P3-FR-013 |
| P3-AC-24 | Given a browser connected to an RV32I session, the UI dynamically renders `x0`–`x31` with ABI labels, suppresses CPSR and flags panels, and enables Step/Run/Breakpoint interactions. | P3-FR-015 |


