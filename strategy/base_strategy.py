"""
策略基类定义
"""
from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """策略抽象基类"""
    
    def __init__(self, name, params=None):
        """
        初始化策略
        :param name: 策略名称
        :param params: 参数字典
        """
        self.name = name
        self.params = params or {}
    
    @abstractmethod
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标
        :param df: 股票数据DataFrame
        :return: 添加了指标列的DataFrame
        """
        pass
    
    @abstractmethod
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑
        :param df: 包含指标的股票数据
        :param stock_name: 股票名称，用于过滤退市股票
        :return: 选股信号列表，每个元素为字典包含信号详情
        """
        pass
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        return []
    
    def analyze_stock(self, stock_code, stock_name, df):
        """
        分析单只股票 - 专注于流程处理
        
        :param stock_code: 股票代码
        :param stock_name: 股票名称
        :param df: 股票数据DataFrame
        :return: 标准化的选股结果或None
        """
        try:
            # 1. 数据验证
            if df is None or df.empty or len(df) < 20:
                return None
            
            # 2. 执行策略 - 直接调用select_stocks，由策略自身负责具体执行逻辑
            # 这样可以利用策略的快速预检查，避免不必要的计算
            signals = self.select_stocks(df, stock_name)
            
            # 3. 结果过滤和标准化
            if signals:
                return {
                    'code': stock_code,
                    'name': stock_name,
                    'signals': signals
                }
            return None
            
        except Exception as e:
            # 4. 错误处理
            # 记录错误但不影响整体流程
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"分析股票 {stock_code} 失败: {str(e)}")
            return None
