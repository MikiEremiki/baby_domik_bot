from os import getenv
from pathlib import Path
from typing import Optional

from pydantic import SecretStr, BaseModel, PostgresDsn
from pydantic_settings import BaseSettings
from yaml import load as yaml_load

try:
    from yaml import CSafeLoader as Loader
except ImportError:
    from yaml import Loader


class BotSettings(BaseModel):
    token: SecretStr
    admin_group: Optional[int] = None
    feedback_thread_id_group_admin: Optional[int] = None
    developer_chat_id: Optional[int]


class TimeWebSettings(BaseModel):
    token: SecretStr


class PostgresSettings(BaseModel):
    db_url: PostgresDsn


class GoogleSheetsSettings(BaseModel):
    credentials_path: str
    sheet_id: str


class YookassaSettings(BaseModel):
    account_id: int
    secret_key: SecretStr
    payment_method_type: str


class Settings(BaseSettings):
    bot: BotSettings
    timeweb: TimeWebSettings
    postgres: PostgresSettings
    sheets: GoogleSheetsSettings
    yookassa: YookassaSettings


def parse_settings(local_file_name: str = "config/settings.yml") -> Settings:
    file_path = getenv("CONFIG_PATH")
    if file_path is not None:
        # Check if path exists
        file_path += '/settings.yml'
        if not Path(file_path).is_file():
            raise ValueError("Path %s is not a file or doesn't exist", file_path)
    else:
        parent_dir = Path(__file__).parent.parent.parent
        settings_file = Path(Path.joinpath(parent_dir, local_file_name))
        if not Path(settings_file).is_file():
            raise ValueError("Path %s is not a file or doesn't exist",
                             settings_file)
        file_path = settings_file.absolute()
    with open(file_path, "rt") as file:
        config_data = yaml_load(file, Loader)
    return Settings.model_validate(config_data)
