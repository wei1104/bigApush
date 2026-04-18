# -*- coding: utf-8 -*-
"""
交易日工具模块

提供判断日期是否为交易日的功能。
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

# 配置日志记录器
logger = logging.getLogger(__name__)


def is_trading_day(date_str: str) -> bool:
    """
    判断指定日期是否为交易日

    简单实现：
    1. 排除周六和周日
    2. 后续可扩展为使用 Tushare 或其他数据源获取真实交易日

    参数:
        date_str: 日期字符串，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        bool: 是否为交易日
    """
    try:
        # 统一日期格式
        if '-' in date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d')
        else:
            date = datetime.strptime(date_str, '%Y%m%d')
        
        # 排除周六(5)和周日(6)
        weekday = date.weekday()
        if weekday >= 5:
            logger.debug(f"日期 {date_str} 是周末，不是交易日")
            return False
        
        # 后续可扩展：排除法定节假日
        # TODO: 从数据源获取法定节假日列表并排除
        
        logger.debug(f"日期 {date_str} 是交易日")
        return True
    except Exception as e:
        logger.error(f"判断交易日时出错: {e}")
        return False


def get_trading_days(start_date: str, end_date: str) -> List[str]:
    """
    获取指定日期范围内的交易日列表

    参数:
        start_date: 开始日期，支持 YYYY-MM-DD 或 YYYYMMDD 格式
        end_date: 结束日期，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        List[str]: 交易日列表，格式为 YYYY-MM-DD
    """
    try:
        # 统一日期格式
        if '-' in start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start = datetime.strptime(start_date, '%Y%m%d')
        
        if '-' in end_date:
            end = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end = datetime.strptime(end_date, '%Y%m%d')
        
        # 生成日期范围
        trading_days = []
        current = start
        while current <= end:
            if is_trading_day(current.strftime('%Y-%m-%d')):
                trading_days.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        logger.info(f"获取到 {len(trading_days)} 个交易日")
        return trading_days
    except Exception as e:
        logger.error(f"获取交易日列表时出错: {e}")
        return []
