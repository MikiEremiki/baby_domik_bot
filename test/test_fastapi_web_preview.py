import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.web.main import app
from api.web.config import broker
from api.web.deps import get_session
from api.web.routes import pages, booking, api as api_route
from api.web.services import booking_service
from db.enum import PromotionDiscountType, UserRole
from yookassa import Payment


def _create_mock_event(free_seats_child=10, free_seats_adult=5):
    event = MagicMock()
    event.id = 1
    event.name = "Test Event"
    event.note = "Test Description"
    event.duration = None
    event.min_age_child = 3
    event.flag_active_repertoire = True  # Активен по умолчанию
    event.link = "http://test.com/image.jpg"
    
    # Сеанс в будущем
    s_event = MagicMock()
    s_event.id = 101
    s_event.datetime_event = datetime(2030, 1, 1, tzinfo=timezone.utc)
    s_event.qty_child_free_seat = free_seats_child
    s_event.qty_adult_free_seat = free_seats_adult
    s_event.qty_child_nonconfirm_seat = 0
    s_event.qty_adult_nonconfirm_seat = 0
    s_event.flag_turn_in_bot = True
    s_event.theater_event = event
    s_event.type_event_id = 1
    type_event_mock = MagicMock()
    type_event_mock.name = 'Репертуарный'
    s_event.type_event = type_event_mock
    
    event.schedule_events = [s_event]
    return event


def _create_mock_session_event(free_seats_child=None, free_seats_adult=None):
    # Чтобы избежать дублирования объектов, создаем событие через базовый метод
    event = _create_mock_event(
        free_seats_child=free_seats_child if free_seats_child is not None else 10,
        free_seats_adult=free_seats_adult if free_seats_adult is not None else 5
    )
    s_event = event.schedule_events[0]
    s_event.type_event = MagicMock()
    s_event.type_event.base_tickets = []
    return s_event


def _create_client(monkeypatch) -> TestClient:
    # Инфраструктурные моки, чтобы тесты работали быстро и не зависали
    monkeypatch.setattr(broker, 'connect', AsyncMock(return_value=None))
    monkeypatch.setattr(broker, 'close', AsyncMock(return_value=None))
    monkeypatch.setattr(broker, 'publish', AsyncMock(return_value=None))
    monkeypatch.setattr(booking_service, 'cleanup_expired_bookings', AsyncMock())

    # Переопределяем зависимость сессии
    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # session.add — синхронный метод
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()
    
    app.dependency_overrides[get_session] = lambda: mock_session

    return TestClient(app)


def test_index_page_is_rendered(monkeypatch):
    mock_event = _create_mock_event()
    monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[mock_event]))
    with _create_client(monkeypatch) as client:
        response = client.get('/')

    assert response.status_code == 200
    assert 'Афиша спектаклей' in response.text
    assert 'Test Event' in response.text
    assert '/static/img/logo.jpg' in response.text
    assert 'rel="icon"' in response.text
    assert 'object-contain' in response.text
    assert 'w-auto' in response.text


def test_event_details_page_is_rendered(monkeypatch):
    mock_event = _create_mock_event()
    monkeypatch.setattr(pages, 'get_theater_event', AsyncMock(return_value=mock_event))
    with _create_client(monkeypatch) as client:
        response = client.get('/event/1')

    assert response.status_code == 200
    assert 'Свободно мест (Дети)' in response.text
    assert 'Свободно мест (Взрослые)' in response.text


def test_event_details_returns_404_for_unknown_event(monkeypatch):
    monkeypatch.setattr(pages, 'get_theater_event', AsyncMock(return_value=None))
    with _create_client(monkeypatch) as client:
        response = client.get('/event/9999')

    assert response.status_code == 404


