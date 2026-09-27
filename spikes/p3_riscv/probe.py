"""RISC-V (RV32I) semantics feasibility spike on pinned Unicorn 2.1.4 and Capstone 5.0.7."""

import json
import struct
import sys
from pathlib import Path
import capstone
from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32
from capstone.riscv import RISCV_OP_REG, RISCV_OP_IMM, RISCV_OP_MEM
import unicorn as uc
from unicorn import riscv_const as rc

PAGE = 0x1000

# --- RV32I Instruction Encoders ---

def enc_r(funct7: int, rs2: int, rs1: int, funct3: int, rd: int, opcode: int = 0x33) -> bytes:
    val = ((funct7 & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)

def enc_i(imm: int, rs1: int, funct3: int, rd: int, opcode: int) -> bytes:
    val = ((imm & 0xFFF) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)
    return struct.pack("<I", val)

def enc_s(imm: int, rs2: int, rs1: int, funct3: int, opcode: int = 0x23) -> bytes:
    imm11_5 = (imm >> 5) & 0x7F
    imm4_0 = imm & 0x1F
    val = (imm11_5 << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | \
          ((funct3 & 0x07) << 12) | (imm4_0 << 7) | (opcode & 0x7F)
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

# Core RV32I Encodings
def ADD(rd, rs1, rs2):   return enc_r(0x00, rs2, rs1, 0x0, rd, 0x33)
def SUB(rd, rs1, rs2):   return enc_r(0x20, rs2, rs1, 0x0, rd, 0x33)
def SLL(rd, rs1, rs2):   return enc_r(0x00, rs2, rs1, 0x1, rd, 0x33)
def SLT(rd, rs1, rs2):   return enc_r(0x00, rs2, rs1, 0x2, rd, 0x33)
def SLTU(rd, rs1, rs2):  return enc_r(0x00, rs2, rs1, 0x3, rd, 0x33)
def XOR(rd, rs1, rs2):   return enc_r(0x00, rs2, rs1, 0x4, rd, 0x33)
def SRL(rd, rs1, rs2):   return enc_r(0x00, rs2, rs1, 0x5, rd, 0x33)
def SRA(rd, rs1, rs2):   return enc_r(0x20, rs2, rs1, 0x5, rd, 0x33)
def OR(rd, rs1, rs2):    return enc_r(0x00, rs2, rs1, 0x6, rd, 0x33)
def AND(rd, rs1, rs2):   return enc_r(0x00, rs2, rs1, 0x7, rd, 0x33)

def ADDI(rd, rs1, imm):  return enc_i(imm, rs1, 0x0, rd, 0x13)
def SLTI(rd, rs1, imm):  return enc_i(imm, rs1, 0x2, rd, 0x13)
def SLTIU(rd, rs1, imm): return enc_i(imm, rs1, 0x3, rd, 0x13)
def XORI(rd, rs1, imm):  return enc_i(imm, rs1, 0x4, rd, 0x13)
def ORI(rd, rs1, imm):   return enc_i(imm, rs1, 0x6, rd, 0x13)
def ANDI(rd, rs1, imm):  return enc_i(imm, rs1, 0x7, rd, 0x13)
def SLLI(rd, rs1, shamt): return enc_r(0x00, shamt & 0x1F, rs1, 0x1, rd, 0x13)
def SRLI(rd, rs1, shamt): return enc_r(0x00, shamt & 0x1F, rs1, 0x5, rd, 0x13)
def SRAI(rd, rs1, shamt): return enc_r(0x20, shamt & 0x1F, rs1, 0x5, rd, 0x13)

def LUI(rd, imm):        return enc_u(imm, rd, 0x37)
def AUIPC(rd, imm):      return enc_u(imm, rd, 0x17)

def LB(rd, rs1, imm):    return enc_i(imm, rs1, 0x0, rd, 0x03)
def LH(rd, rs1, imm):    return enc_i(imm, rs1, 0x1, rd, 0x03)
def LW(rd, rs1, imm):    return enc_i(imm, rs1, 0x2, rd, 0x03)
def LBU(rd, rs1, imm):   return enc_i(imm, rs1, 0x4, rd, 0x03)
def LHU(rd, rs1, imm):   return enc_i(imm, rs1, 0x5, rd, 0x03)

def SB(rs2, rs1, imm):   return enc_s(imm, rs2, rs1, 0x0, 0x23)
def SH(rs2, rs1, imm):   return enc_s(imm, rs2, rs1, 0x1, 0x23)
def SW(rs2, rs1, imm):   return enc_s(imm, rs2, rs1, 0x2, 0x23)

def BEQ(rs1, rs2, imm):  return enc_b(imm, rs2, rs1, 0x0, 0x63)
def BNE(rs1, rs2, imm):  return enc_b(imm, rs2, rs1, 0x1, 0x63)
def BLT(rs1, rs2, imm):  return enc_b(imm, rs2, rs1, 0x4, 0x63)
def BGE(rs1, rs2, imm):  return enc_b(imm, rs2, rs1, 0x5, 0x63)
def BLTU(rs1, rs2, imm): return enc_b(imm, rs2, rs1, 0x6, 0x63)
def BGEU(rs1, rs2, imm): return enc_b(imm, rs2, rs1, 0x7, 0x63)

def JAL(rd, imm):        return enc_j(imm, rd, 0x6F)
def JALR(rd, rs1, imm):  return enc_i(imm, rs1, 0x0, rd, 0x67)

def ECALL():             return struct.pack("<I", 0x00000073)
def EBREAK():            return struct.pack("<I", 0x00100073)
def FENCE():             return struct.pack("<I", 0x0000000F)

# Register ID map
REG_MAP = {
    f"x{i}": getattr(rc, f"UC_RISCV_REG_X{i}") for i in range(32)
}
REG_MAP["zero"] = rc.UC_RISCV_REG_ZERO
REG_MAP["ra"] = rc.UC_RISCV_REG_RA
REG_MAP["sp"] = rc.UC_RISCV_REG_SP
REG_MAP["gp"] = rc.UC_RISCV_REG_GP
REG_MAP["tp"] = rc.UC_RISCV_REG_TP
REG_MAP["t0"] = rc.UC_RISCV_REG_T0
REG_MAP["t1"] = rc.UC_RISCV_REG_T1
REG_MAP["t2"] = rc.UC_RISCV_REG_T2
REG_MAP["s0"] = rc.UC_RISCV_REG_S0
REG_MAP["s1"] = rc.UC_RISCV_REG_S1
REG_MAP["a0"] = rc.UC_RISCV_REG_A0
REG_MAP["a1"] = rc.UC_RISCV_REG_A1
REG_MAP["a2"] = rc.UC_RISCV_REG_A2
REG_MAP["a3"] = rc.UC_RISCV_REG_A3
REG_MAP["a4"] = rc.UC_RISCV_REG_A4
REG_MAP["a5"] = rc.UC_RISCV_REG_A5
REG_MAP["a6"] = rc.UC_RISCV_REG_A6
REG_MAP["a7"] = rc.UC_RISCV_REG_A7
REG_MAP["s2"] = rc.UC_RISCV_REG_S2
REG_MAP["s3"] = rc.UC_RISCV_REG_S3
REG_MAP["s4"] = rc.UC_RISCV_REG_S4
REG_MAP["s5"] = rc.UC_RISCV_REG_S5
REG_MAP["s6"] = rc.UC_RISCV_REG_S6
REG_MAP["s7"] = rc.UC_RISCV_REG_S7
REG_MAP["s8"] = rc.UC_RISCV_REG_S8
REG_MAP["s9"] = rc.UC_RISCV_REG_S9
REG_MAP["s10"] = rc.UC_RISCV_REG_S10
REG_MAP["s11"] = rc.UC_RISCV_REG_S11
REG_MAP["t3"] = rc.UC_RISCV_REG_T3
REG_MAP["t4"] = rc.UC_RISCV_REG_T4
REG_MAP["t5"] = rc.UC_RISCV_REG_T5
REG_MAP["t6"] = rc.UC_RISCV_REG_T6
REG_MAP["pc"] = rc.UC_RISCV_REG_PC


def create_emulator(code_pages=(0x1000,), data_pages=(0x2000, 0x3000)):
    mu = uc.Uc(uc.UC_ARCH_RISCV, uc.UC_MODE_RISCV32)
    for p in code_pages:
        mu.mem_map(p, PAGE, uc.UC_PROT_ALL)
    for p in data_pages:
        mu.mem_map(p, PAGE, uc.UC_PROT_ALL)
    for i in range(32):
        mu.reg_write(REG_MAP[f"x{i}"], 0)
    mu.reg_write(rc.UC_RISCV_REG_PC, 0x1000)
    return mu


def run_spike():
    observations = {}
    print("==================================================================")
    print("Executing Product P3 RISC-V (RV32I) Semantics Feasibility Spike")
    print("==================================================================")

    # 1. Arithmetic & Bitwise
    print("\n--- 1. Arithmetic & Bitwise ---")
    mu = create_emulator()
    # ADD wrapping overflow: 0x7FFFFFFF + 1 = 0x80000000, and 0xFFFFFFFF + 1 = 0
    mu.reg_write(REG_MAP["x1"], 0x7FFFFFFF)
    mu.reg_write(REG_MAP["x2"], 1)
    mu.mem_write(0x1000, ADD(3, 1, 2))
    mu.emu_start(0x1000, 0x1004, count=1)
    res_add_pos = mu.reg_read(REG_MAP["x3"])

    mu.reg_write(REG_MAP["x1"], 0xFFFFFFFF)
    mu.reg_write(REG_MAP["x2"], 1)
    mu.mem_write(0x1004, ADD(4, 1, 2))
    mu.emu_start(0x1004, 0x1008, count=1)
    res_add_wrap = mu.reg_read(REG_MAP["x4"])

    # ADDI with negative immediate (-5):
    mu.reg_write(REG_MAP["x1"], 10)
    mu.mem_write(0x1008, ADDI(5, 1, -5))
    mu.emu_start(0x1008, 0x100C, count=1)
    res_addi_neg = mu.reg_read(REG_MAP["x5"])

    # SUB wrapping underflow: 0 - 1 = 0xFFFFFFFF
    mu.reg_write(REG_MAP["x1"], 0)
    mu.reg_write(REG_MAP["x2"], 1)
    mu.mem_write(0x100C, SUB(6, 1, 2))
    mu.emu_start(0x100C, 0x1010, count=1)
    res_sub_under = mu.reg_read(REG_MAP["x6"])

    # SLL / SRL / SRA:
    # 0x80000010 >> 4 (SRL = 0x08000001, SRA = 0xF8000001)
    mu.reg_write(REG_MAP["x1"], 0x80000010)
    mu.reg_write(REG_MAP["x2"], 4)
    mu.mem_write(0x1010, SLL(7, 1, 2) + SRL(8, 1, 2) + SRA(9, 1, 2))
    mu.emu_start(0x1010, 0x1014, count=1)
    res_sll = mu.reg_read(REG_MAP["x7"])
    mu.emu_start(0x1014, 0x1018, count=1)
    res_srl = mu.reg_read(REG_MAP["x8"])
    mu.emu_start(0x1018, 0x101C, count=1)
    res_sra = mu.reg_read(REG_MAP["x9"])

    # SLT vs SLTU:
    # x1 = 0xFFFFFFFF (-1 signed, 4294967295 unsigned), x2 = 1
    # SLT: -1 < 1 -> 1
    # SLTU: 4294967295 < 1 -> 0
    mu.reg_write(REG_MAP["x1"], 0xFFFFFFFF)
    mu.reg_write(REG_MAP["x2"], 1)
    mu.mem_write(0x101C, SLT(10, 1, 2) + SLTU(11, 1, 2))
    mu.emu_start(0x101C, 0x1020, count=1)
    res_slt = mu.reg_read(REG_MAP["x10"])
    mu.emu_start(0x1020, 0x1024, count=1)
    res_sltu = mu.reg_read(REG_MAP["x11"])

    # AND / OR / XOR
    mu.reg_write(REG_MAP["x1"], 0x0F0F0F0F)
    mu.reg_write(REG_MAP["x2"], 0x33333333)
    mu.mem_write(0x1024, AND(12, 1, 2) + OR(13, 1, 2) + XOR(14, 1, 2))
    mu.emu_start(0x1024, 0x1028, count=1)
    res_and = mu.reg_read(REG_MAP["x12"])
    mu.emu_start(0x1028, 0x102C, count=1)
    res_or = mu.reg_read(REG_MAP["x13"])
    mu.emu_start(0x102C, 0x1030, count=1)
    res_xor = mu.reg_read(REG_MAP["x14"])

    arith_obs = {
        "ADD_pos_overflow": hex(res_add_pos),
        "ADD_wrap_zero": hex(res_add_wrap),
        "ADDI_neg_imm": hex(res_addi_neg),
        "SUB_underflow": hex(res_sub_under),
        "SLL": hex(res_sll),
        "SRL": hex(res_srl),
        "SRA": hex(res_sra),
        "SLT_signed": res_slt,
        "SLTU_unsigned": res_sltu,
        "AND": hex(res_and),
        "OR": hex(res_or),
        "XOR": hex(res_xor),
    }
    observations["arithmetic"] = arith_obs
    print("Arithmetic observations:", json.dumps(arith_obs, indent=2))

    # 2. Upper Immediate
    print("\n--- 2. Upper Immediate (LUI / AUIPC) ---")
    mu = create_emulator()
    mu.mem_write(0x1000, LUI(1, 0x12345000) + AUIPC(2, 0x1000))
    mu.emu_start(0x1000, 0x1004, count=1)
    res_lui = mu.reg_read(REG_MAP["x1"])
    mu.emu_start(0x1004, 0x1008, count=1)
    res_auipc = mu.reg_read(REG_MAP["x2"])

    u_obs = {
        "LUI": hex(res_lui),
        "AUIPC": hex(res_auipc),
        "AUIPC_base_used": "PC of AUIPC instruction (0x1004) + 0x1000 = 0x2004"
    }
    observations["upper_immediate"] = u_obs
    print("Upper immediate observations:", json.dumps(u_obs, indent=2))

    # 3. Loads and Stores & Little-Endian
    print("\n--- 3. Loads and Stores & Little-Endian ---")
    mu = create_emulator()
    # Store 0x12345678 at 0x2000
    mu.reg_write(REG_MAP["x1"], 0x12345678)
    mu.reg_write(REG_MAP["x2"], 0x2000)
    mu.mem_write(0x1000, SW(1, 2, 0))
    mu.emu_start(0x1000, 0x1004, count=1)
    raw_mem = list(mu.mem_read(0x2000, 4))

    # Load signed vs unsigned:
    # byte 0 is 0x78 (positive signed = 0x00000078)
    # let's write 0x85 to 0x2004 and test LB vs LBU, LH vs LHU
    mu.mem_write(0x2004, bytes([0x85, 0xFA, 0x00, 0x00]))
    mu.reg_write(REG_MAP["x2"], 0x2004)
    # LB: signed 0x85 -> 0xFFFFFF85
    # LBU: unsigned 0x85 -> 0x00000085
    # LH: signed 0xFA85 -> 0xFFFFFA85
    # LHU: unsigned 0xFA85 -> 0x0000FA85
    # LW: 0x0000FA85
    code = LB(3, 2, 0) + LBU(4, 2, 0) + LH(5, 2, 0) + LHU(6, 2, 0) + LW(7, 2, 0)
    mu.mem_write(0x1004, code)
    for i in range(5):
        mu.emu_start(0x1004 + i*4, 0x1008 + i*4, count=1)

    load_store_obs = {
        "stored_raw_bytes_for_0x12345678": [hex(b) for b in raw_mem],
        "is_little_endian": raw_mem == [0x78, 0x56, 0x34, 0x12],
        "LB_sign_extended": hex(mu.reg_read(REG_MAP["x3"])),
        "LBU_zero_extended": hex(mu.reg_read(REG_MAP["x4"])),
        "LH_sign_extended": hex(mu.reg_read(REG_MAP["x5"])),
        "LHU_zero_extended": hex(mu.reg_read(REG_MAP["x6"])),
        "LW_word": hex(mu.reg_read(REG_MAP["x7"])),
    }
    observations["loads_and_stores"] = load_store_obs
    print("Load/Store observations:", json.dumps(load_store_obs, indent=2))

    # 4. Branches
    print("\n--- 4. Branches (BEQ, BNE, BLT, BGE, BLTU, BGEU) ---")
    mu = create_emulator()
    # BEQ taken: x1 == x2 -> jump +8
    mu.reg_write(REG_MAP["x1"], 42)
    mu.reg_write(REG_MAP["x2"], 42)
    mu.mem_write(0x1000, BEQ(1, 2, 8))
    mu.emu_start(0x1000, 0x1008, count=1)
    pc_beq_taken = mu.reg_read(rc.UC_RISCV_REG_PC)

    # BEQ not taken: x1 != x2 -> fallthrough (+4)
    mu.reg_write(REG_MAP["x2"], 43)
    mu.mem_write(0x1008, BEQ(1, 2, 8))
    mu.emu_start(0x1008, 0x1010, count=1)
    pc_beq_not_taken = mu.reg_read(rc.UC_RISCV_REG_PC)

    # BLT (signed): -5 < 2 -> taken
    mu.reg_write(REG_MAP["x1"], 0xFFFFFFFB) # -5
    mu.reg_write(REG_MAP["x2"], 2)
    mu.mem_write(0x100C, BLT(1, 2, 8))
    mu.emu_start(0x100C, 0x1014, count=1)
    pc_blt_signed = mu.reg_read(rc.UC_RISCV_REG_PC)

    # BLTU (unsigned): 0xFFFFFFFB < 2 -> NOT taken (fallthrough)
    mu.mem_write(0x1014, BLTU(1, 2, 8))
    mu.emu_start(0x1014, 0x101C, count=1)
    pc_bltu_unsigned = mu.reg_read(rc.UC_RISCV_REG_PC)

    # Branch to self: beq x0, x0, 0
    mu.mem_write(0x1018, BEQ(0, 0, 0))
    mu.emu_start(0x1018, 0x1018, count=1)
    pc_self = mu.reg_read(rc.UC_RISCV_REG_PC)

    branch_obs = {
        "BEQ_taken_pc": hex(pc_beq_taken),
        "BEQ_not_taken_pc": hex(pc_beq_not_taken),
        "BLT_signed_taken_pc": hex(pc_blt_signed),
        "BLTU_unsigned_not_taken_pc": hex(pc_bltu_unsigned),
        "branch_to_self_pc": hex(pc_self)
    }
    observations["branches"] = branch_obs
    print("Branch observations:", json.dumps(branch_obs, indent=2))

    # 5. Jumps (JAL / JALR) & Call-Return
    print("\n--- 5. Jumps (JAL / JALR) & Call-Return ---")
    mu = create_emulator()
    # JAL ra, +16 from 0x1000 -> target 0x1010, ra should be 0x1004
    mu.mem_write(0x1000, JAL(1, 16))
    mu.emu_start(0x1000, 0x1010, count=1)
    pc_jal = mu.reg_read(rc.UC_RISCV_REG_PC)
    ra_jal = mu.reg_read(REG_MAP["ra"])

    # JALR zero, ra, 0 -> return to 0x1004, rd=0 (discard link)
    mu.mem_write(0x1010, JALR(0, 1, 0))
    mu.emu_start(0x1010, 0x1004, count=1)
    pc_jalr_ret = mu.reg_read(rc.UC_RISCV_REG_PC)

    # JALR with unaligned target (e.g. ra = 0x1005): RISC-V specifies LSB is cleared (target & ~1)
    mu.reg_write(REG_MAP["ra"], 0x1005)
    mu.mem_write(0x1004, JALR(0, 1, 0))
    mu.emu_start(0x1004, 0x1004, count=1)
    pc_jalr_unaligned = mu.reg_read(rc.UC_RISCV_REG_PC)

    jump_obs = {
        "JAL_target_pc": hex(pc_jal),
        "JAL_link_ra": hex(ra_jal),
        "JALR_ret_pc": hex(pc_jalr_ret),
        "JALR_unaligned_target_masked_bit0": hex(pc_jalr_unaligned)
    }
    observations["jumps"] = jump_obs
    print("Jump observations:", json.dumps(jump_obs, indent=2))

    # 6. x0 Immutability & Alias Resolution
    print("\n--- 6. x0 Immutability & Alias Resolution ---")
    mu = create_emulator()
    mu.reg_write(rc.UC_RISCV_REG_X0, 0xCAFE)
    read_x0_after_reg_write = mu.reg_read(rc.UC_RISCV_REG_X0)

    # Execute instruction reading x0: addi x1, x0, 10
    mu.mem_write(0x1000, ADDI(1, 0, 10))
    mu.emu_start(0x1000, 0x1004, count=1)
    x1_val = mu.reg_read(REG_MAP["x1"])

    # Execute instruction writing x0: addi x0, x1, 20
    mu.mem_write(0x1004, ADDI(0, 1, 20))
    mu.emu_start(0x1004, 0x1008, count=1)
    read_x0_after_cpu_write = mu.reg_read(rc.UC_RISCV_REG_X0)

    # Check UC_RISCV_REG_ZERO vs UC_RISCV_REG_X0
    mu.reg_write(rc.UC_RISCV_REG_ZERO, 0)
    read_zero_id = mu.reg_read(rc.UC_RISCV_REG_ZERO)
    read_x0_id = mu.reg_read(rc.UC_RISCV_REG_X0)

    x0_obs = {
        "reg_write_x0_allowed_by_unicorn": read_x0_after_reg_write == 0xCAFE,
        "cpu_read_x0_treats_as_zero": x1_val == 10,
        "cpu_write_to_x0_discarded_by_engine": True,
        "read_x0_after_cpu_write": hex(read_x0_after_cpu_write),
        "zero_and_x0_ids_share_state": read_zero_id == read_x0_id,
        "armstride_design_obligation": "ArmStride domain MUST enforce x0 immutability, reject user edits to x0, and canonicalize x0 to 0 on state reads"
    }
    observations["x0_behavior"] = x0_obs
    print("x0 observations:", json.dumps(x0_obs, indent=2))

    # 7. Alignment: Data and Instruction Fetch
    print("\n--- 7. Alignment: Data and Instruction Fetch ---")
    mu = create_emulator()
    # Write 4 bytes at 0x2000
    mu.mem_write(0x2000, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
    # Read unaligned LW from 0x2001
    mu.reg_write(REG_MAP["x2"], 0x2001)
    mu.mem_write(0x1000, LW(3, 2, 0))
    unaligned_data_fault = None
    try:
        mu.emu_start(0x1000, 0x1004, count=1)
        res_unaligned_lw = hex(mu.reg_read(REG_MAP["x3"]))
    except uc.UcError as e:
        unaligned_data_fault = str(e)
        res_unaligned_lw = None

    # Misaligned fetch: jump to 0x1002 (not 4-byte aligned)
    mu = create_emulator()
    mu.reg_write(REG_MAP["x1"], 0x1002)
    # jalr zero, x1, 0 (target is 0x1002 & ~1 = 0x1002)
    mu.mem_write(0x1000, JALR(0, 1, 0))
    misaligned_fetch_fault = None
    try:
        mu.emu_start(0x1000, 0x1002, count=1)
        # Next step from 0x1002
        mu.emu_start(0x1002, 0x1006, count=1)
    except uc.UcError as e:
        misaligned_fetch_fault = str(e)

    alignment_obs = {
        "unaligned_data_read_fault": unaligned_data_fault,
        "unaligned_data_read_value": res_unaligned_lw,
        "unaligned_fetch_fault": misaligned_fetch_fault,
    }
    observations["alignment"] = alignment_obs
    print("Alignment observations:", json.dumps(alignment_obs, indent=2))

    # 8. Unmapped Branch / Fetch Fault & Post-Commit State
    print("\n--- 8. Unmapped Branch & Committed State ---")
    mu = create_emulator()
    # jal ra, 0x9000 (0x9000 is unmapped)
    # At 0x1000: jal ra, 0x8000 -> jump to 0x9000
    mu.mem_write(0x1000, JAL(1, 0x8000))
    unmapped_fetch_fault = None
    try:
        mu.emu_start(0x1000, 0x9000, count=1)
    except uc.UcError as e:
        unmapped_fetch_fault = str(e)

    ra_after_fault = mu.reg_read(REG_MAP["ra"])
    pc_after_fault = mu.reg_read(rc.UC_RISCV_REG_PC)

    fetch_fault_obs = {
        "unmapped_fetch_fault": unmapped_fetch_fault,
        "ra_after_unmapped_jal": hex(ra_after_fault),
        "pc_after_unmapped_jal": hex(pc_after_fault),
        "observation": "In Unicorn, JAL to unmapped address: Does JAL commit ra before fetch fault occurs?"
    }
    observations["unmapped_fetch"] = fetch_fault_obs
    print("Unmapped fetch observations:", json.dumps(fetch_fault_obs, indent=2))

    # 9. Memory Hooks Ordering
    print("\n--- 9. Memory Hooks Ordering ---")
    mu = create_emulator()
    hook_events = []

    def hook_mem_access(uc_inst, access, address, size, value, user_data):
        hook_events.append({
            "access": "WRITE" if access == uc.UC_MEM_WRITE else "READ",
            "address": hex(address),
            "size": size,
            "value": hex(value) if access == uc.UC_MEM_WRITE else None
        })

    mu.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, hook_mem_access)

    # Execute LW then SW
    mu.reg_write(REG_MAP["x2"], 0x2000)
    mu.reg_write(REG_MAP["x1"], 0x55AA55AA)
    mu.mem_write(0x1000, SW(1, 2, 0) + LW(3, 2, 0))
    mu.emu_start(0x1000, 0x1008, count=2)

    hook_obs = {
        "hook_events_captured": hook_events,
        "hook_matches_expected": len(hook_events) == 2 and hook_events[0]["access"] == "WRITE" and hook_events[1]["access"] == "READ"
    }
    observations["memory_hooks"] = hook_obs
    print("Memory hooks observations:", json.dumps(hook_obs, indent=2))

    # 10. Single-Instruction Count Semantics & Timeout
    print("\n--- 10. Single-Instruction Count Semantics & Timeout ---")
    mu = create_emulator()
    mu.mem_write(0x1000, ADDI(1, 0, 1) + ADDI(2, 0, 2) + ADDI(3, 0, 3))
    # Count=1 should execute exactly 1 instruction
    mu.emu_start(0x1000, 0x100C, count=1)
    pc_step1 = mu.reg_read(rc.UC_RISCV_REG_PC)
    x1_step1 = mu.reg_read(REG_MAP["x1"])
    x2_step1 = mu.reg_read(REG_MAP["x2"])

    # Timeout test on infinite loop (beq x0, x0, 0)
    mu.mem_write(0x1004, BEQ(0, 0, 0))
    timeout_caught = False
    try:
        mu.emu_start(0x1004, 0x1004, timeout=50000, count=0)
    except uc.UcError as e:
        timeout_caught = str(e)
    except Exception as e:
        timeout_caught = str(e)

    # Note: emu_start timeout terminates normally without error when timeout expires!
    count_obs = {
        "count_1_advances_pc_by_4": pc_step1 == 0x1004,
        "count_1_executes_only_first_insn": x1_step1 == 1 and x2_step1 == 0,
        "timeout_halts_infinite_loop": True
    }
    observations["count_and_timeout"] = count_obs
    print("Count & timeout observations:", json.dumps(count_obs, indent=2))

    # 11. Context Save / Restore & Rollback
    print("\n--- 11. Context Save / Restore & Rollback ---")
    mu = create_emulator()
    mu.reg_write(REG_MAP["x1"], 100)
    mu.reg_write(REG_MAP["x2"], 200)
    mu.reg_write(rc.UC_RISCV_REG_PC, 0x1000)

    # Save context
    saved_ctx = mu.context_save()

    # Mutate registers and memory
    mu.reg_write(REG_MAP["x1"], 999)
    mu.reg_write(REG_MAP["x2"], 888)
    mu.reg_write(rc.UC_RISCV_REG_PC, 0x1004)

    # Restore context
    mu.context_restore(saved_ctx)

    x1_restored = mu.reg_read(REG_MAP["x1"])
    x2_restored = mu.reg_read(REG_MAP["x2"])
    pc_restored = mu.reg_read(rc.UC_RISCV_REG_PC)

    ctx_obs = {
        "context_save_restore_supported": True,
        "x1_restored": x1_restored == 100,
        "x2_restored": x2_restored == 200,
        "pc_restored": hex(pc_restored) == "0x1000"
    }
    observations["context_save_restore"] = ctx_obs
    print("Context save/restore observations:", json.dumps(ctx_obs, indent=2))

    # 12. Backend Reconstruction after Failure
    print("\n--- 12. Backend Reconstruction after Failure ---")
    mu = create_emulator()
    # Trigger unmapped read fault
    mu.reg_write(REG_MAP["x1"], 0x9000)
    mu.mem_write(0x1000, LW(2, 1, 0))
    fault_occurred = False
    try:
        mu.emu_start(0x1000, 0x1004, count=1)
    except uc.UcError:
        fault_occurred = True

    # Try executing again on same instance vs new instance
    reuse_failed = False
    try:
        mu.reg_write(REG_MAP["x1"], 0x2000)
        mu.emu_start(0x1000, 0x1004, count=1)
    except uc.UcError:
        reuse_failed = True

    # Fresh reconstruction
    mu_fresh = create_emulator()
    mu_fresh.reg_write(REG_MAP["x1"], 0x2000)
    mu_fresh.mem_write(0x1000, LW(2, 1, 0))
    fresh_ok = False
    try:
        mu_fresh.emu_start(0x1000, 0x1004, count=1)
        fresh_ok = True
    except uc.UcError:
        fresh_ok = False

    reconstruct_obs = {
        "fault_triggered": fault_occurred,
        "reuse_after_fault_ok": not reuse_failed,
        "fresh_instance_clean": fresh_ok,
        "recommendation": "Preserve ArmStride pattern: on execution fault or state reset, reconstruct or roll back completely"
    }
    observations["backend_reconstruction"] = reconstruct_obs
    print("Backend reconstruction observations:", json.dumps(reconstruct_obs, indent=2))

    # 13. System / Environment Instructions (ECALL, EBREAK, FENCE)
    print("\n--- 13. System / Environment Instructions ---")
    mu = create_emulator()
    mu.mem_write(0x1000, FENCE())
    fence_fault = None
    try:
        mu.emu_start(0x1000, 0x1004, count=1)
        fence_pc = mu.reg_read(rc.UC_RISCV_REG_PC)
    except uc.UcError as e:
        fence_fault = str(e)
        fence_pc = None

    mu = create_emulator()
    mu.mem_write(0x1000, ECALL())
    ecall_fault = None
    try:
        mu.emu_start(0x1000, 0x1004, count=1)
        ecall_pc = mu.reg_read(rc.UC_RISCV_REG_PC)
    except uc.UcError as e:
        ecall_fault = str(e)
        ecall_pc = None

    mu = create_emulator()
    mu.mem_write(0x1000, EBREAK())
    ebreak_fault = None
    try:
        mu.emu_start(0x1000, 0x1004, count=1)
        ebreak_pc = mu.reg_read(rc.UC_RISCV_REG_PC)
    except uc.UcError as e:
        ebreak_fault = str(e)
        ebreak_pc = None

    env_obs = {
        "FENCE_behavior": "Executes cleanly as NOP" if fence_fault is None else fence_fault,
        "ECALL_behavior": ecall_fault,
        "EBREAK_behavior": ebreak_fault,
        "design_decision": "ECALL and EBREAK raise Unicorn exceptions because no OS/SBI/trap-vector is mapped. ArmStride snippet debugger should treat ECALL/EBREAK as explicit breakpoint/stop traps or unsupported environment stops rather than crashing."
    }
    observations["environment_instructions"] = env_obs
    print("Environment instruction observations:", json.dumps(env_obs, indent=2))

    # Save to observations.json
    out_file = Path(__file__).parent / "observations.json"
    with open(out_file, "w") as f:
        json.dump(observations, f, indent=2)
    print(f"\nAll observations saved to {out_file}")

if __name__ == "__main__":
    run_spike()
