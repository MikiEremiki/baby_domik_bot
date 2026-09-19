import asyncio
from datetime import datetime, date, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from db import db_postgres
from db.models import Place, ScheduleEvent, TheaterEvent, TypeEvent, BaseTicket, BotSettings, BaseModel
from handlers.reserve.choice import choice_time, choice_place, choice_option_of_reserve
from handlers import support_hl
from db.enum import TicketPriceType
from utilities.schemas import kv_name_attr_schedule_event
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


def test_format_place_footnote_html_escaping():
    from sulguk import transform_html
    p_special = Place(
        id=3,
        name="<b>Зал</b> & 'Сцена' \"VIP\"",
        address="ул. <Мира>, д. 10 & 12 \"корпус А\"",
        link_on_yndx_maps='https://yandex.ru/maps/?q="1"&b=<2>',
        link_about='https://example.com/about?x=1&y="2"&z=<3>'
    )
    res = format_place_footnote(p_special)
    # Проверяем экранирование HTML-метасимволов
    assert "&lt;b&gt;Зал&lt;/b&gt; &amp;" in res
    assert "&lt;Мира&gt;, д. 10 &amp; 12 &quot;корпус А&quot;" in res
    assert 'href="https://yandex.ru/maps/?q=&quot;1&quot;&amp;b=&lt;2&gt;"' in res
    assert 'href="https://example.com/about?x=1&amp;y=&quot;2&quot;&amp;z=&lt;3&gt;"' in res

    # Проверяем, что sulguk.transform_html успешно парсит сформированный HTML
    parsed = transform_html(res)
    assert parsed.text.startswith("📍 <b>Зал</b> & 'Сцена' \"VIP\": ул. <Мира>, д. 10 & 12 \"корпус А\"")


def test_format_place_footnote_unsafe_url_schemes():
    unsafe_places = [
        Place(id=4, name="Зал 1", address="Адрес 1", link_on_yndx_maps="javascript:alert(1)", link_about="data:text/html,hack"),
        Place(id=5, name="Зал 2", address="Адрес 2", link_on_yndx_maps="ftp://ftp.example.com", link_about="file:///etc/passwd"),
        Place(id=6, name="Зал 3", address="Адрес 3", link_on_yndx_maps="vbscript:msgbox(1)", link_about="//evil.com"),
        Place(id=7, name="Зал 4", address="Адрес 4", link_on_yndx_maps="   ", link_about=None),
    ]
    for p in unsafe_places:
        res = format_place_footnote(p)
        assert "href=" not in res
        assert "javascript" not in res
        assert "ftp:" not in res
        assert "file:" not in res
        assert "data:" not in res


def test_reservation_summary_place_html_escaping():
    import html
    from sulguk import transform_html
    place_name = "<b>Камерный зал</b> & 'Люкс'"
    place_address = "<ул. Театральная>, д. 5 & \"Б\""

    escaped_place_name = html.escape(place_name)
    escaped_place_address = f" ({html.escape(place_address)})" if place_address else ""

    text = (
        f"<b>Подтверждение бронирования</b><br><br>"
        f"<b>Мероприятие:</b> Спектакль<br>"
        f"<b>Локация:</b> {escaped_place_name}{escaped_place_address}<br>"
        f"<b>Дата и время:</b> 15.10.2026 в 11:00<br>"
    )

    parsed = transform_html(text)
    assert "Локация: <b>Камерный зал</b> & 'Люкс' (<ул. Театральная>, д. 5 & \"Б\")" in parsed.text


def test_place_admin_formatters_escaping():
    import html
    from sulguk import transform_html

    row = Place(
        id=10,
        name="<b>Новый зал</b> & VIP",
        address="<ул. Пушкина, 10> & \"Дом 2\"",
        link_on_yndx_maps='https://yandex.ru/maps/?a="1"&b=<2>',
        link_about='https://example.com/about?a="1"&b=<2>'
    )
    default_id = 1

    is_def = " ⭐️ (по умолчанию)" if row.id == default_id else ""
    maps = f"\n  🗺 {html.escape(row.link_on_yndx_maps, quote=True)}" if row.link_on_yndx_maps else ""
    about = f"\n  ℹ️ {html.escape(row.link_about, quote=True)}" if row.link_about else ""
    res = f"• ID {row.id}: <b>{html.escape(row.name)}</b>{is_def}\n  📍 {html.escape(row.address)}{maps}{about}\n"

    assert "&lt;b&gt;Новый зал&lt;/b&gt; &amp; VIP" in res
    assert "&lt;ул. Пушкина, 10&gt; &amp; &quot;Дом 2&quot;" in res
    assert '&quot;1&quot;&amp;b=&lt;2&gt;' in res

    parsed = transform_html(res)
    assert "<b>Новый зал</b> & VIP" in parsed.text


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
    monkeypatch.setattr(pages, 'get_default_place', AsyncMock(return_value=p1))

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