def test_booking_page_has_add_child_button(monkeypatch):
    mock_event = _create_mock_event()
    mock_event.flag_indiv_cost = True
    mock_s_event = _create_mock_session_event()
    mock_ticket_type = MagicMock()
    mock_ticket_type.base_ticket_id = 1
    mock_ticket_type.flag_active = True
    mock_ticket_type.name = "1+1"
    mock_ticket_type.get_price_from_date = MagicMock(return_value=(2400, 2000))

    monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
    monkeypatch.setattr(booking, 'get_base_tickets_by_event_or_all', AsyncMock(return_value=[mock_ticket_type]))
    # Убираем мок get_ticket_price_for_web в booking, чтобы проверить работу get_special_ticket_price через booking_service
    monkeypatch.setattr(booking_service, 'get_base_ticket', AsyncMock(return_value=mock_ticket_type))
    monkeypatch.setattr(booking_service, 'get_special_ticket_price', AsyncMock(return_value=3000))

    with _create_client(monkeypatch) as client:
        response = client.get('/booking/101')

    assert response.status_code == 200
    assert '3000' in response.text  # Проверяем, что подставилась спец. цена
    assert 'id="add-child"' in response.text
    assert 'id="children-container"' in response.text
    assert 'name="child_name"' in response.text
    assert 'name="child_age"' in response.text


def test_post_booking_form_success(monkeypatch):
    # Мокаем YooKassa
    mock_payment = MagicMock()
    mock_payment.id = "pay_12345"
    mock_payment.confirmation.confirmation_url = "https://yookassa.ru/confirm"
    monkeypatch.setattr(Payment, "create", MagicMock(return_value=mock_payment))

    mock_ticket_type = MagicMock()
    mock_ticket_type.base_ticket_id = 1
    mock_ticket_type.flag_active = True
    mock_ticket_type.name = "1+1"
    mock_ticket_type.quality_of_children = 1
    mock_ticket_type.quality_of_adult = 1
    mock_ticket_type.quality_of_add_adult = 0
    mock_ticket_type.to_dto = MagicMock(return_value={})

    monkeypatch.setattr(booking, 'get_base_tickets_by_event_or_all', AsyncMock(return_value=[mock_ticket_type]))
    monkeypatch.setattr(booking, 'get_ticket_price_for_web', AsyncMock(return_value=2400))
    monkeypatch.setattr(booking, 'get_promotion', AsyncMock(return_value=MagicMock(id=10, min_purchase_sum=100, discount_value=500, discount_type=PromotionDiscountType.fixed)))
    monkeypatch.setattr(booking, 'check_promo_restrictions_web', AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(booking, 'publish_write_data_reserve', AsyncMock())
    monkeypatch.setattr(booking, 'publish_write_client_reserve', AsyncMock())

    with _create_client(monkeypatch) as client:
        # Мокаем БД
        mock_s_event = _create_mock_session_event(free_seats_child=10, free_seats_adult=10)
        monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))

        form_data = {
            'ticket_type': '1',
            'adult_name': 'Анна',
            'phone': '+79991112233',
            'email': 'anna@example.com',
            'child_name': ['Миша', 'Саша'],
            'child_age': ['3', '5'],
            'promo_code': 'SPRING',
            'applied_promo_id': '10'
        }
        
        # Отправляем POST с данными формы
        response = client.post('/booking/101', data=form_data, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers['location'] == "https://yookassa.ru/confirm"


def test_post_booking_discontinued_event(monkeypatch):
    # Создаем мок события, которое снято с производства
    mock_event = _create_mock_event()
    mock_event.flag_active_repertoire = False
    
    mock_s_event = _create_mock_session_event()
    mock_s_event.theater_event = mock_event

    monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
    
    with _create_client(monkeypatch) as client:

        form_data = {
            'ticket_type': '1',
            'adult_name': 'Иван Иванов',
            'phone': '9001234567',
            'email': 'test@test.com',
            'child_name': ['Миша'],
            'child_age': ['3'],
        }
        response = client.post('/booking/101', data=form_data)

    assert response.status_code == 400
    assert "этот спектакль более не доступен" in response.text


def test_post_booking_no_seats(monkeypatch):
    # Создаем сеанс без мест
    mock_s_event = _create_mock_session_event(free_seats_child=0)
    monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
    
    with _create_client(monkeypatch) as client:

        form_data = {
            'ticket_type': '1',
            'adult_name': 'Иван Иванов',
            'phone': '9001234567',
            'email': 'test@test.com',
            'child_name': ['Миша'],
            'child_age': ['3'],
        }
        response = client.post('/booking/101', data=form_data)

    assert response.status_code == 400
    assert "осталось всего 0 детских мест" in response.text


def test_negative_free_seats_shown_as_zero(monkeypatch):
    # Создаем мок-событие с отрицательным количеством мест
    mock_event = _create_mock_event(free_seats_child=-5, free_seats_adult=-2)
    mock_s_event = _create_mock_session_event(free_seats_child=-3, free_seats_adult=-1)
    
    with _create_client(monkeypatch) as client:
        monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[mock_event]))
        monkeypatch.setattr(pages, 'get_theater_event', AsyncMock(return_value=mock_event))
        monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
        monkeypatch.setattr(booking, 'get_base_tickets_by_event_or_all', AsyncMock(return_value=[]))

        # Проверяем главную страницу
        response_index = client.get('/')
        assert response_index.status_code == 200
        assert 'мест нет' in response_index.text

        # Проверяем страницу деталей мероприятия
        response_details = client.get('/event/1')
        assert response_details.status_code == 200
        assert 'Мест нет' in response_details.text
        assert '>0</td>' in response_details.text

        # Проверяем страницу бронирования
        response_booking = client.get('/booking/101')
        assert response_booking.status_code == 200
        assert 'Мест: 0 (дети), 0 (взрослые)' in response_booking.text
        assert 'Свободно мест: -3' not in response_booking.text


