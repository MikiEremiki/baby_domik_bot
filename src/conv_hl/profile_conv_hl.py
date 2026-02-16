from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler,
)

from conv_hl import (
    F_text_and_no_command, cancel_callback_handler, common_fallbacks,
)
from handlers import profile_hl

states = {
    profile_hl.MENU: [
        cancel_callback_handler,
        CallbackQueryHandler(profile_hl.select_add_type, pattern='^add_'),
        CallbackQueryHandler(profile_hl.profile_callback, pattern='^profile:'),
    ],
    profile_hl.PERSON_MENU: [
        cancel_callback_handler,
        CallbackQueryHandler(profile_hl.profile_callback, pattern='^profile:'),
    ],
    profile_hl.ADD_ADULT_NAME: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.add_adult_name),
    ],
    profile_hl.ADD_ADULT_PHONE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.add_adult_phone),
    ],
    profile_hl.ADD_CHILD_NAME: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.add_child_name),
    ],
    profile_hl.ADD_CHILD_AGE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.add_child_age),
    ],
    profile_hl.EDIT_NAME: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.set_new_name),
    ],
    profile_hl.EDIT_ADULT_PHONE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.set_new_adult_phone),
    ],
    profile_hl.EDIT_CHILD_AGE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, profile_hl.set_new_child_age),
    ],
    profile_hl.CONFIRM_DELETE: [
        cancel_callback_handler,
        CallbackQueryHandler(profile_hl.profile_callback, pattern='^profile:'),
    ],
}

profile_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler('profile', profile_hl.start_profile),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='profile',
    persistent=True,
    allow_reentry=True,
)
