import threading
import time
import pytest
from fastapi.testclient import TestClient

from armstride.app import create_app
from armstride.domain.models import DomainError
from armstride.parser import parse
from armstride.simulation.session import SimulationSession


def test_session_breakpoints_crud_and_persistence():
    source = """    $a
    0x00008000:    e3a00001    ....    MOV      r0,#1
    0x00008004:    e3a01002    ....    MOV      r1,#2
    $d
    0x00008008:    12345678    .4Vx    DCD      0x12345678
"""
    parsed = parse(source, mode="arm", format="fromelf")
    assert parsed.load_success
    session = SimulationSession()
    try:
        session.load(parsed.program)

        # 1. Add valid breakpoint
        bp = session.add_breakpoint(0x8004)
        assert bp.address == 0x8004
        assert bp.mode == "arm"
        assert len(session.list_breakpoints()) == 1

        # 2. Reject breakpoint on data region
        with pytest.raises(DomainError) as exc_info:
            session.add_breakpoint(0x8008)
        assert exc_info.value.code == "invalid_breakpoint"

        # 3. Reject breakpoint on unaligned address
        with pytest.raises(DomainError) as exc_info:
            session.add_breakpoint(0x8001)
        assert exc_info.value.code == "invalid_breakpoint"

        # 4. Reject breakpoint on unloaded address
        with pytest.raises(DomainError) as exc_info:
            session.add_breakpoint(0x9000)
        assert exc_info.value.code == "invalid_breakpoint"

        # 5. Reject mode mismatch
        with pytest.raises(DomainError) as exc_info:
            session.add_breakpoint(0x8000, mode="thumb")
        assert exc_info.value.code == "invalid_breakpoint"

        # 6. Breakpoints persist across manual edits and reset
        session.set_register("r0", 99)
        assert len(session.list_breakpoints()) == 1
        session.reset()
        assert len(session.list_breakpoints()) == 1

        # 7. Breakpoints persist across single Step
        step = session.step()
        assert step["status"] == "executed"
        assert len(session.list_breakpoints()) == 1

        # 8. Remove breakpoint
        assert session.remove_breakpoint(0x8004) is True
        assert session.remove_breakpoint(0x8004) is False
        assert len(session.list_breakpoints()) == 0

        # 9. Replacement load clears all breakpoints
        session.add_breakpoint(0x8000)
        assert len(session.list_breakpoints()) == 1
        session.load(parsed.program)
        assert len(session.list_breakpoints()) == 0
    finally:
        session.close()


def test_run_halts_at_breakpoint_and_supports_one_step_bypass():
    source = """    $a
    0x00008000:    e3a00001    ....    MOV      r0,#1
    0x00008004:    e3a01002    ....    MOV      r1,#2
    0x00008008:    e3a02003    ....    MOV      r2,#3
"""
    parsed = parse(source, mode="arm", format="fromelf")
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.add_breakpoint(0x8004)

        # Run 1: Should halt at 0x8004 before executing it
        res1 = session.run()
        assert res1["stop_reason"] == "breakpoint"
        assert res1["breakpoint_hit"] == 0x8004
        assert res1["steps_committed"] == 1
        assert session.runtime.registers["pc"] == 0x8004
        assert session.runtime.registers["r0"] == 1
        assert session.runtime.registers["r1"] == 0  # 0x8004 NOT yet executed!

        # Run 2: Resume past 0x8004 (one-step bypass). It should execute 0x8004 and 0x8008, then stop at pc_not_loaded
        res2 = session.run()
        assert res2["stop_reason"] == "pc_not_loaded"
        assert res2["steps_committed"] == 2
        assert session.runtime.registers["r1"] == 2
        assert session.runtime.registers["r2"] == 3
        assert session.runtime.registers["pc"] == 0x800c
    finally:
        session.close()


def test_run_breakpoint_in_loop_rehalts():
    # Loop that decrements r0 until 0:
    # 8000: sub r0, r0, #1
    # 8004: cmp r0, #0
    # 8008: bne 0x8000
    source = """    $a
    0x00008000:    e2400001    ....    SUB      r0,r0,#1
    0x00008004:    e3500000    ..P.    CMP      r0,#0
    0x00008008:    1afffffc    ....    BNE      0x00008000
"""
    parsed = parse(source, mode="arm", format="fromelf")
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("r0", 3)
        session.add_breakpoint(0x8000)

        # Initially at 0x8000 (breakpoint). Run 1 should bypass once, loop around, and halt at 0x8000 again!
        res1 = session.run()
        assert res1["stop_reason"] == "breakpoint"
        assert res1["breakpoint_hit"] == 0x8000
        assert session.runtime.registers["r0"] == 2  # decremented once
        assert session.runtime.registers["pc"] == 0x8000

        # Run 2: bypass once, loop around, halt again
        res2 = session.run()
        assert res2["stop_reason"] == "breakpoint"
        assert res2["breakpoint_hit"] == 0x8000
        assert session.runtime.registers["r0"] == 1

        # Run 3: bypass once, decrement to 0, branch not taken, terminates at pc_not_loaded (0x800c)
        res3 = session.run()
        assert res3["stop_reason"] == "pc_not_loaded"
        assert session.runtime.registers["r0"] == 0
        assert session.runtime.registers["pc"] == 0x800c
    finally:
        session.close()


