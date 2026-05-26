"""
顺势宝策略实现
顺势而为，在趋势启动初期捕捉买点，在趋势转弱时及时离场
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from trading.technical_indicators import TechnicalIndicators
from typing import Dict, Optional


class ShunShiBaoStrategy(TimingStrategy):
    """顺势宝策略"""
    
    def __init__(self, config):
        """初始化策略
        
        Args:
            config: 策略配置字典
        """
        super().__init__(config)
        
        # MACD参数（默认标准参数）
        self.macd_fast = self.config.get('macd_fast', 12)
        self.macd_slow = self.config.get('macd_slow', 26)
        self.macd_signal = self.config.get('macd_signal', 9)
        
        # 布林带参数（默认标准参数）
        self.boll_period = self.config.get('boll_period', 20)
        self.boll_multiplier = self.config.get('boll_multiplier', 2)
        
        # 底仓金额（参考海龟策略设置，默认20000元）
        self.base_position_amount = self.config.get('base_position_amount', 20000)
        
        # 初始化技术指标计算器
        self.technical_indicators = TechnicalIndicators()
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD和布林带指标
        
        Args:
            df: 股票数据DataFrame
            
        Returns:
            添加了指标的DataFrame
        """
        result = df.copy()
        
        # 确保数据按日期正序排列（最新在最后）
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算MACD指标（直接计算，不使用缓存）
        ema_short = result['close'].ewm(span=self.macd_fast, adjust=False).mean()
        ema_long = result['close'].ewm(span=self.macd_slow, adjust=False).mean()
        macd_line = ema_short - ema_long
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        hist = macd_line - signal_line
        
        result['dif'] = macd_line
        result['dea'] = signal_line
        result['macd'] = hist
        
        # 计算布林带指标（直接计算，不使用缓存）
        mid = result['close'].rolling(window=self.boll_period).mean()
        std = result['close'].rolling(window=self.boll_period).std()
        upper = mid + self.boll_multiplier * std
        lower = mid - self.boll_multiplier * std
        
        result['boll_mid'] = mid
        result['boll_upper'] = upper
        result['boll_lower'] = lower
        
        return result
    
    def _check_indicators_valid(self, row: pd.Series) -> bool:
        """检查指标是否有效（非空值）
        
        Args:
            row: 数据行
            
        Returns:
            是否有效
        """
        required = ['dif', 'dea', 'macd', 'boll_mid', 'boll_upper', 'boll_lower']
        for indicator in required:
            if pd.isna(row.get(indicator)):
                return False
        return True
    
    def _check_buy_signal_1(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断一档买入信号（稳健型）
        条件：MACD零轴上方刚金叉 且 价格突破布林带中轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足买入条件
        """
        # MACD条件：零轴上方刚金叉
        macd_buy_1 = (
            current['dif'] > 0 and                    # DIF在零轴上方（上升趋势）
            current['dif'] > current['dea'] and       # DIF > DEA（金叉状态）
            prev['dif'] <= prev['dea']                # 前日未金叉（刚刚金叉）
        )
        
        # 布林带条件：突破中轨确认
        boll_buy_1 = (
            current['close'] > current['boll_mid'] and   # 收盘价突破中轨
            prev['close'] <= prev['boll_mid']           # 前日未突破（刚突破）
        )
        
        return macd_buy_1 and boll_buy_1
    
    def _check_buy_signal_2(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断二档买入信号（突破型）
        条件：MACD强势多头 且 价格突破布林带上轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足买入条件
        """
        # MACD条件：强势多头
        macd_buy_2 = (
            current['dif'] > 0 and                    # DIF在零轴上方
            current['macd'] > prev['macd'] and        # MACD柱持续增长（多头力量增强）
            current['dif'] > current['dea']           # 保持金叉状态
        )
        
        # 布林带条件：突破上轨
        boll_buy_2 = (
            current['high'] > current['boll_upper'] and  # 最高价突破上轨
            current['close'] > current['boll_mid']       # 收盘价在中轨上方（收盘稳健）
        )
        
        return macd_buy_2 and boll_buy_2
    
    def _check_add_signal(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断加仓信号
        条件：MACD持续强势 且 价格突破布林带上轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足加仓条件
        """
        # MACD条件：强势延续
        macd_add = (
            current['dif'] > 0 and                    # DIF在零轴上方
            current['macd'] > prev['macd'] and        # MACD柱持续放大
            current['dif'] > current['dea']           # 保持金叉状态
        )
        
        # 布林带条件：突破上轨（放宽条件）
        boll_add = (
            current['close'] > current['boll_upper']   # 收盘价站上轨
        )
        
        # 成交量确认：温和放量（放宽条件）
        volume_add = (
            current['volume'] > prev['volume'] * 1.1   # 温和放量
        )
        
        return macd_add and boll_add and volume_add
    
    def _check_sell_signal_1(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断一档清仓信号（止损型）
        条件：MACD柱状图由正转负 且 价格跌破布林带中轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足清仓条件
        """
        # 计算MACD柱状图
        current_hist = current['dif'] - current['dea']
        prev_hist = prev['dif'] - prev['dea']
        
        # MACD条件：由多转空
        macd_sell_1 = (
            current_hist < 0 and           # MACD柱为负
            prev_hist >= 0                 # 前日为正（刚转负）
        )
        
        # 布林带条件：跌破中轨
        boll_sell_1 = (
            current['close'] < current['boll_mid'] and       # 跌破中轨支撑
            prev['close'] >= prev['boll_mid']                 # 前日未跌破
        )
        
        return macd_sell_1 and boll_sell_1
    
    def _check_sell_signal_2(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断二档清仓信号（止盈型）
        条件：MACD顶背离迹象 且 价格触碰上轨后回落
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足清仓条件
        """
        # MACD条件：顶背离迹象
        macd_sell_2 = (
            current['dif'] < prev['dif'] and             # DIF下降（动能减弱）
            current['close'] >= prev['close'] and         # 价格持平或创新高
            current['dif'] > 0                           # 仍在多头区域（提前预警）
        )
        
        # 布林带条件：触碰上轨回落
        boll_sell_2 = (
            current['high'] > current['boll_upper'] and    # 曾触碰上轨
            current['close'] < current['boll_upper'] and   # 收盘回落
            current['close'] < current['open']             # 阴线（空头力量显现）
        )
        
        return macd_sell_2 and boll_sell_2
    
    def _check_sell_signal_3(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断三档清仓信号（破位型）
        条件：MACD空头确认 且 放量跌破布林带下轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足清仓条件
        """
        # MACD条件：空头确认
        macd_sell_3 = (
            current['dif'] < 0                        # DIF在零轴下方（空头趋势）
        )
        
        # 布林带条件：跌破下轨
        boll_sell_3 = (
            current['close'] < current['boll_lower'] and    # 收盘价跌破下轨
            current['volume'] > prev['volume'] * 1.5        # 放量下跌（恐慌抛盘）
        )
        
        return macd_sell_3 and boll_sell_3
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, 
                          cash: Optional[float] = None, use_prev_day_signal: bool = True) -> TimingResult:
        """获取择时结果
        
        Args:
            df: 股票数据DataFrame
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号
                - True: 回测模式，使用T-1日数据判断信号
                - False: 狩猎场模式，使用T日数据判断信号
                
        Returns:
            TimingResult对象
        """
        result = TimingResult()
        
        # 计算指标
        df = self.calculate_indicators(df)
        
        # 数据验证
        if len(df) < 2:
            return result
        
        # 获取当前和前一日数据
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 检查指标完整性
        if not self._check_indicators_valid(current) or not self._check_indicators_valid(prev):
            return result
        
        # 判断信号逻辑：
        # - 无持仓时：检查一档买入 → 二档买入
        # - 有持仓时：检查加仓信号 → 一档买入（作为加仓）→ 二档买入（作为加仓）
        if not position:
            # 无持仓：检查买入信号
            if self._check_buy_signal_1(current, prev):
                result.is_buy = True
                result.message = "MACD零轴上方金叉且价格突破中轨，买入信号（稳健型）"
                result.signal_strength = 1.0
                result.trade_type = 'buy'
            elif self._check_buy_signal_2(current, prev):
                result.is_buy = True
                result.message = "MACD强势且价格突破上轨，买入信号（突破型）"
                result.signal_strength = 0.8
                result.trade_type = 'buy'
        else:
            # 有持仓：检查加仓信号或买入信号，都作为加仓处理
            if self._check_add_signal(current, prev):
                result.is_buy = True
                result.message = "MACD持续强势且放量突破上轨，加仓信号"
                result.signal_strength = 0.9
                result.trade_type = 'add'
                # 计算加仓数量：使用已有持仓数量的一半
                current_quantity = position.get('quantity', 0)
                add_quantity = int(current_quantity * 0.5) // 100 * 100
                result.buy_quantity = max(add_quantity, 100)
            elif self._check_buy_signal_1(current, prev):
                result.is_buy = True
                result.message = "MACD零轴上方金叉且价格突破中轨，加仓信号（稳健型）"
                result.signal_strength = 1.0
                result.trade_type = 'add'
                # 计算加仓数量：使用已有持仓数量的一半
                current_quantity = position.get('quantity', 0)
                add_quantity = int(current_quantity * 0.5) // 100 * 100
                result.buy_quantity = max(add_quantity, 100)
            elif self._check_buy_signal_2(current, prev):
                result.is_buy = True
                result.message = "MACD强势且价格突破上轨，加仓信号（突破型）"
                result.signal_strength = 0.8
                result.trade_type = 'add'
                # 计算加仓数量：使用已有持仓数量的一半
                current_quantity = position.get('quantity', 0)
                add_quantity = int(current_quantity * 0.5) // 100 * 100
                result.buy_quantity = max(add_quantity, 100)
        
        # 判断清仓信号（优先级：三档 > 一档 > 二档）
        if not result.is_buy:
            if self._check_sell_signal_3(current, prev):
                result.is_sell = True
                result.message = "DIF<0且放量跌破下轨，清仓信号（破位型）"
                result.signal_strength = 1.0
                result.trade_type = 'sell'
                if position:
                    result.sell_quantity = position.get('quantity', 0)
            elif self._check_sell_signal_1(current, prev):
                result.is_sell = True
                result.message = "MACD转负且价格跌破中轨，清仓信号（止损型）"
                result.signal_strength = 1.0
                result.trade_type = 'sell'
                if position:
                    result.sell_quantity = position.get('quantity', 0)
            elif self._check_sell_signal_2(current, prev):
                result.is_sell = True
                result.message = "MACD顶背离且上轨回落，清仓信号（止盈型）"
                result.signal_strength = 0.7
                result.trade_type = 'sell'
                if position:
                    result.sell_quantity = position.get('quantity', 0)
        
        # 填充支撑位和压力位
        result.support_level = current['boll_lower']
        result.resistance_level = current['boll_upper']
        
        # 填充指标值
        result.indicators = {
            'dif': current['dif'],
            'dea': current['dea'],
            'macd_hist': current['macd'],
            'boll_upper': current['boll_upper'],
            'boll_mid': current['boll_mid'],
            'boll_lower': current['boll_lower'],
            'boll_width': current['boll_upper'] - current['boll_lower'],
            'current_price': current['close']
        }
        
        return result
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算支撑位
        
        Args:
            df: 股票数据DataFrame
            key_date: 关键日期（可选）
            
        Returns:
            支撑位价格（布林带下轨）
        """
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        
        if pd.notna(latest['boll_lower']):
            return latest['boll_lower']
        
        return 0.0