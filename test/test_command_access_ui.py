import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update, User, Chat, Message, CallbackQuery

import permissions
from handlers import command_mgmt_hl as hl
from permissions import grantable_items
from settings.settings import (
    ADMIN_ID, ACCESS_INTENT_ID, SETTINGS_DATABASE_KEY,
)

ROOT = ADMIN_ID[0]
ACTOR = 111111111      # non-privileged actor with settings:database
TARGET = 222222222     # regular user from `users`
USERNAMES = {ROOT: 'root', ACTOR: 'actor', TARGET: 'target', ADMIN_ID[1]: 'admin2'}


class FakeEnv:
    """In-memory replacement for DB access used by command_mgmt_hl."""

    def __init__(self, access=None, actor_allowed=True):
        self.access = {uid: set(keys) for uid, keys in (access or {}).items()}
        self.actor_allowed = actor_allowed
        self.grant_calls = []
        self.revoke_calls = []

    async def get_user_access(self, user_id, session):
        return set(self.access.get(user_id, set()))

    async def grant(self, user_id, command, session, actor_id=None):
        self.grant_calls.append((user_id, command, actor_id))
        if not permissions._actor_may_manage(command, actor_id):
            return False
        keys = self.access.setdefault(user_id, set())
        if command in keys:
            return False
        keys.add(command)
        return True

    async def revoke(self, user_id, command, session, actor_id=None):
        self.revoke_calls.append((user_id, command, actor_id))
        if not permissions._actor_may_manage(command, actor_id):
            return False
        keys = self.access.setdefault(user_id, set())
        if command not in keys:
            return False
        keys.discard(command)
        return True

    async def list_users_with_access(self, session):
        return sorted((uid, len(keys)) for uid, keys in self.access.items() if keys)

    async def usernames(self, session, ids):
        return {i: USERNAMES[i] for i in ids if i in USERNAMES}

    async def can(self, user_id, key, session=None):
        return self.actor_allowed


def _patches(env: FakeEnv):
    from handlers.command_mgmt import keyboards
    stack = ExitStack()
    stack.enter_context(patch.object(permissions, 'get_user_access', env.get_user_access))
    stack.enter_context(patch.object(hl, 'grant', env.grant))
    stack.enter_context(patch.object(hl, 'revoke', env.revoke))
    stack.enter_context(patch.object(keyboards, 'list_users_with_access', env.list_users_with_access))
    stack.enter_context(patch.object(hl, 'can', env.can))
    stack.enter_context(patch.object(hl.db_postgres, 'get_usernames_by_ids', env.usernames))
    stack.enter_context(patch.object(keyboards.db_postgres, 'get_usernames_by_ids', env.usernames))
    return stack


def _make_update(user_id, callback_data=None, text=None, forward_origin=None):
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = user_id
    chat = MagicMock(spec=Chat)
    chat.send_message = AsyncMock()
    update.effective_user = user
    update.effective_chat = chat

    message = MagicMock(spec=Message)
    message.text = text
    message.forward_origin = forward_origin
    update.effective_message = message

    if callback_data is not None:
        query = MagicMock(spec=CallbackQuery)
        query.data = callback_data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update.callback_query = query
    else:
        update.callback_query = None
    return update


def _context(target=None):
    context = MagicMock()
    context.user_data = {}
    if target is not None:
        context.user_data[hl.TARGET_KEY] = target
    context.session = object()
    return context


def _cb(payload):
    return f'{ACCESS_INTENT_ID}|{payload}'


def _idx(actor_id, key):
    return next(i for i, it in enumerate(grantable_items(actor_id)) if it.key == key)


def _item(actor_id, key):
    return grantable_items(actor_id)[_idx(actor_id, key)]