def test_index_page_places_filter_respects_all_other_filters(monkeypatch):
    p1 = Place(id=1, name="Основная сцена", address="ул. Ленина, 1")
    p2 = Place(id=2, name="Камерная сцена", address="ул. Мира, 10")
    p3 = Place(id=3, name="Летняя сцена", address="ул. Парковая, 5")

    # Event 1: Type 1 (Репертуарный), min_age_child=2, Place 1 (Май 2030)
    event1 = MagicMock()
    event1.id = 1
    event1.name = "Гуси-Лебеди"
    event1.note = ""
    event1.duration = None
    event1.min_age_child = 2
    event1.flag_active_repertoire = True

    s1 = MagicMock()
    s1.id = 101
    s1.datetime_event = datetime(2030, 5, 10, 11, 0, tzinfo=timezone.utc)
    s1.qty_child_free_seat = 8
    s1.qty_adult_free_seat = 4
    s1.flag_turn_in_bot = True
    s1.theater_event = event1
    s1.type_event_id = 1
    s1.type_event = MagicMock(name='Репертуарный')
    s1.place_id = 1
    s1.place = p1
    event1.schedule_events = [s1]

    # Event 2: Type 2 (Новогодний), min_age_child=5, Place 2 (Май 2030)
    event2 = MagicMock()
    event2.id = 2
    event2.name = "Новогодняя сказка"
    event2.note = ""
    event2.duration = None
    event2.min_age_child = 5
    event2.flag_active_repertoire = True

    s2 = MagicMock()
    s2.id = 102
    s2.datetime_event = datetime(2030, 5, 12, 12, 0, tzinfo=timezone.utc)
    s2.qty_child_free_seat = 6
    s2.qty_adult_free_seat = 3
    s2.flag_turn_in_bot = True
    s2.theater_event = event2
    s2.type_event_id = 2
    s2.type_event = MagicMock(name='Новогодний')
    s2.place_id = 2
    s2.place = p2
    event2.schedule_events = [s2]

    # Event 3: Type 1 (Репертуарный), min_age_child=1, Place 3 (Июнь 2030)
    event3 = MagicMock()
    event3.id = 3
    event3.name = "Колобок"
    event3.note = ""
    event3.duration = None
    event3.min_age_child = 1
    event3.flag_active_repertoire = True

    s3 = MagicMock()
    s3.id = 103
    s3.datetime_event = datetime(2030, 6, 15, 10, 0, tzinfo=timezone.utc)
    s3.qty_child_free_seat = 10
    s3.qty_adult_free_seat = 5
    s3.flag_turn_in_bot = True
    s3.theater_event = event3
    s3.type_event_id = 1
    s3.type_event = MagicMock(name='Репертуарный')
    s3.place_id = 3
    s3.place = p3
    event3.schedule_events = [s3]

    events_list = [event1, event2, event3]
    monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=events_list))
    monkeypatch.setattr(pages, 'get_default_place', AsyncMock(return_value=p1))

    with _create_web_client(monkeypatch) as client:
        # 1. Без фильтров — все 3 площадки присутствуют
        resp_all = client.get('/')
        assert resp_all.status_code == 200
        assert "Основная сцена" in resp_all.text
        assert "Камерная сцена" in resp_all.text
        assert "Летняя сцена" in resp_all.text

        # 2. Фильтр type_id=1 (Репертуарный) — только Основная (Event 1) и Летняя (Event 3), Камерной (только Type 2) быть не должно
        resp_type1 = client.get('/?type_id=1')
        assert resp_type1.status_code == 200
        assert "Основная сцена" in resp_type1.text
        assert "Летняя сцена" in resp_type1.text
        assert "Камерная сцена" not in resp_type1.text

        # 3. Фильтр type_id=2 (Новогодний) — только Камерная сцена (Event 2)
        resp_type2 = client.get('/?type_id=2')
        assert resp_type2.status_code == 200
        assert "Камерная сцена" in resp_type2.text
        assert "Основная сцена" not in resp_type2.text
        assert "Летняя сцена" not in resp_type2.text

        # 4. Фильтр age=4 — проходит только Event 2 (min_age_child=5), т.е. только Камерная сцена
        resp_age = client.get('/?age=4')
        assert resp_age.status_code == 200
        assert "Камерная сцена" in resp_age.text
        assert "Основная сцена" not in resp_age.text
        assert "Летняя сцена" not in resp_age.text

        # 5. Фильтр month=2030-05 — проходят Event 1 (Май) и Event 2 (Май), но не Event 3 (Июнь)
        resp_month = client.get('/?month=2030-05')
        assert resp_month.status_code == 200
        assert "Основная сцена" in resp_month.text
        assert "Камерная сцена" in resp_month.text
        assert "Летняя сцена" not in resp_month.text

        # 6. Фильтр type_id=1 и place_id=1:
        # Свитчер мест по-прежнему предлагает Основную и Летнюю (обе имеют тип 1), но не Камерную
        resp_t1_p1 = client.get('/?type_id=1&place_id=1')
        assert resp_t1_p1.status_code == 200
        assert "Основная сцена" in resp_t1_p1.text
        assert "Летняя сцена" in resp_t1_p1.text
        assert "Камерная сцена" not in resp_t1_p1.text
        # В теле афиши отображается только Гуси-Лебеди (на Основной сцене)
        assert "Гуси-Лебеди" in resp_t1_p1.text
        assert "Колобок" not in resp_t1_p1.text


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
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)):
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

    asyncio.run(_test())


