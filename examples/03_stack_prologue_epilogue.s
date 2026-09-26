.syntax unified
.arm

// Scenario: Stack inspection with scratch stack
// Observe SP adjustment, stack word writes, and register restoration.
push {r4, r5, lr}
sub sp, sp, #8

mov r4, #0x42
str r4, [sp, #0]
mov r5, #0x84
str r5, [sp, #4]

ldr r0, [sp, #0]
ldr r1, [sp, #4]
add sp, sp, #8
pop {r4, r5, pc}
