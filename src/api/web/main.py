import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import broker
from .logger import logger
from .services.booking_service import cleanup_expired_bookings
from .routes.pages import router as pages_router
from .routes.booking import router as booking_router
from .routes.api import router as api_router
from .routes.auth import router as auth_router

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
    await broker.close()

app = FastAPI(lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception at {request.url.path}: {exc}")
    if isinstance(exc, HTTPException):
        return HTMLResponse(content="Internal Server Error", status_code=exc.status_code)
    return HTMLResponse(content="Internal Server Error", status_code=500)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.mount('/static', StaticFiles(directory='static'), name='static')
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('WEB_SESSION_SECRET', 'web-preview-secret-key'),
)

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
