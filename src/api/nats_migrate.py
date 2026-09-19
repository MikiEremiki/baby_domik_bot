"""
Скрипт миграции и синхронизации JetStream в NATS для BabyDomikBot.

Проверяет наличие стрима 'baby_domik', вычисляет и добавляет недостающие subjects,
а также настраивает необходимые Durable Consumers.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Добавляем корень проекта и src в sys.path для возможности прямого запуска
current_dir = Path(__file__).resolve().parent
src_dir = current_dir.parent
root_dir = src_dir.parent
for p in (str(src_dir), str(root_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import nats
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, StreamConfig
from nats.js.errors import NotFoundError

try:
    from settings.settings import nats_url as default_nats_url
except ImportError:
    default_nats_url = os.getenv("NATS_URL", "nats://nats:4222")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("nats_migrate")

STREAM_NAME = "baby_domik"
STREAM_MAX_MSGS = 100
STREAM_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 дней (604800 сек)

# Все темы (subjects), используемые микросервисами и ботом
REQUIRED_SUBJECTS = [
    "yookassa",
    "gspread",
    "gspread_failed",
    "sales",
    "sales_report",
    "schedule_sync_result",
]

# Конфигурация Durable Consumers
REQUIRED_CONSUMERS: List[Dict[str, Any]] = [
    {
        "durable_name": "yookassa",
        "filter_subject": "yookassa",
        "ack_wait": 10,
        "deliver_policy": DeliverPolicy.NEW,
    },
    {
        "durable_name": "gspread",
        "filter_subject": "gspread",
        "ack_wait": 60,
        "deliver_policy": DeliverPolicy.NEW,
    },
    {
        "durable_name": "gspread_failed",
        "filter_subject": "gspread_failed",
        "ack_wait": 10,
        "deliver_policy": DeliverPolicy.NEW,
    },
    {
        "durable_name": "sales",
        "filter_subject": "sales",
        "ack_wait": 300,
        "deliver_policy": DeliverPolicy.NEW,
    },
    {
        "durable_name": "sales_report",
        "filter_subject": "sales_report",
        "ack_wait": 10,
        "deliver_policy": DeliverPolicy.NEW,
    },
    {
        "durable_name": "schedule_sync_result",
        "filter_subject": "schedule_sync_result",
        "ack_wait": 60,
        "deliver_policy": DeliverPolicy.NEW,
    },
]


async def run_nats_migration(
    url: Optional[str] = None,
    stream_name: str = STREAM_NAME,
    required_subjects: Optional[List[str]] = None,
    consumers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Выполняет миграцию NATS JetStream:
    1. Создает или обновляет стрим, добавляя отсутствующие subjects.
    2. Создает или обновляет Durable Consumers.
    """
    target_url = url or os.getenv("NATS_URL") or default_nats_url
    target_subjects = required_subjects or REQUIRED_SUBJECTS
    target_consumers = consumers or REQUIRED_CONSUMERS

    logger.info(f"Connecting to NATS at {target_url}...")
    nc = await nats.connect(target_url)
    jsm = nc.jsm()

    result = {
        "stream": stream_name,
        "created_stream": False,
        "updated_stream": False,
        "added_subjects": [],
        "all_subjects": [],
        "consumers_created": [],
        "consumers_updated": [],
    }

    try:
        # --- 1. Проверка и миграция Стрима ---
        try:
            stream_info = await jsm.stream_info(stream_name)
            current_subjects = list(stream_info.config.subjects or [])
            missing_subjects = [
                subj for subj in target_subjects if subj not in current_subjects
            ]

            if missing_subjects:
                new_subjects = list(dict.fromkeys(current_subjects + missing_subjects))
                logger.info(
                    f"Stream '{stream_name}' exists. Found missing subjects: {missing_subjects}. Updating..."
                )
                # Копируем текущую конфигурацию и обновляем subjects
                config = stream_info.config
                config.subjects = new_subjects
                await jsm.update_stream(config)
                result["updated_stream"] = True
                result["added_subjects"] = missing_subjects
                result["all_subjects"] = new_subjects
                logger.info(
                    f"Successfully updated stream '{stream_name}'. Current subjects: {new_subjects}"
                )
            else:
                result["all_subjects"] = current_subjects
                logger.info(
                    f"Stream '{stream_name}' already contains all required subjects: {current_subjects}"
                )

        except NotFoundError:
            logger.info(
                f"Stream '{stream_name}' not found. Creating new stream with subjects: {target_subjects}..."
            )
            config = StreamConfig(
                name=stream_name,
                subjects=target_subjects,
                max_msgs=STREAM_MAX_MSGS,
                max_age=STREAM_MAX_AGE_SECONDS,
            )
            await jsm.add_stream(config)
            result["created_stream"] = True
            result["added_subjects"] = list(target_subjects)
            result["all_subjects"] = list(target_subjects)
            logger.info(f"Stream '{stream_name}' created successfully.")

        # --- 2. Проверка и миграция Consumers ---
        for c_def in target_consumers:
            durable_name = c_def["durable_name"]
            filter_subj = c_def["filter_subject"]
            ack_wait = c_def["ack_wait"]
            deliver_policy = c_def.get("deliver_policy", DeliverPolicy.NEW)

            consumer_config = ConsumerConfig(
                durable_name=durable_name,
                filter_subject=filter_subj,
                ack_wait=ack_wait,
                deliver_policy=deliver_policy,
                ack_policy=AckPolicy.EXPLICIT,
            )

            try:
                # Проверяем наличие консьюмера
                await jsm.consumer_info(stream_name, durable_name)
                # Обновляем консьюмер с актуальными параметрами
                await jsm.add_consumer(stream_name, consumer_config)
                result["consumers_updated"].append(durable_name)
                logger.info(
                    f"Consumer '{durable_name}' on subject '{filter_subj}' ensured/updated."
                )
            except NotFoundError:
                await jsm.add_consumer(stream_name, consumer_config)
                result["consumers_created"].append(durable_name)
                logger.info(
                    f"Consumer '{durable_name}' on subject '{filter_subj}' created."
                )

        logger.info("NATS migration completed successfully.")
        return result

    finally:
        await nc.close()


def main():
    custom_url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_nats_migration(url=custom_url))


if __name__ == "__main__":
    main()
