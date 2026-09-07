import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import broker
from .logger import logger
from .middlewares.timing import TimingMiddleware
from .services.metrics_service import metrics_service
from .services.booking_service import cleanup_expired_bookings
from .routes.pages import router as pages_router
from .routes.booking import router as booking_router
from .routes.api import router as api_router
from .routes.auth import router as auth_router

class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Подключение к NATS
    await broker.connect()
    # Запуск фоновой задачи очистки просроченных броней
    cleanup_task = asyncio.create_task(cleanup_expired_bookings())
    yield
    # Отмена задачи при выключении
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    # Отключение от NATS
    if hasattr(broker, 'close') and callable(getattr(broker, 'close')):
        await broker.close()
    elif hasattr(broker, 'stop') and callable(getattr(broker, 'stop')):
        await broker.stop()

app = FastAPI(lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception at {request.url.path}: {exc}")
    if isinstance(exc, HTTPException):
        return HTMLResponse(content="Internal Server Error", status_code=exc.status_code)
    return HTMLResponse(content="Internal Server Error", status_code=500)

app.add_middleware(TimingMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.mount('/static', CachedStaticFiles(directory='static'), name='static')
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('WEB_SESSION_SECRET', 'web-preview-secret-key'),
)

@app.get('/metrics', include_in_schema=False)
async def prometheus_metrics():
    content = metrics_service.generate_prometheus_metrics()
    return PlainTextResponse(content=content, media_type="text/plain; version=0.0.4; charset=utf-8")

# Подключаем роутеры
app.include_router(pages_router, tags=["pages"])
app.include_router(booking_router, tags=["booking"])
app.include_router(api_router, tags=["api"])
app.include_router(auth_router, tags=["auth"])

async def main():
    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=app,
            host='0.0.0.0',
            port=8443,
        )
    )
    await webserver.serve()

if __name__ == "__main__":
    asyncio.run(main())
