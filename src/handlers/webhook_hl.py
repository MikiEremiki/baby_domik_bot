from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import TypeHandler, ContextTypes
from yookassa.domain.notification import WebhookNotification

from settings.settings import CHAT_ID_MIKIEREMIKI


async def webhook_update(update: WebhookNotification,
                         context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(CHAT_ID_MIKIEREMIKI, update.json())
    if update.object.status == 'pending':
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI,
                                       'Платеж ожидает оплаты')
    if update.object.status == 'waiting_for_capture':
        pass  # Для двух стадийной оплаты
    if update.object.status == 'succeeded':
        message_id = update.object.metadata['message_id']
        chat_id = update.object.metadata['chat_id']

        await context.bot.edit_message_reply_markup(chat_id, message_id)

        text = ('Платеж успешно обработан\n\n'
                'Нажмите <b>«ДАЛЕЕ»</b> под сообщением\n\n'
                '<i>Или отправьте квитанцию/чек об оплате</i>')
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton('ДАЛЕЕ', callback_data='Next')]])
        await context.bot.send_message(chat_id=chat_id,
                                       text=text,
                                       reply_markup=reply_markup)
        state = 'PAID'
        return state
    if update.object.status == 'canceled':
        pass


WebhookHandler = TypeHandler(WebhookNotification, webhook_update)
