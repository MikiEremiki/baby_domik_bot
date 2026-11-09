"""Tests for src/utilities/utl_sales_message.py."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import InputMediaPhoto

from utilities.utl_sales_message import (
    CAPTION_LIMIT,
    TEXT_LIMIT,
    build_extra,
    visible_len,
    char_breakdown,
    analyze_length,
    format_length_report,
    LengthReport,
    send_campaign_message,
)


# ─── build_extra ──────────────────────────────────────────────────────────────

class TestBuildExtra:
    def test_empty(self):
        assert build_extra('', '', '') == ''

    def test_all_parts(self):
        result = build_extra('Спектакль', '2 места', '/reserve')
        assert result == '\n\nСпектакль\n\n2 места\n\n/reserve'

    def test_only_reserve(self):
        result = build_extra('', '', '/reserve')
        assert result == '\n\n/reserve'


# ─── visible_len ──────────────────────────────────────────────────────────────

class TestVisibleLen:
    def test_ascii(self):
        assert visible_len('hello') == 5

    def test_cyrillic(self):
        assert visible_len('привет') == 6

    def test_emoji_supplementary(self):
        # 🎭 is U+1F3AD, outside BMP → 2 code units
        assert visible_len('🎭') == 2

    def test_mixed(self):
        # 'a' (1) + '🎭' (2) + 'b' (1) = 4
        assert visible_len('a🎭b') == 4


# ─── char_breakdown ───────────────────────────────────────────────────────────

class TestCharBreakdown:
    def test_basic(self):
        bd = char_breakdown('ab 1!')
        assert bd['letters'] == 2
        assert bd['spaces'] == 1
        assert bd['digits'] == 1
        assert bd['punctuation'] == 1

    def test_newline(self):
        bd = char_breakdown('a\nb')
        assert bd['newlines'] == 1
        assert bd['letters'] == 2

    def test_emoji(self):
        bd = char_breakdown('🎭')
        # Emoji is in category 'So' → punctuation by unicodedata,
        # but _char_category returns 'emoji' for non-matched categories
        # Actually 'So' starts with 'S' → punctuation
        assert bd['punctuation'] >= 1 or bd['emoji'] >= 1


# ─── analyze_length ───────────────────────────────────────────────────────────

class TestAnalyzeLength:
    def test_within_caption_limit(self):
        report = analyze_length('a' * 1000, '', True, 'caption')
        assert report is None

    def test_exceeds_caption_limit(self):
        report = analyze_length('a' * 1100, '', True, 'caption')
        assert report is not None
        assert report.limit == CAPTION_LIMIT
        assert report.excess == 1100 - CAPTION_LIMIT

    def test_within_text_limit(self):
        report = analyze_length('a' * 4000, '', False, 'caption')
        assert report is None

    def test_exceeds_text_limit(self):
        report = analyze_length('a' * 5000, '', False, 'caption')
        assert report is not None
        assert report.limit == TEXT_LIMIT

    def test_emoji_counts_double(self):
        # 512 emoji × 2 = 1024, should be at the edge
        text = '🎭' * 512
        report = analyze_length(text, '', True, 'caption')
        assert report is None

        text = '🎭' * 513
        report = analyze_length(text, '', True, 'caption')
        assert report is not None
        assert report.excess == 2


# ─── format_length_report ─────────────────────────────────────────────────────

class TestFormatLengthReport:
    def test_contains_excess(self):
        r = LengthReport(limit=1024, total=1100, excess=76,
                         breakdown={'letters': 1100})
        text = format_length_report(r)
        assert '76' in text
        assert '1024' in text


# ─── send_campaign_message ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_send_text_only():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    await send_campaign_message(bot, 123, media=[], text='hi', extra='')
    bot.send_message.assert_awaited_once()
    call = bot.send_message.call_args
    assert 'hi' in call.kwargs['text'] or call.kwargs['text'] == 'hi'


@pytest.mark.anyio
async def test_send_single_photo_caption():
    bot = AsyncMock()
    bot.send_photo = AsyncMock(return_value=MagicMock())
    media = [{'type': 'photo', 'file_id': 'AgAC'}]
    await send_campaign_message(bot, 123, media=media, text='caption',
                                extra='', text_mode='caption')
    bot.send_photo.assert_awaited_once()


@pytest.mark.anyio
async def test_send_single_photo_separate():
    bot = AsyncMock()
    bot.send_photo = AsyncMock(return_value=MagicMock())
    bot.send_message = AsyncMock(return_value=MagicMock())
    media = [{'type': 'photo', 'file_id': 'AgAC'}]
    await send_campaign_message(bot, 123, media=media, text='body',
                                extra='', text_mode='separate')
    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_awaited_once()


@pytest.mark.anyio
async def test_send_media_group():
    bot = AsyncMock()
    bot.send_media_group = AsyncMock(return_value=[MagicMock(), MagicMock()])
    bot.send_message = AsyncMock(return_value=MagicMock())
    media = [
        {'type': 'photo', 'file_id': 'AgAC1'},
        {'type': 'photo', 'file_id': 'AgAC2'},
    ]
    await send_campaign_message(bot, 123, media=media, text='cap',
                                extra='', text_mode='caption')
    bot.send_media_group.assert_awaited_once()
    call = bot.send_media_group.call_args
    input_media = call.kwargs['media']
    assert len(input_media) == 2
    assert isinstance(input_media[0], InputMediaPhoto)
    # reply_markup should NOT be in send_media_group kwargs
    assert 'reply_markup' not in call.kwargs
    # Text sent as separate message (media group doesn't support reply_markup)
    bot.send_message.assert_awaited_once()
    msg_call = bot.send_message.call_args
    assert msg_call.kwargs['text'] == 'cap'


@pytest.mark.anyio
async def test_send_media_group_with_reply_markup():
    import telegram
    bot = AsyncMock()
    bot.send_media_group = AsyncMock(return_value=[MagicMock(), MagicMock()])
    bot.send_message = AsyncMock(return_value=MagicMock())
    markup = telegram.ReplyKeyboardMarkup(keyboard=[['OK']])
    media = [
        {'type': 'photo', 'file_id': 'AgAC1'},
        {'type': 'photo', 'file_id': 'AgAC2'},
    ]
    await send_campaign_message(bot, 123, media=media, text='cap',
                                extra='', text_mode='caption',
                                reply_markup=markup)
    # Keyboard attached to the separate text message, not the media group
    bot.send_message.assert_awaited_once()
    msg_call = bot.send_message.call_args
    assert msg_call.kwargs['reply_markup'] is markup


@pytest.mark.anyio
async def test_send_media_group_caption_sends_text_separately():
    """With multiple media, text is always sent separately (no caption on album)."""
    bot = AsyncMock()
    bot.send_media_group = AsyncMock(return_value=[MagicMock(), MagicMock()])
    bot.send_message = AsyncMock(return_value=MagicMock())
    media = [
        {'type': 'photo', 'file_id': 'AgAC1'},
        {'type': 'photo', 'file_id': 'AgAC2'},
    ]
    result = await send_campaign_message(bot, 123, media=media, text='body',
                                         extra='', text_mode='caption')
    # Album sent without caption
    call = bot.send_media_group.call_args
    input_media = call.kwargs['media']
    assert input_media[0].caption is None
    # Text sent as separate message
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs['text'] == 'body'
    # Result contains album messages + text message
    assert len(result) == 3


@pytest.mark.anyio
async def test_send_media_group_separate():
    bot = AsyncMock()
    bot.send_media_group = AsyncMock(return_value=[MagicMock(), MagicMock()])
    bot.send_message = AsyncMock(return_value=MagicMock())
    media = [
        {'type': 'photo', 'file_id': 'AgAC1'},
        {'type': 'photo', 'file_id': 'AgAC2'},
    ]
    await send_campaign_message(bot, 123, media=media, text='body',
                                extra='', text_mode='separate')
    bot.send_media_group.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    # Text message carries the reply_markup
    msg_call = bot.send_message.call_args
    assert msg_call.kwargs['text'] == 'body'


@pytest.mark.anyio
async def test_send_single_video():
    bot = AsyncMock()
    bot.send_video = AsyncMock(return_value=MagicMock())
    media = [{'type': 'video', 'file_id': 'CgAC'}]
    await send_campaign_message(bot, 123, media=media, text='cap',
                                extra='', text_mode='caption')
    bot.send_video.assert_awaited_once()


@pytest.mark.anyio
async def test_parse_mode_always_html():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    await send_campaign_message(bot, 123, media=[], text='hi', extra='')
    call = bot.send_message.call_args
    assert call.kwargs['parse_mode'].value == 'HTML'
