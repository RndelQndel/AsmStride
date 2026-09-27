"""HTTP API tests for Stage P3 features: RV32I profile, x0 immutability, step, breakpoints, reset."""

from fastapi.testclient import TestClient

from armstride.app import create_app


def test_p3_api_load_and_profile_state():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        # 1. Load RV32I assembly program
        source = "addi a0, zero, 42\nadd a1, a0, a0\n"
        body = {
            "input_kind": "assembly",
            "text": source,
            "profile": "rv32i-le",
            "mode": "riscv32",
            "base_address": 0x1000,
        }
        resp = client.post(path + "/program", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Check program view
        assert data["program"]["profile"] == "rv32i-le"
        assert data["program"]["mode"] == "riscv32"
        assert len(data["program"]["instructions"]) == 2

        # Check state view: cpsr and flags must be None
        state = data["state"]
        assert state["profile"] == "rv32i-le"
        assert state["mode"] == "riscv32"
        assert state["cpsr"] is None
        assert state["flags"] is None

        # Check 32 registers present
        for i in range(32):
            assert f"x{i}" in state["registers"]
        # sp (x2) starts at top of stack (0x20100000)
        assert state["registers"]["x2"]["value"] == 0x20100000

        # Query GET /state
        st_resp = client.get(path + "/state")
        assert st_resp.status_code == 200
        st = st_resp.json()
        assert st["cpsr"] is None
        assert st["flags"] is None


def test_p3_api_x0_immutability_and_aliases():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        body = {
            "input_kind": "assembly",
            "text": "nop\n",
            "profile": "rv32i-le",
            "mode": "riscv32",
            "base_address": 0x1000,
        }
        assert client.post(path + "/program", json=body).status_code == 200

        # Rejection of writes to x0 via API with HTTP 422 x0_immutable (P3-AC-03, P3-AC-17)
        resp_x0 = client.put(path + "/registers/x0", json={"value": 10})
        assert resp_x0.status_code == 422
        assert resp_x0.json()["error"]["code"] == "x0_immutable"

        resp_zero = client.put(path + "/registers/zero", json={"value": 10})
        assert resp_zero.status_code == 422
        assert resp_zero.json()["error"]["code"] == "x0_immutable"

        # Rejection of CPSR on RISC-V session
        resp_cpsr = client.put(path + "/registers/cpsr", json={"value": 16})
        assert resp_cpsr.status_code == 422

        # Modification via ABI alias
        resp_a0 = client.put(path + "/registers/a0", json={"value": 77})
        assert resp_a0.status_code == 200
        assert resp_a0.json()["registers"]["x10"]["value"] == 77


def test_p3_api_step_and_deltas():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        body = {
            "input_kind": "assembly",
            "text": "addi a0, zero, 42\naddi x0, a0, 5\n",
            "profile": "rv32i-le",
            "mode": "riscv32",
            "base_address": 0x1000,
        }
        assert client.post(path + "/program", json=body).status_code == 200

        # Step 1: addi a0, zero, 42
        step1 = client.post(path + "/step", json={}).json()
        result1 = step1["result"]
        assert result1["status"] == "executed"
        assert result1["cpsr_change"] is None
        assert result1["flag_changes"] == {}
        assert "x10" in result1["register_changes"]
        assert result1["register_changes"]["x10"]["after"] == 42
        assert step1["state"]["registers"]["x10"]["value"] == 42

        # Step 2: addi x0, a0, 5 -> x0 remains 0, no x0 in register_changes
        step2 = client.post(path + "/step", json={}).json()
        result2 = step2["result"]
        assert result2["status"] == "executed"
        assert "x0" not in result2["register_changes"]
        assert "zero" not in result2["register_changes"]
        assert step2["state"]["registers"]["x0"]["value"] == 0


def test_p3_api_breakpoints_alignment_and_run():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        body = {
            "input_kind": "assembly",
            "text": "addi a0, zero, 1\naddi a0, a0, 2\naddi a0, a0, 3\n",
            "profile": "rv32i-le",
            "mode": "riscv32",
            "base_address": 0x1000,
        }
        assert client.post(path + "/program", json=body).status_code == 200

        # 4-byte aligned breakpoint succeeds
        bp_resp = client.post(path + "/breakpoints", json={"address": 0x1004})
        assert bp_resp.status_code == 201

        # Unaligned breakpoint fails with 422
        bp_bad = client.post(path + "/breakpoints", json={"address": 0x1002})
        assert bp_bad.status_code == 422
        assert bp_bad.json()["error"]["code"] == "invalid_breakpoint"

        # Run to breakpoint
        run_resp = client.post(path + "/run", json={"step_limit": 10})
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["run_result"]["stop_reason"] == "breakpoint"
        assert run_data["run_result"]["breakpoint_hit"] == 0x1004
        assert run_data["state"]["registers"]["x10"]["value"] == 1


def test_p3_api_step_back_and_reset():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        body = {
            "input_kind": "assembly",
            "text": "addi a0, a0, 10\naddi a0, a0, 20\n",
            "profile": "rv32i-le",
            "mode": "riscv32",
            "base_address": 0x1000,
        }
        assert client.post(path + "/program", json=body).status_code == 200

        # User edit establishing baseline
        client.put(path + "/registers/a0", json={"value": 5})

        client.post(path + "/step", json={})
        assert client.get(path + "/state").json()["registers"]["x10"]["value"] == 15

        client.post(path + "/step", json={})
        assert client.get(path + "/state").json()["registers"]["x10"]["value"] == 35

        # Step back
        sb_resp = client.post(path + "/step-back", json={})
        assert sb_resp.status_code == 200
        assert sb_resp.json()["state"]["registers"]["x10"]["value"] == 15

        # Reset
        rst_resp = client.post(path + "/reset", json={})
        assert rst_resp.status_code == 200
        assert rst_resp.json()["registers"]["x10"]["value"] == 5
        assert rst_resp.json()["pc"] == 0x1000


def test_p3_trap_results_serialize_for_step_run_and_state():
    """Public schemas must accept trap values already emitted by the simulator."""
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        for instruction, reason in [("ecall", "environment_call"), ("ebreak", "breakpoint_trap")]:
            for action in ["step", "run"]:
                session_id = client.post("/api/sessions", json={}).json()["session_id"]
                path = f"/api/sessions/{session_id}"
                loaded = client.post(path + "/program", json={
                    "input_kind": "assembly", "text": instruction, "profile": "rv32i-le",
                    "mode": "riscv32", "base_address": 0x1000,
                })
                assert loaded.status_code == 200
                response = client.post(path + f"/{action}", json={})
                assert response.status_code == 200, response.text
                assert response.json()["state"]["last_step"]["stop_reason"] == reason
                state = client.get(path + "/state")
                assert state.status_code == 200
                assert state.json()["last_step"]["branch"]["kind"] == "trap"
                client.delete(path)
