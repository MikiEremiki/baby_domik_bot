import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update, CallbackQuery, Message, Chat, User
from telegram.ext import ContextTypes

from db.models import Place, TypeEvent, TheaterEvent, BaseTicket
from db.enum import TicketPriceType
from handlers import schedule_hl
from utilities.utl_func import MOSCOW_TZ


def _make_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {
        'reserve_user_data': {'back': {}}
    }
    context.session = AsyncMock()
    context.bot = MagicMock()
    context.bot.edit_message_text = AsyncMock()
    return context


def _make_update():
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345
    update.effective_chat.send_message = AsyncMock()
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 111
    update.effective_user.username = "test_user"
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.message_id = 999
    update.effective_message.delete = AsyncMock()
    return update


def test_full_schedule_creation_wizard_9_steps():
    async def _run():
        mock_context = _make_context()
        mock_update = _make_update()

        # Mock DB objects
        type_obj = TypeEvent(id=1, name="Основной", name_alias="О")
        theater_obj = TheaterEvent(id=10, name="Колобок")
        place_1 = Place(id=1, name="Домик", address="ул. Ленина, 1")
        place_2 = Place(id=2, name="Филиал", address="ул. Мира, 2")
        base_ticket_1 = BaseTicket(base_ticket_id=1, name="Билет 1")

        # Step 1: schedule_create_start
        with patch('db.db_postgres.get_all_type_events', AsyncMock(return_value=[type_obj])):
            mock_update.callback_query = None
            sent_msg = MagicMock(spec=Message)
            sent_msg.message_id = 1001
            mock_update.effective_chat.send_message = AsyncMock(return_value=sent_msg)

            state = await schedule_hl.schedule_create_start(mock_update, mock_context)
            assert state == schedule_hl.SCH_TYPE
            assert "Шаг 1/9" in mock_update.effective_chat.send_message.call_args[0][0]

        # Step 2: handle_type_selected -> ask_theater_event
        cb_query = MagicMock(spec=CallbackQuery)
        cb_query.data = 'sch_tp_1'
        cb_query.answer = AsyncMock()
        cb_query.edit_message_text = AsyncMock()
        mock_update.callback_query = cb_query

        with patch('db.db_postgres.get_all_theater_events_actual', AsyncMock(return_value=[theater_obj])):
            state = await schedule_hl.handle_type_selected(mock_update, mock_context)
            assert state == schedule_hl.SCH_THEATER
            assert mock_context.user_data['new_schedule_event']['data']['type_event_id'] == 1
            assert "Шаг 2/9" in cb_query.edit_message_text.call_args[0][0]

        # Step 3: handle_theater_cb -> ask_place (should be Step 3/9!)
        cb_query.data = 'sch_th_t_10_0'
        with patch('db.db_postgres.get_places', AsyncMock(return_value=[place_1, place_2])), \
             patch('db.db_postgres.get_default_place', AsyncMock(return_value=place_1)):
            state = await schedule_hl.handle_theater_cb(mock_update, mock_context)
            assert state == schedule_hl.SCH_PLACE
            assert mock_context.user_data['new_schedule_event']['data']['theater_event_id'] == 10
            assert "Шаг 3/9" in cb_query.edit_message_text.call_args[0][0]

        # Step 4: handle_place_selected (custom place) -> ask_datetime
        cb_query.data = 'sch_plc_2'
        state = await schedule_hl.handle_place_selected(mock_update, mock_context)
        assert state == schedule_hl.SCH_DATETIME
        assert mock_context.user_data['new_schedule_event']['data']['place_id'] == 2
        assert "Шаг 4/9" in cb_query.edit_message_text.call_args[0][0]

        # Step 5: handle_datetime (text input) -> ask_qty_child
        mock_update.callback_query = None
        mock_update.effective_message.text = "25.12.2026 11:00"
        state = await schedule_hl.handle_datetime(mock_update, mock_context)
        assert state == schedule_hl.SCH_QTY_CHILD
        assert mock_context.user_data['new_schedule_event']['data']['datetime_event'] is not None
        assert "Шаг 5/9" in mock_context.bot.edit_message_text.call_args[1]['text']

        # Step 6: handle_qty_child (text input) -> ask_qty_adult
        mock_update.callback_query = None
        mock_update.effective_message.text = "10"
        state = await schedule_hl.handle_qty_child(mock_update, mock_context)
        assert state == schedule_hl.SCH_QTY_ADULT
        assert mock_context.user_data['new_schedule_event']['data']['qty_child'] == 10
        assert "Шаг 6/9" in mock_context.bot.edit_message_text.call_args[1]['text']

        # Step 7: handle_qty_adult (text input) -> ask_price_type
        mock_update.callback_query = None
        mock_update.effective_message.text = "12"
        state = await schedule_hl.handle_qty_adult(mock_update, mock_context)
        assert state == schedule_hl.SCH_PRICE_TYPE
        assert mock_context.user_data['new_schedule_event']['data']['qty_adult'] == 12
        assert "Шаг 7/9" in mock_context.bot.edit_message_text.call_args[1]['text']

        # Step 8: handle_price_type (button) -> ask_flags
        cb_query.data = 'sch_pt_weekday'
        mock_update.callback_query = cb_query
        state = await schedule_hl.handle_price_type(mock_update, mock_context)
        assert state == schedule_hl.SCH_FLAGS
        assert mock_context.user_data['new_schedule_event']['data']['ticket_price_type'] == TicketPriceType.weekday
        assert "Шаг 8/9" in cb_query.edit_message_text.call_args[0][0]

        # Step 9: handle_flags ('sch_next_bt') -> ask_base_tickets
        cb_query.data = 'sch_next_bt'
        with patch('db.db_postgres.get_all_base_tickets', AsyncMock(return_value=[base_ticket_1])):
            state = await schedule_hl.handle_flags(mock_update, mock_context)
            assert state == schedule_hl.SCH_BT_SELECT
            assert "Шаг 9/9" in cb_query.edit_message_text.call_args[0][0]

        # Summary: handle_base_tickets_cb ('sch_bt_done') -> ask_summary
        cb_query.data = 'sch_bt_done'
        with patch('db.db_postgres.get_all_type_events', AsyncMock(return_value=[type_obj])), \
             patch('db.db_postgres.get_all_theater_events', AsyncMock(return_value=[theater_obj])), \
             patch('db.db_postgres.get_default_place', AsyncMock(return_value=place_1)), \
             patch('db.db_postgres.get_place', AsyncMock(return_value=place_2)):
            state = await schedule_hl.handle_base_tickets_cb(mock_update, mock_context)
            assert state == schedule_hl.SCH_CONFIRM
            summary_text = cb_query.edit_message_text.call_args[0][0]
            assert "Проверьте данные события" in summary_text
            assert "Локация: Филиал" in summary_text

    asyncio.run(_run())


