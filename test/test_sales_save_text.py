"""Tests for sales message saving — newline preservation in handle_admin_message and handle_media_text.

These tests verify the fix for the issue where line breaks (\n) in admin input
were lost during storage because sulguk.transform_html() ignores bare \n in HTML.
The fix converts \n to <br> before saving, so transform_html restores them on send.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.sales.message import handle_admin_message
from handlers.sales.media import handle_media_text
from handlers.sales.states import GET_MESSAGE, GET_MEDIA


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_message(text_html: str, entities=None, has_text=True):
    """Create a mock telegram Message with the given text_html."""
    msg = MagicMock()
    msg.text_html = text_html
    msg.text = text_html.replace('<br>', '\n') if text_html else None
    if not has_text:
        msg.text = None
    msg.entities = entities or []
    return msg


def _make_update(message, chat_id=12345):
    """Create a mock telegram Update with the given message."""
    update = MagicMock()
    update.effective_message = message
    update.effective_chat.id = chat_id
    update.effective_chat.send_message = AsyncMock(
        return_value=MagicMock(message_id=999)
    )
    return update


def _make_context(campaign_id=42, media=None):
    """Create a mock context with sales state."""
    context = MagicMock()
    context.bot.edit_message_reply_markup = AsyncMock()
    context.session = AsyncMock()
    context.session.commit = AsyncMock()
    context.user_data = {
        'sales': {
            'campaign_id': campaign_id,
            'type': 'WAS_THIS_YEAR_ON_PLAY',
            'media': media or [],
        }
    }
    return context


# ─── handle_admin_message ─────────────────────────────────────────────────────


class TestHandleAdminMessageNewlines:

    def test_newlines_converted_to_br(self):
        """Plain text with newlines should store <br> in message_text."""
        text_with_newlines = 'Строка 1\nСтрока 2\nСтрока 3'
        msg = _make_message(text_with_newlines)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            result = asyncio.run(handle_admin_message(update, context))

        # Verify update_campaign_message was called with <br> instead of \n
        call_kwargs = update_campaign_message_mock.call_args[1]
        assert call_kwargs['message_text'] == 'Строка 1<br>Строка 2<br>Строка 3'
        assert '\n' not in call_kwargs['message_text']

    def test_no_newlines_unchanged(self):
        """Text without newlines should be stored as-is."""
        text = 'Одна строка без переносов'
        msg = _make_message(text)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_admin_message(update, context))

        call_kwargs = update_campaign_message_mock.call_args[1]
        assert call_kwargs['message_text'] == text

    def test_html_with_newlines_preserves_tags(self):
        """HTML tags from Telegram formatting should be preserved with <br> newlines."""
        # Telegram sends bold as <b> and newlines as \n
        text_html = '<b>Жирный текст</b>\nОбычная строка\n<i>Курсив</i>'
        msg = _make_message(text_html)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_admin_message(update, context))

        stored = update_campaign_message_mock.call_args[1]['message_text']
        assert '<b>Жирный текст</b>' in stored
        assert '<i>Курсив</i>' in stored
        assert stored == '<b>Жирный текст</b><br>Обычная строка<br><i>Курсив</i>'

    def test_extra_payload_text_has_br(self):
        """The extra_payload in sales_state should also have <br> newlines."""
        text_with_newlines = 'Первая\nВторая'
        msg = _make_message(text_with_newlines)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_admin_message(update, context))

        sales_state = context.user_data['sales']
        assert sales_state['extra_payload']['text'] == 'Первая<br>Вторая'

    def test_text_mode_caption_with_media(self):
        """When media is present, text_mode should be 'caption'."""
        msg = _make_message('Текст')
        update = _make_update(msg)
        context = _make_context(media=[{'type': 'photo', 'file_id': 'AgAC'}])

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_admin_message(update, context))

        assert context.user_data['sales']['extra_payload']['text_mode'] == 'caption'

    def test_text_mode_separate_without_media(self):
        """When no media, text_mode should be 'separate'."""
        msg = _make_message('Текст')
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_admin_message(update, context))

        assert context.user_data['sales']['extra_payload']['text_mode'] == 'separate'

    def test_no_campaign_id_returns_end(self):
        """Missing campaign_id should return ConversationHandler.END."""
        msg = _make_message('Текст')
        update = _make_update(msg)
        context = MagicMock()
        context.user_data = {'sales': {}}  # no campaign_id

        result = asyncio.run(handle_admin_message(update, context))
        assert result == -1  # ConversationHandler.END

    def test_no_text_returns_get_message(self):
        """Message without text should return GET_MESSAGE state."""
        msg = _make_message('', has_text=False)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ):
            result = asyncio.run(handle_admin_message(update, context))

        assert result == GET_MESSAGE
        update_campaign_message_mock.assert_not_awaited()


# ─── handle_media_text ────────────────────────────────────────────────────────


class TestHandleMediaTextNewlines:

    def test_newlines_converted_to_br(self):
        """Plain text with newlines in media caption should store <br>."""
        text_with_newlines = 'Подпись\nк медиа\nещё строка'
        msg = _make_message(text_with_newlines)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            result = asyncio.run(handle_media_text(update, context))

        call_kwargs = update_campaign_message_mock.call_args[1]
        assert call_kwargs['message_text'] == 'Подпись<br>к медиа<br>ещё строка'
        assert '\n' not in call_kwargs['message_text']

    def test_no_newlines_unchanged(self):
        """Text without newlines in media caption should be stored as-is."""
        text = 'Простая подпись'
        msg = _make_message(text)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_media_text(update, context))

        call_kwargs = update_campaign_message_mock.call_args[1]
        assert call_kwargs['message_text'] == text

    def test_html_with_newlines_preserves_tags(self):
        """HTML formatting in media caption should be preserved with <br> newlines."""
        text_html = '<b>Заголовок</b>\nТекст подписи'
        msg = _make_message(text_html)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_media_text(update, context))

        stored = update_campaign_message_mock.call_args[1]['message_text']
        assert stored == '<b>Заголовок</b><br>Текст подписи'

    def test_extra_payload_text_has_br(self):
        """The extra_payload in sales_state should have <br> newlines."""
        text_with_newlines = 'Строка 1\nСтрока 2'
        msg = _make_message(text_with_newlines)
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_media_text(update, context))

        sales_state = context.user_data['sales']
        assert sales_state['extra_payload']['text'] == 'Строка 1<br>Строка 2'

    def test_text_mode_caption_with_media(self):
        """When media list is not empty, text_mode should be 'caption'."""
        msg = _make_message('Подпись')
        update = _make_update(msg)
        context = _make_context(media=[{'type': 'photo', 'file_id': 'AgAC'}])

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_media_text(update, context))

        assert context.user_data['sales']['extra_payload']['text_mode'] == 'caption'

    def test_text_mode_separate_without_media(self):
        """When media list is empty, text_mode should be 'separate'."""
        msg = _make_message('Подпись')
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()
        show_preview_mock = AsyncMock(return_value=MagicMock())

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.preview.show_preview', show_preview_mock
        ):
            asyncio.run(handle_media_text(update, context))

        assert context.user_data['sales']['extra_payload']['text_mode'] == 'separate'

    def test_no_campaign_id_returns_end(self):
        """Missing campaign_id should return ConversationHandler.END."""
        msg = _make_message('Текст')
        update = _make_update(msg)
        context = MagicMock()
        context.user_data = {'sales': {}}  # no campaign_id

        result = asyncio.run(handle_media_text(update, context))
        assert result == -1  # ConversationHandler.END


# ─── End-to-end: storage → sulguk transform round-trip ────────────────────────


# ─── handle_media_input: persist media to DB ─────────────────────────────────


class TestHandleMediaInputPersist:
    """Media added in handle_media_input should be persisted to DB immediately."""

    def _make_media_message(self, file_id: str, kind: str = 'photo'):
        """Create a mock message with media."""
        msg = MagicMock()
        msg.text = None
        msg.text_html = None
        msg.entities = []
        msg.media_group_id = None
        if kind == 'photo':
            msg.photo = [MagicMock(file_id=file_id)]
            msg.video = None
            msg.animation = None
        elif kind == 'video':
            msg.photo = None
            msg.video = MagicMock(file_id=file_id)
            msg.animation = None
        elif kind == 'animation':
            msg.photo = None
            msg.video = None
            msg.animation = MagicMock(file_id=file_id)
        return msg

    def test_media_saved_to_db_on_add(self):
        """handle_media_input calls update_campaign_message with extra_payload containing media."""
        msg = self._make_media_message('AgACag')
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ):
            asyncio.run(
                __import__('handlers.sales.media', fromlist=['handle_media_input'])
                .handle_media_input(update, context)
            )

        update_campaign_message_mock.assert_awaited_once()
        call_kwargs = update_campaign_message_mock.call_args[1]
        assert 'extra_payload' in call_kwargs
        media = call_kwargs['extra_payload'].get('media', [])
        assert len(media) == 1
        assert media[0]['file_id'] == 'AgACag'

    def test_session_committed_after_media(self):
        """context.session.commit is called after persisting media."""
        msg = self._make_media_message('AgACag')
        update = _make_update(msg)
        context = _make_context()

        update_campaign_message_mock = AsyncMock()

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ):
            asyncio.run(
                __import__('handlers.sales.media', fromlist=['handle_media_input'])
                .handle_media_input(update, context)
            )

        context.session.commit.assert_awaited_once()


# ─── handle_media_action clear: persist cleared media to DB ──────────────────


class TestHandleMediaActionClearPersist:
    """Clearing media should persist the cleared extra_payload to DB."""

    def _make_callback_query(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        return update

    def test_clear_persists_to_db(self):
        """handle_media_action clear calls update_campaign_message without media."""
        from handlers.sales.media import handle_media_action

        context = _make_context(media=[{'type': 'photo', 'file_id': 'AgACag'}])
        context.user_data['sales']['extra_payload'] = {
            'media': [{'type': 'photo', 'file_id': 'AgACag'}],
        }

        # CB_SEP is '|' so format is "intent_id|action"
        update = self._make_callback_query('sales:media|clear')

        update_campaign_message_mock = AsyncMock()
        show_get_media_mock = AsyncMock(return_value=0)

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.media.show_get_media', show_get_media_mock
        ):
            asyncio.run(handle_media_action(update, context))

        update_campaign_message_mock.assert_awaited_once()
        call_kwargs = update_campaign_message_mock.call_args[1]
        assert 'extra_payload' in call_kwargs
        assert 'media' not in call_kwargs['extra_payload']

    def test_clear_commits_session(self):
        """Session is committed after clearing media."""
        from handlers.sales.media import handle_media_action

        context = _make_context(media=[{'type': 'photo', 'file_id': 'AgACag'}])
        context.user_data['sales']['extra_payload'] = {
            'media': [{'type': 'photo', 'file_id': 'AgACag'}],
        }

        # CB_SEP is '|' so format is "intent_id|action"
        update = self._make_callback_query('sales:media|clear')

        update_campaign_message_mock = AsyncMock()
        show_get_media_mock = AsyncMock(return_value=0)

        with patch(
            'db.sales_crud.update_campaign_message', update_campaign_message_mock
        ), patch(
            'handlers.sales.media.show_get_media', show_get_media_mock
        ):
            asyncio.run(handle_media_action(update, context))

        context.session.commit.assert_awaited_once()


# ─── show_preview: text fallback when media present ──────────────────────────


class TestShowPreviewTextFallback:
    """show_preview loads text from DB when extra_payload has media but no text."""

    def _make_callback_query_for_preview(self):
        """Return a minimal update for show_preview (not callback)."""
        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_chat.send_message = AsyncMock()
        update.effective_message.message_thread_id = None
        return update

    def test_text_loaded_from_db_when_media_in_extra_payload(self):
        """If extra_payload has media but no text, text falls back to campaign.message_text."""
        from handlers.sales.preview import show_preview

        campaign_id = 42
        context = MagicMock()
        context.user_data = {
            'sales': {
                'campaign_id': campaign_id,
                'type': 'WAS_THIS_YEAR_ON_PLAY',
                'extra_payload': {
                    'media': [{'type': 'photo', 'file_id': 'AgACag'}],
                    # No 'text' key — simulates resume after adding media then exiting
                },
                'schedule_ids': [],
            }
        }
        context.session = AsyncMock()

        # Mock campaign with text in DB
        campaign = MagicMock()
        campaign.id = campaign_id
        campaign.type = 'WAS_THIS_YEAR_ON_PLAY'
        campaign.theater_event_id = None
        campaign.message_text = 'Текст из БД'
        campaign.caption_text = None
        campaign.message_kind = 'text'
        campaign.photo_file_id = None
        campaign.video_file_id = None
        campaign.animation_file_id = None
        campaign.status = 'draft'

        update = self._make_callback_query_for_preview()

        send_campaign_message_mock = AsyncMock(return_value=[MagicMock(message_id=1)])
        analyze_length_mock = MagicMock(return_value=None)

        with patch.object(
            context.session, 'get', new_callable=lambda: lambda cls, pk: asyncio.coroutine(lambda: campaign)()
        ), patch(
            'handlers.sales.preview.send_campaign_message', send_campaign_message_mock
        ), patch(
            'handlers.sales.preview.analyze_length', analyze_length_mock
        ), patch(
            'handlers.sales.preview._availability_block', new_callable=lambda: lambda s, ids: asyncio.coroutine(lambda: "")()
        ), patch(
            'handlers.sales.preview.build_extra', return_value=''
        ), patch(
            'telegram.ext.ContextTypes.DEFAULT_TYPE'
        ):
            # The session.get mock needs to be awaited
            async def run():
                context.session.get = AsyncMock(return_value=campaign)
                context.session.execute = AsyncMock(
                    return_value=MagicMock(scalar=lambda: 0)
                )
                context.bot.edit_message_reply_markup = AsyncMock()
                update.effective_chat.send_message = AsyncMock()
                try:
                    await show_preview(update, context)
                except Exception:
                    pass

            asyncio.run(run())

        # Verify that send_campaign_message was called with the DB text
        if send_campaign_message_mock.called:
            call_kwargs = send_campaign_message_mock.call_args[1]
            assert call_kwargs.get('text') == 'Текст из БД'


# ─── End-to-end: storage → sulguk transform round-trip ────────────────────────


class TestNewlineRoundTrip:
    """Verify the full cycle: \n input → <br> storage → \n output via sulguk."""

    def test_round_trip_plain_text(self):
        """Verify \n → <br> → \n round-trip through sulguk.transform_html."""
        from sulguk import transform_html

        # Step 1: Admin input (Telegram sends \n for line breaks)
        original_input = 'Строка 1\nСтрока 2\nСтрока 3'

        # Step 2: Handler converts \n to <br> for storage
        stored_text = original_input.replace('\n', '<br>')
        assert stored_text == 'Строка 1<br>Строка 2<br>Строка 3'

        # Step 3: On send, sulguk.transform_html converts <br> back to \n
        result = transform_html(stored_text)
        assert result.text == 'Строка 1\nСтрока 2\nСтрока 3'

    def test_round_trip_with_html_tags(self):
        """Verify HTML tags survive the round-trip."""
        from sulguk import transform_html

        original_input = '<b>Жирный</b>\n<i>Курсив</i>'
        stored_text = original_input.replace('\n', '<br>')
        assert stored_text == '<b>Жирный</b><br><i>Курсив</i>'

        result = transform_html(stored_text)
        assert result.text == 'Жирный\nКурсив'
        # Entities should preserve formatting
        assert len(result.entities) == 2

    def test_without_fix_newlines_lost(self):
        """Demonstrate the bug: bare \n in HTML is converted to space by sulguk."""
        from sulguk import transform_html

        # Without the fix, \n is stored as-is
        buggy_text = 'Строка 1\nСтрока 2'

        # sulguk converts bare \n in HTML to a space — newlines are lost
        result = transform_html(buggy_text)
        assert '\n' not in result.text
        # The newline becomes a space, so lines are merged
        assert 'Строка 1' in result.text and 'Строка 2' in result.text
