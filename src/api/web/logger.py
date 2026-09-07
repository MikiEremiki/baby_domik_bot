import logging
import sys

logger = logging.getLogger("api.web")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '{asctime:16s}|{name:20s}|{lineno:4d}|{levelname:8s}|{message}',
        datefmt='%y%m%d %H:%M:%S',
        style='{'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = True


class PaymentLogContext:
    def __init__(
        self,
        request_id: str | None = None,
        schedule_id: int | None = None,
        ticket_id: int | None = None,
        phone: str | None = None,
    ):
        self.request_id = request_id or "-"
        self.schedule_id = str(schedule_id) if schedule_id is not None else "-"
        self.ticket_id = str(ticket_id) if ticket_id is not None else "-"
        self.phone = phone or "-"

    def format(self, step: str, message: str) -> str:
        return f"[req:{self.request_id}][sched:{self.schedule_id}][ticket:{self.ticket_id}][phone:{self.phone}] [{step}] {message}"

    def info(self, step: str, message: str):
        logger.info(self.format(step, message))

    def warning(self, step: str, message: str):
        logger.warning(self.format(step, message))

    def error(self, step: str, message: str):
        logger.error(self.format(step, message))

    def exception(self, step: str, message: str):
        logger.exception(self.format(step, message))
