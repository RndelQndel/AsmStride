.syntax unified
.cpu cortex-a15
.arm
.text
.global _start
_start:
.org 0
mov r0,#5
.org 4
b .-4
