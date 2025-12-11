import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Response, APIRouter
from faststream.nats.fastapi import NatsBroker
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

broker = NatsBroker('nats://nats:4222')
router = APIRouter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 3. Ручное управление подключением при старте приложения
    await broker.connect()
    yield
    # Отключение при остановке
    await broker.close()


class WebhookNotification(BaseModel):
    type: str
    event: str
    object: dict


@router.get("/")
async def hello_http():
    return "Hello, HTTP!"


@router.post("/yookassa")
async def post_notification(message: WebhookNotification):
    logger.info(message)
    await broker.publish(message, subject='yookassa', stream="baby_domik")
    return Response(status_code=200)


app = FastAPI(lifespan=lifespan)
app.include_router(router, tags=["main requests"])


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
