import datetime
from typing import List

from pydantic import BaseModel, computed_field, ConfigDict

from telegram import Contact, User
from utilities.schemas.ticket import BaseTicket


class CustomerChild(BaseModel):
    child_id: int = None
    child_name: str = None
    child_date_birth: datetime = None
    _child_age: str = None

    @computed_field
    @property
    def child_age(self) -> str | None:
        if not self.child_date_birth:
            if self._child_age:
                return self._child_age
            return None
        else:
            age = (str((datetime.datetime.now() -
                        self.child_date_birth).days // 365) + 'г' +
                   str((datetime.datetime.now() -
                        self.child_date_birth).days % 365 // 30) + 'м')
            return age

    @child_age.setter
    def child_age(self, new_child_age: str):
        self._child_age = str(new_child_age)


class Customer(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int
    date_first_use_bot: datetime = None
    contact: Contact = None
    user: User
    callback_name: str = None
    callback_phone: int = None
    list_child: List[CustomerChild] = None
    list_ticket: List[BaseTicket] = None


if __name__ == '__main__':
    child1 = CustomerChild(
        child_id=1,
        child_name='Mike',
    )
    print(child1)
