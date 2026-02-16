from telegram.ext.filters import MessageFilter


class ReplyInTopicFromBotFilter(MessageFilter):
    def filter(self, message):
        return message.message_thread_id is not None


REPLY_IN_TOPIC_FROM_BOT = ReplyInTopicFromBotFilter(
    name='custom_filters.REPLY_IN_TOPIC')
