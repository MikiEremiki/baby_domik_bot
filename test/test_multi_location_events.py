import asyncio
from datetime import datetime, date, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from db import db_postgres
from db.models import Place, ScheduleEvent, TheaterEvent, BotSettings
from handlers.reserve.choice import choice_time, choice_place
from handlers.sub_hl import update_schedule_event_data
from utilities.utl_place import (
    effective_place, needs_place_choice, collect_places, format_place_footnote
)
from utilities.schemas.place import PlaceDTO
from utilities.schemas.schedule_event import ScheduleEventDTO
from utilities.utl_text import format_receipt_description
from api.web.main import app
from api.web.config import broker
from api.web.deps import get_session
from api.web.routes import pages, booking
from api.web.services import booking_service


# -------------------------------------------------------------
# 1. Тесты для модуля utl_place.py
# -------------------------------------------------------------

def test_effective_place():
    default_place = Place(id=1, name="Домик", address="ул. Ленина, 1")
    custom_place = Place(id=2, name="Театр на Покровке", address="ул. Покровка, 10")

    ev_with_place = ScheduleEvent(id=101, place_id=2)
    ev_with_place.place = custom_place

    ev_without_place = ScheduleEvent(id=102, place_id=None)
    ev_without_place.place = None

    assert effective_place(ev_with_place, default_place).id == 2
    assert effective_place(ev_with_place, default_place).name == "Театр на Покровке"
    assert effective_place(ev_without_place, default_place).id == 1
    assert effective_place(ev_without_place, default_place).name == "Домик"
    assert effective_place(None, default_place).id == 1


def test_needs_place_choice_conditions():
    default_place = Place(id=1, name="Домик", address="ул. Ленина, 1")
    custom_place = Place(id=2, name="Театр на Покровке", address="ул. Покровка, 10")

    dt_same_day_1 = datetime(2026, 10, 15, 11, 0)
    dt_same_day_2 = datetime(2026, 10, 15, 16, 0)
    dt_other_day = datetime(2026, 10, 16, 11, 0)

    # 1. Одинаковый спектакль в один день в разных локациях -> True
    ev1 = ScheduleEvent(id=1, theater_event_id=10, datetime_event=dt_same_day_1)
    ev1.place = default_place
    ev2 = ScheduleEvent(id=2, theater_event_id=10, datetime_event=dt_same_day_2)
    ev2.place = custom_place

    assert needs_place_choice([ev1, ev2], default_place) is True

    # 2. Разные спектакли в один день в разных локациях -> False
    ev3 = ScheduleEvent(id=3, theater_event_id=20, datetime_event=dt_same_day_2)
    ev3.place = custom_place

    assert needs_place_choice([ev1, ev3], default_place) is False

    # 3. Один спектакль в разные дни в разных локациях -> False
    ev4 = ScheduleEvent(id=4, theater_event_id=10, datetime_event=dt_other_day)
    ev4.place = custom_place

    assert needs_place_choice([ev1, ev4], default_place) is False

    # 4. Один спектакль в один день в одной локации -> False
    ev5 = ScheduleEvent(id=5, theater_event_id=10, datetime_event=dt_same_day_2)
    ev5.place = default_place

    assert needs_place_choice([ev1, ev5], default_place) is False


def test_collect_places():
    p1 = Place(id=1, name="Домик", address="ул. Ленина, 1")
    p2 = Place(id=2, name="Театр на Покровке", address="ул. Покровка, 10")

    ev1 = ScheduleEvent(id=1, datetime_event=datetime(2026, 10, 15, 11, 0))
    ev1.place = p1
    ev2 = ScheduleEvent(id=2, datetime_event=datetime(2026, 10, 15, 16, 0))
    ev2.place = p2
    ev3 = ScheduleEvent(id=3, datetime_event=datetime(2026, 10, 16, 11, 0))
    ev3.place = p1

    collected = collect_places([ev1, ev2, ev3], p1)
    assert len(collected) == 2
    assert collected[0].id == 1
    assert collected[1].id == 2


def test_format_place_footnote():
    p_full = Place(
        id=1,
        name="Большой зал",
        address="Невский пр., 1",
        link_on_yndx_maps="https://yandex.ru/maps/1",
        link_about="https://example.com/about"
    )
    res_full = format_place_footnote(p_full)
    assert "<b>Большой зал</b>" in res_full
    assert "Невский пр., 1" in res_full
    assert 'href="https://yandex.ru/maps/1"' in res_full
    assert 'href="https://example.com/about"' in res_full

    p_min = Place(id=2, name="Домик", address="ул. Ленина, 1")
    res_min = format_place_footnote(p_min)
    assert "<b>Домик</b>: ул. Ленина, 1" in res_min
    assert "href=" not in res_min