def test_booking_returns_404_for_unknown_session(monkeypatch):
    monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=None))
    with _create_client(monkeypatch) as client:
        response = client.get('/booking/9999')

    assert response.status_code == 404


def test_index_filtering_and_button_states(monkeypatch):
    # Мокаем события: 
    # 1. Event 1: age 3, has future session
    # 2. Event 2: age 5, has NO future sessions
    
    event1 = MagicMock()
    event1.id = 1
    event1.name = "Future Show"
    event1.min_age_child = 3
    event1.note = "Show with future sessions"
    event1.duration = None
    s_future = MagicMock()
    s_future.datetime_event = datetime(2030, 1, 1, tzinfo=timezone.utc)
    s_future.qty_child_free_seat = 10
    s_future.qty_adult_free_seat = 5
    s_future.flag_turn_in_bot = True
    s_future.type_event_id = 1
    s_future.type_event = MagicMock(name='Репертуарный')
    event1.schedule_events = [s_future]
    
    event2 = MagicMock()
    event2.id = 2
    event2.name = "Old Show"
    event2.min_age_child = 5
    event2.note = "Show without future sessions"
    event2.duration = None
    s_past = MagicMock()
    s_past.datetime_event = datetime(2020, 1, 1, tzinfo=timezone.utc)
    s_past.qty_child_free_seat = 0
    s_past.qty_adult_free_seat = 0
    s_past.flag_turn_in_bot = True
    s_past.type_event_id = 1
    s_past.type_event = MagicMock(name='Репертуарный')
    event2.schedule_events = [s_past]
    
    with _create_client(monkeypatch) as client:
        monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event1, event2]))

        # 1. Проверка без фильтра (only_actual=True по умолчанию)
        resp = client.get('/')
        assert "Future Show" in resp.text
        assert "Old Show" not in resp.text

        # 2. Фильтр only_actual=false (должны быть оба, но у одного кнопка неактивна)
        resp_all = client.get('/?only_actual=false')
        assert "Future Show" in resp_all.text
        assert "Old Show" in resp_all.text
        assert 'href="/event/1"' in resp_all.text
        assert 'cursor-not-allowed' in resp_all.text
        assert 'Нет доступных сеансов' in resp_all.text

        # 3. Фильтр only_actual=true (должен остаться только Future Show)
        resp_actual = client.get('/?only_actual=true')
        assert "Future Show" in resp_actual.text
        assert "Old Show" not in resp_actual.text

        # 4. Фильтр age=5 (должен остаться только Old Show, если only_actual=false)
        resp_age5 = client.get('/?age=5&only_actual=false')
        assert "Future Show" not in resp_age5.text
        assert "Old Show" in resp_age5.text

        # 5. Комбинированный фильтр: age=3, only_actual=true (только Future Show)
        resp_comb = client.get('/?age=3&only_actual=true')
        assert "Future Show" in resp_comb.text
        assert "Old Show" not in resp_comb.text

        # 5. Комбинированный фильтр: age=5, only_actual=true (никто, так как Old Show не актуален)
        resp_comb2 = client.get('/?age=5&only_actual=true')
        assert "Future Show" not in resp_comb2.text
        assert "Old Show" not in resp_comb2.text
        assert "По заданным критериям спектаклей не найдено" in resp_comb2.text


