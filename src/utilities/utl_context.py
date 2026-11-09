# Context management utilities for ConversationHandler cleanup.
#
# This module is kept separate from utl_func and utl_ticket to avoid
# a circular import: utl_ticket → utl_func → utl_ticket.


async def clean_context_on_end_handler(logger, context):
    """Clean up all known conversation state keys from context.user_data.

    Called at the end of a ConversationHandler to remove stale state.
    Logs the STATE key if present, then removes all known keys.

    :param logger: Logger instance for logging the STATE value.
    :param context: telegram.ext ContextTypes.DEFAULT_TYPE (has user_data dict).
    """
    if context.user_data.get('STATE', False):
        logger.info(
            f'Обработчик завершился на этапе {context.user_data["STATE"]}')
        context.user_data.pop('STATE')
    else:
        logger.info('STATE не задан')

    if context.user_data.get('command', False):
        context.user_data.pop('command')
    if context.user_data.get('common_data', False):
        context.user_data.pop('common_data')
    if context.user_data.get('birthday_user_data', False):
        context.user_data.pop('birthday_user_data')
    if context.user_data.get('reserve_user_data', False):
        context.user_data.pop('reserve_user_data')
    if context.user_data.get('reserve_admin_data', False):
        context.user_data.pop('reserve_admin_data')
    if context.user_data.get('editing_auto_sending', False):
        context.user_data.pop('editing_auto_sending')
    if context.user_data.get('new_auto_sending', False):
        context.user_data.pop('new_auto_sending')
