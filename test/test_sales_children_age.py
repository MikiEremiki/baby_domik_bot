import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram import Update, User, Chat, Message, CallbackQuery, InlineKeyboardMarkup

from handlers import sales_hl
from conv_hl.sales_conv_hl import sales_conv_hl
from api import sales_worker


def create_mock_update(user_id: int = 12345, callback_data: str = None, text: str = None) -> Update:
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = user_id
    user.full_name = f"User_{user_id}"
    user.username = f"user_{user_id}"

    chat = MagicMock(spec=Chat)
    chat.id = user_id
    chat.send_message = AsyncMock()

    message = MagicMock(spec=Message)
    message.message_id = 100
    message.text = text
    message.text_html = text
    message.caption = None
    message.caption_html = None
    message.photo = []
    message.video = None
    message.animation = None
    message.entities = []
    message.caption_entities = []
    message.delete = AsyncMock()

    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message

    if callback_data is not None:
        query = MagicMock(spec=CallbackQuery)
        query.data = callback_data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.delete_message = AsyncMock()
        query.message = message
        update.callback_query = query
    else:
        update.callback_query = None

    return update


def create_mock_context():
    context = MagicMock()
    context.user_data = {'sales': {}}
    context.session = AsyncMock()
    return context


@pytest.mark.anyio
async def test_children_age_type_registered():
    assert "CHILDREN_AGE" in sales_hl.SALES_TYPES
    meta = sales_hl.SALES_TYPES["CHILDREN_AGE"]
    assert meta["enabled"] is True
    assert meta["start_state"] == sales_hl.PICK_CHILD_AGE_MIN
    
    usage_text = sales_hl._get_usage_text_for_type("CHILDREN_AGE")
    assert "возраст детей" in usage_text.lower()


@pytest.mark.anyio
async def test_children_age_flow_12plus():
    context = create_mock_context()
    context.user_data['sales']['type'] = 'CHILDREN_AGE'

    # 1. show_pick_child_age_min
    update = create_mock_update(callback_data='sales:child_age_min|12plus')
    state = await sales_hl.pick_child_age_min(update, context)
    assert context.user_data['sales']['child_age_min'] == 12
    assert context.user_data['sales']['child_age_max'] is None
    assert state == sales_hl.PICK_ATTACH_THEATER


@pytest.mark.anyio
async def test_children_age_flow_min_and_max():
    context = create_mock_context()
    context.user_data['sales']['type'] = 'CHILDREN_AGE'

    # 1. pick_child_age_min -> 3
    update = create_mock_update(callback_data='sales:child_age_min|3')
    state = await sales_hl.pick_child_age_min(update, context)
    assert context.user_data['sales']['child_age_min'] == 3
    assert state == sales_hl.PICK_CHILD_AGE_MAX

    # 2. pick_child_age_max -> 7
    update_max = create_mock_update(callback_data='sales:child_age_max|7')
    state_max = await sales_hl.pick_child_age_max(update_max, context)
    assert context.user_data['sales']['child_age_max'] == 7
    assert state_max == sales_hl.PICK_ATTACH_THEATER

    # 3. pick_attach_theater -> no
    update_attach = create_mock_update(callback_data='sales:attach_theater|no')
    with patch.object(sales_hl, 'show_build_audience', AsyncMock(return_value=sales_hl.GET_MESSAGE)) as mock_build:
        state_attach = await sales_hl.pick_attach_theater(update_attach, context)
        assert context.user_data['sales']['attach_theater'] is False
        assert context.user_data['sales']['theater_event_id'] is None
        assert mock_build.called
        assert state_attach == sales_hl.GET_MESSAGE


@pytest.mark.anyio
async def test_children_age_flow_attach_theater():
    context = create_mock_context()
    context.user_data['sales']['type'] = 'CHILDREN_AGE'
    context.user_data['sales']['child_age_min'] = 4
    context.user_data['sales']['child_age_max'] = 8

    # pick_attach_theater -> yes
    update_attach = create_mock_update(callback_data='sales:attach_theater|yes')
    with patch.object(sales_hl, 'show_pick_theater', AsyncMock(return_value=sales_hl.PICK_THEATER)) as mock_theater:
        state_attach = await sales_hl.pick_attach_theater(update_attach, context)
        assert context.user_data['sales']['attach_theater'] is True
        assert mock_theater.called
        assert state_attach == sales_hl.PICK_THEATER


@pytest.mark.anyio
async def test_conversation_states_registered():
    assert sales_hl.PICK_CHILD_AGE_MIN in sales_conv_hl.states
    assert sales_hl.PICK_CHILD_AGE_MAX in sales_conv_hl.states
    assert sales_hl.PICK_ATTACH_THEATER in sales_conv_hl.states


@pytest.mark.anyio
async def test_select_child_age_audience():
    session = AsyncMock()
    mock_result = MagicMock()
    # Return duplicate chat_ids to test dedup
    mock_result.all.return_value = [(1, 1001), (2, 1002), (3, 1001)]
    session.execute.return_value = mock_result

    rows = await sales_hl._select_child_age_audience(session, child_age_min=3, child_age_max=6)
    assert len(rows) == 2
    assert rows == [(1, 1001), (2, 1002)]


@pytest.mark.anyio
async def test_ensure_campaign_children_age():
    update = create_mock_update()
    context = create_mock_context()
    context.user_data['sales'] = {
        'type': 'CHILDREN_AGE',
        'child_age_min': 2,
        'child_age_max': 5,
        'theater_event_id': None,
        'schedule_ids': [],
    }

    mock_campaign = MagicMock(id=99)
    with patch('handlers.sales_hl.create_campaign', AsyncMock(return_value=mock_campaign)) as mock_create:
        cid = await sales_hl._ensure_campaign_and_schedules(update, context)
        assert cid == 99
        mock_create.assert_called_once()
        title = mock_create.call_args[1]['title']
        assert "Дети 2–5 лет" in title
        assert "без спектакля" in title
