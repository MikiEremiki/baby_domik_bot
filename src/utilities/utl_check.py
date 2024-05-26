import re

from db import db_postgres
from handlers.sub_hl import sub_hl_logger, send_request_email, send_agreement


def check_available_seats(schedule_event, only_child=False):
    qty_child = schedule_event.qty_child_free_seat
    qty_adult = schedule_event.qty_adult_free_seat

    check_qty_child = qty_child > 0
    check_qty_adult = qty_adult > 0
    if only_child:
        check_qty_adult = True

    return check_qty_child and check_qty_adult


def check_available_ticket_by_free_seat(schedule_event,
                                        ticket,
                                        only_child=False):
    quality_child = ticket.quality_of_children
    quality_adults = ticket.quality_of_adult + ticket.quality_of_add_adult
    quality_child_free = schedule_event.qty_child_free_seat
    quality_adults_free = schedule_event.qty_adult_free_seat

    check_child = quality_child_free >= quality_child
    check_adult = quality_adults_free >= quality_adults
    if only_child:
        check_adult = True

    check_ratio_child_and_adult = True
    if quality_adults > 0:
        delta_ticket = quality_adults - quality_child
        delta_free = quality_adults_free - quality_child_free

        check_ratio_child_and_adult = delta_ticket <= delta_free

    return check_child and check_adult and check_ratio_child_and_adult


def check_email(email: str):
    return re.fullmatch(r"^[-a-z0-9!#$%&'*+/=?^_`{|}~]+"
                        r"(?:\.[-a-z0-9!#$%&'*+/=?^_`{|}~]+)*"
                        r"@(?:[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?\.)*"
                        r"(?:aero|arpa|asia|biz|cat|com|coop|"
                        r"edu|gov|info|int|jobs|mil|mobi|museum|"
                        r"name|net|org|pro|tel|travel|[a-z][a-z])$",
                        email.lower())


def check_entered_command(context, command_to_check):
    return context.user_data.get('command', False) == command_to_check


async def check_topic(update, context):
    thread_id = None
    if context.user_data['command'] == 'list':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Списки на показы', None))
    if context.user_data['command'] == 'list_wait':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Лист ожидания', None))
    if update.effective_message.message_thread_id != thread_id:
        await update.effective_message.reply_text(
            'Выполните команду в правильном топике')
        return False
    else:
        return True


async def check_input_text(text):
    count = text.count('\n')
    result = re.findall(
        r'\w+ \d',
        text,
        flags=re.U | re.M
    )
    if len(result) <= count:
        sub_hl_logger.info('Не верный формат текста')
        return False
    return True


async def check_and_get_agreement(update, context):
    user = await db_postgres.get_user(context.session, update.effective_chat.id)
    if user.agreement_received:
        text, reply_markup = await send_request_email(update, context)
        state = 'EMAIL'
    else:
        text, reply_markup = await send_agreement(update, context)
        state = 'OFFER'
    return reply_markup, state, text


def is_skip_ticket(ticket_status):
    if ticket_status == 'Создан' or ticket_status == 'Отменен':
        return True
    return False