def test_schedule_creation_wizard_default_place():
    async def _run():
        mock_context = _make_context()
        mock_update = _make_update()

        # Test choosing default place button
        mock_context.user_data['new_schedule_event'] = {
            'data': {
                'type_event_id': 1,
                'theater_event_id': 10,
                'place_id': 5, # previous value
            },
            'service': {'message_id': 100}
        }

        cb_query = MagicMock(spec=CallbackQuery)
        cb_query.data = 'sch_plc_none'
        cb_query.answer = AsyncMock()
        cb_query.edit_message_text = AsyncMock()
        mock_update.callback_query = cb_query

        state = await schedule_hl.handle_place_selected(mock_update, mock_context)
        assert state == schedule_hl.SCH_DATETIME
        assert mock_context.user_data['new_schedule_event']['data']['place_id'] is None
        assert "Шаг 4/9" in cb_query.edit_message_text.call_args[0][0]

    asyncio.run(_run())


def test_schedule_edit_place_jump_to_summary():
    async def _run():
        mock_context = _make_context()
        mock_update = _make_update()

        # Test editing place from summary screen
        mock_context.user_data['new_schedule_event'] = {
            'data': {
                'type_event_id': 1,
                'theater_event_id': 10,
                'place_id': None,
                'flag_turn_in_bot': True,
                'datetime_event': datetime(2026, 12, 25, 11, 0, tzinfo=MOSCOW_TZ),
                'qty_child': 5,
                'qty_adult': 5,
                'ticket_price_type': TicketPriceType.NONE,
                'flag_gift': False,
                'flag_christmas_tree': False,
                'flag_santa': False,
                'base_ticket_ids': [],
            },
            'service': {
                'message_id': 100,
                'jump_to_summary': True
            }
        }

        cb_query = MagicMock(spec=CallbackQuery)
        cb_query.data = 'sch_plc_2'
        cb_query.answer = AsyncMock()
        cb_query.edit_message_text = AsyncMock()
        mock_update.callback_query = cb_query

        with patch('db.db_postgres.get_type_event', AsyncMock(return_value=TypeEvent(id=1, name="Основной"))), \
             patch('db.db_postgres.get_theater_event', AsyncMock(return_value=TheaterEvent(id=10, name="Колобок"))), \
             patch('db.db_postgres.get_default_place', AsyncMock(return_value=Place(id=1, name="Домик", address=""))), \
             patch('db.db_postgres.get_place', AsyncMock(return_value=Place(id=2, name="Филиал", address=""))):
            state = await schedule_hl.handle_place_selected(mock_update, mock_context)
            assert state == schedule_hl.SCH_CONFIRM
            assert mock_context.user_data['new_schedule_event']['data']['place_id'] == 2

    asyncio.run(_run())


