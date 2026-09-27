"""Loopback Host/origin checks and a bounded JSON body before framework parsing."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders

from armstride.api.routes import error_response
from armstride.domain.models import MAX_ELF_FILE_BYTES, MAX_TEXT_BYTES

# Bounded JSON body: accommodate encoded assembly text or base64 ELF binaries.
MAX_REQUEST_BYTES = max(6 * MAX_TEXT_BYTES, 4 * MAX_ELF_FILE_BYTES // 3) + (64 << 10)


class LocalBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if scope['path'].startswith('/api/'):
            original_send = send

            async def uncached_send(message):
                if message['type'] == 'http.response.start':
                    MutableHeaders(scope=message)['cache-control'] = 'no-store'
                await original_send(message)

            send = uncached_send
        host = headers.get('host', '')
        try:
            parsed = urlsplit('//' + host)
            valid_host = (len(headers.getlist('host')) == 1 and
                          parsed.hostname in ('127.0.0.1', 'localhost', '::1') and
                          parsed.username is None and parsed.password is None and
                          not parsed.path and not parsed.query and not parsed.fragment and
                          (parsed.port is None or 0 < parsed.port <= 65535))
        except ValueError:
            valid_host = False
        if not valid_host:
            await error_response('invalid_host', 'Only loopback hosts are accepted.', 400)(scope, receive, send)
            return
        mutation = scope['method'] not in ('GET', 'HEAD', 'OPTIONS')
        if mutation:
            origin = headers.get('origin')
            if (len(headers.getlist('origin')) > 1 or
                    (origin is not None and origin != f"{scope['scheme']}://{host}") or
                    headers.get('sec-fetch-site') == 'cross-site'):
                await error_response('invalid_origin', 'Use the served application origin.', 403)(scope, receive, send)
                return
        if scope['path'].startswith('/api/') and scope['method'] in ('POST', 'PUT', 'PATCH'):
            if headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                await error_response('invalid_input', 'Requests require application/json.', 415)(scope, receive, send)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                    await error_response('input_limit', 'JSON request body is too large.', 413)(scope, receive, send)
                    return
                body.extend(chunk)
                if not message.get('more_body', False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return dict(type='http.request', body=bytes(body), more_body=False)
                return await receive()

            await self.app(scope, bounded_receive, send)
        else:
            await self.app(scope, receive, send)
