"""Native HTTP workflow checks using fixed independent ARM/Thumb expectations."""

from fastapi.testclient import TestClient
import pytest

from armstride.app import create_app

pytestmark = pytest.mark.native


@pytest.mark.parametrize('mode,source,listing', [
    ('arm', 'mov r0,#5\nadd r0,r0,#1', '0x1000: E3A00005 MOV r0,#5\n0x1004: E2800001 ADD r0,r0,#1'),
    ('thumb', 'movs r0,#5\nadds r0,#1', '0x1000: 2005 MOVS r0,#5\n0x1002: 3001 ADDS r0,#1'),
])
@pytest.mark.parametrize('input_kind', ['assembly', 'disassembly'])
def test_native_load_inject_step_reset(mode, source, listing, input_kind):
    with TestClient(create_app(), base_url='http://127.0.0.1') as client:
        session_id = client.post('/api/sessions', json={}).json()['session_id']
        path = '/api/sessions/' + session_id
        body = dict(input_kind=input_kind, mode=mode, text=source if input_kind == 'assembly' else listing)
        body.update({'base_address': 4096} if input_kind == 'assembly' else {'format': 'generic'})
        assert client.post(path + '/program', json=body).status_code == 200
        assert client.put(path + '/registers/r0', json={'value': 7}).status_code == 200
        first = client.post(path + '/step', json={}).json()
        assert first['result']['register_changes']['r0'] == dict(before=7, after=5)
        second = client.post(path + '/step', json={}).json()
        assert second['state']['registers']['r0'] == dict(value=6, origin='execution')
        assert second['state']['step_seq'] == 2
        assert second['state']['status'] == 'stopped'
        assert second['result'] == second['state']['last_step']
        assert second['result']['stop_reason'] == 'pc_not_loaded'
        failed = client.post(path + '/step', json={}).json()
        assert failed['result']['error']['code'] == 'invalid_pc'
        assert failed['state']['step_seq'] == 2
        reset = client.post(path + '/reset', json={}).json()
        assert reset['registers']['r0'] == dict(value=7, origin='user')
        assert reset['pc'] == reset['baseline_pc'] == 4096
        assert reset['step_seq'] == 2 and reset['last_step'] is None
        # Replacement retry explicitly discards edits but never resets the counter.
        replaced = client.post(path + '/program', json=body).json()['state']
        assert replaced['registers']['r0']['value'] == 0
        assert replaced['step_seq'] == 2
        assert client.delete(path).status_code == 204


def test_native_fault_repair_and_failed_replacement():
    with TestClient(create_app(), base_url='http://localhost') as client:
        path = '/api/sessions/' + client.post('/api/sessions', json={}).json()['session_id']
        body = dict(input_kind='disassembly', text='0x1000: E5910000 LDR r0,[r1]', mode='arm', format='generic')
        assert client.post(path + '/program', json=body).status_code == 200
        assert client.put(path + '/registers/r1', json={'value': 8192}).status_code == 200
        fault = client.post(path + '/step', json={}).json()
        assert fault['state']['status'] == 'stopped'
        assert fault['result']['stop_reason'] == 'memory_fault'
        assert fault['result']['memory_writes'] == []
        assert fault['result']['error']['restored'] is True
        before = client.get(path + '/state').json()
        assert client.post(path + '/program', json=body | {'text': 'broken'}).status_code == 422
        assert client.get(path + '/state').json() == before
        assert client.put(path + '/memory', json={'address': 8192, 'bytes': '78563412'}).status_code == 200
        step = client.post(path + '/step', json={}).json()
        assert step['state']['registers']['r0']['value'] == 0x12345678
        assert step['result']['memory_reads'] == [dict(address=8192, size=4, bytes='78563412')]
        assert step['state']['step_seq'] == 1
        client.post(path + '/reset', json={})
        assert client.get(path + '/memory?address=8192&length=4').json()['cells'] == [
            dict(value=value, origin='user') for value in (0x78, 0x56, 0x34, 0x12)]
