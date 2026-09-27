# RV32I Arithmetic Loop & Branch Example
# Demonstrates register arithmetic, pseudo-instructions (li), local labels, and branch condition (blt)

li a0, 0          # sum = 0
li a1, 10         # limit = 10
li a2, 1          # step = 1

loop:
    add a0, a0, a2    # sum += step
    addi a2, a2, 1    # step += 1
    blt a2, a1, loop  # if step < limit goto loop

ebreak            # Trap halt: breakpoint_trap
