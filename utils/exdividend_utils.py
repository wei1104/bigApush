"""
除权信息工具类，提供获取除权信息和复权因子的方法

除权检测逻辑：
1. 每日开盘前获取持仓股票的当日 adj_factor（复权因子）
2. 与前一日因子对比，如果有变化（factor_diff != 1），则说明当日发生除权
"""

import logging
from typing import Optional
from pathlib import Path
import json

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ExdividendUtils:
    """
    除权信息工具类，提供获取除权信息和复权因子的方法
    """
    
    @staticmethod
    def get_exdividend_info(stock_code: str, trade_date: str) -> Optional[dict]:
        """
        获取股票在指定日期的除权信息（通过复权因子变化判断）
        
        Args:
            stock_code: 股票代码（格式：sh600000、600000.SH 或 600000）
            trade_date: 交易日期（格式：YYYYMMDD）
        
        Returns:
            除权信息字典，无除权返回None
            
        返回字段说明：
            - stock_code: 股票代码
            - ex_date: 除权日期
            - adj_factor: 当日复权因子
            - prev_adj_factor: 前一日复权因子
            - factor: 除权因子（当日因子/前一日因子）
        """
        try:
            # 统一股票代码格式为 Tushare 格式（600000.SH）
            ts_code = ExdividendUtils._convert_to_ts_code(stock_code)
            
            # 获取 Tushare API
            pro = ExdividendUtils._get_tushare_api()
            if not pro:
                return None
            
            # ========== 1. 获取当日复权因子 ==========
            today_factor = ExdividendUtils._get_adj_factor(pro, ts_code, trade_date)
            if not today_factor:
                return None
            
            # ========== 2. 获取前一日复权因子 ==========
            prev_date = ExdividendUtils._get_previous_trading_day(pro, trade_date)
            if not prev_date:
                return None
            
            prev_factor = ExdividendUtils._get_adj_factor(pro, ts_code, prev_date)
            if not prev_factor:
                return None
            
            # ========== 3. 判断是否除权（因子变化超过阈值）==========
            factor_diff = today_factor / prev_factor
            
            # 因子变化阈值（避免浮点精度问题）
            threshold = 0.0001
            if abs(factor_diff - 1.0) <= threshold:
                # 因子未变化，无除权
                return None
            
            # ========== 4. 返回除权信息 ==========
            return {
                'stock_code': stock_code,
                'ex_date': trade_date,
                'adj_factor': today_factor,
                'prev_adj_factor': prev_factor,
                'factor': factor_diff  # 除权因子 = 当日因子 / 前一日因子
            }
            
        except Exception as e:
            logger.debug(f"获取除权信息失败: {e}")
            return None
    
    @staticmethod
    def _get_adj_factor(pro, ts_code: str, trade_date: str) -> Optional[float]:
        """
        获取指定日期的复权因子（从Tushare获取）
        
        Args:
            pro: Tushare API实例
            ts_code: Tushare格式股票代码（600000.SH）
            trade_date: 交易日期（格式：YYYYMMDD）
        
        Returns:
            复权因子，获取失败返回None
        """
        try:
            # 获取前复权数据（包含复权因子）
            df = pro.pro_bar(
                ts_code=ts_code,
                start_date=trade_date,
                end_date=trade_date,
                adj='qfq',
                fields='trade_date,adj_factor'
            )
            
            if df is not None and not df.empty:
                return df.iloc[0]['adj_factor']
            
            return None
            
        except Exception as e:
            logger.debug(f"获取复权因子失败: {e}")
            return None
    
    @staticmethod
    def _get_previous_trading_day(pro, date: str) -> Optional[str]:
        """
        获取前一个交易日
        
        Args:
            pro: Tushare API实例
            date: 日期（格式：YYYYMMDD）
        
        Returns:
            前一个交易日日期，获取失败返回None
        """
        try:
            # 获取交易日历
            trade_dates = pro.trade_cal(
                start_date='19900101',
                end_date=date,
                is_open='1'
            )
            
            if trade_dates is None or len(trade_dates) < 2:
                return None
            
            # 找到当前日期在交易日历中的位置
            current_idx = trade_dates[trade_dates['cal_date'] == date].index
            if len(current_idx) > 0 and current_idx[0] > 0:
                return trade_dates.iloc[current_idx[0] - 1]['cal_date']
            
            return None
            
        except Exception as e:
            logger.debug(f"获取前一个交易日失败: {e}")
            return None
    
    @staticmethod
    def _get_tushare_api():
        """
        获取Tushare API实例
        
        Returns:
            Tushare pro API实例，配置失败返回None
        """
        try:
            import tushare as ts
            
            # 读取 Tushare 配置
            config_path = Path(__file__).parent.parent / "config" / "tushare_config.json"
            if not config_path.exists():
                logger.debug("Tushare配置文件不存在")
                return None
            
            with open(config_path, 'r', encoding='utf-8') as f:
                tushare_config = json.load(f)
            
            token = tushare_config.get('token') or tushare_config.get('api_key')
            if not token:
                logger.debug("Tushare token未配置")
                return None
            
            return ts.pro_api(token)
            
        except Exception as e:
            logger.debug(f"初始化Tushare API失败: {e}")
            return None
    
    @staticmethod
    def _convert_to_ts_code(stock_code: str) -> str:
        """
        统一股票代码格式为Tushare格式（600000.SH）
        
        Args:
            stock_code: 股票代码
        
        Returns:
            Tushare格式股票代码
        """
        stock_code = str(stock_code).strip()
        
        # 处理格式：sh600000 → 600000.SH
        if stock_code.startswith('sh'):
            return f"{stock_code[2:]}.SH"
        # 处理格式：sz000001 → 000001.SZ
        elif stock_code.startswith('sz'):
            return f"{stock_code[2:]}.SZ"
        # 处理格式：600000 → 600000.SH（默认沪市）
        elif len(stock_code) == 6:
            if stock_code.startswith('6'):
                return f"{stock_code}.SH"
            else:
                return f"{stock_code}.SZ"
        
        return stock_code
