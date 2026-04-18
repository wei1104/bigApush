"""
W底策略（WBottomStrategy）

基于经典双底反转形态的量化选股策略。
通过识别W底形态、颈线突破确认、趋势反转验证和量价配合分析，寻找潜在买入机会。
核心流程：W底形态识别 → 颈线突破确认 → 趋势反转验证 → 量价配合分析 → 假W底过滤
"""
import pandas as pd
from strategy.base_strategy import BaseStrategy


class WBottomStrategy(BaseStrategy):
    """
    W底策略类
    
    继承 BaseStrategy，实现 calculate_indicators() 和 select_stocks() 方法。
    通过五个核心步骤实现选股：
    1. W底形态识别（局部低点扫描 + 双底结构验证）
    2. 颈线突破确认（价格突破 + 放量验证）
    3. 趋势反转验证（3选2逻辑）
    4. 量价配合分析（缩量为加分项）
    5. 假W底过滤（下跌前置 + 突破后支撑）
    """

    def __init__(self, params=None):
        """
        初始化W底策略
        
        :param params: 用户自定义参数字典，会覆盖默认参数
        """
        # 默认参数 - 与 config/strategy_params.yaml 中的默认值保持一致
        default_params = {
            # W底形态识别参数
            'pattern_days': 40,              # 形态扫描回溯天数
            'low_window': 5,                 # 局部低点识别窗口
            'min_gap': 10,                   # 相邻低点最小间隔（交易日）
            'bottom_diff_threshold': 0.03,   # L1/L2价格差异阈值（3%）
            'min_pattern_days': 10,          # L1到突破日最小间隔（交易日）
            # 颈线突破参数
            'neckline_break_ratio': 1.01,    # 颈线突破比例（101%）
            'volume_ma_period': 5,           # 成交量均线周期
            'volume_expand_ratio': 1.2,      # 突破放量倍数
            # 趋势反转参数
            'short_ma_period': 10,           # 短期均线周期
            'long_ma_period': 30,            # 长期均线周期
            # 量价配合参数
            'volume_shrink_ratio': 0.8,      # 右侧缩量比例
            # 假W底过滤参数
            'support_days': 3,               # 突破后支撑验证天数
            'support_ratio': 0.02,           # 支撑位容忍比例（2%）
            # 突破时效参数
            'max_break_days': 10,            # 突破日距今最大天数
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("W底策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（MA、KDJ、趋势线、成交量均线）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 添加了指标列的DataFrame
        """
        from utils.technical import MA, KDJ, calculate_zhixing_trend

        # 检查输入数据是否为空
        if df is None or df.empty:
            return df

        # 1. 检查是否已经计算过指标，避免重复计算
        if all(col in df.columns for col in ['short_ma', 'long_ma', 'K', 'D', 'J', 'short_term_trend', 'bull_bear_line', 'volume_ma']):
            return df

        result = df.copy()

        # 2. 计算短期均线和长期均线
        short_period = self.params['short_ma_period']
        long_period = self.params['long_ma_period']
        result['short_ma'] = MA(result['close'], short_period)
        result['long_ma'] = MA(result['close'], long_period)

        # 3. 计算KDJ指标（K、D、J）
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']

        # 4. 计算知行趋势线（短期趋势线和多空线）
        # 优化：直接计算，减少函数调用开销
        from utils.technical import EMA
        # 知行短期趋势线 = EMA(EMA(CLOSE,10),10)
        result['short_term_trend'] = EMA(EMA(result['close'], 10), 10)
        # 知行多空线 = (MA(m1) + MA(m2) + MA(m3) + MA(m4)) / 4
        m1, m2, m3, m4 = 14, 28, 57, 114
        result['bull_bear_line'] = (MA(result['close'], m1) + MA(result['close'], m2) + 
                                   MA(result['close'], m3) + MA(result['close'], m4)) / 4

        # 5. 计算成交量均线（排除当日，shift(1)后再rolling）
        vol_period = self.params['volume_ma_period']
        # 倒序数据：先转正序计算，再恢复倒序
        reversed_vol = result['volume'].iloc[::-1]
        # shift(1) 排除当日成交量
        shifted_vol = reversed_vol.shift(1)
        # 计算均线
        vol_ma_reversed = shifted_vol.rolling(window=vol_period, min_periods=1).mean()
        # 恢复倒序
        result['volume_ma'] = vol_ma_reversed.iloc[::-1].values

        # 6. 计算市值（如无 market_cap 字段或值为NaN则用 close * volume 估算）
        if 'market_cap' not in result.columns or result['market_cap'].isna().all():
            # 简单估算：收盘价 × 成交量 / 1e8（亿元）
            result['market_cap'] = result['close'] * result['volume'] / 1e8
        else:
            # 填充NaN值
            result['market_cap'] = result['market_cap'].fillna(result['close'] * result['volume'] / 1e8)

        return result


    def _find_local_lows(self, df, pattern_days):
        """
        在回溯窗口内识别局部低点（优化版本）
        
        使用 LLV 函数在 low_window 窗口内识别局部低点，
        并施加最小间隔约束过滤噪声低点。
        使用向量化操作优化性能。
        
        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :param pattern_days: 形态扫描回溯天数
        :return: 局部低点列表 [(index, price, date), ...]
        """
        from utils.technical import LLV
        import numpy as np

        # 获取参数
        low_window = self.params['low_window']
        min_gap = self.params['min_gap']

        # 限定扫描范围为最近 pattern_days 个交易日
        scan_df = df.head(pattern_days).copy()
        if len(scan_df) < low_window:
            return []

        # 使用 LLV 计算窗口内最低值
        llv_values = LLV(scan_df['low'], low_window)

        # 识别局部低点：该交易日的 low == LLV 窗口最小值 - 使用向量化操作优化
        # 创建布尔掩码：low等于LLV值（浮点数比较使用近似相等）
        local_low_mask = (scan_df['low'] - llv_values).abs() < 1e-6
        
        # 获取所有局部低点的索引
        local_low_indices = scan_df.index[local_low_mask].tolist()
        
        # 如果没有局部低点，直接返回
        if not local_low_indices:
            return []
        
        # 施加最小间隔约束（倒序数据中索引越小越新）- 向量化优化
        # 按索引升序排列（从新到旧），间隔不足时保留价格更低的低点
        filtered_lows = []
        
        # 转换为numpy数组进行向量化操作
        indices_array = np.array([scan_df.index.get_loc(idx) for idx in local_low_indices])
        prices_array = np.array([scan_df['low'].iloc[idx] for idx in local_low_indices])
        dates_array = np.array([scan_df['date'].iloc[idx] for idx in local_low_indices])
        
        # 按索引排序（从新到旧）
        sorted_indices = np.argsort(indices_array)
        
        # 遍历排序后的索引
        for i in sorted_indices:
            idx_pos = indices_array[i]
            low_price = prices_array[i]
            date_val = dates_array[i]
            
            # 检查与已保留低点的间隔
            if filtered_lows:
                last_idx = filtered_lows[-1][0]
                last_price = filtered_lows[-1][1]
                # 倒序数据中索引差即为交易日间隔
                if abs(idx_pos - last_idx) < min_gap:
                    # 间隔不足，保留价格更低的低点
                    if low_price < last_price:
                        filtered_lows[-1] = (idx_pos, low_price, date_val)
                    continue
            filtered_lows.append((idx_pos, low_price, date_val))

        return filtered_lows

    def _find_w_bottom(self, local_lows, df):
        """
        从局部低点中筛选W底形态（L1, H, L2）
        
        遍历相邻低点对，验证价格差异和中间高点，
        返回第一个满足条件的W底形态。
        
        :param local_lows: 局部低点列表 [(index, price, date), ...]
        :param df: 含指标的DataFrame（倒序）
        :return: (l1_idx, l1_price, h_idx, h_price, l2_idx, l2_price) 或 None
        """
        threshold = self.params['bottom_diff_threshold']

        # 至少需要两个低点才能构成W底
        if len(local_lows) < 2:
            return None

        # 遍历所有相邻低点对（倒序数据中索引大的更早）
        for i in range(len(local_lows) - 1):
            # L2 是较新的低点（索引较小），L1 是较早的低点（索引较大）
            l2_idx, l2_price, l2_date = local_lows[i]
            l1_idx, l1_price, l1_date = local_lows[i + 1]

            # 验证价格差异 <= bottom_diff_threshold
            if l1_price == 0:
                continue
            price_diff = abs(l2_price - l1_price) / l1_price
            if price_diff > threshold:
                continue

            # 在 L1 和 L2 之间查找最高价作为 H
            # 倒序数据：L1 索引 > L2 索引，中间区间为 (l2_idx, l1_idx)
            between_start = l2_idx + 1
            between_end = l1_idx
            if between_start >= between_end:
                continue

            # 获取中间区间的数据
            between_df = df.loc[between_start:between_end - 1]
            if between_df.empty:
                continue

            # 找到中间最高价
            h_pos = between_df['high'].idxmax()
            h_price = between_df['high'].loc[h_pos]

            # 验证 H > L1 且 H > L2
            if h_price <= l1_price or h_price <= l2_price:
                continue

            # 返回第一个满足条件的W底形态
            return (l1_idx, l1_price, h_pos, h_price, l2_idx, l2_price)

        return None

    def _check_neckline_break(self, df, l2_idx, neckline):
        """
        检测颈线突破+放量确认（优化版本）
        
        在 L2 之后的交易日中检测收盘价是否放量突破颈线。
        倒序数据中 L2 之后的交易日索引 < l2_idx。
        使用向量化操作优化性能。
        
        :param df: 含指标的DataFrame（倒序）
        :param l2_idx: L2 的索引
        :param neckline: 颈线价格（H的价格）
        :return: 突破日的索引，或 None
        """
        # 获取参数
        break_ratio = self.params['neckline_break_ratio']
        expand_ratio = self.params['volume_expand_ratio']
        max_break_days = self.params.get('max_break_days', 10)

        # 突破价格阈值
        break_price = neckline * break_ratio

        # 在 L2 之后（索引 < l2_idx）的交易日中检测
        # 限制搜索范围
        search_start = max(0, l2_idx - max_break_days)
        search_df = df.iloc[search_start:l2_idx]
        
        if search_df.empty:
            return None
        
        # 向量化检查突破条件
        # 突破条件：收盘价 >= 颈线 × neckline_break_ratio
        close_condition = search_df['close'] >= break_price
        
        # 放量条件：成交量 >= volume_ma × volume_expand_ratio
        # 防止 volume_ma 为 0 或 NaN
        vol_condition = (
            (search_df['volume_ma'] > 0) & 
            (~pd.isna(search_df['volume_ma'])) &
            (search_df['volume'] >= search_df['volume_ma'] * expand_ratio)
        )
        
        # 找到同时满足两个条件的交易日
        valid_breaks = search_df[close_condition & vol_condition]
        
        if not valid_breaks.empty:
            # 返回最早满足条件的突破日（倒序数据中索引最小的是最早的）
            first_break_idx = valid_breaks.index.min()
            return first_break_idx

        # 无有效突破或突破日距今过久
        return None

    def _check_trend_reversal(self, df):
        """
        趋势反转验证（3选2逻辑）
        
        检查以下三个子条件，满足 >= 2 个即通过：
        (a) short_ma > long_ma
        (b) short_term_trend > 0
        (c) 最新收盘价 > long_ma
        
        :param df: 含指标的DataFrame（倒序，index=0为最新）
        :return: 布尔值
        """
        # 取最新一行数据（index=0）
        latest = df.iloc[0]
        count = 0

        # 子条件 (a)：短期均线 > 长期均线
        if not pd.isna(latest.get('short_ma')) and not pd.isna(latest.get('long_ma')):
            if latest['short_ma'] > latest['long_ma']:
                count += 1

        # 子条件 (b)：短期趋势线 > 0
        if not pd.isna(latest.get('short_term_trend')):
            if latest['short_term_trend'] > 0:
                count += 1

        # 子条件 (c)：最新收盘价 > 长期均线
        if not pd.isna(latest.get('close')) and not pd.isna(latest.get('long_ma')):
            if latest['close'] > latest['long_ma']:
                count += 1

        # 满足 >= 2 个子条件即通过
        return count >= 2

    def _check_volume_analysis(self, df, l1_idx, l2_idx):
        """
        量价配合分析：比较 L1 和 L2 处的成交量
        
        缩量判定：L2 成交量 < L1 成交量 × volume_shrink_ratio。
        此结果为加分项，不影响选股通过与否。
        
        :param df: 含指标的DataFrame
        :param l1_idx: L1 索引
        :param l2_idx: L2 索引
        :return: {'shrink': bool, 'shrink_ratio': float}
        """
        shrink_ratio_param = self.params['volume_shrink_ratio']

        # 获取 L1 和 L2 处的成交量
        vol_l1 = df['volume'].iloc[l1_idx]
        vol_l2 = df['volume'].iloc[l2_idx]

        # 防止除零
        if pd.isna(vol_l1) or vol_l1 <= 0:
            return {'shrink': False, 'shrink_ratio': 0.0}

        # 计算缩量比例
        ratio = vol_l2 / vol_l1
        # 缩量判定
        is_shrink = vol_l2 < vol_l1 * shrink_ratio_param

        return {'shrink': is_shrink, 'shrink_ratio': round(ratio, 2)}

    def _check_fake_w_bottom(self, df, l1_idx, neckline, break_idx):
        """
        假W底过滤（优化版本）
        
        条件1：L1 之前存在下跌趋势（最高价 > L1 × 1.2）
        条件2：突破后价格维持在颈线支撑位之上
        两个条件都满足才通过（不是假W底）。
        使用向量化操作优化性能。
        
        :param df: 含指标的DataFrame（倒序）
        :param l1_idx: L1 索引
        :param neckline: 颈线价格
        :param break_idx: 突破日索引
        :return: True 表示通过过滤（不是假W底）
        """
        long_period = self.params['long_ma_period']
        support_days = self.params['support_days']
        support_ratio = self.params['support_ratio']

        # 条件1：L1 之前 long_ma_period 个交易日内最高价 > L1 × 1.2
        # 倒序数据中 L1 之前 = 索引 > l1_idx
        l1_price = df['low'].iloc[l1_idx]
        before_start = l1_idx + 1
        before_end = min(l1_idx + long_period + 1, len(df))
        if before_start >= len(df):
            return False

        # 获取 L1 之前的数据
        before_df = df.iloc[before_start:before_end]
        if before_df.empty:
            return False
        max_high = before_df['high'].max()
        # 验证存在 20% 以上的下跌
        if max_high <= l1_price * 1.2:
            return False

        # 条件2：突破后至今所有交易日收盘价 >= 颈线 × (1 - support_ratio)
        support_price = neckline * (1 - support_ratio)
        # 倒序数据中突破后 = 索引 0 到 break_idx-1
        after_df = df.iloc[0:break_idx]
        
        # 向量化检查：是否有任何交易日跌破支撑位
        # 过滤掉NaN值
        valid_closes = after_df['close'].dropna()
        
        if not valid_closes.empty:
            # 检查是否有任何收盘价跌破支撑位
            if (valid_closes < support_price).any():
                return False

        return True
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：W底形态识别
        pattern_days = self.params['pattern_days']
        low_window = self.params['low_window']
        min_gap = self.params['min_gap']
        bottom_diff_threshold = self.params['bottom_diff_threshold'] * 100
        criteria.append(f"1. W底形态：最近{pattern_days}个交易日内形成双底结构，两个低点价格差异不超过{bottom_diff_threshold:.0f}%，间隔至少{min_gap}个交易日")
        
        # 条件2：颈线突破确认
        neckline_break_ratio = self.params['neckline_break_ratio'] * 100
        volume_expand_ratio = self.params['volume_expand_ratio']
        volume_ma_period = self.params['volume_ma_period']
        criteria.append(f"2. 颈线突破：价格突破颈线（突破{neckline_break_ratio:.0f}%），且成交量是前{volume_ma_period}日均量的{volume_expand_ratio:.1f}倍以上")
        
        # 条件3：趋势反转验证
        short_ma_period = self.params['short_ma_period']
        long_ma_period = self.params['long_ma_period']
        criteria.append(f"3. 趋势反转：{short_ma_period}日均线向上穿过{long_ma_period}日均线，或价格突破{long_ma_period}日均线，或MACD金叉（满足2个即可）")
        
        # 条件4：量价配合分析
        volume_shrink_ratio = self.params['volume_shrink_ratio'] * 100
        criteria.append(f"4. 量价配合：右侧低点成交量比左侧低点缩量{volume_shrink_ratio:.0f}%以上（加分项）")
        
        # 条件5：假W底过滤
        support_days = self.params['support_days']
        support_ratio = self.params['support_ratio'] * 100
        max_break_days = self.params['max_break_days']
        criteria.append(f"5. 假W底过滤：突破颈线后{support_days}天内收盘价不低于颈线{support_ratio:.0f}%，且突破发生在最近{max_break_days}天内")
        
        return criteria

    def _quick_precheck(self, df):
        """
        快速预检查：提前过滤不符合条件的股票
        
        检查内容：
        1. 检查是否有放量长阳线（涨幅≥5%）
        2. 检查是否有明显的双底形态（两个相近的低点）
        
        :param df: 股票数据DataFrame（倒序）
        :return: True表示通过预检查，False表示不通过
        """
        import numpy as np
        
        max_break_days = self.params.get('max_break_days', 10)
        
        # 检查1：检查是否有放量长阳线（涨幅≥5%）
        recent_df = df.head(max_break_days + 1)
        if len(recent_df) < 2:
            return False
        
        # 向量化计算涨跌幅
        pct_change = recent_df['close'].pct_change(-1)
        
        # 检查是否有涨幅≥5%的交易日
        if not (pct_change >= 0.05).any():
            return False
        
        # 检查2：检查是否有明显的双底形态
        # 获取最近20个交易日的最低价
        check_days = min(20, len(recent_df))
        lows = recent_df['low'].head(check_days).values
        
        if len(lows) < 10:
            return False
        
        # 找到最低点
        min_idx = np.argmin(lows)
        
        # 检查最低点位置是否合理（在中间位置）
        if min_idx < 2 or min_idx > check_days - 3:
            return False
        
        # 检查是否有两个相近的低点
        min_price = lows[min_idx]
        
        # 在最低点前后寻找第二个低点
        left_lows = lows[:min_idx]
        right_lows = lows[min_idx+1:]
        
        # 左侧寻找
        left_candidate = None
        if len(left_lows) >= 2:
            left_min_idx = np.argmin(left_lows)
            left_min_price = left_lows[left_min_idx]
            # 检查价格差异是否在合理范围内（±5%）
            if abs(left_min_price - min_price) / min_price <= 0.05:
                left_candidate = left_min_idx
        
        # 右侧寻找
        right_candidate = None
        if len(right_lows) >= 2:
            right_min_idx = np.argmin(right_lows)
            right_min_price = right_lows[right_min_idx]
            # 检查价格差异是否在合理范围内（±5%）
            if abs(right_min_price - min_price) / min_price <= 0.05:
                right_candidate = right_min_idx
        
        # 至少找到一个相近的低点
        if left_candidate is None and right_candidate is None:
            return False
        
        # 通过预检查
        return True

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股主逻辑，串联五个核心步骤
        
        流程：数据验证 → 计算指标 → W底形态识别 → 颈线突破确认 →
              趋势反转验证 → 量价配合分析 → 假W底过滤 → 生成信号
        
        :param df: 股票数据DataFrame
        :param stock_name: 股票名称，用于过滤ST/退市股票
        :return: 选股信号列表，每个元素为字典包含信号详情
        """
        try:
            # 数据验证：行数 < 60 返回空列表
            if df is None or len(df) < 60:
                return []

            # 过滤 ST/*ST 和退市股票
            if stock_name:
                name_upper = stock_name.upper()
                # ST 股票过滤
                if 'ST' in name_upper or '*ST' in name_upper:
                    return []
                # 退市/异常股票过滤
                for keyword in ['退', '未知', '退市', '已退']:
                    if keyword in stock_name:
                        return []

            # 快速预检查：提前过滤不符合条件的股票
            if not self._quick_precheck(df):
                return []

            # 计算技术指标
            df_with_indicators = self.calculate_indicators(df)
            if df_with_indicators.empty:
                return []

            # 步骤1：识别局部低点
            pattern_days = self.params['pattern_days']
            local_lows = self._find_local_lows(df_with_indicators, pattern_days)
            if len(local_lows) < 2:
                return []

            # 步骤2：识别W底形态
            w_bottom = self._find_w_bottom(local_lows, df_with_indicators)
            if w_bottom is None:
                return []
            l1_idx, l1_price, h_idx, h_price, l2_idx, l2_price = w_bottom
            # 颈线价格 = H 的价格
            neckline = h_price

            # 步骤3：颈线突破确认
            break_idx = self._check_neckline_break(df_with_indicators, l2_idx, neckline)
            if break_idx is None:
                return []

            # 步骤3.5：验证形态时间间隔（L1到突破日至少10个交易日）
            min_pattern_days = self.params['min_pattern_days']
            pattern_interval = l1_idx - break_idx
            if pattern_interval < min_pattern_days:
                return []

            # 步骤4：趋势反转验证
            trend_ok = self._check_trend_reversal(df_with_indicators)
            if not trend_ok:
                return []

            # 步骤5：量价配合分析（缩量为加分项）
            vol_analysis = self._check_volume_analysis(df_with_indicators, l1_idx, l2_idx)

            # 步骤6：假W底过滤
            fake_ok = self._check_fake_w_bottom(df_with_indicators, l1_idx, neckline, break_idx)
            if not fake_ok:
                return []

            # 生成信号：构建 reasons 列表
            reasons = ['W底形态确认']

            # 计算突破放量倍数
            break_vol = df_with_indicators['volume'].iloc[break_idx]
            break_vol_ma = df_with_indicators['volume_ma'].iloc[break_idx]
            if break_vol_ma > 0:
                vol_ratio = round(break_vol / break_vol_ma, 1)
            else:
                vol_ratio = 0.0
            reasons.append(f'颈线突破放量{vol_ratio}倍')

            # 趋势反转信息
            latest = df_with_indicators.iloc[0]
            trend_count = 0
            if not pd.isna(latest.get('short_ma')) and not pd.isna(latest.get('long_ma')):
                if latest['short_ma'] > latest['long_ma']:
                    trend_count += 1
            if not pd.isna(latest.get('short_term_trend')):
                if latest['short_term_trend'] > 0:
                    trend_count += 1
            if not pd.isna(latest.get('close')) and not pd.isna(latest.get('long_ma')):
                if latest['close'] > latest['long_ma']:
                    trend_count += 1
            reasons.append(f'趋势反转({trend_count}/3)')

            # 缩量加分项（可选）
            if vol_analysis['shrink']:
                reasons.append('右侧底部缩量')

            # 获取颈线突破日的日期
            break_date = df_with_indicators['date'].iloc[break_idx]
            
            # 构建信号字典
            signal = {
                'date': str(df_with_indicators['date'].iloc[0]),
                'close': float(df_with_indicators['close'].iloc[0]),
                'J': float(df_with_indicators['J'].iloc[0]) if 'J' in df_with_indicators.columns else 0.0,
                'volume_ratio': vol_ratio,
                'market_cap': float(df_with_indicators['market_cap'].iloc[0]) if 'market_cap' in df_with_indicators.columns else 0.0,
                'short_term_trend': float(df_with_indicators['short_term_trend'].iloc[0]) if 'short_term_trend' in df_with_indicators.columns else 0.0,
                'bull_bear_line': float(df_with_indicators['bull_bear_line'].iloc[0]) if 'bull_bear_line' in df_with_indicators.columns else 0.0,
                'neckline': float(neckline),
                'l1_price': float(l1_price),
                'l2_price': float(l2_price),
                # 格式化关键日期，只保留日期部分
                'key_date': break_date.strftime('%Y-%m-%d') if hasattr(break_date, 'strftime') else str(break_date)[:10],
                'key_date_type': '颈线突破日',
                'reasons': reasons
            }

            return [signal]

        except Exception:
            # 异常保护：返回空列表
            return []
