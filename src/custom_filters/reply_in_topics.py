from telegram.ext.filters import MessageFilter

from settings.settings import FEEDBACK_THREAD_ID_GROUP_ADMIN


class ReplyInTopicFromBotFilter(MessageFilter):
    def filter(self, message):
        reply_msg = message.reply_to_message
        if hasattr(reply_msg, 'text'):
            return (reply_msg.text and
                    reply_msg.from_user.is_bot and
                    message.message_thread_id == FEEDBACK_THREAD_ID_GROUP_ADMIN)
        else:
            return False


REPLY_IN_TOPIC_FROM_BOT = ReplyInTopicFromBotFilter(
    name='custom_filters.REPLY_IN_TOPIC')