def test_index_date_filtering(monkeypatch):
    # Тестируем фильтрацию по дате и наличие данных для календаря
    event = _create_mock_event()
    # Устанавливаем конкретную дату сеанса
    target_date = "2026-05-20"
    event.schedule_events[0].datetime_event = datetime.strptime(target_date, "%Y-%m-%d")
    
    with _create_client(monkeypatch) as client:
        # Мокаем БД для возврата нашего события
        monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event]))
        
        response = client.get(f'/?date={target_date}')
        
    assert response.status_code == 200
    assert 'Test Event' in response.text
    # Проверяем, что дата попала в available_dates (в скрытом div)
    assert f'"{target_date}"' in response.text
    assert 'data-available-dates' in response.text

def test_index_month_filtering(monkeypatch):
    # Мокаем события: 
    # 1. Event 1: session in Jan 2030
    # 2. Event 2: session in Feb 2030
    
    event1 = MagicMock()
    event1.id = 1
    event1.name = "January Show"
    event1.min_age_child = 0
    event1.note = ""
    event1.duration = None
    s_jan = MagicMock()
    s_jan.datetime_event = datetime(2030, 1, 15, tzinfo=timezone.utc)
    s_jan.qty_child_free_seat = 10
    s_jan.qty_adult_free_seat = 5
    s_jan.flag_turn_in_bot = True
    s_jan.type_event_id = 1
    s_jan.type_event = MagicMock(name='Репертуарный')
    event1.schedule_events = [s_jan]
    
    event2 = MagicMock()
    event2.id = 2
    event2.name = "February Show"
    event2.min_age_child = 0
    event2.note = ""
    event2.duration = None
    s_feb = MagicMock()
    s_feb.datetime_event = datetime(2030, 2, 20, tzinfo=timezone.utc)
    s_feb.qty_child_free_seat = 5
    s_feb.qty_adult_free_seat = 2
    s_feb.flag_turn_in_bot = True
    s_feb.type_event_id = 1
    s_feb.type_event = MagicMock(name='Репертуарный')
    event2.schedule_events = [s_feb]
    
    with _create_client(monkeypatch) as client:
        monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event1, event2]))

        # 1. Без фильтра (оба спектакля и оба месяца в фильтре)
        resp = client.get('/')
        assert "January Show" in resp.text
        assert "February Show" in resp.text
        assert "Янв 30" in resp.text
        assert "Фев 30" in resp.text

        # 2. Фильтр по Январю 2030
        resp_jan = client.get('/?month=2030-01')
        assert "January Show" in resp_jan.text
        assert "February Show" not in resp_jan.text

        # 3. Фильтр по Февралю 2030
        resp_feb = client.get('/?month=2030-02')
        assert "January Show" not in resp_feb.text
        assert "February Show" in resp_feb.text




def test_payment_result_pages_are_rendered(monkeypatch):
    monkeypatch.setattr(booking, 'get_ticket', AsyncMock(return_value=None))
    with _create_client(monkeypatch) as client:
        success_response = client.get('/payment-result?status=success')
        fail_response = client.get('/payment-result?status=fail')

    assert success_response.status_code == 200
    assert 'Оплата прошла успешно' in success_response.text
    assert fail_response.status_code == 200
    assert 'Оплата не завершена' in fail_response.text
def test_no_seats_disables_button(monkeypatch):
    # 1. Проверка на главной странице
    event_no_seats = _create_mock_event(free_seats_child=0, free_seats_adult=0)
    monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event_no_seats]))
    monkeypatch.setattr(pages, 'get_theater_event', AsyncMock(return_value=event_no_seats))
    
    with _create_client(monkeypatch) as client:
        resp_details = client.get('/event/1')
        assert "Мест нет" in resp_details.text
        assert "cursor-not-allowed" in resp_details.text


