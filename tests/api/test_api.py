"""HTTP contract/lifecycle tests with a scripted backend, not an ARM oracle."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

from fastapi.testclient import TestClient
import pytest

from armstride.api.boundary import MAX_REQUEST_BYTES
from armstride.api.sessions import IDLE_SECONDS, SessionRegistry
from armstride.app import create_app
from armstride.domain.models import DomainError
from armstride.simulation import SimulationSession
from armstride.simulation.state import ExecutionOutcome


class ScriptedBackend:
    def __init__(self, factory):
        self.factory = factory
        self.closed = False

    def execute_one(self, instruction, state):
        assert not self.closed
        self.factory.threads.append(get_ident())
        self.factory.started.set()
        assert self.factory.release.wait(5)
        if self.factory.error:
            raise self.factory.error
        return ExecutionOutcome(state, (), ())

    def close(self):
        self.closed = True


class BackendFactory:
    def __init__(self):
        self.created = []
        self.fail = False
        self.error = None
        self.threads = []
        self.started = Event()
        self.release = Event()
        self.release.set()

    def __call__(self, program, state):
        if self.fail:
            raise DomainError('backend_unavailable', 'Injected initialization failure.')
        backend = ScriptedBackend(self)
        self.created.append(backend)
        return backend


@pytest.fixture
def harness():
    factory = BackendFactory()
    now = [0.0]
    registry = SessionRegistry(lambda: SimulationSession(factory), clock=lambda: now[0])
    app = create_app(registry=registry)
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        yield client, factory, registry, now
    assert all(backend.closed for backend in factory.created)


def new_session(client):
    response = client.post('/api/sessions', json={})
    assert response.status_code == 201, response.text
    return '/api/sessions/' + response.json()['session_id']


def load(client, path, **changes):
    body = dict(input_kind='disassembly', mode='arm', format='generic',
                text='0x1000: EAFFFFFE B 0x1000')
    return client.post(path + '/program', json=body | changes)


def test_empty_limits_isolation_and_delete(harness):
    client, factory, _, _ = harness
    paths = [new_session(client) for _ in range(8)]
    assert not factory.created
    empty = client.get(paths[0] + '/state').json()
    assert empty['status'] == 'empty' and empty['step_seq'] == 0
    assert empty['regions'] == [] and empty['registers'] == {}
    assert empty['pc'] is empty['cpsr'] is empty['last_step'] is empty['stack'] is None
    assert client.post('/api/sessions', json={}).status_code == 429
    assert client.post(paths[0] + '/step', json={}).status_code == 409
    assert load(client, paths[0]).status_code == 200
    assert client.put(paths[0] + '/registers/r0', json={'value': 7}).status_code == 200
    assert client.get(paths[1] + '/state').json() == empty | {'session_id': paths[1].rsplit('/', 1)[1]}
    assert client.delete(paths[0]).status_code == 204
    assert factory.created[-1].closed
    assert client.delete(paths[0]).json()['error']['code'] == 'session_not_found'
    new_session(client)


def test_step_lost_response_counter_and_baseline(harness):
    client, factory, _, _ = harness
    path = new_session(client)
    loaded = load(client, path).json()
    assert loaded['program']['instructions'][0]['bytes'] == 'feffffea'
    assert loaded['state']['registers']['r0'] == {'value': 0, 'origin': 'default'}
    assert 'cpsr' not in loaded['state']['registers']
    assert client.put(path + '/registers/R14', json={'value': 8192}).status_code == 200
    assert client.put(path + '/registers/cpsr', json={'value': 0x40000000, 'mask': 0x40000000}).status_code == 200
    assert client.put(path + '/pc', json={'value': 4096}).status_code == 200
    # Deliberately discard the response: recovery reads state, never resends Step.
    client.post(path + '/step', json={})
    state = client.get(path + '/state').json()
    assert state['step_seq'] == state['last_step']['step_seq'] == 1
    assert state['pc'] == state['baseline_pc'] == 4096
    assert state['last_step']['branch']['taken'] is True
    assert get_ident() not in factory.threads
    second = client.post(path + '/step', json={}).json()
    assert second['result'] == second['state']['last_step']
    assert second['state']['step_seq'] == 2
    factory.error = DomainError('unmapped_memory_access', 'Missing bytes.', address=8192, size=4)
    failed = client.post(path + '/step', json={})
    assert failed.status_code == 200
    assert failed.json()['state']['status'] == 'stopped'
    assert failed.json()['result']['step_seq'] == 2
    assert failed.json()['result']['error']['restored'] is True
    assert client.put(path + '/registers/r0', json={'value': 9}).json()['status'] == 'ready'
    reset = client.post(path + '/reset', json={}).json()
    assert reset['step_seq'] == 2 and reset['last_step'] is None
    assert reset['registers']['r0']['value'] == 9
    assert reset['registers']['lr']['value'] == 8192
    assert reset['flags']['z'] is True
    replaced = load(client, path).json()['state']
    assert replaced['step_seq'] == 2 and replaced['registers']['r0']['value'] == 0


def test_memory_unknown_stack_origins_and_atomic_rejection(harness):
    client, _, _, _ = harness
    path = new_session(client)
    assert load(client, path, stack={'base': 12288, 'size': 256}).status_code == 200
    assert client.get(path + '/memory?address=8192&length=4').json()['cells'] == [dict(value=None, origin='unknown')] * 4
    assert client.get(path + '/memory?address=12288&length=1').json()['cells'] == [dict(value=0, origin='stack')]
    assert client.put(path + '/memory', json={'address': 8192, 'bytes': '01000000'}).status_code == 200
    assert client.put(path + '/memory', json={'address': 8196, 'zero_fill_length': 4}).status_code == 200
    before = client.get(path + '/state').json()
    assert client.put(path + '/memory', json={'address': 4095, 'bytes': '1234'}).status_code == 422
    assert client.get(path + '/state').json() == before
    assert client.get(path + '/memory?address=8192&length=4').json()['cells'] == [
        dict(value=value, origin='user') for value in (1, 0, 0, 0)]
    assert client.get(path + '/memory?address=8192&length=4097').status_code == 422
    assert client.get(path + '/memory?address=4294967295&length=2').status_code == 422
    assert client.get(path + '/memory?address=0x1000&length=4').status_code == 422
    assert client.put(path + '/memory', json={'address': 8192, 'zero_fill_length': 65537}).status_code == 413
    assert client.put(path + '/memory', json={'address': 8192, 'bytes': '00' * 65537}).status_code == 413
    assert client.get(path + '/state').json() == before


@pytest.mark.parametrize('suffix,body', [
    ('/step', {'again': True}), ('/reset', {'x': 1}), ('/pc', {'value': '4096'}),
    ('/pc', {'value': True}), ('/pc', {'value': 4096.0}), ('/pc', {'value': -1}),
    ('/pc', {'value': 1 << 32}), ('/registers/r0', {'value': 1, 'extra': 2}),
    ('/registers/r0', {'value': 1, 'mask': 0x80000000}),
    ('/registers/cpsr', {'value': 0, 'mask': 0}),
    ('/memory', {'address': 8192, 'bytes': '00', 'zero_fill_length': 1}),
    ('/memory', {'address': 8192}), ('/memory', {'address': 8192, 'bytes': 'a'}),
    ('/memory', {'address': 8192, 'bytes': ''}), ('/memory', {'address': 8192, 'bytes': '0g'}),
    ('/memory', {'address': 8192, 'bytes': '00 00'}),
    ('/memory', {'address': 8192, 'zero_fill_length': True}),
    ('/program', {'input_kind': 'assembly', 'mode': 'arm', 'text': 'mov r0,#1'}),
    ('/program', {'input_kind': 'assembly', 'mode': 'arm', 'text': 'mov r0,#1', 'base_address': 4096, 'format': 'auto'}),
    ('/program', {'input_kind': 'disassembly', 'mode': 'arm', 'text': '', 'base_address': 4096}),
])
def test_strict_inputs_preserve_state(harness, suffix, body):
    client, _, _, _ = harness
    path = new_session(client)
    load(client, path)
    before = client.get(path + '/state').json()
    method = client.post if suffix in ('/program', '/step', '/reset') else client.put
    response = method(path + suffix, json=body)
    assert response.status_code == 422, response.text
    assert 'error' in response.json()
    assert client.get(path + '/state').json() == before


def test_atomic_load_failures_and_recovery(harness):
    client, factory, _, _ = harness
    path = new_session(client)
    load(client, path)
    client.post(path + '/step', json={})
    before = client.get(path + '/state').json()
    for changes, status in [({'text': 'nonsense'}, 422),
                             ({'text': '0x1000: EAFFFFFE B 0x1000\nnonsense'}, 422),
                             ({'text': 'x' * ((1 << 20) + 1)}, 413),
                             ({'mode': 'aarch64'}, 422), ({'profile': 'other'}, 422),
                             ({'stack': {'base': 4096, 'size': 16}}, 422),
                             ({'stack': {'base': 8192, 'size': 32 << 20}}, 409)]:
        response = load(client, path, **changes)
        assert response.status_code == status, response.text
        assert client.get(path + '/state').json() == before
    failed = load(client, path, text='0x1000: EAFFFFFE B 0x1000\nnonsense').json()
    assert len(failed['preview']) == 1 and failed['diagnostics'][0]['line'] == 2
    factory.fail = True
    assert load(client, path).status_code == 503
    assert client.post(path + '/reset', json={}).status_code == 503
    assert client.get(path + '/state').json() == before
    factory.fail = False
    factory.error = DomainError('backend_unavailable', 'Restore failed.', restored=False)
    assert client.post(path + '/step', json={}).json()['state']['status'] == 'unavailable'
    assert client.post(path + '/step', json={}).status_code == 409
    assert client.put(path + '/registers/r0', json={'value': 3}).status_code == 409
    assert client.get(path + '/memory?address=4096&length=4').status_code == 200
    assert client.post(path + '/reset', json={}).json()['status'] == 'ready'


@pytest.mark.parametrize('mode,source,expected', [('arm', 'mov r0,#5', '0500a0e3'),
                                                ('thumb', 'movs r0,#5\nmovw r1,#8', '052040f20801')])
def test_source_load_and_failure(harness, mode, source, expected):
    client, _, _, _ = harness
    path = new_session(client)
    body = dict(input_kind='assembly', text=source, mode=mode, base_address=4096)
    response = client.post(path + '/program', json=body)
    assert response.status_code == 200, response.text
    program = response.json()['program']
    assert program['format'] == 'assembly' and program['source_text'] == source
    assert ''.join(i['bytes'] for i in program['instructions']) == expected
    assert all(i['source_line'] is None for i in program['instructions'])
    before = client.get(path + '/state').json()
    for source in ('this_is_not_an_instruction', '.word 0'):
        failed = client.post(path + '/program', json=body | {'text': source})
        assert failed.status_code == 422
        assert 'preview' not in failed.json()
        assert client.get(path + '/state').json() == before


def test_expiry_and_reads_extend_lifetime(harness):
    client, factory, _, now = harness
    first, second = new_session(client), new_session(client)
    load(client, first)
    now[0] = IDLE_SECONDS - 1
    assert client.get(first + '/state').status_code == 200
    now[0] += 1
    assert client.get(second + '/state').status_code == 404
    assert client.get(first + '/state').status_code == 200
    now[0] += IDLE_SECONDS
    assert client.get(first + '/state').json()['error']['code'] == 'session_not_found'
    assert factory.created[-1].closed


def test_concurrent_steps_are_serialized(harness):
    client, factory, _, _ = harness
    path = new_session(client)
    load(client, path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post(path + '/step', json={}), range(16)))
    assert sorted(r.json()['result']['step_seq'] for r in responses) == list(range(1, 17))
    assert all(r.json()['result'] == r.json()['state']['last_step'] for r in responses)
    assert client.get(path + '/state').json()['step_seq'] == 16


def test_active_operation_survives_expiry_and_delete_waits(harness):
    client, factory, registry, now = harness
    path = new_session(client)
    load(client, path)
    other = new_session(client)
    factory.release.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        step = pool.submit(client.post, path + '/step', json={})
        try:
            assert factory.started.wait(2)
            now[0] = IDLE_SECONDS + 1
            registry.sweep()
            assert not factory.created[-1].closed
            # The event loop and unrelated sessions remain responsive.
            assert client.get(other + '/state').status_code == 404
            deletion = pool.submit(client.delete, path)
            assert not deletion.done()
        finally:
            factory.release.set()
        assert step.result(timeout=5).status_code == 200
        assert deletion.result(timeout=5).status_code == 204
    assert factory.created[-1].closed


@pytest.mark.parametrize('headers,status', [({'host': 'evil.example'}, 400),
    ({'host': '127.0.0.1.evil.example'}, 400), ({'host': 'localhost:bad'}, 400),
    ({'origin': 'https://evil.example'}, 403), ({'origin': 'null'}, 403),
    ({'origin': 'http://127.0.0.1:8001'}, 403), ({'sec-fetch-site': 'cross-site'}, 403),
    ({'origin': 'http://127.0.0.1:8000'}, 201)])
def test_local_boundary(harness, headers, status):
    client, _, _, _ = harness
    response = client.post('/api/sessions', json={}, headers=headers)
    assert response.status_code == status
    assert 'access-control-allow-origin' not in response.headers


def test_json_errors_and_wire_limit(harness):
    client, _, _, _ = harness
    assert client.post('/api/sessions', content='{}').status_code == 415
    assert client.post('/api/sessions', content='{', headers={'content-type': 'application/json'}).status_code == 422
    assert client.post('/api/sessions', json={'extra': 1}).status_code == 422
    assert client.post('/api/sessions', content=b' ' * (MAX_REQUEST_BYTES + 1),
                       headers={'content-type': 'application/json'}).status_code == 413


def test_static_contract_openapi_and_safe_internal_error(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>Packaged browser</h1>')
    (tmp_path / 'asset.js').write_text('console.log("local");')
    app = create_app(static_directory=tmp_path)
    with TestClient(app, base_url='http://localhost', raise_server_exceptions=False) as client:
        assert client.get('/').text == '<h1>Packaged browser</h1>'
        assert client.get('/asset.js').status_code == 200
        assert client.get('/api/missing').status_code == 404
        schema = client.get('/api/openapi.json').json()
        assert len(schema['paths']) == 13
        assert 'State' in schema['components']['schemas']
        assert 'discriminator' in schema['paths']['/api/sessions/{session_id}/program']['post']['requestBody']['content']['application/json']['schema']
        def fail():
            raise RuntimeError('private native traceback')
        app.state.registry.create = fail
        failure = client.post('/api/sessions', json={})
        assert failure.status_code == 500 and failure.json()['error']['code'] == 'internal_error'
        assert 'private native' not in failure.text


def test_cleanup_task_and_shutdown():
    swept = Event()
    registry = SessionRegistry()
    original = registry.sweep
    def sweep():
        original()
        swept.set()
    registry.sweep = sweep
    with TestClient(create_app(registry=registry, cleanup_interval=0.01), base_url='http://localhost'):
        assert swept.wait(2)
    with pytest.raises(DomainError):
        registry.create()


def test_launcher(monkeypatch, capsys):
    from armstride import cli
    calls = []
    monkeypatch.setattr(cli.uvicorn, 'run', lambda app, **kwargs: calls.append(kwargs))
    cli.main(['--port', '8123'])
    assert calls == [dict(host='127.0.0.1', port=8123, workers=1, proxy_headers=False)]
    assert 'http://127.0.0.1:8123' in capsys.readouterr().out
    for arguments in (['--port', '0'], ['--port', '65536'], ['--host', '0.0.0.0']):
        with pytest.raises(SystemExit):
            cli.main(arguments)


def test_two_loaded_sessions_and_cache_policy(harness):
    client, _, _, _ = harness
    first, second = new_session(client), new_session(client)
    load(client, first)
    load(client, second)
    before = client.get(second + '/state')
    assert before.headers['cache-control'] == 'no-store'
    client.put(first + '/registers/r0', json={'value': 13})
    client.put(first + '/memory', json={'address': 8192, 'bytes': 'aabb'})
    client.post(first + '/step', json={})
    client.post(first + '/reset', json={})
    load(client, first, stack={'base': 12288, 'size': 256})
    client.delete(first)
    assert client.get(second + '/state').json() == before.json()
    assert client.get(second + '/memory?address=8192&length=1').json()['cells'][0]['value'] is None


def test_shutdown_waits_for_active_session(harness):
    client, factory, registry, _ = harness
    path = new_session(client)
    load(client, path)
    factory.release.clear()
    closing = Event()
    def close():
        closing.set()
        registry.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        step = pool.submit(client.post, path + '/step', json={})
        try:
            assert factory.started.wait(2)
            shutdown = pool.submit(close)
            assert closing.wait(2)
            assert not factory.created[-1].closed
        finally:
            factory.release.set()
        assert step.result(timeout=5).status_code == 200
        shutdown.result(timeout=5)
    assert factory.created[-1].closed