def test_run_step_limit_and_time_limit():
    # Tight self-branch: 8000: b 0x8000
    source = """    $a
    0x00008000:    eafffffe    ....    B        0x00008000
"""
    parsed = parse(source, mode="arm", format="fromelf")
    session = SimulationSession()
    try:
        session.load(parsed.program)

        # 1. Step limit test
        res1 = session.run(max_steps=50)
        assert res1["stop_reason"] == "step_limit"
        assert res1["steps_committed"] == 50
        assert session.step_seq == 50

        # 2. Time limit test
        res2 = session.run(max_steps=1_000_000, timeout_seconds=0.1)
        assert res2["stop_reason"] == "time_limit"
        assert res2["steps_committed"] > 0
        assert session.step_seq > 50
    finally:
        session.close()


def test_run_stops_on_execution_fault_and_rolls_back():
    # 8000: mov r0, #42
    # 8004: ldr r1, [r2]  (r2 is 0x0 -> unmapped fault)
    source = """    $a
    0x00008000:    e3a0002a    *...    MOV      r0,#42
    0x00008004:    e5921000    ....    LDR      r1,[r2]
"""
    parsed = parse(source, mode="arm", format="fromelf")
    session = SimulationSession()
    try:
        session.load(parsed.program)
        session.set_register("r2", 0x0)  # unmapped

        res = session.run()
        assert res["stop_reason"] == "memory_fault"
        assert res["steps_committed"] == 1
        assert session.step_seq == 1
        assert session.runtime.registers["r0"] == 42
        assert session.runtime.registers["pc"] == 0x8004  # rolled back to before failed LDR
        assert session.runtime.register_origins["r1"] == "default"
    finally:
        session.close()


def test_api_run_and_concurrent_stop():
    app = create_app()
    with TestClient(app, base_url="http://localhost") as client:
        # Create session
        res = client.post("/api/sessions", json={})
        assert res.status_code == 201
        sid = res.json()["session_id"]

        # Load infinite loop: B 0x1000
        load_res = client.post(f"/api/sessions/{sid}/program", json={
            "input_kind": "assembly",
            "text": "loop:\n  b loop",
            "base_address": 0x1000,
            "mode": "arm"
        })
        assert load_res.status_code == 200

        # Add breakpoint via API
        bp_res = client.post(f"/api/sessions/{sid}/breakpoints", json={"address": 0x1000})
        assert bp_res.status_code == 201
        assert bp_res.json() == {"address": 0x1000, "mode": "arm"}

        # List breakpoints via API
        list_res = client.get(f"/api/sessions/{sid}/breakpoints")
        assert list_res.status_code == 200
        assert list_res.json() == [{"address": 0x1000, "mode": "arm"}]

        # State should include breakpoints
        state_res = client.get(f"/api/sessions/{sid}/state")
        assert state_res.status_code == 200
        assert state_res.json()["breakpoints"] == [{"address": 0x1000, "mode": "arm"}]

        # Remove breakpoint
        del_res = client.delete(f"/api/sessions/{sid}/breakpoints/4096")
        assert del_res.status_code == 204
        assert client.get(f"/api/sessions/{sid}/breakpoints").json() == []

        # Start concurrent Run and Stop test
        # We start a run with 100,000 steps and 5.0 seconds timeout in a background thread
        run_output = {}

        def background_run():
            run_output["response"] = client.post(f"/api/sessions/{sid}/run", json={
                "step_limit": 100_000,
                "time_limit_ms": 5000
            })

        t = threading.Thread(target=background_run)
        t.start()

        # Give the thread a short moment to start executing steps
        time.sleep(0.05)

        # Concurrent stop request
        stop_res = client.post(f"/api/sessions/{sid}/stop", json={})
        assert stop_res.status_code == 200
        assert stop_res.json() == {"signaled": True}

        t.join(timeout=2.0)
        assert not t.is_alive(), "Background run thread should have halted after stop signal"

        resp = run_output["response"]
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_result"]["stop_reason"] == "user_stop"
        assert data["run_result"]["steps_committed"] > 0
        assert data["state"]["pc"] == 0x1000