# -------------------------------------------------------------
# 8. Тесты валидации актуальности и контекста сеанса/локации (F5)
# -------------------------------------------------------------

def test_bot_choice_place_rejects_unknown_or_unavailable_place():
    async def _test():
        p1 = Place(id=1, name="Домик", address="ул. Ленина, 1")
        p2 = Place(id=2, name="Покровка", address="ул. Покровка, 10")

        ev1 = MagicMock(id=101, theater_event_id=10, datetime_event=datetime(2026, 10, 15, 11, 0),
                        flag_turn_in_bot=True, place=p1, place_id=1)
        ev2 = MagicMock(id=102, theater_event_id=10, datetime_event=datetime(2026, 10, 15, 16, 0),
                        flag_turn_in_bot=True, place=p2, place_id=2)

        mock_update = MagicMock()
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_message.photo = False

        mock_context = MagicMock()
        mock_context.user_data = {
            'STATE': 'PLACE',
            'command': 'reserve',
            'postfix_for_cancel': 'reserve|',
            'reserve_user_data': {
                'back': {'PLACE': {'text': 'Текст выбора локации', 'keyboard': MagicMock(), 'del_message_ids': []}},
                'PLACE': {
                    'branch': 'DATE',
                    'selected_date': '2026-10-15',
                    'schedule_event_ids': [101, 102]
                }
            }
        }
        mock_context.session = AsyncMock()

        # 1. Неизвестный place_id=999 не должен подменяться на default_place
        mock_update.callback_query.data = "PLACE|999"
        with patch.object(db_postgres, 'get_schedule_events_by_ids', AsyncMock(return_value=[ev1, ev2])), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)), \
             patch.object(db_postgres, 'get_place', AsyncMock(return_value=None)):
            state = await choice_place(mock_update, mock_context)
            assert state == 'PLACE'
            assert mock_context.user_data['reserve_user_data'].get('chosen_place_id') is None
            mock_update.callback_query.edit_message_text.assert_called_once()
            call_args = mock_update.callback_query.edit_message_text.call_args
            call_text = call_args[0][0] if call_args[0] else (call_args[1].get('text') if call_args[1] else '')
            assert "локация более недоступна" in call_text

        # 2. Место p2 выключено админом (все сеансы для p2 стали flag_turn_in_bot=False или исчезли)
        mock_update.callback_query.edit_message_text.reset_mock()
        mock_update.callback_query.data = "PLACE|2"
        # get_schedule_events_by_ids с actual_only=True вернет только ev1
        with patch.object(db_postgres, 'get_schedule_events_by_ids', AsyncMock(return_value=[ev1])), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)), \
             patch.object(db_postgres, 'get_place', AsyncMock(return_value=p2)):
            state = await choice_place(mock_update, mock_context)
            assert state == 'PLACE'
            assert mock_context.user_data['reserve_user_data'].get('chosen_place_id') is None
            mock_update.callback_query.edit_message_text.assert_called_once()
            call_args = mock_update.callback_query.edit_message_text.call_args
            call_text = call_args[0][0] if call_args[0] else (call_args[1].get('text') if call_args[1] else '')
            assert "локация более недоступна" in call_text

    asyncio.run(_test())