def _buttons(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def _texts(markup):
    return [btn.text for btn in _buttons(markup)]


def _datas(markup):
    return [btn.callback_data for btn in _buttons(markup)]


def _run(env, handler, update, context):
    async def _call():
        with _patches(env):
            return await handler(update, context)
    return asyncio.run(_call())


# ─── toggle ────────────────────────────────────────────────────────────────────

def test_toggle_grants_then_revokes():
    env = FakeEnv()
    idx = _idx(ROOT, 'list')
    cb = _cb(f'tg|commands|{idx}')

    update = _make_update(ROOT, cb)
    state = _run(env, hl.access_toggle, update, _context(TARGET))
    assert state == hl.ACCESS_ASK_USER
    assert 'list' in env.access[TARGET]
    update.callback_query.answer.assert_any_call('Выдано', show_alert=False)
    markup = update.callback_query.edit_message_reply_markup.call_args[1]['reply_markup']
    assert any(t.startswith('✅') and '/list' in t for t in _texts(markup))

    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))
    assert 'list' not in env.access[TARGET]
    update.callback_query.answer.assert_any_call('Забрано', show_alert=False)
    markup = update.callback_query.edit_message_reply_markup.call_args[1]['reply_markup']
    assert any(t.startswith('⬜') and '/list' in t for t in _texts(markup))


def test_toggle_settings_section_by_delegated_actor():
    env = FakeEnv()
    key = 'settings:place'
    cb = _cb(f'tg|settings|{_idx(ACTOR, key)}')
    update = _make_update(ACTOR, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))
    assert key in env.access[TARGET]


def test_toggle_forged_database_callback_rejected_for_non_privileged_actor():
    env = FakeEnv()
    # index of settings:database as seen by root, replayed by a non-privileged actor
    forged_idx = _idx(ROOT, SETTINGS_DATABASE_KEY)
    for group in ('settings', 'commands', 'update', 'tech'):
        update = _make_update(ACTOR, _cb(f'tg|{group}|{forged_idx}'))
        _run(env, hl.access_toggle, update, _context(TARGET))
        assert SETTINGS_DATABASE_KEY not in env.access.get(TARGET, set())
    assert all(call[1] != SETTINGS_DATABASE_KEY for call in env.grant_calls)


def test_toggle_database_allowed_for_root():
    env = FakeEnv()
    cb = _cb(f'tg|settings|{_idx(ROOT, SETTINGS_DATABASE_KEY)}')
    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))
    assert SETTINGS_DATABASE_KEY in env.access[TARGET]


def test_toggle_stale_index_answers_error_without_exception():
    env = FakeEnv()
    update = _make_update(ROOT, _cb('tg|commands|9999'))
    state = _run(env, hl.access_toggle, update, _context(TARGET))
    assert state == hl.ACCESS_ASK_USER
    update.callback_query.answer.assert_called_with(hl.STALE_TEXT, show_alert=True)
    assert not env.grant_calls and not env.revoke_calls
    assert not update.callback_query.edit_message_reply_markup.called


def test_toggle_group_mismatch_is_stale():
    env = FakeEnv()
    idx = _idx(ROOT, 'list')
    update = _make_update(ROOT, _cb(f'tg|tech|{idx}'))
    _run(env, hl.access_toggle, update, _context(TARGET))
    assert not env.grant_calls


def test_toggle_without_target_is_rejected():
    env = FakeEnv()
    update = _make_update(ROOT, _cb(f'tg|commands|{_idx(ROOT, "list")}'))
    _run(env, hl.access_toggle, update, _context())
    assert not env.grant_calls
    assert update.callback_query.answer.call_args[1]['show_alert'] is True


def test_toggle_root_target_has_no_toggles():
    env = FakeEnv()
    update = _make_update(ROOT, _cb(f'tg|commands|{_idx(ROOT, "list")}'))
    _run(env, hl.access_toggle, update, _context(ADMIN_ID[1]))
    assert not env.grant_calls
    assert update.callback_query.answer.call_args[1]['show_alert'] is True


def test_toggle_denied_without_database_permission():
    env = FakeEnv(actor_allowed=False)
    update = _make_update(ACTOR, _cb(f'tg|commands|{_idx(ACTOR, "list")}'))
    _run(env, hl.access_toggle, update, _context(TARGET))
    assert not env.grant_calls
    update.callback_query.answer.assert_called_with(hl.NO_ACCESS_TEXT, show_alert=True)