def test_only_child_seats_determine_availability(monkeypatch):
    with _create_client(monkeypatch) as client:
        # 1. Случай: 0 детских, 10 взрослых. Кнопка должна быть заблокирована.
        event_only_adult = _create_mock_event(free_seats_child=0, free_seats_adult=10)
        monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event_only_adult]))
        
        resp_index = client.get('/')
        assert "Test Event" in resp_index.text
        assert "мест нет" in resp_index.text
        assert "cursor-not-allowed" in resp_index.text

        # 2. Проверка на странице деталей: кнопка "Выбрать" должна быть заблокирована
        monkeypatch.setattr(pages, 'get_theater_event', AsyncMock(return_value=event_only_adult))
        resp_details = client.get('/event/1')
        assert "Мест нет" in resp_details.text
        assert "cursor-not-allowed" in resp_details.text

        # 3. Случай: 1 детское, 0 взрослых. Кнопка должна быть активна.
        event_only_child = _create_mock_event(free_seats_child=1, free_seats_adult=0)
        monkeypatch.setattr(pages, 'get_all_theater_events_actual', AsyncMock(return_value=[event_only_child]))
        
        resp_index_2 = client.get('/')
        assert "Test Event" in resp_index_2.text
        assert "мест нет" not in resp_index_2.text
        assert "bg-domik-green-soft" in resp_index_2.text