def test_bot_choice_option_of_reserve_validation():
    async def _test():
        p1 = Place(id=1, name="Домик", address="ул. Ленина, 1")
        p2 = Place(id=2, name="Покровка", address="ул. Покровка, 10")

        te = MagicMock(id=10, name="Тестовый спектакль")
        type_ev = MagicMock(id=1, name="Репертуарный")
        bt = MagicMock(
            base_ticket_id=1,
            name="Стандарт",
            flag_individual=False,
            quality_of_children=1,
            quality_of_adult=1,
            quality_of_add_adult=0,
            flag_active=True
        )

        ev_valid = MagicMock(
            id=101,
            theater_event_id=10,
            type_event_id=1,
            place_id=1,
            place=p1,
            datetime_event=datetime(2026, 10, 15, 11, 0),
            flag_turn_in_bot=True,
            qty_child_free_seat=5,
            qty_adult_free_seat=5
        )

        mock_update = MagicMock()
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_message.photo = False
        mock_msg = AsyncMock()
        mock_msg.delete = AsyncMock()
        mock_msg.edit_text = AsyncMock()
        mock_update.effective_chat.send_message = AsyncMock(return_value=mock_msg)
        mock_update.effective_chat.send_action = AsyncMock()

        mock_context = MagicMock()
        mock_context.user_data = {
            'STATE': 'TIME',
            'command': 'reserve',
            'postfix_for_cancel': 'reserve|',
            'reserve_user_data': {
                'back': {'TIME': {'text': 'Текст времени', 'keyboard': MagicMock(), 'del_message_ids': []}},
                'TIME': {
                    'schedule_event_ids': [101]
                },
                'chosen_place_id': 1
            }
        }
        mock_context.session = AsyncMock()

        # 1. Сеанс 999 отсутствует в TIME schedule_event_ids
        mock_update.callback_query.data = "TIME|999"
        state = await choice_option_of_reserve(mock_update, mock_context)
        assert state == 'TIME'
        mock_msg.delete.assert_called_once()
        mock_update.callback_query.edit_message_text.assert_called_once()
        call_args = mock_update.callback_query.edit_message_text.call_args
        call_text = call_args[0][0] if call_args[0] else (call_args[1].get('text') if call_args[1] else '')
        assert "данный сеанс более недоступен" in call_text

        # 2. Сеанс 101 выключен в БД (actual_only=True вернет ошибку / None)
        mock_update.callback_query.edit_message_text.reset_mock()
        mock_msg.delete.reset_mock()
        mock_update.callback_query.data = "TIME|101"
        with patch('handlers.reserve.choice.get_schedule_theater_base_tickets',
                   AsyncMock(side_effect=ValueError("Schedule event not found or inactive"))):
            state = await choice_option_of_reserve(mock_update, mock_context)
            assert state == 'TIME'
            mock_msg.delete.assert_called_once()
            call_args = mock_update.callback_query.edit_message_text.call_args
            call_text = call_args[0][0] if call_args[0] else (call_args[1].get('text') if call_args[1] else '')
            assert "данный сеанс более недоступен" in call_text

        # 3. Сеансу 101 в БД изменили площадку на p2 (а пользователь выбирал p1)
        ev_changed_place = MagicMock(
            id=101,
            theater_event_id=10,
            type_event_id=1,
            place_id=2,
            place=p2,
            datetime_event=datetime(2026, 10, 15, 11, 0),
            flag_turn_in_bot=True,
            qty_child_free_seat=5,
            qty_adult_free_seat=5
        )
        mock_update.callback_query.edit_message_text.reset_mock()
        mock_msg.delete.reset_mock()
        mock_update.callback_query.data = "TIME|101"
        with patch('handlers.reserve.choice.get_schedule_theater_base_tickets',
                   AsyncMock(return_value=([bt], ev_changed_place, te, type_ev))), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)):
            state = await choice_option_of_reserve(mock_update, mock_context)
            assert state == 'TIME'
            mock_msg.delete.assert_called_once()
            call_args = mock_update.callback_query.edit_message_text.call_args
            call_text = call_args[0][0] if call_args[0] else (call_args[1].get('text') if call_args[1] else '')
            assert "данный сеанс более недоступен" in call_text

        # 4. Валидный сеанс успешно загружается
        mock_update.callback_query.edit_message_text.reset_mock()
        mock_msg.delete.reset_mock()
        mock_update.callback_query.data = "TIME|101"
        with patch('handlers.reserve.choice.get_schedule_theater_base_tickets',
                   AsyncMock(return_value=([bt], ev_valid, te, type_ev))), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)), \
             patch('handlers.reserve.choice.create_str_info_by_schedule_event_id', AsyncMock(return_value="Инфо о показе")), \
             patch('handlers.reserve.choice.create_kbd_and_text_tickets_for_choice', AsyncMock(return_value=([], "Текст билетов"))):
            state = await choice_option_of_reserve(mock_update, mock_context)
            assert state == 'TICKET'
            assert mock_context.user_data['reserve_user_data']['choose_schedule_event_id'] == 101
            assert mock_context.user_data['reserve_user_data']['choose_theater_event_id'] == 10

    asyncio.run(_test())


