"""Fail native-test collection cleanly when the host cannot initialize Unicorn."""

import signal
import subprocess
import sys

import pytest

NATIVE_PROBE = '''
import faulthandler
faulthandler.disable()
import unicorn as uc
from unicorn import arm_const as arm
engine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
engine.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A15)
engine.mem_map(0x1000, 0x1000)
engine.mem_write(0x1000, bytes.fromhex("0100a0e3"))
engine.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
engine.emu_start(0x1000, 0x1004, timeout=1000000, count=1)
if engine.reg_read(arm.UC_ARM_REG_R0) != 1 or engine.query(uc.UC_QUERY_TIMEOUT):
    raise RuntimeError("Native execution probe did not complete correctly.")
'''


def native_failure(completed):
    if completed.returncode < 0:
        return f'Native Unicorn probe terminated by {signal.Signals(-completed.returncode).name}.'
    return f'Native Unicorn probe failed (exit {completed.returncode}): {completed.stderr.strip()}'


def pytest_collection_finish(session):
    if session.config.option.collectonly or not any(test.get_closest_marker('native') for test in session.items):
        return
    try:
        completed = subprocess.run([sys.executable, '-c', NATIVE_PROBE],
                                   capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.exit('Native Unicorn probe timed out; native tests were not executed.', returncode=4)
    if completed.returncode:
        pytest.exit(native_failure(completed) + '\nNative tests were not executed. '
                    'Use a host that permits native Unicorn execution; '
                    'pytest without a path runs the independent unit suite.', returncode=4)
