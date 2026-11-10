from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import TheaterEvent
import sqlalchemy as sa

from .states import SALES_PAGE_SIZE
from utilities.utl_kbd import (
    add_intent_id, adjust_kbd, add_btn_back_and_cancel,
)


async def fetch_active_theaters(session) -> List[TheaterEvent]:
    """Fetch all active repertoire theater events ordered by ID."""
    rows = (await session.execute(
        sa.select(TheaterEvent)
        .where(TheaterEvent.flag_active_repertoire == True)
        .order_by(TheaterEvent.id)
    )).scalars().all()
    return rows


def paginate_list(items: list, page: int, page_size: int):
    """Return (page_items, page1, pages_total) for a paginated list."""
    total = len(items)
    pages_total = max(1, (total + page_size - 1) // page_size)
    page1 = max(1, min(page, pages_total))
    start_idx = (page1 - 1) * page_size
    end_idx = min(start_idx + page_size, total)
    return items[start_idx:end_idx], page1, pages_total


def build_theater_selection_text(
    page_theaters: list,
    selected_ids: set,
    title: str,
    hint: str,
    page: int,
    pages_total: int,
    use_real_id: bool = True,
) -> str:
    """Build numbered list text with ✅/▫️ markers for theater selection."""
    lines: List[str] = [f'<b>{title}</b>']
    if pages_total > 1:
        lines.append(f'Стр. {page}/{pages_total}. {hint}')
    else:
        lines.append(hint)

    for idx, t in enumerate(page_theaters, start=1):
        tid = int(t['id']) if isinstance(t, dict) else int(t.id)
        name = t['name'] if isinstance(t, dict) else t.name
        mark = '✅' if tid in selected_ids else '▫️'
        if use_real_id:
            lines.append(f"{tid}. {mark} {name}")
        else:
            lines.append(f"{idx}. {mark} {name}")
    lines.append('')
    lines.append('')
    return '\n'.join(lines)


def build_theater_keyboard(
    page_theaters: list,
    intent_id: str,
    page: int,
    pages_total: int,
    rows_per_row: int = 6,
    *,
    use_real_id: bool = True,
    done_label: str = None,
    done_callback_data: str = 'done',
    back_postfix: str = None,
    page_callback_prefix: str = 'page',
) -> InlineKeyboardMarkup:
    """Build inline keyboard for theater selection with pagination."""
    kb_btns: List[InlineKeyboardButton] = []
    for t in page_theaters:
        tid = int(t['id']) if isinstance(t, dict) else int(t.id)
        kb_btns.append(InlineKeyboardButton(str(tid), callback_data=str(tid)))

    btn_rows = adjust_kbd(kb_btns, rows_per_row)
    btn_rows = add_intent_id(btn_rows, intent_id)

    final_kb: List[List[InlineKeyboardButton]] = list(btn_rows)

    # Pagination nav
    if pages_total > 1:
        nav_row: List[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(InlineKeyboardButton('« Пред', callback_data=f"{page_callback_prefix}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f'{page}/{pages_total}', callback_data=f"{page_callback_prefix}:{page}"))
        if page < pages_total:
            nav_row.append(InlineKeyboardButton('След »', callback_data=f"{page_callback_prefix}:{page + 1}"))
        final_kb.extend(add_intent_id([nav_row], intent_id))

    # Done button
    if done_label:
        done_row = add_intent_id(
            [[InlineKeyboardButton(done_label, callback_data=done_callback_data)]],
            intent_id
        )
        final_kb.extend(done_row)

    # Back + Cancel
    final_kb.append(add_btn_back_and_cancel(
        postfix_for_cancel='sales',
        add_back_btn=True,
        postfix_for_back=back_postfix,
    ))

    return InlineKeyboardMarkup(final_kb)


async def _show_step(
    update,
    context,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    state: str,
) -> str:
    """Render a wizard step by editing the current step message."""
    from telegram.error import BadRequest
    from utilities.utl_func import set_back_context
    from utilities.utl_tg import is_not_modified

    sales_state = context.user_data.setdefault('sales', {})
    chat_id = update.effective_chat.id
    step_msg_id = sales_state.get('step_msg_id')

    edited = False
    if step_msg_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=step_msg_id,
                text=text,
                reply_markup=reply_markup,
            )
            edited = True
        except BadRequest as e:
            if "Message to edit not found" in str(e) or is_not_modified(e):
                if is_not_modified(e):
                    edited = True
            else:
                raise

    if not edited:
        sent = await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None),
        )
        sales_state['step_msg_id'] = sent.message_id

        if update.callback_query:
            try:
                await update.callback_query.answer()
            except BadRequest:
                pass

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def _safe_edit_message(query, text: str):
    import logging
    from utilities.utl_tg import safe_edit_text, safe_edit_caption

    sales_logger = logging.getLogger('bot.sales')
    msg = getattr(query, 'message', None)
    if msg is not None and (
            getattr(msg, 'photo', None) or
            getattr(msg, 'video', None) or
            getattr(msg, 'animation', None)
    ):
        await safe_edit_caption(query, caption=text, logger=sales_logger)
    else:
        await safe_edit_text(query, text=text, logger=sales_logger)
