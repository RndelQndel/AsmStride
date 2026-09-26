.syntax unified
.arm

// Scenario: Branch & Condition Flag Inspection
// Set r0 and r1 in UI, step through CMP, and observe N/Z/C/V and branch results.
cmp r0, r1
beq equal_target
bgt greater_target

less_target:
mov r2, #1
b done

equal_target:
mov r2, #2
b done

greater_target:
mov r2, #3

done:
bx lr
