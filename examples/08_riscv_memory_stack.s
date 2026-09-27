# RV32I Stack Operations & Sign/Zero Extension Example
# Demonstrates stack frame allocation, store/load variants (sb/lb/lbu/sw/lw), and ABI aliases

addi sp, sp, -16      # Allocate stack frame (16 bytes)

li t0, 0x000080F0     # 32-bit immediate with high bit set in byte/halfword
sw t0, 0(sp)          # Store 32-bit word

lb a0, 0(sp)          # Load byte (sign-extended): 0xF0 -> 0xFFFFFFF0
lbu a1, 0(sp)         # Load byte unsigned (zero-extended): 0xF0 -> 0x000000F0

lh a2, 0(sp)          # Load halfword (sign-extended): 0x80F0 -> 0xFFFF80F0
lhu a3, 0(sp)         # Load halfword unsigned (zero-extended): 0x80F0 -> 0x000080F0

lw a4, 0(sp)          # Load 32-bit word: 0x000080F0

addi sp, sp, 16       # Deallocate stack frame
ret                   # jalr zero, 0(ra)
