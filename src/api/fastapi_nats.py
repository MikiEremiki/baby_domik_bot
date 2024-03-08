import asyncio
from dataclasses import dataclass

import uvicorn
from fastapi import FastAPI, Response
from faststream.nats.fastapi import NatsRouter, Logger, NatsBroker

router = NatsRouter('nats://nats:4222')


@dataclass
class WebhookNotification:
    type: str
    event: str
    object: dict


@router.get("/")
async def hello_http():
    return "Hello, HTTP!"


@router.post("/yookassa")
async def post_notification(
        message: WebhookNotification,
        logger: Logger,
        broker: NatsBroker
):
    logger.info(message)
    await broker.publish(message, 'bot', stream="baby_domik")
    return Response(status_code=200)


app = FastAPI(lifespan=router.lifespan_context)
app.include_router(router, tags=["main requests"])


async def main():
    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=app,
            host='0.0.0.0',
            port=443,
            ssl_keyfile='server.key',
            ssl_certfile='server.crt'
        )
    )
    await webserver.serve()


if __name__ == "__main__":
    asyncio.run(main())
