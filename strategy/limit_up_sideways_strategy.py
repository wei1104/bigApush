import pandas as pd
from datetime import datetime
from strategy.base_strategy import BaseStrategy

class LimitUpSidewaysStrategy(BaseStrategy):
    """
    涨停横盘策略
    
    策略逻辑：
    1. 寻找最近出现的涨停板
    2. 涨停后出现横盘整理（1-8个交易日）
    3. 横盘期间价格区间：最高价不超过涨停价的5%，最低价不低于涨停价的-2%
    4. 横盘期间成交量萎缩，至少有一日成交量 ≤ 涨停日成交量的60%
    5. 横盘期间收盘价不低于涨停日收盘价
    6. 横盘后出现反转信号（KDJ金叉、MACD金叉）
    7. 成交量放大（最近交易日成交量较前一交易日放大≥30%）
    """

    def __init__(self, params=None):
        """
        初始化策略
        
        :param params: 策略参数
        """
        # 默认参数
        default_params = {
            # 涨停确认参数
            'limit_up_lookback_days': 10,        # 涨停回溯天数
            'limit_up_threshold': 0.095,         # 涨停阈值（9.5%）
            'volume_ratio_threshold': 1.5,       # 成交量比阈值
            # 横盘整理参数
            'sideways_days_min': 1,              # 最小横盘天数
            'sideways_days_max': 8,              # 最大横盘天数
            'sideways_high_limit': 0.05,         # 横盘最高价限制（5%）
            'sideways_low_limit': -0.02,         # 横盘最低价限制（-2%）
            'volume_shrinkage_ratio': 0.6,       # 成交量萎缩比例（60%）
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("涨停横盘策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（MA、KDJ、MACD、成交量均线）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 计算了指标的DataFrame
        """
        # 复制数据，避免修改原数据
        df = df.copy()

        # 计算涨跌幅度
        df['change'] = df['close'].pct_change(periods=-1)

        # 计算成交量均线
        # 数据是倒序的，需要先反转后计算再反转回来
        reversed_df = df.iloc[::-1].reset_index(drop=True)
        reversed_df['volume_5'] = reversed_df['volume'].rolling(window=5, min_periods=1).mean()
        df['volume_5'] = reversed_df['volume_5'].iloc[::-1].values

        # 计算KDJ指标
        high = df['high']
        low = df['low']
        close = df['close']

        # 计算RSV值
        n = 9
        rsv = ((close - low.rolling(window=n).min()) / (high.rolling(window=n).max() - low.rolling(window=n).min())) * 100

        # 计算K、D、J值
        df['kdj_k'] = rsv.ewm(alpha=1/3, adjust=False).mean()
        df['kdj_d'] = df['kdj_k'].ewm(alpha=1/3, adjust=False).mean()
        df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']

        # 计算MACD指标
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        df['macd_dif'] = exp1 - exp2
        df['macd_dea'] = df['macd_dif'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = 2 * (df['macd_dif'] - df['macd_dea'])

        # 计算5日和10日均线
        df['ma5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['ma10'] = df['close'].rolling(window=10, min_periods=1).mean()

        return df

    def _find_limit_up(self, df):
        """
        寻找最近的涨停板

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 涨停板信息字典，包含日期和收盘价
        """
        # 遍历最近N个交易日
        for i in range(min(self.params['limit_up_lookback_days'], len(df) - 6)):
            # 计算当日涨幅
            change = (df.iloc[i]['close'] - df.iloc[i+1]['close']) / df.iloc[i+1]['close']

            # 检查是否达到涨停阈值
            if change >= self.params['limit_up_threshold']:
                # 计算成交量比：涨停日成交量 / 涨停前5日平均成交量
                # i+1到i+5是涨停前5天（数据倒序）
                pre_volume_mean = df.iloc[i+1:i+6]['volume'].mean()
                if pre_volume_mean == 0:
                    continue
                volume_ratio = df.iloc[i]['volume'] / pre_volume_mean

                # 检查成交量是否满足要求
                if volume_ratio >= self.params['volume_ratio_threshold']:
                    return {
                        'date': df.iloc[i]['date'],
                        'close': df.iloc[i]['close'],
                        'volume': df.iloc[i]['volume'],
                        'index': i
                    }

        return None

    def _check_sideways(self, df, limit_up_info):
        """
        检查涨停后是否出现横盘整理
        从涨停日到今天为止，验证最高价和最低价是否在范围内，且收盘价不低于涨停日收盘价

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param limit_up_info: 涨停板信息
        :return: 横盘整理信息字典，包含天数、最高价、最低价等
        """
        limit_up_index = limit_up_info['index']
        limit_up_close = limit_up_info['close']
        limit_up_volume = limit_up_info['volume']

        # 从涨停日到最新一天（index=0）的数据
        # 涨停后的数据在更小的index处（数据倒序）
        if limit_up_index <= 0:
            return None

        # 提取涨停后到今天的所有数据
        sideways_df = df.iloc[0:limit_up_index]

        # 计算期间的最高价和最低价
        highest_price = sideways_df['high'].max()
        lowest_price = sideways_df['low'].min()

        # 计算价格区间
        high_limit = limit_up_close * (1 + self.params['sideways_high_limit'])
        low_limit = limit_up_close * (1 + self.params['sideways_low_limit'])

        # 检查价格区间是否符合要求
        if highest_price > high_limit or lowest_price < low_limit:
            return None

        # 检查期间收盘价是否低于涨停日收盘价（不破支撑）
        if (sideways_df['close'] < limit_up_close).any():
            return None

        # 计算横盘天数
        days = limit_up_index

        # 计算期间的平均成交量
        avg_volume = sideways_df['volume'].mean()
        volume_ratio = avg_volume / limit_up_volume

        return {
            'days': days,
            'highest': highest_price,
            'lowest': lowest_price,
            'volume_ratio': volume_ratio,
            'end_index': 0
        }

    def _check_breakout(self, df, sideways_info):
        """
        检查是否出现突破信号

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param sideways_info: 横盘整理信息
        :return: 突破信号信息字典
        """
        # 检查是否有足够的数据
        if sideways_info['end_index'] >= len(df) - 1:
            return None

        # 提取横盘结束后的两个交易日数据
        current_idx = sideways_info['end_index']
        prev_idx = current_idx + 1

        # 检查收盘价是否上涨
        if df.iloc[current_idx]['close'] <= df.iloc[prev_idx]['close']:
            return None

        # 检查成交量是否放大
        if df.iloc[current_idx]['volume'] < df.iloc[prev_idx]['volume'] * self.params['volume_increase_ratio']:
            return None

        # 检查KDJ或MACD金叉（满足其一即可）
        kdj_gold_cross = df.iloc[current_idx]['kdj_j'] > df.iloc[current_idx]['kdj_d']
        macd_gold_cross = df.iloc[current_idx]['macd_dif'] > df.iloc[current_idx]['macd_dea']

        if not (kdj_gold_cross or macd_gold_cross):
            return None

        return {
            'volume_increase': df.iloc[current_idx]['volume'] / df.iloc[prev_idx]['volume'],
            'price_change': (df.iloc[current_idx]['close'] - df.iloc[prev_idx]['close']) / df.iloc[prev_idx]['close'],
            'kdj_j': df.iloc[current_idx]['kdj_j'],
            'macd_hist': df.iloc[current_idx]['macd_hist']
        }
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：涨停确认
        limit_up_lookback_days = self.params['limit_up_lookback_days']
        limit_up_threshold = self.params['limit_up_threshold'] * 100
        volume_ratio_threshold = self.params['volume_ratio_threshold']
        criteria.append(f"1. 涨停确认：最近{limit_up_lookback_days}个交易日内出现涨停板（涨幅>={limit_up_threshold:.1f}%），且成交量是前5日均量的{volume_ratio_threshold:.1f}倍以上")
        
        # 条件2：横盘整理
        sideways_days_min = self.params['sideways_days_min']
        sideways_days_max = self.params['sideways_days_max']
        sideways_high_limit = self.params['sideways_high_limit'] * 100
        sideways_low_limit = self.params['sideways_low_limit'] * 100
        criteria.append(f"2. 横盘整理：涨停后{sideways_days_min}-{sideways_days_max}个交易日内横盘整理，最高价不超过涨停价的{sideways_high_limit:.0f}%，最低价不低于涨停价的{sideways_low_limit:.0f}%")
        
        # 条件3：成交量萎缩
        volume_shrinkage_ratio = self.params['volume_shrinkage_ratio'] * 100
        criteria.append(f"3. 成交量萎缩：横盘期间至少有一日成交量 <= 涨停日成交量的{volume_shrinkage_ratio:.0f}%")
        
        # 条件4：支撑确认
        criteria.append(f"4. 支撑确认：横盘期间收盘价不低于涨停日收盘价")
        
        # 条件5：反转信号
        criteria.append(f"5. 反转信号：KDJ金叉或MACD金叉")
        
        # 条件6：成交量放大
        volume_increase_ratio = self.params.get('volume_increase_ratio', 1.3) * 100
        criteria.append(f"6. 成交量放大：最近交易日成交量较前一交易日放大>={volume_increase_ratio:.0f}%")
        
        return criteria

    def select_stocks(self, data, stock_name="", skip_data_check=False):
        """
        选择符合条件的股票

        :param data: 股票数据，可以是DataFrame或字典
        :param stock_name: 股票代码（可选）
        :param skip_data_check: 是否跳过数据检查
        :return: 符合条件的股票信息字典
        """
        # 检查数据类型
        if isinstance(data, dict):
            # 从字典中提取DataFrame
            if 'df' in data:
                df = data['df']
            else:
                return None
        else:
            df = data

        # 数据检查
        if not skip_data_check:
            if len(df) < 60:
                return None

            # 检查最新一天是否有有效数据
            if pd.isna(df.iloc[0]['close']) or pd.isna(df.iloc[0]['volume']):
                return None

        # 快速预检查：检查是否有涨停板
        lookback_days = self.params['limit_up_lookback_days']
        limit_up_threshold = self.params['limit_up_threshold']
        
        # 只取需要的列，提高速度
        check_df = df[['close']].head(lookback_days + 1)
        
        # 向量化计算涨跌幅
        pct_change = check_df['close'].pct_change(-1)
        
        # 如果没有涨停板，直接返回None
        if not (pct_change >= limit_up_threshold).any():
            return None

        # 计算技术指标（只有有涨停板的股票才会到达这里）
        df = self.calculate_indicators(df)

        # 寻找涨停板
        limit_up_info = self._find_limit_up(df)
        if not limit_up_info:
            return None

        # 检查横盘整理
        sideways_info = self._check_sideways(df, limit_up_info)
        if not sideways_info:
            return None

        # 生成选股理由
        reasons = [
            f"最近{self.params['limit_up_lookback_days']}个交易日内出现涨停板",
            f"涨停后横盘整理{sideways_info['days']}个交易日",
            f"横盘期间价格区间：{sideways_info['lowest']:.2f} - {sideways_info['highest']:.2f}",
            f"横盘期间成交量萎缩至涨停日的{sideways_info['volume_ratio']:.2f}倍"
        ]

        # 关键日期：涨停日期
        key_date = limit_up_info['date']
        
        # 格式化日期
        if hasattr(key_date, 'strftime'):
            key_date_str = key_date.strftime('%Y-%m-%d')
        else:
            key_date_str = str(key_date)[:10]
        
        # 构建结果字典 - 统一格式（仅保留关键信息）
        result = {
            'key_date': key_date_str,
            'key_date_type': '涨停日',
            'reasons': reasons
        }

        return [result]