def test_db_postgres_actual_only_filters():
    async def _test():
        future_dt = datetime(2030, 1, 1, 12, 0)
        ev_active_future = MagicMock(id=1, flag_turn_in_bot=True, datetime_event=future_dt, theater_event_id=10, type_event_id=1)

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = ev_active_future
        mock_res.scalars.return_value.all.return_value = [ev_active_future]
        mock_session.execute.return_value = mock_res

        with patch('db.db_postgres.populate_schedule_events_seats', AsyncMock()):
            # 1. get_schedule_event with actual_only
            res = await db_postgres.get_schedule_event(mock_session, 1, actual_only=True)
            assert res == ev_active_future
            query_arg = mock_session.execute.call_args[0][0]
            query_str = str(query_arg)
            assert "schedule_events.flag_turn_in_bot" in query_str

            # 2. get_schedule_events_by_ids with actual_only
            mock_session.execute.reset_mock()
            res_ids = await db_postgres.get_schedule_events_by_ids(mock_session, [1, 2, 3], actual_only=True)
            assert res_ids == [ev_active_future]
            query_arg = mock_session.execute.call_args[0][0]
            query_str = str(query_arg)
            assert "schedule_events.flag_turn_in_bot" in query_str

            # 3. get_schedule_events_by_ids_and_theater with actual_only
            mock_session.execute.reset_mock()
            res_theater = await db_postgres.get_schedule_events_by_ids_and_theater(mock_session, [1, 2, 3], [10], actual_only=True)
            assert res_theater == [ev_active_future]
            query_arg = mock_session.execute.call_args[0][0]
            query_str = str(query_arg)
            assert "schedule_events.flag_turn_in_bot" in query_str

    asyncio.run(_test())


# -------------------------------------------------------------
# 9. Тесты альтернативного текстового ввода расписания (F9)
# -------------------------------------------------------------

def test_schedule_event_preview_template():
    async def _test():
        mock_update = MagicMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.callback_query.answer = AsyncMock()

        state = await support_hl.schedule_event_preview(mock_update, MagicMock())
        assert state == 42
        mock_update.callback_query.edit_message_text.assert_called_once()
        sent_template = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert f"{kv_name_attr_schedule_event['place_id']}=" in sent_template
        assert "Локация=" in sent_template

    asyncio.run(_test())


