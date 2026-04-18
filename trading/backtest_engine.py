"""
回测引擎核心模块
实现量化策略的自动化回测功能
"""

import sqlite3
import datetime
import logging
import numpy as np
import pandas as pd
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from utils.db_manager import DBManager
from utils.akshare_fetcher import AKShareFetcher
from strategy.strategy_registry import StrategyRegistry
from trading.stock_score_api import calculate_stock_score
from trading.backtest_scorer import BacktestScoreCalculator

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BacktestEngine:
    """回测引擎核心类"""
    
    def __init__(self, *args, **kwargs):
        """初始化回测引擎
        
        Args:
            *args: 可变参数
            **kwargs: 关键字参数
        """
        # 从参数中获取db_path，默认值为"data/stock_selection.db"
        db_path = kwargs.get('db_path', "data/stock_selection.db")
        if args:
            db_path = args[0]
        
        from utils.global_db import get_global_db
        self.db_manager = get_global_db()
        self.akshare_fetcher = AKShareFetcher("data")
        self.strategy_registry = StrategyRegistry()
        # 初始化K线数据获取器
        from utils.stock_data_fetcher import StockDataFetcher
        self.stock_data_fetcher = StockDataFetcher("data")
        from utils.kline_fetcher import KlineFetcher
        self.kline_fetcher = KlineFetcher(self.db_manager, self.stock_data_fetcher)
        
        # 初始化回测专用评分器
        self.score_calculator = BacktestScoreCalculator(db_manager=self.db_manager)
        
        # 股票数据缓存（性能优化）
        self.stock_data_cache = {}  # {code: df} 完整历史数据
        self.stock_name_cache = {}  # {code: name} 股票名称缓存
        self.stock_filtered_cache = {}  # {code: df} 已过滤ST/退市的股票
        
        # 可买股票池
        self.buy_candidate_pool = []  # 可买股票池，每个元素包含股票信息和加入日期
        
        # 交易日历缓存
        self.trading_calendar_cache = {}  # {date_str: is_open} 交易日历缓存
        self._sorted_trading_dates = []   # 排序后的交易日列表
        
    def run_backtest(self, strategy_name: str, config: Dict) -> Dict:
        """运行回测
        
        Args:
            strategy_name: 策略名称
            config: 回测配置参数
            
        Returns:
            回测结果字典
        """
        try:
            logger.info(f"开始回测策略: {strategy_name}")
            
            # 清空上次的缓存数据
            self.stock_data_cache.clear()
            self.stock_name_cache.clear()
            self.stock_filtered_cache.clear()
            
            # 1. 获取回测日期范围
            start_date = config.get('start_date')
            end_date = config.get('end_date')
            
            if not start_date or not end_date:
                raise ValueError("回测开始日期和结束日期不能为空")
            
            # 2. 确保策略已注册
            if not self.strategy_registry.strategies:
                self.strategy_registry.auto_register_from_directory("strategy")
            
            # 3. 加载交易日历（在预加载数据之前，先确定交易日）
            self._load_trading_calendar(start_date, end_date)
            
            # 4. 获取回测交易日列表并打印
            date_range = self._get_trading_dates(start_date, end_date)
            if not date_range:
                raise ValueError(f"回测期间 {start_date} ~ {end_date} 没有交易日")
            
            # 5. 预加载所有股票数据到内存（根据策略参数动态计算历史数据天数）
            self._preload_stock_data(start_date, end_date, strategy_name)
            
            # 4. 初始化回测环境
            initial_capital = config.get('initial_capital', 1000000)
            current_capital = initial_capital
            positions = []  # 持仓列表
            trades = []     # 交易记录
            capital_history = [initial_capital]  # 资金历史
            dates = []      # 回测日期列表
            
            for i, current_date in enumerate(date_range):
                logger.info(f"处理日期: {current_date}")
                
                # 初始化当日买入计数
                daily_buys = 0
                max_daily_buys = config.get('max_daily_buys', 5)
                candidate_track_days = config.get('candidate_track_days', 5)
                
                # 统一处理逻辑：先处理卖出，再处理买入
                
                # 处理卖出（如果有持仓）
                if positions:
                    logger.info(f"开始执行卖出操作，当前持仓数: {len(positions)}")
                    positions, sell_records = self._process_sell(positions, current_date, config)
                    logger.info(f"卖出操作完成，卖出 {len(sell_records)} 笔交易，剩余持仓数: {len(positions)}")
                    
                    # 更新资金（卖出资金立即可用）
                    for sell_record in sell_records:
                        current_capital += sell_record['sell_amount']
                        trades.append(sell_record)
                        logger.info(f"卖出股票: {sell_record['stock_code']} {sell_record['stock_name']}, 类型: {sell_record['sell_type']}, 收益率: {sell_record['return_rate']:.2f}%")
                
                # 执行选股获得前一日的选股结果
                selection_date = self._get_previous_trading_day(current_date)
                logger.info(f"执行选股日期: {selection_date}")
                
                # 执行选股（内存中处理，不存入数据库）
                logger.info(f"开始执行选股，策略: {strategy_name}，日期: {selection_date}")
                selected_stocks = self._execute_selection(strategy_name, selection_date)
                logger.info(f"选股完成，共选出 {len(selected_stocks)} 只股票")
                
                # 评分并筛选（回测模式：不依赖数据库）
                logger.info(f"开始对 {len(selected_stocks)} 只股票进行评分")
                scored_stocks = self._score_stocks(selected_stocks, strategy_name, selection_date)
                # 记录每只股票的综合评分
                for stock in scored_stocks:
                    logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 综合评分: {stock['score']}，否决标志: {stock.get('veto_flag', False)}")
                candidate_stocks = [stock for stock in scored_stocks if not stock.get('veto_flag', False) and stock['score'] >= config.get('score_threshold', 60)]
                
                logger.info(f"筛选后待买入股票数: {len(candidate_stocks)}")
                
                # 将新选出的股票加入可买股票池
                for stock in candidate_stocks:
                    # 检查是否已经在池中
                    if not any(item['stock']['stock_code'] == stock['stock_code'] for item in self.buy_candidate_pool):
                        self.buy_candidate_pool.append({
                            'stock': stock,
                            'added_date': selection_date,
                            'strategy_name': strategy_name
                        })
                        logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 加入可买股票池")
                
                # 处理可买股票池
                logger.info(f"当前可买股票池数量: {len(self.buy_candidate_pool)}")
                remaining_candidates = []
                
                # 记录当日已买入的股票代码
                today_bought_stocks = set()
                
                for candidate in self.buy_candidate_pool:
                    stock = candidate['stock']
                    stock_code = stock['stock_code']
                    added_date = candidate['added_date']
                    
                    # 检查是否已经持有
                    if any(p['stock_code'] == stock_code for p in positions):
                        logger.info(f"股票 {stock_code} 已持有，从可买股票池中移除")
                        continue
                    
                    # 检查当日是否已经买入过
                    if stock_code in today_bought_stocks:
                        logger.info(f"股票 {stock_code} 当日已买入，从可买股票池中移除")
                        continue
                    
                    # 计算跟踪的交易日天数
                    # 获取从加入日期到当前选股日期的所有交易日
                    trading_dates = self._get_trading_dates(added_date.strftime('%Y-%m-%d'), selection_date.strftime('%Y-%m-%d'))
                    track_days = len(trading_dates)
                    logger.info(f"股票 {stock_code} {stock['stock_name']} 已跟踪 {track_days} 个交易日")
                    
                    # 检查是否跟踪满5个交易日
                    if track_days >= candidate_track_days:
                        logger.info(f"股票 {stock_code} {stock['stock_name']} 跟踪满 {candidate_track_days} 个交易日，从可买股票池中移除")
                        continue
                    
                    # 从选股信号中解析关键日期
                    signal = stock.get('signal', {})
                    key_date = self._extract_key_date(signal)
                    
                    # 如果没有关键日期，跳过支撑位计算
                    if not key_date:
                        logger.warning(f"选股信号中没有关键日期，跳过支撑位计算: {stock_code}")
                        support_level = 0.0
                    else:
                        # 使用关键日期计算支撑位
                        support_level = self._calculate_support_level(stock, key_date, config.get('support_method', 'ma20'))
                    
                    logger.info(f"股票 {stock_code} {stock['stock_name']} 支撑位置: {support_level}")
                    
                    # 计算买入价格（当日开盘价）
                    buy_price = self._get_stock_price(stock_code, current_date, 'open')
                    logger.info(f"股票 {stock_code} {stock['stock_name']} 当日开盘价: {buy_price}")
                    
                    # 买点判断
                    is_buy = self._is_buy_point(buy_price, support_level, config)
                    logger.info(f"股票 {stock_code} {stock['stock_name']} 买点判断: {is_buy}")
                    
                    if is_buy:
                        if daily_buys >= max_daily_buys:
                            logger.info(f"达到单日最大买入限制: {max_daily_buys}")
                            remaining_candidates.append(candidate)
                            continue
                        
                        # 计算买入金额
                        buy_amount = min(config.get('buy_amount', 100000), current_capital)
                        
                        if buy_amount > 0:
                            # 计算买入数量
                            quantity = int(buy_amount / buy_price)
                            if quantity > 0:
                                # 执行买入
                                buy_record = self._execute_buy(
                                    stock_code,
                                    stock['stock_name'],
                                    added_date,
                                    current_date,
                                    buy_price,
                                    buy_amount,
                                    quantity,
                                    support_level
                                )
                                
                                # 更新持仓和资金
                                positions.append({
                                    'stock_code': stock_code,
                                    'stock_name': stock['stock_name'],
                                    'buy_date': current_date,
                                    'buy_price': buy_price,
                                    'quantity': quantity,
                                    'buy_amount': buy_amount,
                                    'support_level': support_level
                                })
                                
                                current_capital -= buy_amount
                                trades.append(buy_record)
                                daily_buys += 1
                                
                                # 记录当日已买入的股票
                                today_bought_stocks.add(stock_code)
                                
                                logger.info(f"买入股票: {stock_code} {stock['stock_name']}, 价格: {buy_price}, 数量: {quantity}, 金额: {buy_amount}")
                    else:
                        # 未达到买点，继续在池中跟踪
                        remaining_candidates.append(candidate)
                
                # 更新可买股票池
                self.buy_candidate_pool = remaining_candidates
                logger.info(f"处理后可买股票池数量: {len(self.buy_candidate_pool)}")
                
                # 计算当日总资产（可用资金 + 持仓市值）
                total_assets = current_capital
                for position in positions:
                    # 获取当日收盘价
                    current_price = self._get_stock_price(position['stock_code'], current_date, 'close')
                    position_value = current_price * position['quantity']
                    total_assets += position_value
                
                # 记录资金历史（包含持仓市值）
                capital_history.append(total_assets)
                dates.append(current_date)
            
            # 4. 结束结算：计算剩余持仓市值
            if positions:
                logger.info("计算剩余持仓市值")
                final_date = date_range[-1]
                for position in positions:
                    # 计算当前市值（最后一日收盘价）
                    current_price = self._get_stock_price(position['stock_code'], final_date, 'close')
                    current_value = current_price * position['quantity']
                    current_capital += current_value
                    logger.info(f"剩余持仓: {position['stock_code']} {position['stock_name']}, 市值: {current_value:.2f}")
            
            # 5. 计算绩效指标
            final_capital = current_capital
            performance = self._calculate_performance(trades, initial_capital, final_capital, dates, capital_history)
            
            # 6. 构建回测结果
            backtest_result = {
                'strategy_name': strategy_name,
                'config': config,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'final_capital': final_capital,
                'performance': performance,
                'trades': trades,
                'capital_history': capital_history,
                'dates': dates
            }
            
            logger.info(f"回测完成，初始资金: {initial_capital}, 最终资金: {final_capital}, 总收益率: {performance['total_return']:.2f}%")
            
            return backtest_result
            
        except Exception as e:
            logger.error(f"回测失败: {str(e)}")
            raise
    
    # ==================== 支撑位计算辅助方法 ====================
    
    def _extract_key_date(self, signal: Dict) -> Optional[datetime.date]:
        """从选股信号中提取关键日期
        
        Args:
            signal: 选股信号字典，可能包含以下字段：
                - key_date: 关键日期（字符串，格式 YYYY-MM-DD）
                - key_dates: 关键日期JSON数组
                
        Returns:
            关键日期（datetime.date）或 None
        """
        try:
            # 方式1：直接获取 key_date 字段
            if 'key_date' in signal and signal['key_date']:
                key_date_str = signal['key_date']
                # 处理字符串格式
                if isinstance(key_date_str, str):
                    return datetime.datetime.strptime(key_date_str, '%Y-%m-%d').date()
                # 处理datetime对象
                elif isinstance(key_date_str, datetime.datetime):
                    return key_date_str.date()
                elif isinstance(key_date_str, datetime.date):
                    return key_date_str
            
            # 方式2：从 key_dates JSON 数组中获取第一个
            if 'key_dates' in signal and signal['key_dates']:
                key_dates_str = signal['key_dates']
                
                # 如果是字符串，需要解析JSON
                if isinstance(key_dates_str, str):
                    try:
                        key_dates_list = json.loads(key_dates_str)
                    except json.JSONDecodeError:
                        logger.warning(f"无法解析key_dates JSON: {key_dates_str}")
                        return None
                else:
                    key_dates_list = key_dates_str
                
                # 获取第一个关键日期
                if key_dates_list and len(key_dates_list) > 0:
                    first_key_date = key_dates_list[0]
                    # 处理字典格式
                    if isinstance(first_key_date, dict):
                        key_date_str = first_key_date.get('date')
                    else:
                        key_date_str = first_key_date
                    
                    if key_date_str:
                        if isinstance(key_date_str, str):
                            return datetime.datetime.strptime(key_date_str, '%Y-%m-%d').date()
                        elif isinstance(key_date_str, datetime.datetime):
                            return key_date_str.date()
                        elif isinstance(key_date_str, datetime.date):
                            return key_date_str
            
            # 如果没有找到关键日期，返回None
            logger.debug(f"选股信号中没有关键日期")
            return None
            
        except Exception as e:
            logger.error(f"解析关键日期失败: {str(e)}")
            return None
    
    def _normalize_support_method(self, method: str) -> str:
        """将旧方法名称转换为新方法名称
        
        Args:
            method: 支撑位计算方法名称
            
        Returns:
            标准化后的方法名称
        """
        # 方法名称映射（旧 -> 新）
        METHOD_NAME_MAPPING = {
            'ma20': 'ma20',
            'close_95': 'key_close_5',
            'open': 'key_open',
            'close': 'key_close',
            'resistance': None,  # 不支持
            'key_close_5': 'key_close_5',
            'key_open': 'key_open',
            'key_close': 'key_close',
        }
        
        # 获取标准化后的方法名称
        normalized_method = METHOD_NAME_MAPPING.get(method, method)
        
        # 如果方法不支持，使用默认方法
        if normalized_method is None:
            logger.warning(f"方法 {method} 不再支持，使用默认方法 'ma20'")
            return 'ma20'
        
        # 如果是旧方法名称，添加警告日志
        if method != normalized_method and method in METHOD_NAME_MAPPING:
            logger.warning(f"方法 {method} 已过时，请使用 {normalized_method}")
        
        return normalized_method
    
    def _load_trading_calendar(self, start_date: str, end_date: str):
        """加载交易日历数据（扩大范围，覆盖前一交易日查找需求）
        
        Args:
            start_date: 回测开始日期 (YYYY-MM-DD)
            end_date: 回测结束日期 (YYYY-MM-DD)
        """
        try:
            import tushare as ts
            
            # 读取Tushare token
            tushare_token = None
            try:
                import json
                with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    tushare_token = config.get('token') or config.get('api_key')
            except:
                pass
            
            if not tushare_token:
                logger.warning("未找到Tushare token，使用简单的交易日判断（仅过滤周末）")
                return
            
            # 扩大加载范围：往前多加载60天，覆盖_get_previous_trading_day的需求
            from datetime import timedelta
            extended_start = (datetime.datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=60)).strftime('%Y%m%d')
            end_date_str = end_date.replace('-', '')
            
            # 获取交易日历（只获取交易日）
            pro = ts.pro_api(tushare_token)
            df = pro.trade_cal(
                exchange='SSE',
                start_date=extended_start,
                end_date=end_date_str,
                is_open='1'
            )
            
            if df.empty:
                logger.warning("未获取到交易日历数据，使用简单的交易日判断（仅过滤周末）")
                return
            
            # 清空旧缓存
            self.trading_calendar_cache.clear()
            
            # 构建交易日缓存和排序列表
            trading_dates_sorted = []
            for _, row in df.iterrows():
                cal_date = row['cal_date']
                date_str = f"{cal_date[:4]}-{cal_date[4:6]}-{cal_date[6:8]}"
                self.trading_calendar_cache[date_str] = True
                trading_dates_sorted.append(date_str)
            
            # 按日期排序（tushare返回的可能是倒序）
            trading_dates_sorted.sort()
            # 保存排序后的交易日列表，供_get_previous_trading_day使用
            self._sorted_trading_dates = trading_dates_sorted
            
            logger.info(f"成功加载交易日历数据，共 {len(self.trading_calendar_cache)} 个交易日")
            
        except Exception as e:
            logger.warning(f"加载交易日历数据失败: {str(e)}，使用简单的交易日判断（仅过滤周末）")
            self.trading_calendar_cache.clear()
            self._sorted_trading_dates = []
    
    def _is_trading_day(self, date: datetime.date) -> bool:
        """判断是否为交易日
        
        Args:
            date: 日期
            
        Returns:
            是否为交易日
        """
        date_str = date.strftime('%Y-%m-%d')
        
        # 如果交易日历缓存已加载，使用缓存判断
        if self.trading_calendar_cache:
            # 缓存中只存了交易日，不在缓存中说明不是交易日
            is_open = date_str in self.trading_calendar_cache
            logger.debug(f"使用交易日历判断日期 {date_str} 是否为交易日: {is_open}")
            return is_open
        
        # 如果没有交易日历数据，使用简单的判断（仅过滤周末）
        is_open = date.weekday() < 5
        logger.debug(f"使用简单判断日期 {date_str} 是否为交易日: {is_open}")
        return is_open
    
    def _get_trading_dates(self, start_date: str, end_date: str) -> List[datetime.date]:
        """获取回测期间的交易日列表
        
        直接从已加载的交易日历缓存中筛选，确保只处理真实交易日。
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            交易日期列表
        """
        # 如果有排序好的交易日列表，直接筛选
        if hasattr(self, '_sorted_trading_dates') and self._sorted_trading_dates:
            dates = [
                datetime.datetime.strptime(d, '%Y-%m-%d').date()
                for d in self._sorted_trading_dates
                if start_date <= d <= end_date
            ]
        else:
            # fallback：逐日遍历，仅过滤周末
            start = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
            dates = []
            current = start
            while current <= end:
                if self._is_trading_day(current):
                    dates.append(current)
                current += datetime.timedelta(days=1)
        
        # 打印回测交易日列表
        logger.info(f"回测交易日: {start_date} 至 {end_date}，共 {len(dates)} 个交易日")
        for d in dates:
            logger.info(f"  交易日: {d.strftime('%Y-%m-%d')}")
        
        return dates
    
    def _get_previous_trading_day(self, date: datetime.date) -> datetime.date:
        """获取前一个交易日
        
        优先从排序好的交易日列表中二分查找，效率更高且准确。
        
        Args:
            date: 当前日期
            
        Returns:
            前一个交易日
        """
        date_str = date.strftime('%Y-%m-%d')
        
        # 优先使用排序好的交易日列表
        if hasattr(self, '_sorted_trading_dates') and self._sorted_trading_dates:
            import bisect
            # 找到date_str在列表中的插入位置
            idx = bisect.bisect_left(self._sorted_trading_dates, date_str)
            # 前一个交易日是idx-1位置的日期
            if idx > 0:
                prev_date_str = self._sorted_trading_dates[idx - 1]
                return datetime.datetime.strptime(prev_date_str, '%Y-%m-%d').date()
        
        # fallback：逐日向前查找
        previous = date - datetime.timedelta(days=1)
        max_attempts = 10
        attempts = 0
        while attempts < max_attempts:
            if self._is_trading_day(previous):
                return previous
            previous -= datetime.timedelta(days=1)
            attempts += 1
        
        logger.warning(f"未找到前一个交易日，返回: {date - datetime.timedelta(days=1)}")
        return date - datetime.timedelta(days=1)
        return date - datetime.timedelta(days=1)
    
    def _get_stock_name(self, code: str) -> str:
        """获取股票名称（优先从缓存获取）
        
        Args:
            code: 股票代码
            
        Returns:
            股票名称，如果未找到则返回"未知"
        """
        # 优先从缓存获取
        if code in self.stock_name_cache:
            return self.stock_name_cache[code]
        
        try:
            cursor = self.db_manager.execute(
                "SELECT name FROM stock_basic WHERE code = ?",
                (code,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                name = row[0]
                self.stock_name_cache[code] = name
                return name
        except Exception as e:
            logger.debug(f"获取股票名称失败 {code}: {str(e)}")
        return "未知"
    
    def _preload_stock_data(self, start_date: str, end_date: str, strategy_name: str = None) -> int:
        """预加载所有股票数据到内存（性能优化）
        
        Args:
            start_date: 回测开始日期
            end_date: 回测结束日期
            strategy_name: 策略名称，用于计算需要的历史数据天数
            
        Returns:
            预加载的股票数量
        """
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        
        # 根据策略参数计算需要的历史数据天数
        buffer_days = 60  # 基础缓冲
        required_days = buffer_days
        
        if strategy_name:
            # 获取策略参数
            strategy = self.strategy_registry.get_strategy(strategy_name)
            if strategy and hasattr(strategy, 'params'):
                params = strategy.params
                max_value = 0
                
                # 常见回溯参数名 - 包含所有策略的历史数据需求参数
                lookback_keys = [
                    'lookback_days',                # 多金叉共振、多方炮、阻力位突破、启明星、底部趋势拐点
                    'pattern_days',                 # W底策略
                    'search_days',                  # 预留
                    'resonance_days',               # 预留
                    'limit_up_lookback_days',       # 涨停回马枪、涨停横盘
                    'lowest_point_lookback_days',   # 趋势加速拐点
                    'surge_lookback_days',          # 趋势加速拐点
                    'uptrend_lookback_days',        # 趋势加速拐点
                ]
                period_keys = ['ma_period', 'ma_short_period', 'ma_long_period', 'kdj_n', 'kdj_m1', 'kdj_m2',
                              'macd_short', 'macd_long', 'macd_signal', 'volume_ma_period', 'short_ma_period', 
                              'long_ma_period', 'period', 'min_pattern_days', 'max_break_days']
                
                # 获取回溯天数
                for key in lookback_keys:
                    if key in params:
                        val = params[key]
                        if isinstance(val, (int, float)):
                            max_value = max(max_value, int(val))
                
                # 获取周期参数
                for key in period_keys:
                    if key in params:
                        val = params[key]
                        if isinstance(val, (int, float)):
                            max_value = max(max_value, int(val))
                
                required_days = max_value + buffer_days
                logger.info(f"策略 {strategy_name} 需要 {max_value} 天历史数据 + {buffer_days} 天缓冲")
        
        # 扩展开始日期
        extended_start = (start_dt - timedelta(days=required_days)).strftime('%Y-%m-%d')
        
        logger.info(f"预加载股票数据: {extended_start} ~ {end_date} (原始: {start_date} ~ {end_date}, 加载历史: {required_days}天)")
        
        # 获取所有股票代码
        stock_codes = self.db_manager.list_all_stocks()
        total = len(stock_codes)
        loaded = 0
        skipped = 0
        
        for i, code in enumerate(stock_codes):
            try:
                # 读取股票数据
                df = self.db_manager.read_stock(code)
                
                if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 60:
                    skipped += 1
                    continue
                
                # 缓存原始数据
                self.stock_data_cache[code] = df.copy()
                
                # 获取并缓存股票名称
                name = self._get_stock_name(code)
                
                # 过滤ST股票和退市股票
                invalid = name.startswith('ST') or name.startswith('*ST')
                if not invalid:
                    for kw in ['退', '未知', '退市', '已退']:
                        if kw in name:
                            invalid = True
                            break
                
                if invalid:
                    skipped += 1
                    continue
                
                # 缓存有效股票
                self.stock_filtered_cache[code] = df.copy()
                loaded += 1
                
            except Exception as e:
                logger.debug(f"预加载股票 {code} 失败: {str(e)}")
                skipped += 1
            
            # 每500只显示一次进度
            if (i + 1) % 500 == 0:
                logger.info(f"预加载进度: {i + 1}/{total}, 有效股票: {loaded}, 跳过: {skipped}")
        
        logger.info(f"预加载完成: 有效股票 {loaded}, 跳过 {skipped}, 总计 {total}")
        return loaded
    
    def _execute_selection(self, strategy_name: str, date: datetime.date) -> List[Dict]:
        """执行选股（从缓存读取，使用日期切片）
        
        Args:
            strategy_name: 策略名称
            date: 选股日期
            
        Returns:
            选股结果列表
        """
        try:
            # 确保策略注册表已加载策略
            if not self.strategy_registry.strategies:
                self.strategy_registry.auto_register_from_directory("strategy")
            
            # 获取策略 - 策略注册时使用 self.name（如"启明星策略"）
            strategy = self.strategy_registry.get_strategy(strategy_name)
            
            if not strategy:
                raise ValueError(f"策略 {strategy_name} 不存在")
            
            # 标准化返回格式
            standardized_stocks = []
            
            # 从缓存遍历有效股票
            for code, df in self.stock_filtered_cache.items():
                try:
                    # 日期切片：只取到目标日期为止的数据
                    date_str = date.strftime('%Y-%m-%d')
                    df_to_date = df[df['date'] <= date_str].copy()
                    
                    # 检查数据是否为空（预加载时已检查过至少60条，这里只检查是否有数据）
                    if df_to_date.empty:
                        continue
                    
                    # 反转数据为倒序（最新的在前）
                    # 策略实现假设数据是倒序排列，但数据库返回的是升序排列
                    df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
                    
                    # 获取股票名称
                    name = self.stock_name_cache.get(code, "未知")
                    
                    # 直接传原始数据给select_stocks，让策略自行决定是否计算指标
                    # 多数策略的select_stocks内部已包含预检查和指标计算逻辑
                    # 避免对所有股票无差别计算指标导致性能瓶颈
                    signal_list = strategy.select_stocks(df_to_date, name)
                    
                    # 处理选股结果
                    if signal_list:
                        for signal in signal_list:
                            stock_info = {
                                'stock_code': code,
                                'stock_name': name,
                                'signal': signal
                            }
                            standardized_stocks.append(stock_info)
                            
                except Exception as e:
                    # 单只股票选股失败不影响整体流程
                    logger.debug(f"股票 {code} 选股失败: {str(e)}")
                    continue
            
            logger.info(f"{strategy_name} 策略在 {date} 选出 {len(standardized_stocks)} 只股票")
            
            return standardized_stocks
            
        except Exception as e:
            logger.error(f"执行选股失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _score_stocks(self, stocks: List[Dict], strategy_name: str, date: datetime.date) -> List[Dict]:
        """对股票进行评分（回测模式）
        
        使用 BacktestScoreCalculator 进行高效评分：
        - 技术面得分 = Σ(策略权重 × 命中标志)
        - 综合得分 = 技术面×0.35 + 资金面×0.35 + 基本面×0.10 + 板块×0.10 + 事件×0.10
        - 一票否决：M头策略 + 多死叉共振同时命中 → -100分
        - 技术面否决后立即跳过其他维度计算
        
        Args:
            stocks: 股票列表（来自选股结果）
            strategy_name: 策略名称
            date: 评分日期
            
        Returns:
            带评分的股票列表
        """
        if not stocks:
            return []
        
        date_str = date.strftime('%Y-%m-%d')
        
        # 使用回测专用评分器进行批量评分
        scored_stocks = self.score_calculator.calculate_batch_scores(
            stocks=stocks,
            score_date=date_str,
            strategy_name=strategy_name
        )
        
        return scored_stocks
    
    def _calculate_support_level(self, stock: Dict, key_date: datetime.date, method: str) -> float:
        """计算支撑位置
        
        Args:
            stock: 股票信息
            key_date: 关键日期（策略识别出的形态日期，不是选股日期）
            method: 支撑位置计算方法 ('ma20', 'key_close_5', 'key_open', 'key_close')
            
        Returns:
            支撑位置价格
            
        说明：
            key_date是策略识别出的关键日期，例如：
            - W底策略：颈线突破日
            - 趋势共振反转：RSI突破日
            - 趋势加速拐点：放量长阳日
            - 多方炮：第三根K线（确认日）
            - 强势洗盘弱转强：反包阳线日
            - 阻力位突破：阻力位突破日
            
            对于ma20方法：计算20日均线，与关键日无关，只基于历史数据
            对于key_*方法：使用关键日期的价格作为支撑位
        """
        try:
            stock_code = stock['stock_code']
            
            # 标准化方法名称
            method = self._normalize_support_method(method)
            
            # 获取股票数据（DataFrame格式）
            df = self.stock_filtered_cache.get(stock_code)
            if df is None or df.empty:
                logger.warning(f"无法获取股票 {stock_code} 的数据")
                return 0.0
            
            # 确保DataFrame包含必要的列
            required_columns = ['date', 'open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required_columns):
                logger.error(f"数据缺少必要的列: {required_columns}")
                return 0.0
            
            # 确保数据按日期升序排列
            df = df.sort_values('date', ascending=True).reset_index(drop=True)
            
            # 转换key_date为字符串格式（与DataFrame中的date列格式一致）
            key_date_str = key_date.strftime('%Y-%m-%d') if isinstance(key_date, datetime.date) else str(key_date)
            
            # 日期切片：获取到关键日期的所有数据
            # 将date列转换为字符串进行比较
            df['date_str'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            df_to_key_date = df[df['date_str'] <= key_date_str].copy()
            if df_to_key_date.empty:
                logger.warning(f"无法获取股票 {stock_code} 在 {key_date_str} 之前的数据")
                return 0.0
            
            # 验证关键日期是否存在于数据中
            if key_date_str not in df_to_key_date['date_str'].values:
                logger.warning(f"关键日期 {key_date_str} 不在股票 {stock_code} 的数据中")
                return 0.0
            
            # 计算支撑位
            if method == 'ma20':
                # 20日均线支撑位：与关键日无关，只基于历史数据计算
                ma20 = df_to_key_date['close'].rolling(window=20).mean()
                support_level = ma20.iloc[-1]
                logger.debug(f"MA20支撑位: {stock_code} = {support_level}")
            
            elif method == 'key_close_5':
                # 关键日收盘价下5%
                key_close = df_to_key_date['close'].iloc[-1]
                support_level = key_close * 0.95
                logger.debug(f"KEY_CLOSE_5支撑位: {stock_code} {key_date_str} 收盘价={key_close} 支撑位={support_level}")
            
            elif method == 'key_open':
                # 关键日开盘价
                support_level = df_to_key_date['open'].iloc[-1]
                logger.debug(f"KEY_OPEN支撑位: {stock_code} {key_date_str} = {support_level}")
            
            elif method == 'key_close':
                # 关键日收盘价
                support_level = df_to_key_date['close'].iloc[-1]
                logger.debug(f"KEY_CLOSE支撑位: {stock_code} {key_date_str} = {support_level}")
            
            else:
                logger.warning(f"不支持的支撑位计算方法: {method}，使用默认方法 'ma20'")
                ma20 = df_to_key_date['close'].rolling(window=20).mean()
                support_level = ma20.iloc[-1]
            
            return support_level
            
        except Exception as e:
            logger.error(f"计算支撑位失败: {str(e)}")
            return 0.0
    
    def _get_stock_price(self, stock_code: str, date: datetime.date, price_type: str) -> float:
        """获取股票价格
        
        Args:
            stock_code: 股票代码
            date: 日期
            price_type: 价格类型 (open, close, high, low)
            
        Returns:
            价格
        """
        try:
            # 1. 优先从本地数据库获取
            date_str = date.strftime('%Y-%m-%d')
            sql = f"""
                SELECT {price_type} FROM stock_kline 
                WHERE code = ? AND date = ?
            """
            result = self.db_manager.query_one(sql, (stock_code, date_str))
            
            if result and result.get(price_type) is not None:
                return float(result[price_type])
            
            # 2. 备选：从tushare获取
            try:
                import tushare as ts
                
                # 读取Tushare token
                tushare_token = None
                try:
                    import json
                    with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        tushare_token = config.get('token') or config.get('api_key')
                except:
                    pass
                
                if tushare_token:
                    pro = ts.pro_api(tushare_token)
                    df = pro.daily(
                        ts_code=f"{stock_code}.SH" if stock_code.startswith('6') else f"{stock_code}.SZ",
                        start_date=date_str,
                        end_date=date_str
                    )
                    if not df.empty:
                        if price_type == 'open':
                            return float(df.iloc[0]['open'])
                        elif price_type == 'close':
                            return float(df.iloc[0]['close'])
                        elif price_type == 'high':
                            return float(df.iloc[0]['high'])
                        elif price_type == 'low':
                            return float(df.iloc[0]['low'])
            except Exception as e:
                logger.debug(f"Tushare获取价格失败: {str(e)}")
            
            # 3. 备选：使用StockDataFetcher获取实时价格（仅用于当前日期）
            if date == datetime.datetime.now().date():
                price = self.stock_data_fetcher.get_stock_price(stock_code)
                if price:
                    return price
            
            # 4. 备选：从缓存中获取价格（用于回测）
            if stock_code in self.stock_data_cache:
                df = self.stock_data_cache[stock_code]
                date_str = date.strftime('%Y-%m-%d')
                df_date = df[df['date'] == date_str]
                if not df_date.empty:
                    if price_type in df_date.columns:
                        price = df_date.iloc[0][price_type]
                        if price is not None and not pd.isna(price):
                            logger.debug(f"从缓存获取股票 {stock_code} 日期 {date_str} {price_type} 价格: {price}")
                            return float(price)
                else:
                    logger.debug(f"缓存中没有股票 {stock_code} 日期 {date_str} 的数据")
            else:
                logger.debug(f"缓存中没有股票 {stock_code} 的数据")
            
            # 如果所有方法都失败，取前一交易日收盘价
            if stock_code in self.stock_data_cache:
                df = self.stock_data_cache[stock_code]
                # 查找目标日期之前最近的有效收盘价
                df_before = df[df['date'] < date_str].head(1)
                if not df_before.empty and 'close' in df_before.columns:
                    prev_close = df_before.iloc[0]['close']
                    if prev_close is not None and not pd.isna(prev_close):
                        logger.warning(f"股票 {stock_code} 日期 {date_str} 无{price_type}数据，使用前一交易日收盘价: {prev_close}")
                        return float(prev_close)
            
            logger.error(f"无法获取股票 {stock_code} 日期 {date_str} 的任何价格数据")
            return 0.0
            
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 价格失败: {str(e)}")
            return 10.0
    
    def _is_buy_point(self, buy_price: float, support_level: float, config: Dict) -> bool:
        """判断是否为买点
        
        Args:
            buy_price: 买入价格
            support_level: 支撑位置
            config: 回测配置
            
        Returns:
            是否为买点
        """
        if support_level <= 0:
            return True
        
        # 计算买点区间
        lower_percent = config.get('buy_point_lower', -1) / 100
        upper_percent = config.get('buy_point_upper', 3) / 100
        
        lower_bound = support_level * (1 + lower_percent)
        upper_bound = support_level * (1 + upper_percent)
        
        return lower_bound <= buy_price <= upper_bound
    
    def _execute_buy(self, stock_code: str, stock_name: str, selection_date: datetime.date, 
                     buy_date: datetime.date, buy_price: float, buy_amount: float, 
                     quantity: int, support_level: float) -> Dict:
        """执行买入操作
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            selection_date: 选入日期
            buy_date: 买入日期
            buy_price: 买入价格
            buy_amount: 买入金额
            quantity: 买入数量
            support_level: 支撑位置
            
        Returns:
            买入记录
        """
        return {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'selection_date': selection_date,
            'buy_date': buy_date,
            'buy_price': buy_price,
            'buy_amount': buy_amount,
            'quantity': quantity,
            'sell_date': None,
            'sell_price': None,
            'sell_amount': None,
            'sell_type': None,
            'return_rate': None,
            'profit_loss': None,
            'hold_days': None,
            'support_level': support_level
        }
    
    def _process_sell(self, positions: List[Dict], current_date: datetime.date, config: Dict) -> Tuple[List[Dict], List[Dict]]:
        """处理卖出操作
        
        Args:
            positions: 持仓列表
            current_date: 当前日期
            config: 回测配置
            
        Returns:
            (剩余持仓列表, 卖出记录列表)
        """
        remaining_positions = []
        sell_records = []
        
        for position in positions:
            # 计算持有天数（基于交易日）
            buy_date_str = position['buy_date'].strftime('%Y-%m-%d')
            current_date_str = current_date.strftime('%Y-%m-%d')
            trading_days = self._get_trading_dates(buy_date_str, current_date_str)
            # 持有天数 = 交易日数 - 1（不包括买入当天，因为T+1规则）
            # 例如：买入日期2026-01-08，当日卖出日期2026-01-08，trading_days=[2026-01-08]，hold_days=0
            # 这意味着当天买入的股票不能当天卖出
            hold_days = len(trading_days) - 1
            
            # 获取当日开盘价
            open_price = self._get_stock_price(position['stock_code'], current_date, 'open')
            
            # 计算收益率
            return_rate = (open_price - position['buy_price']) / position['buy_price'] * 100
            
            # 检查是否需要卖出
            sell_type = None
            
            # T+1规则：当天买入的股票不能当天卖出（hold_days必须 > 0）
            if hold_days > 0:
                # 1. 止盈检查
                if return_rate >= config.get('take_profit', 15):
                    sell_type = 'take_profit'
                
                # 2. 止损检查
                elif return_rate <= config.get('stop_loss', -5):
                    sell_type = 'stop_loss'
                
                # 3. 持有到期检查
                elif hold_days >= config.get('hold_period', 10):
                    sell_type = 'hold_expired'
            
            if sell_type:
                # 执行卖出
                sell_amount = open_price * position['quantity']
                profit_loss = sell_amount - position['buy_amount']
                
                # 创建卖出记录
                sell_record = {
                    'stock_code': position['stock_code'],
                    'stock_name': position['stock_name'],
                    'selection_date': None,  # 卖出记录无选入日期
                    'buy_date': position['buy_date'],
                    'buy_price': position['buy_price'],
                    'buy_amount': position['buy_amount'],
                    'quantity': position['quantity'],
                    'sell_date': current_date,
                    'sell_price': open_price,
                    'sell_amount': sell_amount,
                    'sell_type': sell_type,
                    'return_rate': return_rate,
                    'profit_loss': profit_loss,
                    'hold_days': hold_days,
                    'support_level': position['support_level']
                }
                
                sell_records.append(sell_record)
            else:
                # 继续持有
                remaining_positions.append(position)
        
        return remaining_positions, sell_records
    
    def _calculate_performance(self, trades: List[Dict], initial_capital: float, 
                              final_capital: float, dates: List[datetime.date], 
                              capital_history: List[float]) -> Dict:
        """计算绩效指标
        
        Args:
            trades: 交易记录
            initial_capital: 初始资金
            final_capital: 最终资金
            dates: 回测日期
            capital_history: 资金历史
            
        Returns:
            绩效指标字典
        """
        # 过滤出已完成的交易（有卖出记录）
        completed_trades = [t for t in trades if t['sell_date'] is not None]
        
        if not completed_trades:
            # 即使没有完成交易，也要计算总收益率
            total_return = ((final_capital / initial_capital) - 1) * 100
            total_return = round(total_return, 2)  # 保留两位小数
            return {
                'total_trades': 0,
                'win_trades': 0,
                'loss_trades': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'total_return': total_return,
                'profit_factor': 0.0,
                'max_return': 0,
                'min_return': 0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # 计算基本指标
        total_trades = len(completed_trades)
        win_trades = sum(1 for t in completed_trades if t['return_rate'] > 0)
        loss_trades = sum(1 for t in completed_trades if t['return_rate'] < 0)
        win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0
        
        returns = [t['return_rate'] for t in completed_trades]
        avg_return = np.mean(returns) if returns else 0
        total_return = ((final_capital / initial_capital) - 1) * 100
        total_return = round(total_return, 2)  # 保留两位小数
        
        # 计算最大和最小单笔收益
        max_return = max(returns) if returns else 0
        min_return = min(returns) if returns else 0
        
        # 计算盈利因子
        winning_returns = [t['return_rate'] for t in completed_trades if t['return_rate'] > 0]
        losing_returns = [abs(t['return_rate']) for t in completed_trades if t['return_rate'] < 0]
        total_win = sum(winning_returns) if winning_returns else 0
        total_loss = sum(losing_returns) if losing_returns else 1
        profit_factor = total_win / total_loss if total_loss > 0 else 0
        
        # 计算最大回撤
        capital_array = np.array(capital_history)
        running_max = np.maximum.accumulate(capital_array)
        drawdown = (capital_array - running_max) / running_max * 100
        max_drawdown = abs(np.min(drawdown))
        
        # 计算夏普比率（假设无风险利率为2%）
        daily_returns = []
        for i in range(1, len(capital_history)):
            daily_return = (capital_history[i] - capital_history[i-1]) / capital_history[i-1] * 100
            daily_returns.append(daily_return)
        volatility = np.std(daily_returns) if daily_returns else 0
        risk_free_rate = 2.0 / 252  # 日无风险利率
        excess_returns = [r - risk_free_rate for r in daily_returns]
        sharpe_ratio = np.mean(excess_returns) / volatility * np.sqrt(252) if volatility > 0 else 0
        
        return {
            'total_trades': total_trades,
            'win_trades': win_trades,
            'loss_trades': loss_trades,
            'win_rate': win_rate,
            'avg_return': avg_return,
            'total_return': total_return,
            'max_return': max_return,
            'min_return': min_return,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio
        }
