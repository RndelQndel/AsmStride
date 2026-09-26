"""Local application composition and native-resource lifecycle."""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from armstride.api.boundary import LocalBoundary
from armstride.api.routes import error_response, error_status, router
from armstride.api.sessions import SessionRegistry
from armstride.backends.keystone import KeystoneAssembler
from armstride.domain.models import DomainError

logger = logging.getLogger(__name__)


def create_app(*, registry=None, assembler=None, static_directory=None, cleanup_interval=60):
    registry = registry if registry is not None else SessionRegistry()

    async def sweep_idle():
        while True:
            await asyncio.sleep(cleanup_interval)
            await run_in_threadpool(registry.sweep)

    @asynccontextmanager
    async def lifespan(app):
        cleanup = asyncio.create_task(sweep_idle())
        try:
            yield
        finally:
            cleanup.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await cleanup
            finally:
                await run_in_threadpool(registry.close)

    app = FastAPI(title='ArmStride', version='0.1.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url='/api/openapi.json')
    app.state.registry = registry
    app.state.assembler = assembler if assembler is not None else KeystoneAssembler()
    app.add_middleware(LocalBoundary)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError):
        return error_response(error.code, str(error), error_status(error, request), context=dict(error.context))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        issues = [dict(location=list(e['loc']), message=e['msg'], type=e['type']) for e in error.errors()]
        return error_response('invalid_input', 'Request validation failed.', 422, context=dict(issues=issues))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return error_response('invalid_input', str(error.detail), error.status_code)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        logger.exception('Unexpected request failure', exc_info=error)
        return error_response('internal_error', 'An unexpected application error occurred.', 500)

    app.include_router(router)

    # Reserve the API namespace before mounting packaged browser assets.
    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'],
                   include_in_schema=False)
    def missing_api(path: str):
        return error_response('invalid_input', 'API endpoint not found.', 404)

    static_path = Path(static_directory) if static_directory is not None else Path(__file__).with_name('static')
    if (static_path / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=static_path, html=True), name='browser')
    else:
        @app.get('/', response_class=HTMLResponse, include_in_schema=False)
        def landing():
            return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>ArmStride</title>'
                    '<h1>ArmStride</h1><p>The local API is running. Build the browser workspace with npm ci --prefix frontend and npm --prefix frontend run build.</p>'
                    '<p><a href="/api/openapi.json">OpenAPI contract</a></p></html>')
    return app