def test_schedule_event_text_normalization():
    # 1. Сброс на Домик / По умолчанию
    for val in ["", "По умолчанию", "по умолчанию", "Домик", "домик", "None", "none", "0"]:
        data = support_hl.get_validated_data(f"Локация={val}\nВкл/Выкл в боте=Да\nНазначение стоимости=По умолчанию", 'schedule')
        assert data['place_id'] is None
        assert data['flag_turn_in_bot'] is True
        assert data['ticket_price_type'] == TicketPriceType.NONE

    # 2. Числовой ID
    data_id = support_hl.get_validated_data("Локация=5\nНазначение стоимости=будни", 'schedule')
    assert data_id['place_id'] == 5
    assert data_id['ticket_price_type'] == TicketPriceType.weekday

    # 3. Некорректная строка
    data_bad = support_hl.get_validated_data("Локация=abc\nНазначение стоимости=выходные", 'schedule')
    assert data_bad['place_id'] == 'abc'
    assert data_bad['ticket_price_type'] == TicketPriceType.weekend


def test_schedule_event_check_scenarios():
    async def _test():
        p1 = Place(id=1, name="Домик", address="ул. Ленина, 1")
        p5 = Place(id=5, name="Зал на Пушкина", address="ул. Пушкина, 5")

        mock_update = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 999
        mock_update.effective_chat.send_message = AsyncMock(return_value=mock_msg)
        mock_update.effective_chat.id = 12345

        mock_context = MagicMock()
        mock_context.user_data = {}
        mock_context.session = AsyncMock()

        # 1. Валидный существующий ID локации (Локация=5)
        mock_update.effective_message.text = "id типа мероприятия=1\nid репертуара=2\nЛокация=5\nВкл/Выкл в боте=Нет\nДата и время=2024-01-01T00:00 +3\nКол-во детских мест=8\nКол-во взрослых мест=10\nПодарок=Нет\nЕлка=Нет\nДед Мороз=Нет\nНазначение стоимости=По умолчанию"
        with patch.object(db_postgres, 'get_place', AsyncMock(return_value=p5)), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)):
            state = await support_hl.schedule_event_check(mock_update, mock_context)
            assert state == 42
            assert mock_context.user_data['schedule_event']['place_id'] == 5
            # Проверяем, что в сообщении предпросмотра выведено имя эффективной локации
            sent_preview = mock_update.effective_chat.send_message.call_args[0][0]
            assert "Зал на Пушкина (ID: 5)" in sent_preview

        # 2. Сброс на Домик (Локация=Домик)
        mock_update.effective_chat.send_message.reset_mock()
        mock_update.effective_message.text = "id типа мероприятия=1\nid репертуара=2\nЛокация=Домик\nВкл/Выкл в боте=Нет\nДата и время=2024-01-01T00:00 +3\nКол-во детских мест=8\nКол-во взрослых мест=10\nПодарок=Нет\nЕлка=Нет\nДед Мороз=Нет\nНазначение стоимости=По умолчанию"
        with patch.object(db_postgres, 'get_place', AsyncMock(return_value=None)), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)):
            state = await support_hl.schedule_event_check(mock_update, mock_context)
            assert state == 42
            assert mock_context.user_data['schedule_event']['place_id'] is None
            sent_preview = mock_update.effective_chat.send_message.call_args[0][0]
            assert "Домик (по умолчанию)" in sent_preview

        # 3. Несуществующий ID локации (Локация=999)
        mock_update.effective_chat.send_message.reset_mock()
        mock_update.effective_message.text = "id типа мероприятия=1\nid репертуара=2\nЛокация=999\nВкл/Выкл в боте=Нет"
        with patch.object(db_postgres, 'get_place', AsyncMock(return_value=None)), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)):
            state = await support_hl.schedule_event_check(mock_update, mock_context)
            assert state == 42
            sent_err = mock_update.effective_chat.send_message.call_args[0][0]
            assert "не найдена" in sent_err

        # 4. Некорректное значение (Локация=нечисло)
        mock_update.effective_chat.send_message.reset_mock()
        mock_update.effective_message.text = "id типа мероприятия=1\nid репертуара=2\nЛокация=нечисло\nВкл/Выкл в боте=Нет"
        with patch.object(db_postgres, 'get_place', AsyncMock(return_value=None)), \
             patch.object(db_postgres, 'get_default_place', AsyncMock(return_value=p1)):
            state = await support_hl.schedule_event_check(mock_update, mock_context)
            assert state == 42
            sent_err = mock_update.effective_chat.send_message.call_args[0][0]
            assert "Некорректное значение" in sent_err

    asyncio.run(_test())
