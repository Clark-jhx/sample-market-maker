import logging
from logging import handlers
from market_maker.settings import settings

# 设置log等级
def setup_custom_logger(name, log_level=settings.LOG_LEVEL):
    formatter = logging.Formatter(fmt='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(message)s')

    # 控制台输出
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # 文件输出,按照时间自动分割
    file_handler = handlers.TimedRotatingFileHandler(filename='temp.log', when='midnight', backupCount=30, utc='utf-8')
    file_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.addHandler(handler)
    logger.addHandler(file_handler)
    return logger
