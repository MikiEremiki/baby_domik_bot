import logging.handlers

LOG_FILENAME = 'log_debug\log.txt'


def load_log_config():
    root = logging.getLogger()
    bf = logging.Formatter('{asctime:16s}|{name:8s}|{levelname:8s}|{message}',
                           datefmt='%y%m%d %H:%M:%S',
                           style='{',
                           )
    handler = logging.handlers.RotatingFileHandler(LOG_FILENAME,
                                                   mode='w',
                                                   maxBytes=1024000,
                                                   backupCount=5,
                                                   encoding='utf-8',
                                                   )
    handler.setFormatter(bf)
    root.addHandler(handler)

    logger = logging.getLogger('bot')
    logger.setLevel(logging.DEBUG)

    logger2 = logging.getLogger('telegram.ext.ExtBot')
    logger2.name = 'ExtBot'
    logger2.setLevel(logging.DEBUG)
