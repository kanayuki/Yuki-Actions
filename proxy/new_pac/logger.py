"""new_pac 日志：TimedRotatingFileHandler 30 日循环 + RichHandler。

特性：
- 文件 handler：when="midnight" 每日切分，backupCount=30 保留近 30 天
- 控制台 handler：Rich 美化（支持 [bold]/[cyan] 等 markup）
- propagate=False 防止 root logger 重复记录
- setup_logger() 幂等（重复调用先清空再装）
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from rich.logging import RichHandler

from .config import LOG_FILE, LOGS_DIR

LOGGER_NAME = "new_pac"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s  %(message)s"
BACKUP_COUNT = 30  # 保留最近 30 天日志


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    """配置 new_pac logger。

    Args:
        level: 日志级别（logging.INFO / DEBUG / WARNING / ERROR）

    Returns:
        配置好的 logger 实例
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False  # 避免重复打到 root

    # 清空已有 handler（main() 多次调用幂等）
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # 文件 handler：30 日循环
    fh = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(fh)

    # 控制台 handler：Rich 美化
    ch = RichHandler(rich_tracebacks=True, show_path=False, markup=True)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


def get_logger() -> logging.Logger:
    """获取已配置的 logger（不重新 setup，main() 调用 setup_logger 即可）。"""
    return logging.getLogger(LOGGER_NAME)


__all__ = ["setup_logger", "get_logger", "LOGGER_NAME", "BACKUP_COUNT"]