# -------------------------------------------------------------
# 2. Тесты для схем DTO
# -------------------------------------------------------------

def test_place_dto_validation():
    # Валидные данные
    dto = PlaceDTO(
        place_id="5",
        name="  Театр Кукол  ",
        address="  ул. Мира, 5  ",
        link_on_yndx_maps="https://yandex.ru/maps/5",
        link_about=""
    )
    d = dto.to_dto()
    assert d['id'] == 5
    assert d['name'] == "Театр Кукол"
    assert d['address'] == "ул. Мира, 5"
    assert d['link_on_yndx_maps'] == "https://yandex.ru/maps/5"
    assert d['link_about'] is None

    # Невалидный URL
    with pytest.raises(ValueError):
        PlaceDTO(
            place_id=1,
            name="Тест",
            address="Адрес",
            link_on_yndx_maps="ftp://invalid.com"
        )


def test_schedule_event_dto_with_place_id():
    dto = ScheduleEventDTO(
        event_id=10,
        event_type=1,
        theater_event_id=2,
        place_id="3",
        flag_turn_on_off=True,
        date_show=45000,
        time_show=0.5,
        qty_child="10",
        qty_child_free_seat="10",
        qty_child_nonconfirm_seat="0",
        qty_adult="5",
        qty_adult_free_seat="5",
        qty_adult_nonconfirm_seat="0",
        flag_gift=False,
        flag_christmas_tree=False,
        flag_santa=False,
        ticket_price_type=""
    )
    d = dto.to_dto()
    assert d['id'] == 10
    assert d['place_id'] == 3


# -------------------------------------------------------------
# 3. Тесты для форматтера чека
# -------------------------------------------------------------

def test_format_receipt_description():
    desc = format_receipt_description(
        ticket_id=123,
        event_name="Колобок",
        place_name="Домик",
        date_str="15.10 (Сб)",
        time_str="11:00",
        ticket_format="1+1 | Детский и взрослый",
        max_len=128
    )
    assert "Билет №123 на Колобок (Домик) 15.10 (Сб) в 11:00 (1+1)" == desc
    assert len(desc) <= 128

    # Очень длинное название спектакля
    long_title = "Очень длинное название детского интерактивного спектакля с Дедом Морозом и Снегурочкой в трех действиях"
    desc_long = format_receipt_description(
        ticket_id=9999,
        event_name=long_title,
        place_name="Филиал на Покровке",
        date_str="31.12 (Вс)",
        time_str="18:30",
        ticket_format="Семейный (2+2)",
        max_len=128
    )
    assert len(desc_long) <= 128
    assert "Билет №9999 на " in desc_long
    assert "(Филиал на Покровке) 31.12 (Вс) в 18:30 (Семейный (2+2))" in desc_long


# -------------------------------------------------------------
# 4. Веб-интерфейс: фильтрация по месту и отображение
# -------------------------------------------------------------

