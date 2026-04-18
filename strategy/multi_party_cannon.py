"""
多方炮策略 - 两阳夹一阴的K线组合形态

指标定义：
1. 第一根K线（Day-2）：中阳线或大阳线
   - 收盘价 > 开盘价（阳线）
   - 涨幅 >= first_candle_rise（默认3%）

2. 第二根K线（Day-1）：小阴线或十字星
   - 收盘价 < 开盘价（阴线）
   - 实体大小 <= 第一根阳线实体的50%
   - 回调幅度 <= 第一根阳线涨幅的50%

3. 第三根K线（Day-0）：阳线
   - 收盘价 > 开盘价（阳线）
   - 收盘价 > 第一根K线的收盘价（突破确认）
   - 涨幅 >= third_candle_rise（默认3%）

选股条件：
- 三根K线按顺序出现
- 第一根K线是阳线且涨幅达标
- 第二根K线是阴线且实体和回调幅度受限
- 第三根K线是阳线且涨幅达标并突破前高
- 第二根K线缩量（成交量 <= 第一根的80%）
- 第三根K线放量（成交量 >= 第一根的120%）
- 可选：趋势过滤条件（均线、MACD、KDJ）
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import REF, MA


class MultiPartyCannonStrategy(BaseStrategy):
    """多方炮策略 - 两阳夹一阴的K线组合形态"""
    
    def __init__(self, params=None):
        # 默认参数配置
        default_params = {
            # 形态参数
            'first_candle_rise': 0.03,           # 第一根阳线涨幅阈值（3%）
            'second_candle_body_ratio': 0.5,      # 第二根阴线实体占第一根阳线实体的比例（50%）
            'second_candle_fallback_ratio': 0.5,   # 第二根阴线回调占第一根阳线涨幅的比例（50%）
            'third_candle_rise': 0.03,            # 第三根阳线涨幅阈值（3%）
            'third_candle_breakthrough': True,      # 第三根阳线收盘价是否需要突破第一根阳线收盘价
            
            # 成交量参数
            'second_volume_shrink_ratio': 0.8,     # 第二根阴线成交量占第一根阳线成交量的比例（80%）
            'third_volume_expand_ratio': 1.2,       # 第三根阳线成交量占第一根阳线成交量的比例（120%）
            'third_volume_ma_ratio': 1.5,          # 第三根阳线成交量占均量的比例（1.5倍）
            'volume_ma_period': 5,                  # 成交量均线周期（5日）
            
            # 趋势过滤参数
            'enable_ma_filter': True,                # 是否启用均线过滤
            'ma_period': 20,                       # 均线周期（20日）
            'enable_macd_filter': False,             # 是否启用MACD过滤
            'macd_above_zero': True,                # MACD是否需要大于0
            'enable_kdj_filter': False,              # 是否启用KDJ过滤
            'kdj_j_max': 80,                       # KDJ的J值上限（80）
            
            # 其他参数
            'lookback_days': 3,                     # 回溯天数（3天）
            'min_market_cap': 20,                    # 最小总市值（20亿元）
            'max_market_cap': 1000,                  # 最大总市值（1000亿元）
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("多方炮策略", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算多方炮策略所需的指标
        """
        result = df.copy()
        
        # 数据质量检查：确保open价格不为0或None
        if result['open'].isnull().any() or (result['open'] == 0).any():
            # 对于无效数据，返回原始数据
            return result
        
        # 计算K线实体大小（绝对值）
        result['body_size'] = abs(result['close'] - result['open'])
        
        # 计算K线方向（1=阳线，-1=阴线）
        result['candle_direction'] = (result['close'] > result['open']).astype(int) * 2 - 1
        
        # 计算K线涨幅
        result['candle_rise'] = (result['close'] - result['open']) / result['open']
        
        # 计算成交量均线
        volume_ma_period = self.params['volume_ma_period']
        result[f'VOLUME_MA{volume_ma_period}'] = result['volume'].rolling(window=volume_ma_period).mean()
        
        # 只在需要时计算MACD和KDJ
        if self.params['enable_macd_filter'] or self.params['enable_kdj_filter']:
            # 计算MACD指标（用于MACD过滤）
            result = self._calculate_macd(result)
            
            # 计算KDJ指标（用于KDJ过滤）
            from utils.technical import KDJ
            kdj_df = KDJ(result, n=9, m1=3, m2=3)
            result['K'] = kdj_df['K']
            result['D'] = kdj_df['D']
            result['J'] = kdj_df['J']
        
        # 只在需要时计算均线
        if self.params['enable_ma_filter']:
            # 计算均线（用于均线过滤）
            ma_period = self.params['ma_period']
            result[f'MA{ma_period}'] = result['close'].rolling(window=ma_period).mean()
            
            # 计算趋势线（与其他策略保持一致）
            from utils.technical import calculate_zhixing_trend
            trend_df = calculate_zhixing_trend(
                result,
                m1=14,  # MA周期1
                m2=28,  # MA周期2
                m3=57,  # MA周期3
                m4=114  # MA周期4
            )
            result['short_term_trend'] = trend_df['short_term_trend']
            result['bull_bear_line'] = trend_df['bull_bear_line']
        
        # 计算市值（如果CSV中有market_cap字段则使用，否则估算）
        if 'market_cap' not in result.columns:
            # 估算市值：假设总股本2亿股
            result['market_cap'] = result['close'] * 2e8
        
        return result
    
    def _calculate_macd(self, df) -> pd.DataFrame:
        """
        计算MACD指标
        """
        result = df.copy()
        
        # 确保数据按时间正序排列（从旧到新）
        result = result.sort_values('date', ascending=True).reset_index(drop=True)
        
        # DIF = 12日EMA - 26日EMA
        ema_12 = result['close'].ewm(span=12, adjust=False).mean()
        ema_26 = result['close'].ewm(span=26, adjust=False).mean()
        result['DIF'] = ema_12 - ema_26
        
        # DEA = DIF的9日EMA
        result['DEA'] = result['DIF'].ewm(span=9, adjust=False).mean()
        
        # MACD = DIF - DEA
        result['MACD'] = result['DIF'] - result['DEA']
        
        # 恢复原始顺序（从新到旧）
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        
        return result
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：第一根阳线
        first_candle_rise = self.params['first_candle_rise'] * 100
        criteria.append(f"1. 第一根阳线：中阳线或大阳线，涨幅>={first_candle_rise:.0f}%")
        
        # 条件2：第二根阴线
        second_candle_body_ratio = self.params['second_candle_body_ratio'] * 100
        second_candle_fallback_ratio = self.params['second_candle_fallback_ratio'] * 100
        criteria.append(f"2. 第二根阴线：小阴线或十字星，实体<=第一根阳线的{second_candle_body_ratio:.0f}%，回调幅度<=第一根阳线涨幅的{second_candle_fallback_ratio:.0f}%")
        
        # 条件3：第三根阳线
        third_candle_rise = self.params['third_candle_rise'] * 100
        third_candle_breakthrough = self.params['third_candle_breakthrough']
        breakthrough_text = "且收盘价突破第一根阳线收盘价" if third_candle_breakthrough else ""
        criteria.append(f"3. 第三根阳线：阳线，涨幅>={third_candle_rise:.0f}%{breakthrough_text}")
        
        # 条件4：成交量条件
        second_volume_shrink_ratio = self.params['second_volume_shrink_ratio'] * 100
        third_volume_expand_ratio = self.params['third_volume_expand_ratio'] * 100
        third_volume_ma_ratio = self.params['third_volume_ma_ratio']
        volume_ma_period = self.params['volume_ma_period']
        criteria.append(f"4. 成交量条件：第二根阴线缩量（<=第一根的{second_volume_shrink_ratio:.0f}%），第三根阳线放量（>=第一根的{third_volume_expand_ratio:.0f}%，且>=前{volume_ma_period}日均量的{third_volume_ma_ratio:.1f}倍）")
        
        # 条件5：趋势过滤（可选）
        enable_ma_filter = self.params['enable_ma_filter']
        if enable_ma_filter:
            ma_period = self.params['ma_period']
            criteria.append(f"5. 趋势过滤：收盘价 > {ma_period}日均线")
        
        # 条件6：市值过滤
        min_market_cap = self.params['min_market_cap']
        max_market_cap = self.params['max_market_cap']
        criteria.append(f"6. 市值过滤：市值在{min_market_cap}-{max_market_cap}亿元之间")
        
        return criteria

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别多方炮形态
        """
        if df.empty or len(df) < 3:
            return []
        
        # 快速预检查：确保有足够的K线数据
        if len(df) < 10:  # 至少需要10天数据来计算指标
            return []
        
        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 数据质量检查：确保关键字段不为空
        if df['open'].isnull().any() or df['close'].isnull().any() or df['volume'].isnull().any():
            return []
        
        # 市值过滤（提前过滤）
        if 'market_cap' in df.columns:
            # 检查market_cap是否有效
            if pd.isna(latest['market_cap']) or latest['market_cap'] <= 0:
                return []
            market_cap = latest['market_cap'] / 1e8  # 转换为亿元
            if market_cap < self.params['min_market_cap'] or market_cap > self.params['max_market_cap']:
                return []
        
        # 计算指标
        df = self.calculate_indicators(df)
        
        # 市值过滤（如果CSV中没有market_cap字段）
        if 'market_cap' not in latest.index:
            # 检查market_cap是否有效
            if pd.isna(latest['market_cap']) or latest['market_cap'] <= 0:
                return []
            market_cap = latest['market_cap'] / 1e8  # 转换为亿元
            if market_cap < self.params['min_market_cap'] or market_cap > self.params['max_market_cap']:
                return []
        else:
            # 检查market_cap是否有效
            if pd.isna(latest['market_cap']) or latest['market_cap'] <= 0:
                return []
            market_cap = latest['market_cap'] / 1e8  # 转换为亿元
        
        # 只检查最近的三根K线
        if len(df) < 3:
            return []
        
        # 获取最近的三根K线
        third_candle = df.iloc[0]      # 第三根K线（最新，Day-0）
        second_candle = df.iloc[1]      # 第二根K线（Day-1）
        first_candle = df.iloc[2]       # 第一根K线（Day-2）
        
        # 检查是否满足多方炮形态
        if self._is_multi_party_cannon_pattern(first_candle, second_candle, third_candle):
            # 计算形态分类
            category = self._classify_pattern(first_candle, second_candle, third_candle)
            
            # 计算成交量放大比例
            volume_expand_ratio = third_candle['volume'] / first_candle['volume']
            
            # 关键日期：第三根K线（确认日）的日期
            key_date = third_candle['date']
            
            # 格式化关键日期，只保留日期部分
            key_date_str = key_date.strftime('%Y-%m-%d') if hasattr(key_date, 'strftime') else str(key_date)[:10]
            
            # 构建选股信号
            signal_info = {
                'date': latest_date,
                'close': round(latest['close'], 2),
                'J': round(latest['J'], 2),
                'volume_ratio': round(volume_expand_ratio, 2),
                'market_cap': round(market_cap, 2),
                'short_term_trend': round(latest['short_term_trend'], 2),
                'bull_bear_line': round(latest['bull_bear_line'], 2),
                'key_date': key_date_str,
                'key_date_type': '多方炮确认日',
                'reasons': self._generate_reasons(first_candle, second_candle, third_candle),
                'category': category,
                'pattern_details': {
                    'first_candle_date': first_candle['date'],
                    'first_candle_close': round(first_candle['close'], 2),
                    'first_candle_rise': round(first_candle['candle_rise'] * 100, 2),
                    'second_candle_date': second_candle['date'],
                    'second_candle_close': round(second_candle['close'], 2),
                    'second_candle_fallback': round(self._calculate_fallback_ratio(first_candle, second_candle) * 100, 2),
                    'third_candle_date': third_candle['date'],
                    'third_candle_close': round(third_candle['close'], 2),
                    'third_candle_rise': round(third_candle['candle_rise'] * 100, 2),
                    'volume_expand_ratio': round(volume_expand_ratio, 2),
                }
            }
            return [signal_info]
        
        return []
    
    def _detect_patterns_vectorized(self, df) -> list:
        """
        使用向量化操作检测多方炮形态
        提高检测效率，避免逐行遍历
        
        Args:
            df: 按日期降序排列的K线数据（最新在前）
            
        Returns:
            list: 选股信号列表
        """
        results = []
        
        # 确保数据量足够
        if len(df) < 3:
            return results
        
        # 数据质量检查：确保关键字段不为空
        if df['open'].isnull().any() or df['close'].isnull().any() or df['volume'].isnull().any():
            return results
        
        # 计算所需的向量
        # 第一根K线（Day-2）
        first_is_bullish = df['close'].shift(2) > df['open'].shift(2)
        first_rise = (df['close'].shift(2) - df['open'].shift(2)) / df['open'].shift(2)
        
        # 第二根K线（Day-1）
        second_is_bearish = df['close'].shift(1) < df['open'].shift(1)
        second_body = abs(df['close'].shift(1) - df['open'].shift(1))
        first_body = abs(df['close'].shift(2) - df['open'].shift(2))
        
        # 第三根K线（Day-0）
        third_is_bullish = df['close'] > df['open']
        third_rise = (df['close'] - df['open']) / df['open']
        
        # 成交量条件
        second_volume = df['volume'].shift(1)
        first_volume = df['volume'].shift(2)
        third_volume = df['volume']
        
        # 突破条件
        third_close = df['close']
        first_close = df['close'].shift(2)
        
        # 计算回调幅度
        first_high = df['close'].shift(2)  # 第一根阳线的收盘价
        second_low = df['close'].shift(1)  # 第二根阴线的收盘价
        first_open = df['open'].shift(2)   # 第一根阳线的开盘价
        first_rise_abs = first_high - first_open
        fallback = first_high - second_low
        fallback_ratio = np.where(first_rise_abs > 0, fallback / first_rise_abs, 0)
        
        # 构建条件矩阵（更严格的条件）
        conditions = (
            # 第一根K线条件
            (first_is_bullish) & 
            (first_rise >= self.params['first_candle_rise']) &
            # 第二根K线条件
            (second_is_bearish) & 
            (second_body <= first_body * self.params['second_candle_body_ratio']) &
            (fallback_ratio <= self.params['second_candle_fallback_ratio']) &
            # 第三根K线条件
            (third_is_bullish) & 
            (third_rise >= self.params['third_candle_rise']) &
            # 突破条件
            (third_close > first_close) &  # 强制突破
            # 成交量条件
            (second_volume <= first_volume * self.params['second_volume_shrink_ratio']) &
            (third_volume >= first_volume * self.params['third_volume_expand_ratio']) &
            # 额外的严格条件
            (first_rise >= 0.05) &  # 第一根阳线涨幅至少5%
            (third_rise >= 0.05) &  # 第三根阳线涨幅至少5%
            (second_body <= first_body * 0.3) &  # 第二根阴线实体更小
            (fallback_ratio <= 0.3) &  # 回调幅度更小
            (third_volume >= first_volume * 1.5) &  # 第三根成交量放大更多
            (second_volume <= first_volume * 0.7)  # 第二根成交量萎缩更多
        )
        
        # 找到满足条件的位置
        match_indices = np.where(conditions)[0]
        
        # 处理匹配结果
        for idx in match_indices:
            # 确保索引有效
            if idx >= len(df) - 2:
                continue
            
            # 获取三根K线
            third_candle = df.iloc[idx]
            second_candle = df.iloc[idx + 1]
            first_candle = df.iloc[idx + 2]
            
            # 检查趋势过滤条件
            if not self._check_trend_filters(third_candle):
                continue
            
            # 计算形态分类
            category = self._classify_pattern(first_candle, second_candle, third_candle)
            
            # 计算成交量放大比例
            volume_expand_ratio = third_candle['volume'] / first_candle['volume']
            
            # 关键日期：第三根K线（确认日）的日期
            key_date = third_candle['date']
            
            # 格式化关键日期，只保留日期部分
            key_date_str = key_date.strftime('%Y-%m-%d') if hasattr(key_date, 'strftime') else str(key_date)[:10]
            
            # 构建选股信号
            signal_info = {
                'date': third_candle['date'],
                'close': round(third_candle['close'], 2),
                'J': round(third_candle['J'], 2),
                'volume_ratio': round(volume_expand_ratio, 2),
                'market_cap': round(third_candle['market_cap'] / 1e8, 2),
                'short_term_trend': round(third_candle['short_term_trend'], 2),
                'bull_bear_line': round(third_candle['bull_bear_line'], 2),
                'key_date': key_date_str,
                'key_date_type': '多方炮确认日',
                'reasons': self._generate_reasons(first_candle, second_candle, third_candle),
                'category': category,
                'pattern_details': {
                    'first_candle_date': first_candle['date'],
                    'first_candle_close': round(first_candle['close'], 2),
                    'first_candle_rise': round(first_candle['candle_rise'] * 100, 2),
                    'second_candle_date': second_candle['date'],
                    'second_candle_close': round(second_candle['close'], 2),
                    'second_candle_fallback': round(self._calculate_fallback_ratio(first_candle, second_candle) * 100, 2),
                    'third_candle_date': third_candle['date'],
                    'third_candle_close': round(third_candle['close'], 2),
                    'third_candle_rise': round(third_candle['candle_rise'] * 100, 2),
                    'volume_expand_ratio': round(volume_expand_ratio, 2),
                }
            }
            results.append(signal_info)
        
        # 返回第一个匹配的信号（如果有）
        return results[:1] if results else []
    
    def _is_multi_party_cannon_pattern(self, first_candle, second_candle, third_candle) -> bool:
        """
        检查是否满足多方炮形态
        参数顺序：第一根K线（Day-2，最旧）、第二根K线（Day-1）、第三根K线（Day-0，最新）
        """
        # 数据质量检查
        for candle in [first_candle, second_candle, third_candle]:
            if pd.isna(candle['open']) or pd.isna(candle['close']) or pd.isna(candle['volume']):
                return False
        
        # 第一根K线（Day-2）：必须是阳线且涨幅达标
        first_is_bullish = first_candle['close'] > first_candle['open']
        first_rise = first_candle['candle_rise']
        
        if not first_is_bullish or first_rise < self.params['first_candle_rise']:
            return False
        
        # 第二根K线（Day-1）：必须是阴线
        second_is_bearish = second_candle['close'] < second_candle['open']
        
        if not second_is_bearish:
            return False
        
        # 第二根K线实体大小检查：必须 <= 第一根阳线实体的50%
        first_body = first_candle['body_size']
        second_body = second_candle['body_size']
        
        if second_body > first_body * self.params['second_candle_body_ratio']:
            return False
        
        # 第二根K线回调幅度检查：必须 <= 第一根阳线涨幅的50%
        fallback_ratio = self._calculate_fallback_ratio(first_candle, second_candle)
        
        if fallback_ratio > self.params['second_candle_fallback_ratio']:
            return False
        
        # 第三根K线（Day-0）：必须是阳线且涨幅达标
        third_is_bullish = third_candle['close'] > third_candle['open']
        third_rise = third_candle['candle_rise']
        
        if not third_is_bullish or third_rise < self.params['third_candle_rise']:
            return False
        
        # 第三根K线突破检查（可选）：收盘价必须 > 第一根K线的收盘价
        if self.params['third_candle_breakthrough']:
            if third_candle['close'] <= first_candle['close']:
                return False
        
        # 第二根K线缩量检查：成交量 <= 第一根阳线成交量的80%
        if second_candle['volume'] > first_candle['volume'] * self.params['second_volume_shrink_ratio']:
            return False
        
        # 第三根K线放量检查：成交量 >= 第一根阳线成交量的120%
        if third_candle['volume'] < first_candle['volume'] * self.params['third_volume_expand_ratio']:
            return False
        
        # 趋势过滤条件检查
        if not self._check_trend_filters(third_candle):
            return False
        
        return True
    
    def _calculate_fallback_ratio(self, first_candle, second_candle) -> float:
        """
        计算第二根K线的回调幅度占第一根阳线涨幅的比例
        """
        first_high = first_candle['close']  # 第一根阳线的收盘价（最高点）
        second_low = second_candle['close']  # 第二根阴线的收盘价（最低点）
        first_open = first_candle['open']    # 第一根阳线的开盘价
        
        first_rise = first_high - first_open
        if first_rise <= 0:
            return 0.0
        
        fallback = first_high - second_low
        return fallback / first_rise
    
    def _check_trend_filters(self, candle) -> bool:
        """
        检查趋势过滤条件
        """
        # 均线过滤
        if self.params['enable_ma_filter']:
            ma_period = self.params['ma_period']
            ma_key = f'MA{ma_period}'
            
            # 如果没有计算均线，则计算
            if ma_key not in candle.index:
                return False
            
            ma_value = candle[ma_key]
            if pd.isna(ma_value) or candle['close'] < ma_value:
                return False
        
        # MACD过滤
        if self.params['enable_macd_filter']:
            macd_value = candle['MACD']
            if pd.isna(macd_value):
                return False
            
            if self.params['macd_above_zero'] and macd_value <= 0:
                return False
        
        # KDJ过滤
        if self.params['enable_kdj_filter']:
            j_value = candle['J']
            if pd.isna(j_value):
                return False
            
            if j_value >= self.params['kdj_j_max']:
                return False
        
        return True
    
    def _classify_pattern(self, first_candle, second_candle, third_candle) -> str:
        """
        根据多方炮的强弱进行分类
        """
        first_rise = first_candle['candle_rise']
        third_rise = third_candle['candle_rise']
        
        # 强势多方炮：第一根和第三根都是大阳线（涨幅≥7%）
        if first_rise >= 0.07 and third_rise >= 0.07:
            return 'strong'
        
        # 标准多方炮：第一根和第三根都是中阳线（涨幅3%-7%）
        if 0.03 <= first_rise < 0.07 and 0.03 <= third_rise < 0.07:
            return 'standard'
        
        # 弱势多方炮：第一根和第三根都是小阳线（涨幅1%-3%）
        if 0.01 <= first_rise < 0.03 and 0.01 <= third_rise < 0.03:
            return 'weak'
        
        # 默认为标准多方炮
        return 'standard'
    
    def _generate_reasons(self, first_candle, second_candle, third_candle) -> str:
        """
        生成入选理由
        """
        first_rise_pct = round(first_candle['candle_rise'] * 100, 2)
        fallback_pct = round(self._calculate_fallback_ratio(first_candle, second_candle) * 100, 2)
        third_rise_pct = round(third_candle['candle_rise'] * 100, 2)
        volume_expand_ratio = round(third_candle['volume'] / first_candle['volume'], 2)
        
        reasons = f"多方炮形态：第一根阳线涨幅{first_rise_pct}%，第二根阴线回调{fallback_pct}%，第三根阳线涨幅{third_rise_pct}%且突破前高，成交量放大{volume_expand_ratio}倍"
        
        return reasons