def test_toggle_is_idempotent_on_race():
    """grant() returns False because the row already exists, but the state is as desired."""
    env = FakeEnv()
    idx = _idx(ROOT, 'list')

    original_get = env.get_user_access
    calls = {'n': 0}

    async def racing_get(user_id, session):
        calls['n'] += 1
        if calls['n'] == 1:
            return set()          # stale read before the toggle
        return await original_get(user_id, session)

    env.access[TARGET] = {'list'}  # someone else already granted it
    env.get_user_access = racing_get
    update = _make_update(ROOT, _cb(f'tg|commands|{idx}'))
    _run(env, hl.access_toggle, update, _context(TARGET))
    update.callback_query.answer.assert_any_call('Выдано', show_alert=False)


# ─── user input ────────────────────────────────────────────────────────────────

def test_receive_user_numeric_id():
    env = FakeEnv()
    update = _make_update(ROOT, text=str(TARGET))
    context = _context()
    state = _run(env, hl.access_receive_user, update, context)
    assert state == hl.ACCESS_ASK_USER
    assert context.user_data[hl.TARGET_KEY] == TARGET
    markup = update.effective_chat.send_message.call_args[1]['reply_markup']
    assert any(d.startswith(f'{ACCESS_INTENT_ID}|pg|commands') for d in _datas(markup))


def test_receive_user_forwarded_message():
    env = FakeEnv()
    origin = MagicMock()
    origin.sender_user = MagicMock(id=TARGET)
    update = _make_update(ROOT, forward_origin=origin)
    context = _context()
    _run(env, hl.access_receive_user, update, context)
    assert context.user_data[hl.TARGET_KEY] == TARGET


def test_receive_user_hidden_profile():
    env = FakeEnv()
    origin = MagicMock(spec=['sender_user_name'])
    origin.sender_user_name = 'Hidden'
    update = _make_update(ROOT, forward_origin=origin)
    context = _context()
    _run(env, hl.access_receive_user, update, context)
    assert hl.TARGET_KEY not in context.user_data
    assert 'введите user_id' in update.effective_chat.send_message.call_args[0][0]


def test_receive_user_unknown_id():
    env = FakeEnv()
    update = _make_update(ROOT, text='123456')
    context = _context()
    _run(env, hl.access_receive_user, update, context)
    assert hl.TARGET_KEY not in context.user_data
    assert 'не найден' in update.effective_chat.send_message.call_args[0][0]


@pytest.mark.parametrize('text', ['abc', '12ab', '-5', '', '١٢٣', '1' * 40])
def test_receive_user_invalid_text(text):
    env = FakeEnv()
    update = _make_update(ROOT, text=text)
    context = _context()
    _run(env, hl.access_receive_user, update, context)
    assert hl.TARGET_KEY not in context.user_data
    assert update.effective_chat.send_message.called


def test_receive_user_denied_for_actor_without_permission():
    env = FakeEnv(actor_allowed=False)
    update = _make_update(ACTOR, text=str(TARGET))
    context = _context()
    _run(env, hl.access_receive_user, update, context)
    assert hl.TARGET_KEY not in context.user_data


# ─── groups / pagination / lists ───────────────────────────────────────────────

def test_groups_screen_shows_counters():
    env = FakeEnv(access={TARGET: {'list', 'settings:place'}})
    update = _make_update(ROOT, _cb('grp'))
    _run(env, hl.access_show_groups, update, _context(TARGET))
    markup = update.callback_query.edit_message_text.call_args[1]['reply_markup']
    texts = _texts(markup)
    total_commands = sum(1 for i in grantable_items(ROOT) if i.group == 'commands')
    total_settings = sum(1 for i in grantable_items(ROOT) if i.group == 'settings')
    assert f'Команды (1/{total_commands})' in texts
    assert f'Разделы /settings (1/{total_settings})' in texts


def test_groups_screen_for_non_privileged_actor_hides_database_in_counter():
    env = FakeEnv()
    update = _make_update(ACTOR, _cb('grp'))
    _run(env, hl.access_show_groups, update, _context(TARGET))
    markup = update.callback_query.edit_message_text.call_args[1]['reply_markup']
    total_settings = sum(1 for i in grantable_items(ACTOR) if i.group == 'settings')
    assert f'Разделы /settings (0/{total_settings})' in _texts(markup)
    assert total_settings == sum(
        1 for i in grantable_items(ROOT) if i.group == 'settings') - 1