def _create_web_client(monkeypatch):
    monkeypatch.setattr(broker, 'connect', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(broker, 'close', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(broker, 'stop', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(broker, 'publish', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(booking_service, 'cleanup_expired_bookings', AsyncMock())
    monkeypatch.setattr(booking_service, 'publish_update_ticket', AsyncMock(), raising=False)
    monkeypatch.setattr(booking, 'publish_update_ticket', AsyncMock(), raising=False)
    monkeypatch.setattr(pages, 'get_afishas', AsyncMock(return_value=[]))

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()

    app.dependency_overrides[get_session] = lambda: mock_session
    return TestClient(app)


def test_index_page_places_filter_and_event_details(monkeypatch):
    p1 = Place(id=1, name="Основная сцена", address="ул. Ленина, 1", link_on_yndx_maps="https://yandex.ru/maps/1")
    p2 = Place(id=2, name="Камерная сцена", address="ул. Мира, 10", link_about="https://example.com/about")

    event = MagicMock()
    event.id = 1
    event.name = "Гуси-Лебеди"
    event.note = "Описание"
    event.duration = None
    event.min_age_child = 2
    event.flag_active_repertoire = True

    s1 = MagicMock()
    s1.id = 101
    s1.datetime_event = datetime(2030, 5, 10, 11, 0, tzinfo=timezone.utc)
    s1.qty_child_free_seat = 8
    s1.qty_adult_free_seat = 4
    s1.flag_turn_in_bot = True
    s1.theater_event = event
    s1.type_event_id = 1
    s1.type_event = MagicMock(name='Репертуарный')
    s1.place_id = 1
    s1.place = p1

    s2 = MagicMock()
    s2.id = 102
    s2.datetime_event = datetime(2030, 5, 10, 16, 0, tzinfo=timezone.utc)
    s2.qty_child_free_seat = 6
    s2.qty_adult_free_seat = 3
    s2.flag_turn_in_bot = True
    s2.theater_event = event
    s2.type_event_id = 1
    s2.type_event = MagicMock(name='Репертуарный')
    s2.place_id = 2
    s2.place = p2

    event.schedule_events = [s1, s2]

    monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event]))
    monkeypatch.setattr(pages, 'get_or_create_default_place', AsyncMock(return_value=p1))

    with _create_web_client(monkeypatch) as client:
        # 1. Главная страница афиши: есть фильтр по локациям
        resp = client.get('/')
        assert resp.status_code == 200
        assert "Локация:" in resp.text
        assert "Основная сцена" in resp.text
        assert "Камерная сцена" in resp.text

        # 2. Фильтрация по place_id=2
        resp_p2 = client.get('/?place_id=2')
        assert resp_p2.status_code == 200
        assert "Гуси-Лебеди" in resp_p2.text
        assert "place_id=2" in resp_p2.text

        # 3. Страница спектакля /event/1?place_id=2
        monkeypatch.setattr(pages, 'get_theater_event', AsyncMock(return_value=event))
        resp_details = client.get('/event/1?place_id=2')
        assert resp_details.status_code == 200
        assert "Локация" in resp_details.text  # Первый столбец
        assert "Камерная сцена" in resp_details.text
        assert "Основная сцена" not in resp_details.text  # Отфильтровано
        assert "Адреса площадок:" in resp_details.text
        assert "ул. Мира, 10" in resp_details.text


# -------------------------------------------------------------
# 5. Тесты бота: сценарий выбора локации
# -------------------------------------------------------------

def test_bot_choice_time_with_place_step():
    async def _test():
        p1 = Place(id=1, name="Домик", address="ул. Ленина, 1")
        p2 = Place(id=2, name="Покровка", address="ул. Покровка, 10")

        ev1 = MagicMock()
        ev1.id = 101
        ev1.theater_event_id = 10
        ev1.datetime_event = datetime(2026, 10, 15, 11, 0)
        ev1.qty_child_free_seat = 5
        ev1.qty_adult_free_seat = 5
        ev1.place = p1
        ev1.place_id = 1

        ev2 = MagicMock()
        ev2.id = 102
        ev2.theater_event_id = 10
        ev2.datetime_event = datetime(2026, 10, 15, 16, 0)
        ev2.qty_child_free_seat = 5
        ev2.qty_adult_free_seat = 5
        ev2.place = p2
        ev2.place_id = 2

        mock_update = MagicMock()
        mock_update.callback_query.data = "DATE|2026-10-15"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.delete_message = AsyncMock()
        mock_update.effective_chat.send_message = AsyncMock()

        mock_context = MagicMock()
        mock_context.user_data = {
            'STATE': 'DATE',
            'command': 'reserve',
            'postfix_for_cancel': 'reserve|',
            'reserve_user_data': {
                'back': {},
                'DATE': {'schedule_event_ids': [101, 102]}
            }
        }
        mock_context.session = AsyncMock()

        with patch.object(db_postgres, 'get_schedule_events_by_ids', AsyncMock(return_value=[ev1, ev2])), \
             patch.object(db_postgres, 'get_or_create_default_place', AsyncMock(return_value=p1)):
            # Шаг choice_time должен обнаружить совпадение спектакля в один день в 2 локациях и вернуть PLACE
            next_state = await choice_time(mock_update, mock_context)
            assert next_state == 'PLACE'
            assert mock_context.user_data['STATE'] == 'PLACE'
            assert mock_context.user_data['reserve_user_data']['PLACE']['branch'] == 'DATE'

            mock_update.callback_query.data = "PLACE|2"
            mock_te = MagicMock(id=10, name="Тест", min_age_child=3, max_age_child=5, note="", link=None, flag_active_repertoire=True)
            with patch.object(db_postgres, 'get_place', AsyncMock(return_value=p2)), \
                 patch.object(db_postgres, 'get_theater_events_by_ids', AsyncMock(return_value=[mock_te])):
                time_state = await choice_place(mock_update, mock_context)
                assert time_state == 'TIME'
                assert mock_context.user_data['reserve_user_data']['chosen_place_id'] == 2

    asyncio.run(_test())


# -------------------------------------------------------------
# 6. Тесты синхронизации Google Sheets
# -------------------------------------------------------------

def test_update_schedule_event_data_unknown_place_id():
    async def _test():
        mock_update = MagicMock()
        mock_update.callback_query.answer = AsyncMock()
        mock_update.effective_chat.send_message = AsyncMock()

        mock_context = MagicMock()
        mock_context.session = AsyncMock()

        p_dto = PlaceDTO(place_id=1, name="Домик", address="Адрес")
        # Событие ссылается на place_id=999, которого нет в таблице
        se_dto = ScheduleEventDTO(
            event_id=1,
            event_type=1,
            theater_event_id=1,
            place_id=999,
            flag_turn_on_off=True,
            date_show=45000,
            time_show=0.5,
            qty_child=10,
            qty_child_free_seat=10,
            qty_child_nonconfirm_seat=0,
            qty_adult=5,
            qty_adult_free_seat=5,
            qty_adult_nonconfirm_seat=0,
            flag_gift=False,
            flag_christmas_tree=False,
            flag_santa=False,
            ticket_price_type=""
        )

        with patch('handlers.sub_hl.load_places', AsyncMock(return_value=[p_dto])), \
             patch('handlers.sub_hl.load_schedule_events', AsyncMock(return_value=[se_dto])), \
             patch.object(db_postgres, 'get_places', AsyncMock(return_value=[Place(id=1, name="Домик", address="Адрес")])):
            res = await update_schedule_event_data(mock_update, mock_context)
            assert res == 'updates'
            # Проверяем, что была вызвана отправка сообщения об ошибке
            sent_text = mock_update.effective_chat.send_message.call_args[0][0]
            assert "неизвестный place_id=999" in sent_text

    asyncio.run(_test())


# -------------------------------------------------------------
# 7. Тесты get_default_place
# -------------------------------------------------------------

def test_get_default_place_scenarios():
    async def _test():
        p1 = Place(id=1, name="Домик", address="Адрес 1")
        p2 = Place(id=2, name="Покровка", address="Адрес 2")

        # Сценарий 1: setting default_place_id существует и указывает на Place id=2
        mock_session_1 = AsyncMock()
        mock_res_1 = MagicMock()
        mock_res_1.scalar_one_or_none.return_value = BotSettings(key='default_place_id', value='2')
        mock_session_1.execute.return_value = mock_res_1
        mock_session_1.get.return_value = p2

        place = await db_postgres.get_default_place(mock_session_1)
        assert place == p2

        # Сценарий 2: setting отсутствует, но есть место 'Домик'
        mock_session_2 = AsyncMock()
        mock_res_2 = MagicMock()
        mock_res_2.scalar_one_or_none.return_value = None
        mock_session_2.execute.return_value = mock_res_2

        with patch.object(db_postgres, 'get_place_by_name', AsyncMock(return_value=p1)):
            place = await db_postgres.get_default_place(mock_session_2)
            assert place == p1

        # Сценарий 3: setting отсутствует, 'Домик' отсутствует, есть другие места
        mock_session_3 = AsyncMock()
        mock_res_setting = MagicMock()
        mock_res_setting.scalar_one_or_none.return_value = None
        mock_res_fallback = MagicMock()
        mock_res_fallback.scalars.return_value.first.return_value = p2

        mock_session_3.execute.side_effect = [mock_res_setting, mock_res_fallback]

        with patch.object(db_postgres, 'get_place_by_name', AsyncMock(return_value=None)):
            place = await db_postgres.get_default_place(mock_session_3)
            assert place == p2

        # Сценарий 4: все таблицы пусты или ошибки -> None
        mock_session_4 = AsyncMock()
        mock_res_empty_1 = MagicMock()
        mock_res_empty_1.scalar_one_or_none.return_value = None
        mock_res_empty_2 = MagicMock()
        mock_res_empty_2.scalars.return_value.first.return_value = None

        mock_session_4.execute.side_effect = [mock_res_empty_1, mock_res_empty_2]

        with patch.object(db_postgres, 'get_place_by_name', AsyncMock(return_value=None)):
            place = await db_postgres.get_default_place(mock_session_4)
            assert place is None

    asyncio.run(_test())
