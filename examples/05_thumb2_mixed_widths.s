.syntax unified
.thumb

// Scenario: Thumb 16-bit and 32-bit (Thumb-2) mixed encodings
// Mode: Thumb / Base address: 0x2000
// Observe 2-byte advances for 16-bit instructions and 4-byte advances for 32-bit instructions.
movs r0, #10
adds r1, r0, #5

// Thumb-2 32-bit instructions
movw r2, #0x1234
movt r2, #0x5678

// Conditional branch
cmp r1, #15
beq match

movs r3, #0
b done

match:
movs r3, #1

done:
bx lr