def test_groups_screen_for_root_target_shows_note_without_toggles():
    env = FakeEnv()
    update = _make_update(ROOT, _cb('grp'))
    _run(env, hl.access_show_groups, update, _context(ADMIN_ID[1]))
    kwargs = update.callback_query.edit_message_text.call_args[1]
    assert 'полный доступ' in kwargs['text']
    assert not any('|pg|' in d or '|tg|' in d for d in _datas(kwargs['reply_markup']))


def test_group_pagination_pages_and_bounds():
    env = FakeEnv()
    total = sum(1 for i in grantable_items(ROOT) if i.group == 'commands')
    assert total > hl.PAGE_SIZE, 'commands group must need pagination'
    pages = (total + hl.PAGE_SIZE - 1) // hl.PAGE_SIZE

    seen = []
    for page in range(pages):
        update = _make_update(ROOT, _cb(f'pg|commands|{page}'))
        _run(env, hl.access_show_group, update, _context(TARGET))
        markup = update.callback_query.edit_message_text.call_args[1]['reply_markup']
        datas = _datas(markup)
        toggles = [d for d in datas if '|tg|' in d]
        assert 1 <= len(toggles) <= hl.PAGE_SIZE
        seen.extend(toggles)
        assert (f'{ACCESS_INTENT_ID}|pg|commands|{page + 1}' in datas) == (page < pages - 1)
        assert (f'{ACCESS_INTENT_ID}|pg|commands|{page - 1}' in datas) == (page > 0)
    assert len(seen) == total and len(set(seen)) == total

    # page beyond the range is clamped to the last page
    update = _make_update(ROOT, _cb('pg|commands|99'))
    _run(env, hl.access_show_group, update, _context(TARGET))
    datas = _datas(update.callback_query.edit_message_text.call_args[1]['reply_markup'])
    assert f'{ACCESS_INTENT_ID}|pg|commands|{pages - 2}' in datas
    assert not any(d.endswith(f'|pg|commands|{pages}') for d in datas)


def test_group_without_pagination_has_no_nav_row():
    env = FakeEnv()
    total = sum(1 for i in grantable_items(ACTOR) if i.group == 'settings')
    assert total <= hl.PAGE_SIZE
    update = _make_update(ACTOR, _cb('pg|settings|0'))
    _run(env, hl.access_show_group, update, _context(TARGET))
    datas = _datas(update.callback_query.edit_message_text.call_args[1]['reply_markup'])
    assert 'noop' not in ''.join(datas)
    assert f'{ACCESS_INTENT_ID}|tg|settings|{_idx(ACTOR, "settings:place")}' in datas


def test_toggle_on_second_page_rerenders_same_page():
    env = FakeEnv()
    items = grantable_items(ROOT)
    commands = [(i, it) for i, it in enumerate(items) if it.group == 'commands']
    idx, item = commands[hl.PAGE_SIZE]  # first item of page 1
    update = _make_update(ROOT, _cb(f'tg|commands|{idx}'))
    _run(env, hl.access_toggle, update, _context(TARGET))
    markup = update.callback_query.edit_message_reply_markup.call_args[1]['reply_markup']
    datas = _datas(markup)
    assert f'{ACCESS_INTENT_ID}|tg|commands|{idx}' in datas
    assert f'{ACCESS_INTENT_ID}|pg|commands|0' in datas  # previous-page arrow


def test_callback_data_within_telegram_limit():
    env = FakeEnv()
    for actor in (ROOT, ACTOR):
        for group in ('commands', 'settings', 'update', 'tech'):
            update = _make_update(actor, _cb(f'pg|{group}|0'))
            _run(env, hl.access_show_group, update, _context(TARGET))
            markup = update.callback_query.edit_message_text.call_args[1]['reply_markup']
            assert all(len(d.encode()) <= 64 for d in _datas(markup))


def test_users_list_and_pick():
    env = FakeEnv(access={TARGET: {'list', 'send_msg'}, ACTOR: {SETTINGS_DATABASE_KEY}})
    update = _make_update(ROOT, _cb('usr|0'))
    _run(env, hl.access_users_list, update, _context())
    markup = update.callback_query.edit_message_text.call_args[1]['reply_markup']
    assert f'@target ({TARGET}) — 2' in _texts(markup)
    assert f'{ACCESS_INTENT_ID}|pick|{TARGET}' in _datas(markup)
    # Entry screen has back-to-settings, not back-to-home
    assert 'Назад-2' in _datas(markup)

    update = _make_update(ROOT, _cb(f'pick|{TARGET}'))
    context = _context()
    _run(env, hl.access_pick_user, update, context)
    assert context.user_data[hl.TARGET_KEY] == TARGET
    assert update.callback_query.edit_message_text.called


