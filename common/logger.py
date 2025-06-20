import logging
import os
import sys
from logging import StreamHandler, Formatter, Logger as _LoggerClass
from logging.handlers import RotatingFileHandler


class Logger:
    """
    全局 Logger 单例，支持控制台输出和彩色日志以及文件滚动。

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
        # 始终返回同一个实例
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
        初始化全局 logger，只执行一次（除非 force=True 强制重置）。

        参数：
        - level: 日志级别，优先级高于环境变量
        - log_file: 日志文件路径，如果不需要文件输出可传入 None 或 ''
        - max_bytes, backup_count: 滚动文件配置
        - console: 是否输出到控制台
        - colored: 控制台输出是否启用彩色（依赖 colorlog）
        - force: 是否强制重新配置
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

        # 先确定最终生效的日志级别
        env = os.getenv('LOG_LEVEL') or ('DEBUG' if os.getenv('DEBUG') else 'INFO')
        effective_level = level or getattr(logging, env.upper(), logging.INFO)

        logger = logging.getLogger()
        if force:
            # 移除已有 handler
            for handler in list(logger.handlers):
                logger.removeHandler(handler)

        # 设置根 logger 级别
        logger.setLevel(effective_level)

        # 日志格式，包含毫秒、文件行号、函数名、线程 ID
        base_fmt = (
            "%(asctime)s.%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d %(funcName)s] "
            "[Thread-%(thread)d] %(message)s"
        )
        datefmt = "%Y-%m-%d %H:%M:%S"

        # 控制台输出
        if console:
            if colored:
                try:
                    from colorlog import ColoredFormatter
                    log_colors = {
                        'DEBUG': 'cyan',
                        'INFO': 'green',
                        'WARNING': 'yellow',
                        'ERROR': 'red',
                        'CRITICAL': 'bold_red'
                    }
                    fmt = "%(log_color)s" + base_fmt
                    handler = StreamHandler(sys.stdout)
                    handler.setLevel(effective_level)
                    handler.setFormatter(ColoredFormatter(fmt, datefmt=datefmt, log_colors=log_colors))
                except ImportError:
                    handler = StreamHandler(sys.stdout)
                    handler.setLevel(effective_level)
                    handler.setFormatter(Formatter(base_fmt, datefmt=datefmt))
            else:
                handler = StreamHandler(sys.stdout)
                handler.setLevel(effective_level)
                handler.setFormatter(Formatter(base_fmt, datefmt=datefmt))
            logger.addHandler(handler)

        # 文件输出
        if log_file:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)) or '.', exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(effective_level)
            file_handler.setFormatter(Formatter(base_fmt, datefmt=datefmt))
            logger.addHandler(file_handler)

        cls._configured = True
        cls._instance = logger

    @classmethod
    def get(cls) -> _LoggerClass:
        """获取已初始化的全局 Logger 实例"""
        if cls._instance is None or not cls._configured:
            raise RuntimeError("Logger 尚未初始化，请先调用 Logger.init()")
        return cls._instance


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
