from pydantic import BaseModel


class Afisha(BaseModel):
    file_id: str
    monday: int
