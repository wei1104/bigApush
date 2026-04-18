"""
日志配置模块
提供集中的日志配置管理，使用QueueHandler避免日志操作阻塞主线程
"""

import logging
import logging.handlers
import queue
from pathlib import Path
from typing import Optional


class LogConfig:
    """日志配置管理类"""
    
    # 类变量，存储全局的QueueListener
    _queue_listener: Optional[logging.handlers.QueueListener] = None
    _log_queue: Optional[queue.Queue] = None
    
    @classmethod
    def setup_logging(cls, log_dir: str = "logs", log_file: str = "app.log") -> None:
        """
        设置日志配置，使用QueueHandler避免阻塞
        
        Args:
            log_dir: 日志目录
            log_file: 日志文件名
        """
        # 创建日志目录
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True, parents=True)
        
        # 日志文件完整路径
        log_file_path = log_path / log_file
        
        # 创建日志队列
        cls._log_queue = queue.Queue(-1)
        
        # 配置日志格式
        log_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 创建文件处理器（直接追加，不轮转）
        # 这样避免了 Windows 上重命名文件的权限问题
        file_handler = logging.FileHandler(
            str(log_file_path),
            mode='a',  # 追加模式
            encoding='utf-8',
            delay=True  # 延迟打开文件
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(log_format)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(log_format)
        
        # 创建QueueHandler（非阻塞）
        queue_handler = logging.handlers.QueueHandler(cls._log_queue)
        queue_handler.setLevel(logging.DEBUG)
        
        # 创建QueueListener，在后台线程中处理日志
        cls._queue_listener = logging.handlers.QueueListener(
            cls._log_queue,
            file_handler,
            console_handler,
            respect_handler_level=True
        )
        cls._queue_listener.start()
        
        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # 清除现有的handler
        if root_logger.handlers:
            root_logger.handlers.clear()
        
        # 添加QueueHandler到根logger
        root_logger.addHandler(queue_handler)
        
        # 获取应用日志记录器
        logger = logging.getLogger(__name__)
        logger.info("=" * 60)
        logger.info("日志系统初始化完成（使用 FileHandler，直接追加）")
        logger.info(f"日志文件: {log_file_path}")
        logger.info("=" * 60)
    
    @classmethod
    def shutdown_logging(cls) -> None:
        """关闭日志系统，确保所有日志都被写入"""
        if cls._queue_listener is not None:
            cls._queue_listener.stop()
            cls._queue_listener = None
        
        if cls._log_queue is not None:
            cls._log_queue = None


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 日志记录器名称
    
    Returns:
        logging.Logger: 日志记录器
    """
    return logging.getLogger(name)