def test_users_list_pagination():
    ids = list(range(1000, 1000 + hl.PAGE_SIZE + 3))
    env = FakeEnv(access={uid: {'list'} for uid in ids})
    update = _make_update(ROOT, _cb('usr|0'))
    _run(env, hl.access_users_list, update, _context())
    datas = _datas(update.callback_query.edit_message_text.call_args[1]['reply_markup'])
    assert len([d for d in datas if '|pick|' in d]) == hl.PAGE_SIZE
    assert f'{ACCESS_INTENT_ID}|usr|1' in datas

    update = _make_update(ROOT, _cb('usr|1'))
    _run(env, hl.access_users_list, update, _context())
    datas = _datas(update.callback_query.edit_message_text.call_args[1]['reply_markup'])
    assert len([d for d in datas if '|pick|' in d]) == 3
    assert f'{ACCESS_INTENT_ID}|usr|0' in datas
    # Entry screen has back-to-settings
    assert 'Назад-2' in _datas(update.callback_query.edit_message_text.call_args[1]['reply_markup'])


def test_users_list_empty():
    env = FakeEnv()
    update = _make_update(ROOT, _cb('usr|0'))
    _run(env, hl.access_users_list, update, _context())
    kwargs = update.callback_query.edit_message_text.call_args[1]
    assert 'никому' in kwargs['text']
    # Entry screen has ENTRY_TEXT prefix
    assert hl.ENTRY_TEXT in kwargs['text']


def test_pick_unknown_user():
    env = FakeEnv()
    update = _make_update(ROOT, _cb('pick|424242'))
    context = _context()
    _run(env, hl.access_pick_user, update, context)
    assert hl.TARGET_KEY not in context.user_data
    assert update.callback_query.answer.call_args[1]['show_alert'] is True


# ─── entry ─────────────────────────────────────────────────────────────────────

def test_access_start_shows_entry_screen_with_users():
    """access_start shows the entry screen with users list (merged)."""
    env = FakeEnv(access={TARGET: {'list'}, ACTOR: {SETTINGS_DATABASE_KEY}})
    update = _make_update(ROOT, 'access')
    context = _context(TARGET)
    state = _run(env, hl.access_start, update, context)
    assert state == hl.ACCESS_ASK_USER
    assert hl.TARGET_KEY not in context.user_data
    kwargs = update.callback_query.edit_message_text.call_args[1]
    assert hl.ENTRY_TEXT in kwargs['text']
    assert 'Пользователи с доступом' in kwargs['text']
    # Users with access are shown as buttons
    assert f'{ACCESS_INTENT_ID}|pick|{TARGET}' in _datas(kwargs['reply_markup'])
    assert 'Назад-2' in _datas(kwargs['reply_markup'])


def test_access_start_empty_users_list():
    """access_start shows 'no access' message when no users have grants."""
    env = FakeEnv()
    update = _make_update(ROOT, 'access')
    context = _context()
    state = _run(env, hl.access_start, update, context)
    assert state == hl.ACCESS_ASK_USER
    kwargs = update.callback_query.edit_message_text.call_args[1]
    assert hl.ENTRY_TEXT in kwargs['text']
    assert 'никому' in kwargs['text']
    assert 'Назад-2' in _datas(kwargs['reply_markup'])


def test_access_start_db_error_fallback():
    """access_start shows ENTRY_TEXT only if DB fails."""
    env = FakeEnv()
    update = _make_update(ROOT, 'access')
    context = _context()
    # Make list_users_with_access raise
    async def failing(*_):
        raise RuntimeError('DB down')
    async def _call():
        from handlers.command_mgmt import keyboards
        with _patches(env), patch.object(keyboards, 'list_users_with_access', side_effect=failing):
            return await hl.access_start(update, context)
    state = asyncio.run(_call())
    assert state == hl.ACCESS_ASK_USER
    kwargs = update.callback_query.edit_message_text.call_args[1]
    assert kwargs['text'] == hl.ENTRY_TEXT
    assert 'Назад-2' in _datas(kwargs['reply_markup'])


