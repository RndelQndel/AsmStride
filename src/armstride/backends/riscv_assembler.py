"""Standalone lightweight RV32I two-pass assembler in pure Python."""

import re
import struct

from armstride.architecture.decode import RiscvDecoder
from armstride.architecture.riscv import ALIASES, PROFILE, REGISTERS, validate_profile
from armstride.assembly import AssemblyResult
from armstride.domain.models import MAX_TEXT_BYTES, Diagnostic, DomainError, ProgramImage, validate_range

# Bitfield pack helpers
def enc_r(funct7: int, rs2: int, rs1: int, funct3: int, rd: int, opcode: int = 0x33) -> bytes:
    val = ((funct7 & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)


def enc_i(imm: int, rs1: int, funct3: int, rd: int, opcode: int) -> bytes:
    val = ((imm & 0xFFF) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)


def enc_s(imm: int, rs2: int, rs1: int, funct3: int, opcode: int = 0x23) -> bytes:
    val = (((imm >> 5) & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | ((imm & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)


def enc_b(imm: int, rs2: int, rs1: int, funct3: int, opcode: int = 0x63) -> bytes:
    imm12 = (imm >> 12) & 1
    imm10_5 = (imm >> 5) & 0x3F
    imm4_1 = (imm >> 1) & 0x0F
    imm11 = (imm >> 11) & 1
    val = (imm12 << 31) | (imm10_5 << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | (imm4_1 << 8) | (imm11 << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)


def enc_u(imm: int, rd: int, opcode: int) -> bytes:
    val = (imm & 0xFFFFF000) | ((rd & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)


def enc_j(imm: int, rd: int, opcode: int = 0x6F) -> bytes:
    imm20 = (imm >> 20) & 1
    imm10_1 = (imm >> 1) & 0x3FF
    imm11 = (imm >> 11) & 1
    imm19_12 = (imm >> 12) & 0xFF
    val = (imm20 << 31) | (imm10_1 << 21) | (imm11 << 20) | (imm19_12 << 12) | \
          ((rd & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)


def parse_reg(token: str) -> int:
    name = token.strip().lower().rstrip(",")
    if name in ALIASES:
        name = ALIASES[name]
    if name.startswith("x") and name[1:].isdigit():
        idx = int(name[1:])
        if 0 <= idx <= 31:
            return idx
    raise DomainError("invalid_register", f"Unknown register '{token}'.")


def parse_imm(token: str) -> int:
    token = token.strip().rstrip(",")
    return int(token, 0)


def parse_mem(token: str) -> tuple[int, int]:
    """Parse 'offset(rs)' or '(rs)' or 'rs'."""
    token = token.strip().rstrip(",")
    match = re.match(r"^([+-]?(?:0[xX][0-9a-fA-F]+|[0-9]+))?\s*\(\s*([a-zA-Z0-9]+)\s*\)$", token)
    if match:
        disp_str = match.group(1)
        disp = int(disp_str, 0) if disp_str else 0
        reg = parse_reg(match.group(2))
        return reg, disp
    # Alternative: 'rs, offset' or just 'rs'
    return parse_reg(token), 0


def strip_comments(source: str) -> str:
    # Remove C-style /* */ and single-line # or //
    uncommented = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    lines = []
    for line in uncommented.splitlines():
        # Strip # or // outside quotes
        line = re.sub(r"(#|//).*$", "", line)
        lines.append(line)
    return "\n".join(lines)


class RiscvAssembler:
    def assemble(self, source: str, *, mode: str = "riscv32", base_address: int,
                 profile: str = PROFILE) -> AssemblyResult:
        try:
            validate_profile(profile, mode)
            validate_range(base_address, 4)
            if base_address % 4 != 0:
                raise DomainError("invalid_encoding", "Assembly base address must be 4-byte aligned.")
            if not isinstance(source, str) or "\0" in source:
                raise DomainError("invalid_input", "Assembly source must be text without NUL characters.")
            if len(source) > MAX_TEXT_BYTES or len(source.encode("utf-8")) > MAX_TEXT_BYTES:
                raise DomainError("input_limit", "Input exceeds 1 MiB.")

            # Filter diagnostics for unsupported directives
            clean_lines = []
            labels = {}
            uncommented = strip_comments(source)
            statements = []

            for line_no, raw_line in enumerate(uncommented.splitlines(), 1):
                parts = [p.strip() for p in raw_line.split(";") if p.strip()]
                for part in parts:
                    # Check for labels
                    while True:
                        lbl_match = re.match(r"^([A-Za-z0-9_.$]+)\s*:\s*(.*)$", part)
                        if lbl_match:
                            lbl_name = lbl_match.group(1)
                            part = lbl_match.group(2).strip()
                            statements.append((line_no, "label", lbl_name, ""))
                        else:
                            break
                    if part:
                        statements.append((line_no, "insn", "", part))

            # Pass 1: compute statement addresses and collect labels
            addr = base_address
            pass1_items = []
            for line_no, kind, lbl_name, text in statements:
                if kind == "label":
                    labels[lbl_name] = addr
                elif kind == "insn":
                    # Check if directive
                    if text.startswith("."):
                        directive = text.split()[0].lower()
                        if directive in (".text", ".globl", ".global", ".align", ".balign", ".option", ".attribute"):
                            continue
                        raise DomainError("unsupported_source",
                                          f"Directive {directive} is not supported in RV32I snippet assembly.")
                    tokens = text.replace(",", " ").split()
                    mnemonic = tokens[0].lower()
                    # Check pseudo-instruction expansion size
                    if mnemonic == "li":
                        imm_val = parse_imm(tokens[2])
                        if -2048 <= imm_val <= 2047:
                            insn_size = 4
                        else:
                            insn_size = 8
                    else:
                        insn_size = 4
                    pass1_items.append((line_no, addr, insn_size, tokens, text))
                    addr += insn_size

            # Pass 2: encode instructions
            emitted = bytearray()
            for line_no, insn_addr, insn_size, tokens, orig_text in pass1_items:
                mnemonic = tokens[0].lower()
                try:
                    raw = self._encode_instruction(mnemonic, tokens[1:], insn_addr, labels)
                    emitted.extend(raw)
                except Exception as error:
                    code = error.code if isinstance(error, DomainError) else "assembly_error"
                    raise DomainError(code, f"Line {line_no}: {error}") from error

            raw_bytes = bytes(emitted)
            if not raw_bytes:
                raise DomainError("empty_program", "Assembler produced no instructions.")

            decoder = RiscvDecoder()
            instructions = decoder.decode_stream(base_address, raw_bytes)
            program = ProgramImage(instructions, "riscv32", source, "assembly", PROFILE)
            warnings = tuple(Diagnostic("warning", "unsupported_instruction", instruction.feature_exclusion)
                             for instruction in instructions if instruction.feature_exclusion)
            return AssemblyResult(source, base_address, raw_bytes, program, warnings)

        except (DomainError, UnicodeError) as error:
            diagnostic = Diagnostic("error", error.code if isinstance(error, DomainError) else "invalid_input",
                                    str(error))
            return AssemblyResult(source, base_address, diagnostics=(diagnostic,))

    def _resolve_target(self, token: str, cur_addr: int, labels: dict[str, int]) -> int:
        token = token.strip().rstrip(",")
        if token in labels:
            return labels[token] - cur_addr
        # Numeric immediate offset
        val = int(token, 0)
        return val

    def _encode_instruction(self, mnemonic: str, args: list[str], cur_addr: int, labels: dict[str, int]) -> bytes:
        # R-type
        if mnemonic == "add":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x0, parse_reg(args[0]), 0x33)
        if mnemonic == "sub":
            return enc_r(0x20, parse_reg(args[2]), parse_reg(args[1]), 0x0, parse_reg(args[0]), 0x33)
        if mnemonic == "sll":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x1, parse_reg(args[0]), 0x33)
        if mnemonic == "slt":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x2, parse_reg(args[0]), 0x33)
        if mnemonic == "sltu":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x3, parse_reg(args[0]), 0x33)
        if mnemonic == "xor":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x4, parse_reg(args[0]), 0x33)
        if mnemonic == "srl":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x5, parse_reg(args[0]), 0x33)
        if mnemonic == "sra":
            return enc_r(0x20, parse_reg(args[2]), parse_reg(args[1]), 0x5, parse_reg(args[0]), 0x33)
        if mnemonic == "or":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x6, parse_reg(args[0]), 0x33)
        if mnemonic == "and":
            return enc_r(0x00, parse_reg(args[2]), parse_reg(args[1]), 0x7, parse_reg(args[0]), 0x33)

        # I-type
        if mnemonic == "addi":
            return enc_i(parse_imm(args[2]), parse_reg(args[1]), 0x0, parse_reg(args[0]), 0x13)
        if mnemonic == "slti":
            return enc_i(parse_imm(args[2]), parse_reg(args[1]), 0x2, parse_reg(args[0]), 0x13)
        if mnemonic == "sltiu":
            return enc_i(parse_imm(args[2]), parse_reg(args[1]), 0x3, parse_reg(args[0]), 0x13)
        if mnemonic == "xori":
            return enc_i(parse_imm(args[2]), parse_reg(args[1]), 0x4, parse_reg(args[0]), 0x13)
        if mnemonic == "ori":
            return enc_i(parse_imm(args[2]), parse_reg(args[1]), 0x6, parse_reg(args[0]), 0x13)
        if mnemonic == "andi":
            return enc_i(parse_imm(args[2]), parse_reg(args[1]), 0x7, parse_reg(args[0]), 0x13)
        if mnemonic == "slli":
            return enc_r(0x00, parse_imm(args[2]) & 0x1F, parse_reg(args[1]), 0x1, parse_reg(args[0]), 0x13)
        if mnemonic == "srli":
            return enc_r(0x00, parse_imm(args[2]) & 0x1F, parse_reg(args[1]), 0x5, parse_reg(args[0]), 0x13)
        if mnemonic == "srai":
            return enc_r(0x20, parse_imm(args[2]) & 0x1F, parse_reg(args[1]), 0x5, parse_reg(args[0]), 0x13)

        # Loads
        if mnemonic in ("lb", "lh", "lw", "lbu", "lhu"):
            f3 = {"lb": 0x0, "lh": 0x1, "lw": 0x2, "lbu": 0x4, "lhu": 0x5}[mnemonic]
            rd = parse_reg(args[0])
            if len(args) == 2:
                rs1, offset = parse_mem(args[1])
            else:
                rs1 = parse_reg(args[1])
                offset = parse_imm(args[2])
            return enc_i(offset, rs1, f3, rd, 0x03)

        # Stores
        if mnemonic in ("sb", "sh", "sw"):
            f3 = {"sb": 0x0, "sh": 0x1, "sw": 0x2}[mnemonic]
            rs2 = parse_reg(args[0])
            if len(args) == 2:
                rs1, offset = parse_mem(args[1])
            else:
                rs1 = parse_reg(args[1])
                offset = parse_imm(args[2])
            return enc_s(offset, rs2, rs1, f3, 0x23)

        # Branches
        if mnemonic in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
            f3 = {"beq": 0x0, "bne": 0x1, "blt": 0x4, "bge": 0x5, "bltu": 0x6, "bgeu": 0x7}[mnemonic]
            rs1 = parse_reg(args[0])
            rs2 = parse_reg(args[1])
            offset = self._resolve_target(args[2], cur_addr, labels)
            return enc_b(offset, rs2, rs1, f3, 0x63)

        # Branch pseudos
        if mnemonic in ("beqz", "bnez", "blez", "bgez", "bltz", "bgtz"):
            rs1 = parse_reg(args[0])
            offset = self._resolve_target(args[1], cur_addr, labels)
            if mnemonic == "beqz": return enc_b(offset, 0, rs1, 0x0, 0x63)
            if mnemonic == "bnez": return enc_b(offset, 0, rs1, 0x1, 0x63)
            if mnemonic == "blez": return enc_b(offset, rs1, 0, 0x5, 0x63) # bge x0, rs1
            if mnemonic == "bgez": return enc_b(offset, 0, rs1, 0x5, 0x63) # bge rs1, x0
            if mnemonic == "bltz": return enc_b(offset, 0, rs1, 0x4, 0x63) # blt rs1, x0
            if mnemonic == "bgtz": return enc_b(offset, rs1, 0, 0x4, 0x63) # blt x0, rs1

        if mnemonic in ("bgt", "ble", "bgtu", "bleu"):
            rs = parse_reg(args[0])
            rt = parse_reg(args[1])
            offset = self._resolve_target(args[2], cur_addr, labels)
            if mnemonic == "bgt": return enc_b(offset, rs, rt, 0x4, 0x63)  # blt rt, rs
            if mnemonic == "ble": return enc_b(offset, rs, rt, 0x5, 0x63)  # bge rt, rs
            if mnemonic == "bgtu": return enc_b(offset, rs, rt, 0x6, 0x63) # bltu rt, rs
            if mnemonic == "bleu": return enc_b(offset, rs, rt, 0x7, 0x63) # bgeu rt, rs

        # Upper immediate
        if mnemonic == "lui":
            rd = parse_reg(args[0])
            imm = parse_imm(args[1])
            if imm < 0x100000:
                imm = imm << 12
            return enc_u(imm, rd, 0x37)
        if mnemonic == "auipc":
            rd = parse_reg(args[0])
            imm = parse_imm(args[1])
            if imm < 0x100000:
                imm = imm << 12
            return enc_u(imm, rd, 0x17)

        # Jumps
        if mnemonic == "jal":
            if len(args) == 2:
                rd = parse_reg(args[0])
                offset = self._resolve_target(args[1], cur_addr, labels)
            else:
                rd = 1  # ra
                offset = self._resolve_target(args[0], cur_addr, labels)
            return enc_j(offset, rd, 0x6F)

        if mnemonic == "j":
            offset = self._resolve_target(args[0], cur_addr, labels)
            return enc_j(offset, 0, 0x6F)

        if mnemonic == "jalr":
            if len(args) == 3:
                rd = parse_reg(args[0])
                rs1 = parse_reg(args[1])
                offset = parse_imm(args[2])
            elif len(args) == 2:
                rd = parse_reg(args[0])
                rs1, offset = parse_mem(args[1])
            else:
                rd = 1  # ra
                rs1 = parse_reg(args[0])
                offset = 0
            return enc_i(offset, rs1, 0x0, rd, 0x67)

        if mnemonic == "jr":
            rs1 = parse_reg(args[0])
            return enc_i(0, rs1, 0x0, 0, 0x67)

        if mnemonic == "ret":
            return enc_i(0, 1, 0x0, 0, 0x67)  # jalr x0, ra, 0

        # System
        if mnemonic == "ecall":
            return struct.pack("<I", 0x00000073)
        if mnemonic == "ebreak":
            return struct.pack("<I", 0x00100073)
        if mnemonic == "fence":
            return struct.pack("<I", 0x0000000F)

        # Pseudos
        if mnemonic == "nop":
            return enc_i(0, 0, 0, 0, 0x13)  # addi x0, x0, 0
        if mnemonic == "mv":
            return enc_i(0, parse_reg(args[1]), 0, parse_reg(args[0]), 0x13)
        if mnemonic == "not":
            return enc_i(-1, parse_reg(args[1]), 4, parse_reg(args[0]), 0x13)  # xori rd, rs, -1
        if mnemonic == "neg":
            return enc_r(0x20, parse_reg(args[1]), 0, 0, parse_reg(args[0]), 0x33)  # sub rd, x0, rs
        if mnemonic == "seqz":
            return enc_i(1, parse_reg(args[1]), 3, parse_reg(args[0]), 0x13)  # sltiu rd, rs, 1
        if mnemonic == "snez":
            return enc_r(0x00, parse_reg(args[1]), 0, 3, parse_reg(args[0]), 0x33)  # sltu rd, x0, rs
        if mnemonic == "sltz":
            return enc_r(0x00, 0, parse_reg(args[1]), 2, parse_reg(args[0]), 0x33)  # slt rd, rs, x0
        if mnemonic == "sgtz":
            return enc_r(0x00, parse_reg(args[1]), 0, 2, parse_reg(args[0]), 0x33)  # slt rd, x0, rs

        if mnemonic == "li":
            rd = parse_reg(args[0])
            imm_val = parse_imm(args[1])
            if -2048 <= imm_val <= 2047:
                return enc_i(imm_val, 0, 0, rd, 0x13)
            else:
                imm32 = imm_val & 0xFFFFFFFF
                imm_hi = ((imm32 + 0x800) >> 12) & 0xFFFFF
                imm_lo = (imm32 & 0xFFF)
                if imm_lo >= 2048:
                    imm_lo -= 4096
                b1 = enc_u(imm_hi << 12, rd, 0x37)
                b2 = enc_i(imm_lo, rd, 0, rd, 0x13)
                return b1 + b2

        if mnemonic == "call":
            offset = self._resolve_target(args[0], cur_addr, labels)
            if -1048576 <= offset < 1048576:
                return enc_j(offset, 1, 0x6F)  # jal ra, offset
            else:
                hi = (offset + 0x800) >> 12
                lo = offset - (hi << 12)
                b1 = enc_u(hi << 12, 1, 0x17)  # auipc ra, hi
                b2 = enc_i(lo, 1, 0, 1, 0x67)  # jalr ra, ra, lo
                return b1 + b2

        raise DomainError("unsupported_instruction", f"Unrecognized RV32I instruction '{mnemonic}'.")
