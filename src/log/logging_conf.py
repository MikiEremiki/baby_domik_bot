import pathlib
import os
import logging.handlers

log_folder_name = 'archive'
log_filename = 'log.txt'
postgres_log_filename = 'postgres_log.txt'
parent_dir = pathlib.Path(__file__).parent
absolute_path = pathlib.Path(pathlib.Path.joinpath(parent_dir,
                                                   log_folder_name))
LOG_FILENAME = pathlib.Path(pathlib.Path.joinpath(absolute_path,
                                                  log_filename))
POSTGRES_LOG_FILENAME = pathlib.Path(pathlib.Path.joinpath(absolute_path,
                                                           postgres_log_filename))
if not absolute_path.exists():
    os.mkdir(log_folder_name)

bf = logging.Formatter('{asctime:16s}|{name:20s}|{levelname:8s}|{message}',
                       datefmt='%y%m%d %H:%M:%S',
                       style='{')


class NoParsingFilter(logging.Filter):
    def filter(self, record):
        if (record.getMessage().find('Entering: get_updates') >= 0 or
                record.getMessage().find('Exiting: get_updates') >= 0 or
                record.getMessage().find('No new updates found.') >= 0 or
                record.getMessage().find("'allowed_updates'") >= 0 or
                record.getMessage().find('finished with return value `[]`') >= 0 or
                record.getMessage().find('()') >= 0):
            return False
        if 'sqlalchemy' in record.name:
            return False
        return True


def setup_logs():
    root = logging.getLogger()
    main_log_handler = logging.handlers.RotatingFileHandler(LOG_FILENAME,
                                                            mode='w',
                                                            maxBytes=10000000,
                                                            backupCount=20,
                                                            encoding='utf-8')
    main_log_handler.setFormatter(bf)
    main_log_handler.addFilter(NoParsingFilter())

    root.addHandler(main_log_handler)

    logger = logging.getLogger('bot')
    logger.setLevel(logging.DEBUG)

    logger_ext_bot = logging.getLogger("telegram.ext.ExtBot")
    logger_ext_bot.setLevel(logging.DEBUG)

    postgres_log_handler = logging.handlers.RotatingFileHandler(
        POSTGRES_LOG_FILENAME,
        mode='w',
        maxBytes=2048000,
        backupCount=10,
        encoding='utf-8')
    postgres_log_handler.setFormatter(bf)

    logger_postgres = logging.getLogger('sqlalchemy.engine')
    logger_postgres.setLevel(logging.DEBUG)
    logger_postgres.addHandler(postgres_log_handler)

    return logger
