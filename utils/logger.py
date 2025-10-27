import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

try:
    import colorlog
    COLOR_SUPPORT = True
except ImportError:
    COLOR_SUPPORT = False

LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_LEVEL = "INFO"
LOG_FILE_NAME = "medkg_extractor.log"
LOG_FILE_PATH = LOG_DIR / LOG_FILE_NAME

CONSOLE_LOG_FORMAT = (
    "%(log_color)s%(asctime)s - %(levelname)-8s - "
    "%(name)s:%(funcName)s:%(lineno)d - %(message)s"
)
FILE_LOG_FORMAT = (
    "%(asctime)s - %(levelname)-8s - "
    "%(name)s:%(funcName)s:%(lineno)d - %(message)s"
)

LOG_COLORS = {
    'DEBUG': 'cyan',
    'INFO': 'green',
    'WARNING': 'yellow',
    'ERROR': 'red',
    'CRITICAL': 'bold_red',
}


def setup_logger(name: str = "MedKG-Extractor", log_level: str = LOG_LEVEL) -> logging.Logger:
    """
    设置并返回一个配置好的日志记录器。

    该日志记录器将同时输出到控制台（带颜色）和按时间轮换的文件。

    Args:
        name (str): 日志记录器的名称，通常是模块或应用的名称。
        log_level (str): 要设置的最低日志级别 (e.g., 'DEBUG', 'INFO').

    Returns:
        logging.Logger: 配置好的日志记录器实例。
    """
    logger = logging.getLogger(name)
    
    level = logging.getLevelName(log_level.upper())
    logger.setLevel(level)

    if logger.hasHandlers():
        return logger

    console_handler = logging.StreamHandler(sys.stdout)
    if COLOR_SUPPORT:
        console_formatter = colorlog.ColoredFormatter(
            fmt=CONSOLE_LOG_FORMAT,
            log_colors=LOG_COLORS
        )
    else:
        console_formatter = logging.Formatter(fmt=FILE_LOG_FORMAT)
    
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(level)

    file_handler = TimedRotatingFileHandler(
        filename=LOG_FILE_PATH,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_formatter = logging.Formatter(fmt=FILE_LOG_FORMAT)
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(level)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger

if __name__ == '__main__':
    test_logger = logging.getLogger("MedKG-Extractor")
    
    print("--- Testing Logger ---")
    test_logger.debug("这是一个调试信息 (DEBUG)。")
    test_logger.info("这是一个普通信息 (INFO)。")
    test_logger.warning("这是一个警告信息 (WARNING)。")
    test_logger.error("这是一个错误信息 (ERROR)。")
    test_logger.critical("这是一个严重错误信息 (CRITICAL)。")
    
    print(f"\n日志文件已生成在: {LOG_FILE_PATH}")
    
    module_logger = setup_logger("Pipeline.Stage1")
    module_logger.info("这是来自特定模块的日志。")