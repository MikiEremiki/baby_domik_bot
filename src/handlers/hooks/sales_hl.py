import logging

from telegram.error import BadRequest
from telegram.ext import TypeHandler, ContextTypes

from api.broker_nats import SalesReportData
from handlers.sales_hl import sales_logger
from settings.settings import ADMIN_GROUP, FEEDBACK_THREAD_ID_GROUP_ADMIN

saleshook_logger = logging.getLogger('bot.saleshook')


async def sales_hook_update(update: SalesReportData, context: 'ContextTypes.DEFAULT_TYPE'):
    """Receive sales_report messages and notify admins."""
    try:
        action = update.data.get('action')
        campaign_id = update.data.get('campaign_id')
        status = update.data.get('status')
        totals = update.data.get('totals', {}) or {}
        text = None
        if action == 'sales_done':
            sent = totals.get('sent', 0)
            failed = totals.get('failed', 0)
            blocked = totals.get('blocked', 0)
            text = (
                f'Рассылка завершена (кампания #{campaign_id}).\n'
                f'Статус: {status}.\n'
                f'Итоги: отправлено — {sent}, ошибок — {failed}, блокировок — {blocked}.'
            )
        elif action == 'sales_failed':
            text = f'Рассылка завершилась ошибкой (кампания #{campaign_id}). Статус: {status}.'
        else:
            # Unknown action; log and ignore
            saleshook_logger.info('Unknown sales_report action: %s | payload=%s', action, update)
            return

        # Prefer sending report to the admin who created the campaign (if provided)
        target_chat_id = update.data.get('chat_id') or ADMIN_GROUP
        kwargs = {}
        # Use thread only for group fallback; for direct chat ignore thread id
        if target_chat_id == ADMIN_GROUP:
            kwargs['message_thread_id'] = FEEDBACK_THREAD_ID_GROUP_ADMIN
        await context.bot.send_message(
            chat_id=target_chat_id,
            text=text,
            **kwargs
        )
    except BadRequest as e:
        saleshook_logger.error('Failed to send sales report to admin: %s', e)
        saleshook_logger.info('Payload: %s', update)
    except Exception as e:
        saleshook_logger.exception('Unexpected error in saleshook_update: %s | payload=%s', e, update)


SalesHookHandler = TypeHandler(SalesReportData, sales_hook_update)
