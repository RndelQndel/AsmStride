"""HTTP API tests for Stage P2 features: ELF loading, symbols, watchpoints, step-back."""

import base64
from fastapi.testclient import TestClient
import pytest

from armstride.app import create_app
from tests.elf.elf_builder import make_elf


def test_api_elf_loading_and_symbols():
    ARM_CODE = bytes.fromhex("2a00a0e3 1eff2fe1")  # MOV R0, #42; BX LR
    elf_bytes = make_elf(
        code=ARM_CODE,
        entry_point=0x8000,
        mapping_symbols=[(0x8000, 'arm')],
        symbols=[{'name': 'main', 'address': 0x8000, 'size': 8, 'type': 'func', 'bind': 'global'}],
    )
    elf_b64 = base64.b64encode(elf_bytes).decode("ascii")

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        # 1. Load ELF via API
        resp = client.post(path + "/program", json={"input_kind": "elf", "content_base64": elf_b64})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["program"]["instructions"][0]["address"] == 0x8000

        # 2. Query symbols
        sym_resp = client.get(path + "/symbols")
        assert sym_resp.status_code == 200
        sym_data = sym_resp.json()
        sym_names = [s["name"] for s in sym_data["symbols"]]
        assert "main" in sym_names


def test_api_watchpoints_crud_and_observation():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        # Load program: 0x1000 LDR R0, [R1]
        prog_body = {
            "input_kind": "disassembly",
            "text": "0x1000: E5910000 LDR R0, [R1]\n0x1004: E1A00000 NOP\n",
            "mode": "arm",
            "format": "generic",
        }
        assert client.post(path + "/program", json=prog_body).status_code == 200

        # Add Watchpoint (returns 201 Created)
        wp_resp = client.post(path + "/watchpoints", json={"address": 0x20000000, "length": 4, "kind": "read"})
        assert wp_resp.status_code == 201
        wp = wp_resp.json()
        assert wp["address"] == 0x20000000
        assert wp["length"] == 4
        assert wp["kind"] == "read"

        # List Watchpoints
        list_resp = client.get(path + "/watchpoints")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # Set up memory and register
        client.put(path + "/registers/r1", json={"value": 0x20000000})
        client.put(path + "/memory", json={"address": 0x20000000, "zero_fill_length": 4})

        # Step: triggers read watchpoint hit
        step_resp = client.post(path + "/step", json={})
        assert step_resp.status_code == 200
        step_data = step_resp.json()
        assert len(step_data["result"]["watchpoint_hits"]) == 1
        assert step_data["result"]["watchpoint_hits"][0]["access_type"] == "read"

        # Delete Watchpoint
        del_resp = client.delete(path + "/watchpoints/536870912")  # 0x20000000
        assert del_resp.status_code == 204
        assert len(client.get(path + "/watchpoints").json()) == 0


def test_api_step_back_endpoint():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        path = f"/api/sessions/{session_id}"

        prog_body = {
            "input_kind": "disassembly",
            "text": "0x1000: E3A0002A MOV R0, #42\n0x1004: E1A00000 NOP\n",
            "mode": "arm",
            "format": "generic",
        }
        assert client.post(path + "/program", json=prog_body).status_code == 200

        # Initial step-back fails (history empty -> 409 Conflict)
        empty_resp = client.post(path + "/step-back", json={})
        assert empty_resp.status_code == 409

        # Step forward
        assert client.post(path + "/step", json={}).status_code == 200
        state = client.get(path + "/state").json()
        assert state["registers"]["r0"]["value"] == 42
        assert state["pc"] == 0x1004

        # Step back
        back_resp = client.post(path + "/step-back", json={})
        assert back_resp.status_code == 200
        back_data = back_resp.json()
        assert back_data["status"] == "ok"
        assert back_data["state"]["registers"]["r0"]["value"] == 0
        assert back_data["state"]["pc"] == 0x1000