def test_access_start_denied_without_permission():
    env = FakeEnv(actor_allowed=False)
    update = _make_update(ACTOR, 'access')
    context = _context()
    context.user_data['STATE'] = 2
    state = _run(env, hl.access_start, update, context)
    assert state == 2
    assert not update.callback_query.edit_message_text.called


# ─── helpers ───────────────────────────────────────────────────────────────────

from handlers.command_mgmt.keyboards import _pager_row
from handlers.command_mgmt.parsers import _parse_target_input, _parse_toggle


def test_pager_row_single_page():
    assert _pager_row(0, 1, lambda p: f'pg|{p}') == []


def test_pager_row_zero_pages():
    assert _pager_row(0, 0, lambda p: f'pg|{p}') == []


def test_pager_row_first_page():
    btns = _pager_row(0, 3, lambda p: f'pg|{p}')
    assert len(btns) == 2
    assert btns[0].text == '1/3'
    assert btns[0].callback_data == 'noop'
    assert btns[1].text == '➡️'
    assert btns[1].callback_data == 'pg|1'


def test_pager_row_last_page():
    btns = _pager_row(2, 3, lambda p: f'pg|{p}')
    assert len(btns) == 2
    assert btns[0].text == '⬅️'
    assert btns[0].callback_data == 'pg|1'
    assert btns[1].text == '3/3'
    assert btns[1].callback_data == 'noop'


def test_pager_row_middle_page():
    btns = _pager_row(1, 3, lambda p: f'pg|{p}')
    assert len(btns) == 3
    assert btns[0].text == '⬅️'
    assert btns[1].text == '2/3'
    assert btns[1].callback_data == 'noop'
    assert btns[2].text == '➡️'


def test_parse_target_input_numeric():
    msg = MagicMock()
    msg.text = '12345'
    msg.forward_origin = None
    target_id, error = _parse_target_input(msg)
    assert target_id == 12345
    assert error is None


def test_parse_target_input_whitespace():
    msg = MagicMock()
    msg.text = '  12345  '
    msg.forward_origin = None
    target_id, error = _parse_target_input(msg)
    assert target_id == 12345
    assert error is None


def test_parse_target_input_non_numeric():
    msg = MagicMock()
    msg.text = 'abc'
    msg.forward_origin = None
    target_id, error = _parse_target_input(msg)
    assert target_id is None
    assert 'user_id' in error


def test_parse_target_input_too_long():
    msg = MagicMock()
    msg.text = '1' * 40
    msg.forward_origin = None
    target_id, error = _parse_target_input(msg)
    assert target_id is None
    assert error is not None


def test_parse_target_input_forwarded():
    sender = MagicMock(id=999)
    origin = MagicMock()
    origin.sender_user = sender
    msg = MagicMock()
    msg.text = None
    msg.forward_origin = origin
    target_id, error = _parse_target_input(msg)
    assert target_id == 999
    assert error is None


def test_parse_target_input_hidden_profile():
    origin = MagicMock(spec=['sender_user_name'])
    origin.sender_user_name = 'Hidden'
    msg = MagicMock()
    msg.text = None
    msg.forward_origin = origin
    target_id, error = _parse_target_input(msg)
    assert target_id is None
    assert 'user_id' in error


def test_parse_toggle_valid():
    items = grantable_items(ROOT)
    item = _parse_toggle(f'tg|commands|0', items)
    assert item is not None
    assert item.group == 'commands'


def test_parse_toggle_stale_index():
    items = grantable_items(ROOT)
    item = _parse_toggle(f'tg|commands|9999', items)
    assert item is None


def test_parse_toggle_group_mismatch():
    items = grantable_items(ROOT)
    # index 0 is in commands, not settings
    item = _parse_toggle(f'tg|settings|0', items)
    assert item is None


def test_parse_toggle_malformed():
    items = grantable_items(ROOT)
    assert _parse_toggle('noop', items) is None
    assert _parse_toggle('tg|only', items) is None
    assert _parse_toggle('tg|group|abc', items) is None


