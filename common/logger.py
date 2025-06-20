import logging
import os
import sys
from logging import StreamHandler, Formatter, Logger as _LoggerClass
from logging.handlers import RotatingFileHandler


class Logger:
    """
    全局 Logger 单例，支持控制台彩色输出和文件滚动。

    使用示例：
        Logger.init(
            level=logging.DEBUG,
            log_file='logs/app.log',
            colored=True
        )
        log = Logger.get()
        log.info('应用启动')
    """
    _instance: _LoggerClass = None
    _configured: bool = False

    def __new__(cls, *args, **kwargs):
        # 永远返回同一个实例
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def init(
            cls,
            level: int = None,
            log_file: str = "logs/app.log",
            max_bytes: int = 10_000_000,
            backup_count: int = 5,
            console: bool = True,
            colored: bool = False,
            force: bool = False
    ) -> None:
        """
        初始化全局 logger，只执行一次（或在 force=True 时重新配置）。
        - colored: 控制台彩色输出，依赖 colorlog 库
        - log_file: 指定单一日志文件路径
        """
        cls._configure(
            level=level,
            log_file=log_file,
            max_bytes=max_bytes,
            backup_count=backup_count,
            console=console,
            colored=colored,
            force=force
        )

    @classmethod
    def _configure(
            cls,
            level: int = None,
            log_file: str = "logs/app.log",
            max_bytes: int = 10_000_000,
            backup_count: int = 5,
            console: bool = True,
            colored: bool = False,
            force: bool = False
    ) -> None:
        """
        私有方法：配置全局 logger，只执行一次，除非 force=True。
        """
        if cls._configured and not force:
            return

        logger = logging.getLogger()
        if force:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
        logger.setLevel(logging.DEBUG)

        env = os.getenv('LOG_LEVEL') or ('DEBUG' if os.getenv('DEBUG') else 'INFO')
        level = level or getattr(logging, env.upper(), logging.INFO)

        # 更新格式，包含毫秒、行号、函数名、线程ID
        base_fmt = ("%(asctime)s.%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d %(funcName)s] [Thread-%("
                    "thread)d] %(message)s")
        _datefmt = "%Y-%m-%d %H:%M:%S"

        # 控制台输出
        if console:
            if colored:
                try:
                    from colorlog import ColoredFormatter
                    # 定义默认颜色映射
                    log_colors = {
                        'DEBUG': 'cyan',
                        'INFO': 'green',
                        'WARNING': 'yellow',
                        'ERROR': 'red',
                        'CRITICAL': 'bold_red'
                    }
                    color_fmt = "%(log_color)s" + base_fmt
                    stream_handler = StreamHandler(sys.stdout)
                    stream_handler.setLevel(level)
                    stream_handler.setFormatter(ColoredFormatter(
                        color_fmt,
                        datefmt=_datefmt,
                        log_colors=log_colors
                    ))
                except ImportError:
                    stream_handler = StreamHandler(sys.stdout)
                    stream_handler.setLevel(level)
                    stream_handler.setFormatter(Formatter(base_fmt, datefmt=_datefmt))
            else:
                stream_handler = StreamHandler(sys.stdout)
                stream_handler.setLevel(level)
                stream_handler.setFormatter(Formatter(base_fmt, datefmt=_datefmt))
            logger.addHandler(stream_handler)

        # 文件输出
        if log_file:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)) or '.', exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(Formatter(base_fmt, datefmt=_datefmt))
            logger.addHandler(file_handler)

        cls._configured = True
        cls._instance = logger


if __name__ == '__main__':
    # 示例：初始化 Logger
    Logger.init(
        level=logging.DEBUG,
        log_file='logs/app.log',
        max_bytes=10_000_000,
        backup_count=5,
        console=True,
        colored=True
    )

    # 测试日志输出
    logging.info('Logger 初始化成功')
    logging.debug('这是一个调试信息')
    logging.warning('这是一个警告信息')
    logging.error('这是一个错误信息')
    logging.critical('这是一个严重错误信息')
