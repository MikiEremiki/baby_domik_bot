"""Keyboard builders and screen renderers for command management UI.

Provides the three main screens:
    - Entry screen: paginated list of users with access
    - Groups screen: command groups for a selected user
    - Group screen: toggleable items within one group
"""
from typing import Callable

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from db import db_postgres
from handlers.command_mgmt.parsers import _intent_cb
from permissions import (
    ACCESS_GROUPS, is_privileged, grantable_items, list_users_with_access,
    get_user_access_or_empty,
)
from settings.settings import ACCESS_INTENT_ID
from utilities.utl_kbd import add_btn_back_and_cancel, add_intent_id

PAGE_SIZE = 8

ENTRY_TEXT = 'Введите user_id или перешлите сообщение пользователя'
GROUP_TITLES = dict(ACCESS_GROUPS)


def _user_label(user_id: int, username: str | None) -> str:
    return f'@{username} ({user_id})' if username else str(user_id)


def _chunk_pages(total: int) -> int:
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def _nav_row(back_payload: str) -> list:
    return [InlineKeyboardButton('Назад', callback_data=_intent_cb(back_payload))]


def _cancel_row() -> list:
    return add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=False)


def _pager_row(
    page: int, pages: int, cb_for_page: Callable[[int], str]
) -> list[InlineKeyboardButton]:
    """Build a pagination row: ⬅️ / n/m (noop) / ➡️.

    Returns [] when pages <= 1.
    """
    if pages <= 1:
        return []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton('⬅️', callback_data=cb_for_page(page - 1)))
    nav.append(InlineKeyboardButton(f'{page + 1}/{pages}', callback_data='noop'))
    if page < pages - 1:
        nav.append(InlineKeyboardButton('➡️', callback_data=cb_for_page(page + 1)))
    return nav


async def _get_grants(target_id: int, session) -> set:
    """Wrapper around get_user_access_or_empty for command_mgmt."""
    return await get_user_access_or_empty(target_id, session)


async def _render_entry(
    page: int, session
) -> tuple[str, InlineKeyboardMarkup]:
    """Entry screen: prompt + paginated list of users with access.

    Shows ENTRY_TEXT, then user buttons (or 'no access' message), pagination,
    and 'Назад/Отменить' returning to the 'База данных' menu.
    """
    users = await list_users_with_access(session)
    pages = _chunk_pages(len(users))
    page = max(0, min(page, pages - 1))
    subset = users[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    usernames = await db_postgres.get_usernames_by_ids(
        session, [uid for uid, _ in subset])

    if users:
        text = f'{ENTRY_TEXT}\n\nПользователи с доступом: {len(users)}'
    else:
        text = f'{ENTRY_TEXT}\n\nПока никому не выдан доступ.'

    rows = [[InlineKeyboardButton(
        f'{_user_label(uid, usernames.get(uid))} — {count}',
        callback_data=f'pick|{uid}')] for uid, count in subset]

    if pages > 1:
        rows.append(_pager_row(page, pages, lambda p: f'usr|{p}'))

    keyboard = add_intent_id(rows, ACCESS_INTENT_ID)
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='settings', postfix_for_back='2'))
    return text, InlineKeyboardMarkup(keyboard)


async def _render_groups(
    actor_id: int, target_id: int, label: str, session
) -> tuple[str, InlineKeyboardMarkup]:
    text = f'Пользователь: {label}\n\n'
    keyboard = []

    if is_privileged(target_id):
        text += 'Пользователь имеет полный доступ (root/super_admin), настройка не требуется.'
    else:
        text += 'Выберите группу:'
        granted = await _get_grants(target_id, session)
        items = grantable_items(actor_id)
        rows = []
        for group, title in ACCESS_GROUPS:
            group_items = [i for i in items if i.group == group]
            if not group_items:
                continue
            count = sum(1 for i in group_items if i.key in granted)
            rows.append([InlineKeyboardButton(
                f'{title} ({count}/{len(group_items)})',
                callback_data=f'pg|{group}|0')])
        keyboard = add_intent_id(rows, ACCESS_INTENT_ID)

    # Кнопка «Перезагрузить меню» для целевого пользователя
    keyboard.append([InlineKeyboardButton(
        '🔄 Перезагрузить меню', callback_data=_intent_cb('reload_menu'))])
    keyboard.append(_nav_row('home'))
    keyboard.append(_cancel_row())
    return text, InlineKeyboardMarkup(keyboard)


async def _render_group(
    actor_id: int, target_id: int, label: str, group: str, page: int,
    session
) -> tuple[str, InlineKeyboardMarkup]:
    granted = await _get_grants(target_id, session)
    indexed = [(idx, item) for idx, item in enumerate(grantable_items(actor_id))
               if item.group == group]
    pages = _chunk_pages(len(indexed))
    page = max(0, min(page, pages - 1))
    subset = indexed[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    rows = []
    for idx, item in subset:
        mark = '✅' if item.key in granted else '⬜'
        rows.append([InlineKeyboardButton(
            f'{mark} {item.label}', callback_data=f'tg|{group}|{idx}')])

    if pages > 1:
        rows.append(_pager_row(page, pages, lambda p: f'pg|{group}|{p}'))

    keyboard = add_intent_id(rows, ACCESS_INTENT_ID)
    keyboard.append(_nav_row('grp'))
    keyboard.append(_cancel_row())

    text = (f'{GROUP_TITLES.get(group, group)}\n'
            f'Пользователь: {label}\n'
            f'Нажмите на пункт, чтобы выдать (✅) или забрать (⬜) доступ.')
    return text, InlineKeyboardMarkup(keyboard)