def test_ask_datetime_display_current_value():
    async def _run():
        mock_context = _make_context()
        mock_update = _make_update()

        # Case 1: Initial creation (no previous datetime entered)
        mock_context.user_data['new_schedule_event'] = {
            'data': {
                'type_event_id': 1,
                'theater_event_id': 10,
                'place_id': 1,
                'datetime_event': None,
            },
            'service': {
                'message_id': 100,
                'jump_to_summary': False
            }
        }
        cb_query = MagicMock(spec=CallbackQuery)
        cb_query.answer = AsyncMock()
        cb_query.edit_message_text = AsyncMock()
        mock_update.callback_query = cb_query

        state = await schedule_hl.ask_datetime(mock_update, mock_context)
        assert state == schedule_hl.SCH_DATETIME
        msg_text = cb_query.edit_message_text.call_args[0][0]
        assert "Шаг 4/9" in msg_text
        assert "Текущее значение:" not in msg_text

        # Case 2: Returning to step 4 when datetime was already entered
        dt = datetime(2026, 12, 31, 18, 30, tzinfo=MOSCOW_TZ)
        mock_context.user_data['new_schedule_event']['data']['datetime_event'] = dt
        state = await schedule_hl.ask_datetime(mock_update, mock_context)
        assert state == schedule_hl.SCH_DATETIME
        msg_text = cb_query.edit_message_text.call_args[0][0]
        assert "Шаг 4/9" in msg_text
        assert "Текущее значение: <code>31.12.2026 18:30</code>" in msg_text

        # Case 3: Editing datetime from summary screen (jump_to_summary=True)
        mock_context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
        state = await schedule_hl.edit_datetime_start(mock_update, mock_context)
        assert state == schedule_hl.SCH_DATETIME
        msg_text = cb_query.edit_message_text.call_args[0][0]
        assert "Редактирование: введите дату и время" in msg_text
        assert "Текущее значение: <code>31.12.2026 18:30</code>" in msg_text

    asyncio.run(_run())