def test_require_actor_preserves_name():
    @hl._require_actor
    async def my_handler(update, context):
        """My doc."""
        return 42
    assert my_handler.__name__ == 'my_handler'
    assert my_handler.__doc__ == 'My doc.'


def test_require_actor_denied():
    env = FakeEnv(actor_allowed=False)

    @hl._require_actor
    async def my_handler(update, context):
        return 42

    update = _make_update(ACTOR, 'access')
    state = _run(env, my_handler, update, _context())
    assert state == hl.ACCESS_ASK_USER


def test_require_actor_allowed():
    env = FakeEnv()

    @hl._require_actor
    async def my_handler(update, context):
        return 42

    update = _make_update(ROOT, 'access')
    state = _run(env, my_handler, update, _context())
    assert state == 42


# ─── Reload menu ──────────────────────────────────────────────────────────────

def test_reload_menu_button_in_groups():
    """The groups screen includes the reload menu button."""
    env = FakeEnv()
    update = _make_update(ACTOR, _cb('grp'))
    context = _context(TARGET)

    with _patches(env):
        text, markup = asyncio.run(hl._render_groups(ACTOR, TARGET, '@target (222222222)', object()))
    btn_texts = [btn.text for btn in _buttons(markup)]
    assert '🔄 Перезагрузить меню' in btn_texts


def test_reload_menu_success():
    """Reload menu calls bot.set_my_commands for the target user."""
    env = FakeEnv()
    update = _make_update(ACTOR, _cb('reload_menu'))
    context = _context(TARGET)
    context.bot = MagicMock()
    context.bot.set_my_commands = AsyncMock()

    def fake_menu(uid, session):
        from telegram import BotCommand
        return [BotCommand('list', 'Список')]
    with _patches(env), patch.object(hl, 'get_user_menu_commands', new_callable=AsyncMock) as mock_menu:
        mock_menu.return_value = fake_menu(TARGET, object())
        state = _run(env, hl.access_reload_menu, update, context)

    assert state == hl.ACCESS_ASK_USER
    context.bot.set_my_commands.assert_called_once()
    call_kwargs = context.bot.set_my_commands.call_args[1]
    assert call_kwargs['scope'].chat_id == TARGET
    assert update.callback_query.answer.called


def test_reload_menu_privileged_target():
    """Reload menu for a privileged target shows an alert."""
    env = FakeEnv()
    update = _make_update(ACTOR, _cb('reload_menu'))
    context = _context(ROOT)

    with _patches(env):
        state = _run(env, hl.access_reload_menu, update, context)

    assert state == hl.ACCESS_ASK_USER
    assert update.callback_query.answer.called
    assert 'полный доступ' in update.callback_query.answer.call_args[0][0].lower()


def test_reload_menu_no_target():
    """Reload menu without a selected target asks to pick a user."""
    env = FakeEnv()
    update = _make_update(ACTOR, _cb('reload_menu'))
    context = _context()  # no target

    with _patches(env):
        state = _run(env, hl.access_reload_menu, update, context)

    assert state == hl.ACCESS_ASK_USER
    assert update.callback_query.answer.called


# ─── get_user_menu_commands ───────────────────────────────────────────────────

def test_get_user_menu_commands_privileged():
    """Privileged user gets all in_menu commands."""
    from permissions import get_user_menu_commands

    # Mark one command as in_menu
    with patch.dict('settings.settings.COMMAND_DICT', {}, clear=False) as d:
        pass  # just use existing

    async def _run():
        # ROOT is privileged
        result = await get_user_menu_commands(ROOT, None)
        # Only commands with in_menu=True should appear
        from settings.settings import COMMAND_DICT
        menu_entries = [e for e in COMMAND_DICT.values() if e.in_menu]
        assert len(result) == len(menu_entries)

    asyncio.run(_run())


def test_get_user_menu_commands_regular_no_grants():
    """Regular user with no grants gets only public in_menu commands."""
    from permissions import get_user_menu_commands

    async def _run():
        result = await get_user_menu_commands(TARGET, None)
        from settings.settings import COMMAND_DICT
        public_menu = [e for e in COMMAND_DICT.values() if e.in_menu and e.public]
        assert len(result) == len(public_menu)

    asyncio.run(_run())


