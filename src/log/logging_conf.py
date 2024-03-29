import pathlib
import os
import logging.handlers

log_folder_name = 'archive'
log_filename = 'log.txt'
parent_dir = pathlib.Path(__file__).parent
absolute_path = pathlib.Path(pathlib.Path.joinpath(parent_dir,
                                                   log_folder_name))
LOG_FILENAME = pathlib.Path(pathlib.Path.joinpath(absolute_path,
                                                  log_filename))
if not absolute_path.exists():
    os.mkdir(log_folder_name)


class NoParsingFilter(logging.Filter):
    def filter(self, record):
        if (record.getMessage().find('Entering: get_updates') >= 0 or
                record.getMessage().find('Exiting: get_updates') >= 0 or
                record.getMessage().find('No new updates found.') >= 0 or
                record.getMessage().find('()') >= 0):
            return False
        return True


def load_log_config():
    root = logging.getLogger()
    bf = logging.Formatter('{asctime:16s}|{name:20s}|{levelname:8s}|{message}',
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

    logger_ext_bot = logging.getLogger("telegram.ext.ExtBot")
    logger_ext_bot.setLevel(logging.DEBUG)
    logger_ext_bot.addFilter(NoParsingFilter())

    return logger
