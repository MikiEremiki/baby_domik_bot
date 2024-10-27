from pydantic import BaseModel


class CustomMadeFormatDTO(BaseModel):
    custom_made_format_id: int
    name: str
    price: int
    flag_outside: bool

    def to_dto(self):
        return {
            'id': self.custom_made_format_id,
            'name': self.name,
            'price': self.price,
            'flag_outside': self.flag_outside,
        }


kv_name_attr_custom_made_format = {
    'name': 'Название мероприятия',
    'price': 'Стоимость',
    'flag_outside': 'На выезде'
}