def test_get_user_menu_commands_regular_with_grant():
    """Regular user with a grant gets that command if in_menu."""
    from permissions import get_user_menu_commands

    async def _run():
        session = AsyncMock()
        # Simulate grant for 'list'
        with patch.object(permissions, 'get_user_access', new_callable=AsyncMock) as mock_access:
            mock_access.return_value = {'list'}
            result = await get_user_menu_commands(TARGET, session)
            cmd_names = [cmd.command for cmd in result]
            # 'list' should be included if it has in_menu=True
            from settings.settings import COMMAND_DICT
            if COMMAND_DICT['LIST'].in_menu:
                assert 'list' in cmd_names

    asyncio.run(_run())


# ─── Derived /settings grant ──────────────────────────────────────────────────

def test_granting_first_settings_section_auto_grants_settings():
    """Granting settings:schedule_event also grants the 'settings' command."""
    env = FakeEnv()
    key = 'settings:schedule_event'
    idx = _idx(ROOT, key)
    cb = _cb(f'tg|settings|{idx}')

    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))

    assert key in env.access[TARGET]
    assert 'settings' in env.access[TARGET]
    # The answer should mention the derived grant
    answer_text = update.callback_query.answer.call_args[0][0]
    assert '+ /settings' in answer_text


def test_granting_second_settings_section_no_duplicate_settings():
    """Granting a second settings:* section does not re-grant 'settings'."""
    env = FakeEnv(access={TARGET: {'settings'}})
    key = 'settings:schedule_event'
    idx = _idx(ROOT, key)
    cb = _cb(f'tg|settings|{idx}')

    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))

    assert key in env.access[TARGET]
    assert 'settings' in env.access[TARGET]
    # 'settings' should appear in grant_calls only if it wasn't already present
    settings_grant_calls = [c for c in env.grant_calls if c[1] == 'settings']
    assert len(settings_grant_calls) == 0


def test_revoking_last_settings_section_auto_revokes_settings():
    """Revoking the last settings:* section also revokes the 'settings' command."""
    env = FakeEnv(access={TARGET: {'settings:schedule_event', 'settings'}})
    key = 'settings:schedule_event'
    idx = _idx(ROOT, key)
    cb = _cb(f'tg|settings|{idx}')

    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))

    assert key not in env.access[TARGET]
    assert 'settings' not in env.access[TARGET]
    answer_text = update.callback_query.answer.call_args[0][0]
    assert '− /settings' in answer_text


def test_revoking_non_last_settings_section_keeps_settings():
    """Revoking one settings:* section (when others remain) keeps 'settings'."""
    env = FakeEnv(access={TARGET: {
        'settings:schedule_event', 'settings:place', 'settings'
    }})
    key = 'settings:schedule_event'
    idx = _idx(ROOT, key)
    cb = _cb(f'tg|settings|{idx}')

    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))

    assert key not in env.access[TARGET]
    assert 'settings:place' in env.access[TARGET]
    assert 'settings' in env.access[TARGET]
    # No derived revoke note
    answer_text = update.callback_query.answer.call_args[0][0]
    assert '− /settings' not in answer_text


def test_non_settings_toggle_no_derived_grant():
    """Toggling a non-settings item does not touch the 'settings' command."""
    env = FakeEnv(access={TARGET: {'settings'}})
    idx = _idx(ROOT, 'list')
    cb = _cb(f'tg|commands|{idx}')

    update = _make_update(ROOT, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))

    assert 'list' in env.access[TARGET]
    assert 'settings' in env.access[TARGET]
    answer_text = update.callback_query.answer.call_args[0][0]
    assert '/settings' not in answer_text


def test_derived_settings_grant_works_for_delegated_actor():
    """Non-privileged actor with settings:database can trigger derived grant."""
    env = FakeEnv()
    key = 'settings:place'
    idx = _idx(ACTOR, key)
    cb = _cb(f'tg|settings|{idx}')

    update = _make_update(ACTOR, cb)
    _run(env, hl.access_toggle, update, _context(TARGET))

    assert key in env.access[TARGET]
    assert 'settings' in env.access[TARGET]
