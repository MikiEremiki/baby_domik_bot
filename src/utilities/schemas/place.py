from typing import Optional, Annotated
from pydantic import BaseModel, BeforeValidator, field_validator


def str_to_int(s) -> int:
    try:
        return int(float(s))
    except (ValueError, TypeError) as e:
        raise ValueError(f"Некорректный ID локации: {s}") from e


def empty_str_to_none(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


prepare_int = Annotated[int, BeforeValidator(str_to_int)]
prepare_str_none = Annotated[Optional[str], BeforeValidator(empty_str_to_none)]


class PlaceDTO(BaseModel):
    place_id: prepare_int
    name: str
    address: str
    link_on_yndx_maps: prepare_str_none = None
    link_about: prepare_str_none = None

    @field_validator('link_on_yndx_maps', 'link_about', mode='after')
    @classmethod
    def validate_urls(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError(f"Ссылка должна начинаться с http:// или https://: {v}")
        return v

    def to_dto(self):
        return {
            'id': self.place_id,
            'name': self.name.strip(),
            'address': self.address.strip(),
            'link_on_yndx_maps': self.link_on_yndx_maps,
            'link_about': self.link_about,
        }


kv_name_attr_place = {
    'name': 'Название',
    'address': 'Адрес',
    'link_on_yndx_maps': 'Ссылка на Яндекс Карты',
    'link_about': 'Ссылка Подробнее',
}
