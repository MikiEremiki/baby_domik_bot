from pydantic import BaseModel

class WebhookNotification(BaseModel):
    type: str
    event: str
    object: dict