def test_check_promo_api(monkeypatch):
    from db.enum import PromotionDiscountType

    mock_promo = MagicMock()
    mock_promo.id = 55
    mock_promo.code = "HELLO"
    mock_promo.discount_value = 500
    mock_promo.discount_type = PromotionDiscountType.fixed
    mock_promo.min_purchase_sum = 1000
    mock_promo.flag_active = True
    mock_promo.start_date = None
    mock_promo.expire_date = None
    mock_promo.type_events = []
    mock_promo.theater_events = []
    mock_promo.schedule_events = []
    mock_promo.base_tickets = []
    mock_promo.weekdays = None
    mock_promo.max_count_of_usage = 0
    mock_promo.count_of_usage = 0

    with _create_client(monkeypatch) as client:
        monkeypatch.setattr(api_route, 'get_promotion_by_code', AsyncMock(return_value=mock_promo))
        
        # 1. Успешная проверка
        resp = client.post('/api/check-promo', data={
            'code': 'HELLO',
            'schedule_id': '101',
            'base_ticket_id': '1',
            'price': '2400'
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['new_price'] == 1900
        assert data['promo_id'] == 55

        # 2. Ошибка: сумма меньше минимальной
        resp_min = client.post('/api/check-promo', data={
            'code': 'HELLO',
            'schedule_id': '101',
            'base_ticket_id': '1',
            'price': '800'
        })
        assert resp_min.json()['success'] is False
        assert "Минимальная сумма" in resp_min.json()['message']

        # 3. Ошибка: промокод не найден
        monkeypatch.setattr(api_route, 'get_promotion_by_code', AsyncMock(return_value=None))
        resp_none = client.post('/api/check-promo', data={
            'code': 'NOTFOUND',
            'schedule_id': '101',
            'base_ticket_id': '1',
            'price': '2400'
        })
        assert resp_none.json()['success'] is False
        assert "не найден" in resp_none.json()['message']


def test_booking_page_promo_elements(monkeypatch):
    mock_s_event = _create_mock_session_event()
    monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
    monkeypatch.setattr(booking, 'get_base_tickets_by_event_or_all', AsyncMock(return_value=[]))
    monkeypatch.setattr(booking, 'get_ticket_price_for_web', AsyncMock(return_value=2000))
    
    with _create_client(monkeypatch) as client:
        response = client.get('/booking/101')

    assert response.status_code == 200
    assert 'id="promo_code"' in response.text
    assert 'id="check-promo-btn"' in response.text
    assert 'id="applied_promo_id"' in response.text
    assert 'id="promo-message"' in response.text


def test_post_booking_form_finds_chat_id_by_phone(monkeypatch):
    # Мокаем YooKassa
    mock_payment = MagicMock()
    mock_payment.id = "pay_999"
    mock_payment.confirmation.confirmation_url = "https://yookassa.ru/confirm"
    mock_payment_create = MagicMock(return_value=mock_payment)
    monkeypatch.setattr(Payment, "create", mock_payment_create)

    # Мокаем существующего пользователя в Telegram
    mock_user = MagicMock()
    mock_user.user_id = 123456789
    mock_user.status = MagicMock()
    mock_user.status.role = UserRole.USER  # Обычный пользователь

    with _create_client(monkeypatch) as client:
        # Мокаем функции БД, необходимые для бронирования
        mock_event = _create_mock_event()
        mock_ticket_type = MagicMock()
        mock_ticket_type.base_ticket_id = 1
        mock_ticket_type.flag_active = True
        mock_ticket_type.name = "1+1"
        mock_ticket_type.cost_main = 2400
        mock_ticket_type.quality_of_children = 1
        mock_ticket_type.quality_of_adult = 1
        mock_ticket_type.quality_of_add_adult = 0
        mock_ticket_type.to_dto = MagicMock(return_value={})

        monkeypatch.setattr(booking, 'get_base_tickets_by_event_or_all', AsyncMock(return_value=[mock_ticket_type]))
        monkeypatch.setattr(booking, 'get_ticket_price_for_web', AsyncMock(return_value=2400))
        monkeypatch.setattr(booking, 'publish_write_data_reserve', AsyncMock())
        monkeypatch.setattr(booking, 'publish_write_client_reserve', AsyncMock())

        # Мокаем сеанс с местами
        mock_s_event = _create_mock_session_event(free_seats_child=10, free_seats_adult=10)
        monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
        monkeypatch.setattr(booking, 'get_user_by_phone', AsyncMock(return_value=mock_user))
        
        form_data = {
            'ticket_type': '1',
            'adult_name': 'Анна',
            'phone': '+79991112233',
            'email': 'anna@example.com',
            'child_name': ['Миша'],
            'child_age': ['3'],
        }
        
        client.post('/booking/101', data=form_data)

        # Проверяем, что в YooKassa ушел правильный chat_id
        args, kwargs = mock_payment_create.call_args
        payment_params = args[0]
        assert payment_params['metadata']['chat_id'] == 123456789
        assert payment_params['metadata']['source'] == 'website'


def test_post_booking_form_skips_chat_id_for_admin(monkeypatch):
    # Мокаем YooKassa
    mock_payment = MagicMock()
    mock_payment.id = "pay_admin"
    mock_payment.confirmation.confirmation_url = "https://yookassa.ru/confirm"
    mock_payment_create = MagicMock(return_value=mock_payment)
    monkeypatch.setattr(Payment, "create", mock_payment_create)

    # Мокаем существующего администратора в Telegram
    mock_admin = MagicMock()
    mock_admin.user_id = 111
    mock_admin.status = MagicMock()
    mock_admin.status.role = UserRole.ADMIN  # Администратор

    with _create_client(monkeypatch) as client:
        # Мокаем функции БД, необходимые для бронирования
        mock_event = _create_mock_event()
        mock_ticket_type = MagicMock()
        mock_ticket_type.base_ticket_id = 1
        mock_ticket_type.flag_active = True
        mock_ticket_type.name = "1+1"
        mock_ticket_type.cost_main = 2400
        mock_ticket_type.quality_of_children = 1
        mock_ticket_type.quality_of_adult = 1
        mock_ticket_type.quality_of_add_adult = 0
        mock_ticket_type.to_dto = MagicMock(return_value={})

        monkeypatch.setattr(booking, 'get_base_tickets_by_event_or_all', AsyncMock(return_value=[mock_ticket_type]))
        monkeypatch.setattr(booking, 'get_ticket_price_for_web', AsyncMock(return_value=2400))
        monkeypatch.setattr(booking, 'publish_write_data_reserve', AsyncMock())
        monkeypatch.setattr(booking, 'publish_write_client_reserve', AsyncMock())

        # Мокаем сеанс с местами
        mock_s_event = _create_mock_session_event(free_seats_child=10, free_seats_adult=10)
        monkeypatch.setattr(booking, 'get_schedule_event', AsyncMock(return_value=mock_s_event))
        monkeypatch.setattr(booking, 'get_user_by_phone', AsyncMock(return_value=mock_admin))
        
        form_data = {
            'ticket_type': '1',
            'adult_name': 'Админ',
            'phone': '+79001112233',
            'email': 'admin@example.com',
            'child_name': ['Миша'],
            'child_age': ['3'],
        }
        
        client.post('/booking/101', data=form_data)

        # Проверяем, что в YooKassa ушел chat_id = 0 (потому что админ)
        args, kwargs = mock_payment_create.call_args
        payment_params = args[0]
        assert payment_params['metadata']['chat_id'] == 0
