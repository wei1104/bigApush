"""
Web 服务器 - A股量化选股系统前端
"""
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
import json
import sys
import math
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import logging
import os
import traceback
import sqlite3
from json import JSONEncoder

# 自定义JSON编码器，处理numpy类型和NaN值
class NumpyEncoder(JSONEncoder):
    """自定义JSON编码器，处理numpy类型和NaN值"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            # 处理NaN和Inf值，转换为null或0
            if np.isnan(obj):
                return None  # NaN转换为null
            elif np.isinf(obj):
                return None  # Inf转换为null
            else:
                return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        return super().default(obj)
    
    def encode(self, o):
        """重写encode方法，处理Python原生的float NaN和Inf"""
        result = super().encode(o)
        # 替换JSON中的NaN、Infinity和-Infinity为null
        result = result.replace('NaN', 'null')
        result = result.replace('Infinity', 'null')
        result = result.replace('-Infinity', 'null')
        return result


def clean_data_for_json(obj):
    """
    递归清理数据中的NaN和Inf值，确保可以序列化为JSON
    
    参数:
        obj: 任意Python对象（dict, list, float等）
    
    返回:
        清理后的对象，所有NaN/Inf值转换为None
    """
    if isinstance(obj, dict):
        # 递归处理字典
        return {k: clean_data_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        # 递归处理列表
        return [clean_data_for_json(item) for item in obj]
    elif isinstance(obj, float):
        # 处理Python原生float
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, np.floating):
        # 处理numpy float
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.ndarray):
        return clean_data_for_json(obj.tolist())
    elif isinstance(obj, pd.Timestamp):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    else:
        return obj

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.db_manager import DBManager
from strategy.strategy_registry import get_registry
from main import QuantSystem
import threading
from utils.selection_record_manager import SelectionRecordManager
from utils.ranking_manager import RankingManager
from utils.db_initializer import init_databases_if_needed
from utils.stock_filter import StockFilter
from utils.data_collection_service import get_data_collection_service
from utils.kline_initializer import KlineInitializer
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from stock_analyzer import StockAnalyzer

app = Flask(__name__, 
            template_folder='web/templates',
            static_folder='web/static')

# 配置JSON编码器
app.json_encoder = NumpyEncoder

# 初始化SocketIO（配置长连接参数以支持长时间的回测任务）
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    ping_timeout=3600,  # 1小时 ping 超时
    ping_interval=60,   # 60秒 ping 间隔
    max_http_buffer_size=int(1e8)  # 100MB 缓冲区
)

# ==================== 日志配置 ====================
# 使用新的日志配置模块
from utils.log_config import LogConfig, get_logger

# 初始化日志系统
LogConfig.setup_logging(log_dir="logs", log_file="app.log")

# 获取应用日志记录器
logger = get_logger(__name__)
logger.info("=" * 60)
logger.info("Web服务器启动")
logger.info("=" * 60)


# 初始化数据库（确保所有表都已创建）
logger.info("初始化数据库...")
init_databases_if_needed()
logger.info("数据库初始化完成")

# 检查并添加缺失的数据库列
logger.info("检查数据库模式...")
from utils.db_migration_helper import ensure_database_schema
ensure_database_schema()
logger.info("数据库模式检查完成")

# 导入全局数据库管理器
from utils.global_db import get_global_db

# 全局实例
db_manager = get_global_db()
registry = get_registry("config/strategy_params.yaml")
# 注释掉QuantSystem初始化，避免数据库初始化错误
# quant_system = QuantSystem("config/config.yaml")
selection_record_manager = SelectionRecordManager()
ranking_manager = RankingManager()
stock_analyzer = StockAnalyzer()
data_collection_service = get_data_collection_service("data")

# 初始化K线初始化器
from utils.akshare_fetcher import AKShareFetcher
akshare_fetcher = AKShareFetcher("data")
kline_initializer = KlineInitializer(db_manager, akshare_fetcher)

# 初始化参数锁定机制
from strategy.param_lock import get_param_lock
param_lock = get_param_lock("config/strategy_params.yaml")

# 初始化参数追踪机制
from strategy.param_tracker import get_param_tracker
param_tracker = get_param_tracker("config/strategy_params.yaml")

# 加载策略
logger.info("正在加载策略...")
registry.auto_register_from_directory("strategy")
logger.info(f"已加载 {len(registry.strategies)} 个策略")

# 注册trading蓝图
from trading.routes import trading_bp
app.register_blueprint(trading_bp, url_prefix='/api/trading')
logger.info("已注册trading蓝图")

# 注册个股评分API蓝图
from trading.stock_score_api import stock_score_bp
app.register_blueprint(stock_score_bp)
logger.info("已注册个股评分API蓝图")

# 注册KHunter蓝图
from trading.routes import khunter_bp
app.register_blueprint(khunter_bp)
logger.info("已注册KHunter蓝图")

# 全局更新状态
update_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'success': 0,
    'failed': 0,
    'message': '',
    'start_time': None,
    'end_time': None
}


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/stocks')
def get_stocks():
    """获取股票列表 - 从 stock_basic 表获取基础数据"""
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 500))  # 默认每页500只
        
        # 计算分页偏移
        offset = (page - 1) * per_page
        
        # 从 stock_basic 表获取总数
        total_result = db_manager.query('SELECT COUNT(*) as count FROM stock_basic')
        total = total_result[0]['count'] if total_result else 0
        
        # 从 stock_basic 表获取分页数据
        query = '''
            SELECT code, name, industry, area, market, list_date, market_cap
            FROM stock_basic
            ORDER BY code
            LIMIT ? OFFSET ?
        '''
        basic_stocks = db_manager.query(query, (per_page, offset))
        
        stock_list = []
        for stock in basic_stocks:
            # 处理 market_cap 为 None 或 NaN 的情况
            market_cap = stock.get('market_cap', 0)
            if market_cap is None or (isinstance(market_cap, float) and market_cap != market_cap):
                market_cap = 0
            
            # 单位转换：如果市值 > 10000，说明是万元单位，需要转换为亿元
            # 否则已经是亿元单位
            if market_cap > 10000:
                # 万元转亿元：除以 10000
                market_cap = market_cap / 10000
            
            # 从 stock_kline 表获取最新价格和日期
            kline_query = '''
                SELECT close, date FROM stock_kline
                WHERE code = ?
                ORDER BY date DESC
                LIMIT 1
            '''
            kline_result = db_manager.query(kline_query, (stock['code'],))
            
            latest_price = 0
            latest_date = ''
            data_count = 0
            
            if kline_result:
                latest_price = round(kline_result[0]['close'], 2)
                latest_date = kline_result[0]['date']
                
                # 获取该股票的数据条数
                count_query = 'SELECT COUNT(*) as count FROM stock_kline WHERE code = ?'
                count_result = db_manager.query(count_query, (stock['code'],))
                data_count = count_result[0]['count'] if count_result else 0
            
            stock_list.append({
                'code': stock['code'],
                'name': stock['name'],
                'latest_price': latest_price,
                'latest_date': latest_date,
                'market_cap': round(market_cap, 2),  # 总市值，单位：亿
                'data_count': data_count
            })
        
        return jsonify({
            'success': True, 
            'data': stock_list, 
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/dashboard/my-golden-stocks')
def get_my_golden_stocks():
    """获取我的金股 - 最近一个日期的top5股票"""
    try:
        # 获取最近的选股日期
        date_result = db_manager.query("SELECT DISTINCT selection_date FROM stock_selection_record ORDER BY selection_date DESC LIMIT 1")
        if not date_result:
            return jsonify({
                'success': True,
                'date': '',
                'stocks': []
            })
        
        score_date = date_result[0]['selection_date']
        
        # 获取top5股票（按rank_position排序）
        rows = db_manager.query("""
            SELECT stock_code, stock_name, industry, sector, score, rank_position
            FROM stock_selection_record
            WHERE selection_date = ?
            ORDER BY rank_position ASC
            LIMIT 5
        """, (score_date,))
        
        # 转换为字典列表
        items = []
        for row in rows:
            items.append({
                'stock_code': row['stock_code'],
                'stock_name': row['stock_name'],
                'industry': row['industry'] or '-',
                'area': row['sector'] or '-',  # 这里sector对应前端的area
                'total_score': row['score'] or 0
            })
        
        return jsonify({
            'success': True,
            'date': score_date,
            'stocks': items
        })
    except Exception as e:
        logger.error(f"获取我的金股失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/dashboard/hot-industries')
def get_hot_industries():
    """获取最热行业 - top50股票的行业分布"""
    try:
        # 获取最近的选股日期
        date_result = db_manager.query("SELECT DISTINCT selection_date FROM stock_selection_record ORDER BY selection_date DESC LIMIT 1")
        if not date_result:
            return jsonify({
                'success': True,
                'date': '',
                'industries': []
            })
        
        score_date = date_result[0]['selection_date']
        
        # 获取top50股票
        rows = db_manager.query("""
            SELECT industry
            FROM stock_selection_record
            WHERE selection_date = ?
            ORDER BY rank_position ASC
            LIMIT 50
        """, (score_date,))
        
        # 统计行业分布
        industry_count = {}
        for row in rows:
            industry = row['industry'] or '未知'
            if industry in industry_count:
                industry_count[industry] += 1
            else:
                industry_count[industry] = 1
        
        # 转换为列表并排序
        industries = []
        total = len(rows)
        for industry, count in industry_count.items():
            industries.append({
                'industry': industry,
                'count': count,
                'percentage': round(count / total * 100, 2)
            })
        
        # 按股票数量排序
        industries.sort(key=lambda x: x['count'], reverse=True)
        
        return jsonify({
            'success': True,
            'date': score_date,
            'industries': industries
        })
    except Exception as e:
        logger.error(f"获取最热行业失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/dashboard/hot-areas')
def get_hot_areas():
    """获取最热板块 - top50股票的板块分布"""
    try:
        # 获取最近的选股日期
        date_result = db_manager.query("SELECT DISTINCT selection_date FROM stock_selection_record ORDER BY selection_date DESC LIMIT 1")
        if not date_result:
            return jsonify({
                'success': True,
                'date': '',
                'areas': []
            })
        
        score_date = date_result[0]['selection_date']
        
        # 获取top50股票
        rows = db_manager.query("""
            SELECT sector
            FROM stock_selection_record
            WHERE selection_date = ?
            ORDER BY rank_position ASC
            LIMIT 50
        """, (score_date,))
        
        # 统计板块分布
        area_count = {}
        for row in rows:
            area = row['sector'] or '未知'
            if area in area_count:
                area_count[area] += 1
            else:
                area_count[area] = 1
        
        # 转换为列表并排序
        areas = []
        total = len(rows)
        for area, count in area_count.items():
            areas.append({
                'area': area,
                'count': count,
                'percentage': round(count / total * 100, 2)
            })
        
        # 按股票数量排序
        areas.sort(key=lambda x: x['count'], reverse=True)
        
        return jsonify({
            'success': True,
            'date': score_date,
            'areas': areas
        })
    except Exception as e:
        logger.error(f"获取最热板块失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/dashboard/industry-stocks')
def get_industry_stocks():
    """获取指定行业的股票列表 - top50"""
    try:
        # 获取参数
        industry = request.args.get('industry', '')
        limit = int(request.args.get('limit', 50))
        
        if not industry:
            return jsonify({'success': False, 'error': '行业参数不能为空'})
        
        # 获取最近的选股日期
        date_result = db_manager.query("SELECT DISTINCT selection_date FROM stock_selection_record ORDER BY selection_date DESC LIMIT 1")
        if not date_result:
            return jsonify({
                'success': True,
                'stocks': []
            })
        
        score_date = date_result[0]['selection_date']
        
        # 获取指定行业的股票，按评分排序
        rows = db_manager.query("""
            SELECT stock_code, stock_name, industry, sector, score, rank_position, selection_price
            FROM stock_selection_record
            WHERE selection_date = ? AND industry = ?
            ORDER BY score DESC
            LIMIT ?
        """, (score_date, industry, limit))
        
        # 初始化AKShareFetcher获取实时价格
        from utils.akshare_fetcher import AKShareFetcher
        akshare_fetcher = AKShareFetcher()
        
        # 转换为字典列表并计算实时数据
        stocks = []
        for row in rows:
            stock_code = row['stock_code']
            stock_name = row['stock_name']
            industry = row['industry'] or '-'
            sector = row['sector'] or '-'
            score = row['score'] or 0
            rank_position = row['rank_position'] or 0
            selection_price = row['selection_price'] or 0
            
            # 获取实时价格
            current_price = akshare_fetcher.get_stock_price(stock_code)
            
            # 计算当前收益率
            current_yield = 0.0
            if current_price and selection_price:
                current_yield = (current_price - selection_price) / selection_price * 100
            
            # 获取选入后最高价格
            highest_price = ranking_manager._get_highest_price(stock_code, score_date)
            
            # 计算最高收益率
            highest_yield = 0.0
            if highest_price and selection_price:
                highest_yield = (highest_price - selection_price) / selection_price * 100
            
            stocks.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'industry': industry,
                'sector': sector,
                'score': score,
                'rank_position': rank_position,
                'selection_price': selection_price,
                'current_price': current_price or 0,
                'current_yield': round(current_yield, 2) or 0,
                'highest_price': highest_price or 0,
                'highest_yield': round(highest_yield, 2) or 0
            })
        
        return jsonify({
            'success': True,
            'date': score_date,
            'stocks': stocks
        })
    except Exception as e:
        logger.error(f"获取行业股票失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/dashboard/area-stocks')
def get_area_stocks():
    """获取指定板块的股票列表 - top50"""
    try:
        # 获取参数
        area = request.args.get('area', '')
        limit = int(request.args.get('limit', 50))
        
        if not area:
            return jsonify({'success': False, 'error': '板块参数不能为空'})
        
        # 获取最近的选股日期
        date_result = db_manager.query("SELECT DISTINCT selection_date FROM stock_selection_record ORDER BY selection_date DESC LIMIT 1")
        if not date_result:
            return jsonify({
                'success': True,
                'stocks': []
            })
        
        score_date = date_result[0]['selection_date']
        
        # 获取指定板块的股票，按评分排序
        rows = db_manager.query("""
            SELECT stock_code, stock_name, industry, sector, score, rank_position, selection_price
            FROM stock_selection_record
            WHERE selection_date = ? AND sector = ?
            ORDER BY score DESC
            LIMIT ?
        """, (score_date, area, limit))
        
        # 初始化AKShareFetcher获取实时价格
        from utils.akshare_fetcher import AKShareFetcher
        akshare_fetcher = AKShareFetcher()
        
        # 转换为字典列表并计算实时数据
        stocks = []
        for row in rows:
            stock_code = row['stock_code']
            stock_name = row['stock_name']
            industry = row['industry'] or '-'
            sector = row['sector'] or '-'
            score = row['score'] or 0
            rank_position = row['rank_position'] or 0
            selection_price = row['selection_price'] or 0
            
            # 获取实时价格
            current_price = akshare_fetcher.get_stock_price(stock_code)
            
            # 计算当前收益率
            current_yield = 0.0
            if current_price and selection_price:
                current_yield = (current_price - selection_price) / selection_price * 100
            
            # 获取选入后最高价格
            highest_price = ranking_manager._get_highest_price(stock_code, score_date)
            
            # 计算最高收益率
            highest_yield = 0.0
            if highest_price and selection_price:
                highest_yield = (highest_price - selection_price) / selection_price * 100
            
            stocks.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'industry': industry,
                'sector': sector,
                'score': score,
                'rank_position': rank_position,
                'selection_price': selection_price,
                'current_price': current_price or 0,
                'current_yield': round(current_yield, 2) or 0,
                'highest_price': highest_price or 0,
                'highest_yield': round(highest_yield, 2) or 0
            })
        
        return jsonify({
            'success': True,
            'date': score_date,
            'stocks': stocks
        })
    except Exception as e:
        logger.error(f"获取板块股票失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/stock/<code>')
def get_stock_detail(code):
    """获取单只股票详情"""
    try:
        # 从数据库读取股票数据
        df = db_manager.read_stock(code)
        if df.empty:
            return jsonify({'success': False, 'error': '股票不存在'})
        
        # 计算KDJ指标
        from utils.technical import KDJ
        kdj_df = KDJ(df, n=9, m1=3, m2=3)
        
        # 转换为列表格式
        data = []
        for i, (_, row) in enumerate(df.tail(100).iterrows()):  # 返回最近100条
            data.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'open': round(row['open'], 2) if pd.notna(row['open']) else None,
                'high': round(row['high'], 2) if pd.notna(row['high']) else None,
                'low': round(row['low'], 2) if pd.notna(row['low']) else None,
                'close': round(row['close'], 2) if pd.notna(row['close']) else None,
                'volume': int(row['volume']) if pd.notna(row['volume']) else 0,
                'turnover': round(row.get('turnover', 0), 2) if 'turnover' in row and pd.notna(row.get('turnover')) else 0,
                'market_cap': round(row.get('market_cap', 0) / 1e8, 2) if 'market_cap' in row and pd.notna(row.get('market_cap')) else 0,  # 总市值，单位：亿
                'K': round(kdj_df.iloc[i]['K'], 2) if pd.notna(kdj_df.iloc[i]['K']) else None,
                'D': round(kdj_df.iloc[i]['D'], 2) if pd.notna(kdj_df.iloc[i]['D']) else None,
                'J': round(kdj_df.iloc[i]['J'], 2) if pd.notna(kdj_df.iloc[i]['J']) else None
            })
        
        return jsonify({'success': True, 'code': code, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def analyze_intersection(results):
    """
    分析多策略选股结果的交集。构建股票->策略映射，按交集数量分组
    :param results: 策略选股结果字典 {策略名: [信号列表]}
    :return: 交集分析结果
    """
    try:
        # 获取策略的中文名称映射
        import yaml
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        strategies_config = config.get('strategies', {})
        strategy_display_names = {}
        for strategy_name, strategy_config in strategies_config.items():
            strategy_display_names[strategy_name] = strategy_config.get('display_name', strategy_name)
        
        # 构建股票->策略映射
        stock_strategies = {}
        for strategy_name, signals in results.items():
            # 确保 signals 是列表
            if not isinstance(signals, list):
                logger.warning(f"策略 {strategy_name} 的信号不是列表，跳过")
                continue
            
            for signal in signals:
                # 验证信号结构
                if not isinstance(signal, dict) or 'code' not in signal:
                    logger.warning(f"无效的信号结构: {signal}")
                    continue
                
                code = signal['code']
                if code not in stock_strategies:
                    stock_strategies[code] = {
                        'code': code,
                        'name': signal.get('name', '未知'),
                        'strategies': [],
                        'strategy_display_names': [],  # 存储中文名称
                        'count': 0,
                        'signals': signal.get('signals', [])  # 保存信号信息
                    }
                
                stock_strategies[code]['strategies'].append(strategy_name)
                stock_strategies[code]['strategy_display_names'].append(strategy_display_names.get(strategy_name, strategy_name))
                stock_strategies[code]['count'] += 1
        
        # 按交集数量分组
        by_count = {}
        for code, data in stock_strategies.items():
            count = data['count']
            if count not in by_count:
                by_count[count] = []
            by_count[count].append(data)
        
        # 计算统计信息
        total_strategies = len(results)
        stocks_by_strategy = {name: len(signals) if isinstance(signals, list) else 0 for name, signals in results.items()}
        multi_strategy_count = sum(len(stocks) for count, stocks in by_count.items() if count > 1)
        intersection_rate = (multi_strategy_count / len(stock_strategies)) if stock_strategies else 0
        
        return {
            'total': len(stock_strategies),
            'by_count': by_count,
            'intersection_stats': {
                'total_strategies': total_strategies,
                'stocks_by_strategy': stocks_by_strategy,
                'intersection_rate': round(intersection_rate, 2)
            }
        }
    except Exception as e:
        logger.error(f"交集分析失败: {str(e)}")
        logger.error(f"错误堆栈: {traceback.format_exc()}")
        # 返回空的分析结果而不是抛出异常
        return {
            'total': 0,
            'by_count': {},
            'intersection_stats': {
                'total_strategies': 0,
                'stocks_by_strategy': {},
                'intersection_rate': 0
            }
        }


@app.route('/api/select', methods=['GET', 'POST'])
def run_selection():
    """执行选股 - 支持GET（执行所有策略）和POST（执行指定策略）。POST请求支持OR/AND逻辑：OR（并集）任意策略选中即可；AND（交集）所有策略都选中"""
    import traceback
    
    # 获取日志记录器
    func_logger = logging.getLogger(__name__)
    
    try:
        # 记录请求开始和时间
        request_start_time = datetime.now()
        func_logger.info("=" * 60)
        func_logger.info("选股请求开始")
        
        # 检查参数是否被修改，如果被修改则恢复
        is_modified, restored_params = param_lock.check_and_restore()
        if is_modified:
            func_logger.warning("⚠️  检测到参数被修改，已自动恢复")
            func_logger.warning(f"   恢复的参数: {restored_params}")
        
        # 检查参数是否有变化（用于追踪）
        is_changed, changes = param_tracker.check_changes()
        if is_changed:
            func_logger.warning("⚠️  检测到参数变化")
            for strategy_name, param_changes in changes.items():
                for param_name, change in param_changes.items():
                    func_logger.warning(f"   {strategy_name}.{param_name}: {change['old']} -> {change['new']}")
        
        strategies_to_run = None
        logic = 'or'
        end_date = None
        
        # 解析请求参数
        if request.method == 'POST':
            try:
                data = request.json or {}
                strategies_to_run = data.get('strategies')
                logic = data.get('logic', 'or')
                end_date = data.get('end_date')
                b1_match = data.get('b1_match', False)  # 是否启用B1完美图形匹配
                min_similarity = data.get('min_similarity', 60.0)  # 最小相似度阈值
                lookback_days = data.get('lookback_days', 25)  # 回看天数
                func_logger.info(f"请求参数 - 策略: {strategies_to_run}, 逻辑: {logic}, 结束日期: {end_date}, B1匹配: {b1_match}")
            except Exception as e:
                func_logger.error(f"解析请求参数失败: {str(e)}")
                return jsonify({'success': False, 'error': f'请求参数解析失败: {str(e)}'})
            
            # 检查策略列表是否为空
            if strategies_to_run is not None and len(strategies_to_run) == 0:
                func_logger.info("策略列表为空，返回空结果")
                return jsonify({'success': True, 'data': {}, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        
        # 加载股票数据
        try:
            func_logger.info("开始加载股票数据...")
            # 从数据库获取所有股票代码
            stock_codes = db_manager.list_all_stocks()
            func_logger.info(f"加载了 {len(stock_codes)} 只股票代码")
            
            # 从数据库获取所有股票名称（不再使用 stock_names.json）
            stock_names = db_manager.get_all_stock_names()
            func_logger.info(f"加载了 {len(stock_names)} 只股票名称")
        except Exception as e:
            func_logger.error(f"加载股票数据失败: {str(e)}")
            return jsonify({'success': False, 'error': f'加载股票数据失败: {str(e)}'})
        
        # 构建股票数据字典
        try:
            func_logger.info("构建股票数据字典...")
            stock_data = {}
            skip_count = 0
            load_start_time = datetime.now()
            
            # 加载所有股票的完整数据
            for idx, code in enumerate(stock_codes):
                try:
                    # 读取完整数据，如果指定了结束日期，则只读取到该日期的数据
                    full_df = db_manager.read_stock(code, end_date=end_date)
                    if not full_df.empty and len(full_df) >= 20:
                        # 按日期降序排序（最新的在前）
                        full_df = full_df.sort_values('date', ascending=False)
                        # 从 stock_names 字典中获取股票名称
                        stock_name = stock_names.get(code, '未知')
                        stock_data[code] = (stock_name, full_df)
                except Exception as e:
                    # 跳过无法读取的股票
                    skip_count += 1
                    if skip_count <= 5:  # 只记录前5个错误
                        func_logger.debug(f"无法读取股票 {code}: {str(e)}")
                
                # 每加载500只股票输出一次进度
                if (idx + 1) % 500 == 0:
                    elapsed = (datetime.now() - load_start_time).total_seconds()
                    func_logger.info(f"  加载进度: [{idx + 1}/{len(stock_codes)}] 已加载 {len(stock_data)} 只，耗时 {elapsed:.1f}秒")
            
            load_time = (datetime.now() - load_start_time).total_seconds()
            func_logger.info(f"成功加载 {len(stock_data)} 只股票的K线数据，跳过 {skip_count} 只，总耗时 {load_time:.1f}秒")
        except Exception as e:
            func_logger.error(f"构建股票数据字典失败: {str(e)}")
            return jsonify({'success': False, 'error': f'构建股票数据字典失败: {str(e)}'})
        
        # 检查是否有可用的股票数据
        if not stock_data:
            func_logger.warning("没有可用的股票数据")
            return jsonify({'success': True, 'data': {}, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        
        results = {}
        
        # AND逻辑：找出被所有选中策略都选中的股票
        if logic == 'and' and strategies_to_run and len(strategies_to_run) > 1:
            try:
                func_logger.info(f"执行AND逻辑，策略数: {len(strategies_to_run)}")
                func_logger.info(f"选中策略列表: {strategies_to_run}")
                all_signals = {}
                
                strategy_idx = 0
                for strategy_name, strategy in registry.strategies.items():
                    if strategy_name not in strategies_to_run:
                        continue
                    
                    strategy_idx += 1
                    func_logger.info(f"[{strategy_idx}/{len(strategies_to_run)}] 开始执行策略: {strategy_name}")
                    signals = []
                    error_count = 0
                    success_count = 0
                    strategy_start_time = datetime.now()
                    last_progress_time = datetime.now()
                    
                    total_stocks = len(stock_data)
                    for idx, (code, (name, df)) in enumerate(stock_data.items()):
                        try:
                            result = strategy.analyze_stock(code, name, df)
                            if result:
                                success_count += 1
                                # 从 stock_names 字典中获取股票名称
                                fallback_name = stock_names.get(code, '未知')
                                signals.append({
                                    'code': result['code'],
                                    'name': result.get('name', fallback_name),
                                    'signals': result['signals']
                                })
                        except Exception as e:
                            # 跳过分析失败的股票
                            error_count += 1
                            if error_count <= 5:  # 只记录前5个错误
                                func_logger.warning(f"策略 {strategy_name} 分析股票 {code} 失败: {str(e)}")
                        
                        # 每500只股票输出一次进度
                        if (idx + 1) % 500 == 0:
                            elapsed = (datetime.now() - last_progress_time).total_seconds()
                            progress = (idx + 1) / total_stocks * 100
                            func_logger.info(f"  策略 {strategy_name} 进度: [{idx + 1}/{total_stocks}] {progress:.1f}% - 选中 {len(signals)} 只，耗时 {elapsed:.1f}秒")
                            last_progress_time = datetime.now()
                    
                    strategy_time = (datetime.now() - strategy_start_time).total_seconds()
                    func_logger.info(f"策略 {strategy_name} 执行完成: 选中 {len(signals)} 只股票，分析成功 {success_count} 只，失败 {error_count} 只，耗时 {strategy_time:.1f}秒")
                    
                    results[strategy_name] = signals
                    
                    # 计算交集
                    if not all_signals:
                        all_signals = {s['code']: s for s in signals}
                        func_logger.info(f"第一个策略完成，当前交集数量: {len(all_signals)}")
                    else:
                        prev_count = len(all_signals)
                        all_signals = {code: s for code, s in all_signals.items() if any(sig['code'] == code for sig in signals)}
                        func_logger.info(f"交集计算完成: {prev_count} -> {len(all_signals)}")
                
                # 返回交集结果
                intersection_result = list(all_signals.values())
                results = {'_intersection': intersection_result}
                func_logger.info(f"AND逻辑执行完成，最终交集结果: {len(intersection_result)} 只股票")
            except Exception as e:
                func_logger.error(f"AND逻辑执行失败: {str(e)}")
                func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                return jsonify({'success': False, 'error': f'AND逻辑执行失败: {str(e)}'})
        else:
            # OR逻辑（默认）：分别执行每个策略
            try:
                # 加载策略的中文名称映射
                import yaml
                config_file = Path("config/strategy_params.yaml")
                strategy_display_names = {}
                if config_file.exists():
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f) or {}
                    strategies_config = config.get('strategies', {})
                    for strategy_name, strategy_config in strategies_config.items():
                        strategy_display_names[strategy_name] = strategy_config.get('display_name', strategy_name)
                
                func_logger.info(f"执行OR逻辑，策略数: {len(registry.strategies)}")
                func_logger.info(f"指定执行的策略: {strategies_to_run}")
                
                # 优化：直接从strategies_to_run中获取策略，避免逐个跳过
                strategies_to_execute = []
                if strategies_to_run:
                    # 只获取指定的策略
                    for strategy_name in strategies_to_run:
                        if strategy_name in registry.strategies:
                            strategies_to_execute.append((strategy_name, registry.strategies[strategy_name]))
                        else:
                            func_logger.warning(f"指定的策略不存在: {strategy_name}")
                else:
                    # 如果没有指定策略，执行所有策略
                    strategies_to_execute = list(registry.strategies.items())
                
                for strategy_name, strategy in strategies_to_execute:
                    func_logger.info(f"执行策略: {strategy_name}")
                    signals = []
                    error_count = 0
                    strategy_start_time = datetime.now()
                    
                    # 获取该策略的中文名称
                    strategy_display_name = strategy_display_names.get(strategy_name, strategy_name)
                    
                    for idx, (code, (name, df)) in enumerate(stock_data.items()):
                        try:
                            result = strategy.analyze_stock(code, name, df)
                            if result:
                                # 从 stock_names 字典中获取股票名称
                                fallback_name = stock_names.get(code, '未知')
                                signals.append({
                                    'code': result['code'],
                                    'name': result.get('name', fallback_name),
                                    'signals': result['signals'],
                                    'strategy_display_name': strategy_display_name  # 添加中文名称
                                })
                        except Exception as e:
                            # 跳过分析失败的股票
                            error_count += 1
                            if error_count <= 3:  # 只记录前3个错误
                                func_logger.debug(f"策略 {strategy_name} 分析股票 {code} 失败: {str(e)}")
                        
                        # 每处理100只股票输出一次进度
                        if (idx + 1) % 100 == 0:
                            elapsed = (datetime.now() - strategy_start_time).total_seconds()
                            func_logger.info(f"    {strategy_display_name} 进度: [{idx + 1}/{len(stock_data)}] 已选中 {len(signals)} 只，耗时 {elapsed:.1f}秒")
                    
                    strategy_time = (datetime.now() - strategy_start_time).total_seconds()
                    results[strategy_name] = signals
                    func_logger.info(f"策略 {strategy_name} 完成 - 选中 {len(signals)} 只股票，分析失败 {error_count} 只，总耗时 {strategy_time:.1f}秒")
                
                # 计算交集分析（仅当有多个策略且都有结果时）
                if len(results) > 1:
                    # 检查是否有任何策略有结果
                    has_results = any(len(signals) > 0 for signals in results.values())
                    func_logger.info(f"多策略结果 - 总策略数: {len(results)}, 有结果: {has_results}")
                    
                    if has_results:
                        try:
                            func_logger.info("计算交集分析...")
                            intersection_analysis = analyze_intersection(results)
                            results['_intersection_analysis'] = intersection_analysis
                            func_logger.info(f"交集分析完成 - 总股票数: {intersection_analysis.get('total', 0)}")
                        except Exception as e:
                            func_logger.error(f"交集分析计算失败: {str(e)}")
                            func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                            # 不返回错误，继续返回结果
            except Exception as e:
                func_logger.error(f"OR逻辑执行失败: {str(e)}")
                func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                return jsonify({'success': False, 'error': f'OR逻辑执行失败: {str(e)}'})
        
        # 返回结果
        total_time = (datetime.now() - request_start_time).total_seconds()
        func_logger.info(f"选股完成 - 返回结果数: {len(results)}，总耗时 {total_time:.1f}秒")
        func_logger.info("=" * 60)
        
        # 应用过滤条件
        filter_stats = {}
        try:
            func_logger.info("应用过滤条件...")
            # 直接从配置文件读取过滤配置
            import yaml
            with open('config/config.yaml', 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            filter_config = config.get('filters', {})
            stock_filter = StockFilter(filter_config)
            
            # 构建股票数据字典用于过滤
            stock_data_for_filter = {}
            for code in db_manager.list_all_stocks():
                try:
                    # 从数据库读取股票数据，如果指定了结束日期，则只读取到该日期的数据
                    df = db_manager.read_stock(code, end_date=end_date)
                    if not df.empty:
                        name = stock_names.get(code, '未知')
                        stock_data_for_filter[code] = (name, df)
                except:
                    pass
            
            # 应用过滤
            filtered_results, filter_stats = stock_filter.apply_filters(results, stock_data_for_filter)
            
            # 显示过滤统计
            if filter_stats.get('enabled', False):
                func_logger.info(f"过滤统计: 过滤前{filter_stats['total_before']}只 -> 过滤后{filter_stats['total_after']}只 (被过滤{filter_stats['filtered_out']}只)")
                for filter_name, count in filter_stats.get('filters_applied', {}).items():
                    if count > 0:
                        func_logger.info(f"  - {filter_name}: {count}只")
            
            # 使用过滤后的结果
            results = filtered_results
            
            # 重新计算交集分析（基于过滤后的结果）
            if len(results) > 1:
                # 检查是否有任何策略有结果
                has_results = any(len(signals) > 0 for signals in results.values() if isinstance(signals, list))
                func_logger.info(f"多策略结果（过滤后）- 总策略数: {len(results)}, 有结果: {has_results}")
                
                if has_results:
                    try:
                        func_logger.info("重新计算交集分析...")
                        intersection_analysis = analyze_intersection(results)
                        results['_intersection_analysis'] = intersection_analysis
                        func_logger.info(f"交集分析完成（过滤后）- 总股票数: {intersection_analysis.get('total', 0)}")
                    except Exception as e:
                        func_logger.error(f"交集分析计算失败: {str(e)}")
                        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                        # 不返回错误，继续返回结果
            
        except Exception as e:
            func_logger.warning(f"应用过滤条件失败: {str(e)}")
            func_logger.warning(f"错误堆栈: {traceback.format_exc()}")
        
        # 用腾讯财经实时价格替换选股结果中的close字段
        try:
            from utils.akshare_fetcher import AKShareFetcher
            fetcher = AKShareFetcher()
            # 收集所有选中股票的代码
            all_codes = set()
            for key, signals in results.items():
                if isinstance(signals, list):
                    for s in signals:
                        if isinstance(s, dict) and 'code' in s:
                            all_codes.add(s['code'])
            
            if all_codes:
                # 批量获取实时价格
                realtime_prices = fetcher.get_stock_prices_batch(list(all_codes))
                func_logger.info(f"获取实时价格: 请求{len(all_codes)}只, 成功{len(realtime_prices)}只")
                
                # 替换signals中的close字段为实时价格
                for key, signals in results.items():
                    if isinstance(signals, list):
                        for item in signals:
                            if not isinstance(item, dict):
                                continue
                            code = item.get('code', '')
                            price = realtime_prices.get(code)
                            if price is None:
                                continue
                            # 替换嵌套signals列表中的close
                            if 'signals' in item and isinstance(item['signals'], list):
                                for sig in item['signals']:
                                    if isinstance(sig, dict) and 'close' in sig:
                                        sig['close'] = round(price, 2)
        except Exception as e:
            func_logger.warning(f"获取实时价格失败，使用CSV收盘价: {str(e)}")
        
        # 不再自动保存选股结果，由前端手动触发保存
        # 清理数据中的NaN和Inf值
        cleaned_results = clean_data_for_json(results)
        
        # 如果启用了B1完美图形匹配
        if b1_match:
            func_logger.info(f"启用B1完美图形匹配，最小相似度: {min_similarity}，回看天数: {lookback_days}")
            try:
                # 初始化CSV管理器
                from utils.csv_manager import CSVManager
                csv_manager = CSVManager('data')
                
                # 初始化B1完美图形库
                from strategy.pattern_library import B1PatternLibrary
                library = B1PatternLibrary(csv_manager)
                
                # 执行B1完美图形匹配
                matched_results = []
                # 收集所有选中的股票
                all_stocks = []
                for strategy_name, signals in results.items():
                    if isinstance(signals, list):
                        all_stocks.extend(signals)
                
                # 去重
                seen_codes = set()
                unique_stocks = []
                for stock in all_stocks:
                    if stock['code'] not in seen_codes:
                        seen_codes.add(stock['code'])
                        unique_stocks.append(stock)
                
                func_logger.info(f"B1匹配 - 处理 {len(unique_stocks)} 只股票")
                
                for stock in unique_stocks:
                    code = stock['code']
                    name = stock['name']
                    
                    # 读取股票数据
                    df = csv_manager.read_stock(code)
                    if df.empty:
                        continue
                    
                    # 执行匹配
                    match_result = library.find_best_match(code, df, lookback_days=lookback_days)
                    if match_result.get('best_match'):
                        best = match_result['best_match']
                        similarity_score = best.get('similarity_score', 0)
                        
                        if similarity_score >= min_similarity:
                            # 计算基础数据
                            latest_data = df.iloc[0]
                            base_data = {
                                'price': float(latest_data['close']),
                                'change': float(latest_data.get('change', 0)),
                                'volume': float(latest_data['volume'])
                            }
                            
                            matched_results.append({
                                'code': code,
                                'name': name,
                                'similarity_score': similarity_score,
                                'matched_case': best.get('case_name', ''),
                                'matched_date': best.get('case_date', ''),
                                'matched_code': best.get('case_code', ''),
                                'base_data': base_data,
                                'signals': stock.get('signals', {}),
                                'all_matches': best.get('all_matches', [])
                            })
                
                # 按相似度排序
                matched_results.sort(key=lambda x: x['similarity_score'], reverse=True)
                func_logger.info(f"B1完美图形匹配完成 - 匹配结果数: {len(matched_results)}")
                
                # 返回匹配结果
                return jsonify({
                    'success': True,
                    'data': {
                        'matched': matched_results,
                        'count': len(matched_results)
                    },
                    'filter_stats': filter_stats,
                    'b1_match': True,
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception as e:
                func_logger.error(f"执行B1完美图形匹配失败: {str(e)}")
                func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                # 匹配失败时返回原始结果
                pass
        
        return jsonify({
            'success': True,
            'data': cleaned_results,
            'filter_stats': filter_stats,
            'b1_match': False,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    
    except Exception as e:
        # 捕获所有未预期的异常
        func_logger = logging.getLogger(__name__)
        error_msg = str(e)
        func_logger.error("=" * 60)
        func_logger.error(f"选股执行失败（未预期的异常）: {error_msg}")
        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
        func_logger.error("=" * 60)
        
        return jsonify({
            'success': False,
            'error': f'选股执行失败: {error_msg}'
        })


@app.route('/api/save_selection', methods=['POST'])
def save_selection():
    """手动保存选股结果到数据库"""
    func_logger = logging.getLogger(__name__)
    try:
        data = request.json or {}
        # 从前端接收选股结果数据
        results = data.get('results', {})
        selection_time_str = data.get('time', '')
        end_date = data.get('end_date')

        # 解析选股时间
        try:
            selection_time = datetime.strptime(selection_time_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            selection_time = datetime.now()

        # 收集所有选股信号和策略名称
        all_signals = []
        strategy_names = []
        
        # 构建股票代码到策略名称的映射
        stock_strategy_map = {}
        
        for strategy_name, signals in results.items():
            # 跳过特殊字段（如_intersection_analysis）
            if strategy_name.startswith('_'):
                continue
            strategy_names.append(strategy_name)
            
            # 为每只股票添加策略信息
            for signal in signals:
                code = signal.get('code')
                if code:
                    if code not in stock_strategy_map:
                        stock_strategy_map[code] = []
                    stock_strategy_map[code].append(strategy_name)
            
            all_signals.extend(signals)

        # 处理交集中的股票（被多个策略同时选中的股票）
        intersection_analysis = results.get('_intersection_analysis', {})
        if intersection_analysis:
            by_count = intersection_analysis.get('by_count', {})
            
            # 清空all_signals，重新构建
            all_signals = []
            
            # 处理所有股票（包括被1个策略选中的股票）
            for count, stocks in by_count.items():
                for stock in stocks:
                    code = stock.get('code')
                    if code:
                        # 获取该股票命中的策略列表
                        strategies = stock.get('strategies', [])
                        if not strategies:
                            # 如果没有strategies字段，从stock_strategy_map中获取
                            strategies = stock_strategy_map.get(code, [])
                        
                        # 构建信号对象
                        signal = {
                            'code': code,
                            'name': stock.get('name', '未知'),
                            'strategies': strategies,
                            'signals': stock.get('signals', [])
                        }
                        all_signals.append(signal)
                        func_logger.info(f"添加股票: {code} {stock.get('name')} - 策略: {strategies} (被{count}个策略选中)")

        # 为每只股票添加命中的策略列表
        for signal in all_signals:
            code = signal.get('code')
            if code and code in stock_strategy_map:
                signal['strategies'] = stock_strategy_map[code]

        # 检查是否有数据可保存
        if not all_signals or not strategy_names:
            return jsonify({'success': False, 'error': '没有可保存的选股结果'})

        # 调用保存方法
        save_result = selection_record_manager.save_selection_result(
            strategy_names=strategy_names,
            signals=all_signals,
            selection_time=selection_time,
            end_date=end_date
        )
        func_logger.info(f"手动保存选股结果 - {save_result}")
        return jsonify(save_result)

    except Exception as e:
        func_logger.error(f"手动保存选股结果失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>')
def get_strategy_detail(name):
    """获取策略详情 - 包含参数详细信息"""
    try:
        # 从YAML文件直接读取原始参数，而不是转换后的参数
        import yaml
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 获取策略对象
        strategy = registry.get_strategy(name)
        if not strategy:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 从strategies键下获取策略配置
        strategies_config = config.get('strategies', {})
        
        # 尝试从YAML中获取策略配置
        # 首先使用类名作为键查找
        strategy_class_name = type(strategy).__name__
        strategy_config = strategies_config.get(strategy_class_name, {})
        
        # 如果找不到，再使用中文名称作为键查找
        if not strategy_config:
            strategy_config = strategies_config.get(name, {})
        
        if not strategy_config:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 从YAML中获取原始参数值（不经过转换）
        original_params = strategy_config.get('params', {})
        
        # 构建详情数据
        detail = {
            'name': name,
            'display_name': strategy_config.get('display_name', name),
            'description': strategy_config.get('description', ''),
            'icon': strategy_config.get('icon', '📊'),
            'color': strategy_config.get('color', '#2563eb'),
            'param_groups': strategy_config.get('param_groups', []),
            'param_details': strategy_config.get('param_details', {}),
            'current_params': original_params  # 使用原始参数，不是转换后的
        }
        
        return jsonify({'success': True, 'data': detail})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies')
def get_strategies():
    """获取策略列表 - 包含中文名称和元数据，按照strategy_order.yaml中定义的顺序排列"""
    try:
        # 从YAML文件直接读取原始参数，而不是转换后的参数
        import yaml
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 从strategies键下获取策略配置
        strategies_config = config.get('strategies', {})
        
        # 构建策略列表
        strategies = []
        
        # 使用registry中的排序信息（从strategy_order.yaml加载）
        # 按照排序顺序获取策略名称
        sorted_strategy_names = registry.list_strategies()
        
        # 按照排序顺序遍历策略
        for name in sorted_strategy_names:
            if name not in registry.strategies:
                continue
            
            # 获取策略对象用于获取元数据
            strategy = registry.strategies.get(name)
            metadata = getattr(strategy, 'metadata', {}) if strategy else {}
            
            # 尝试从YAML中获取策略配置
            # 首先使用类名作为键查找
            strategy_class_name = type(strategy).__name__
            strategy_config = strategies_config.get(strategy_class_name, {})
            
            # 如果找不到，再使用中文名称作为键查找
            if not strategy_config:
                strategy_config = strategies_config.get(name, {})
            
            # 从YAML中获取原始参数值（不经过转换）
            original_params = strategy_config.get('params', {})
            
            strategies.append({
                'name': name,
                'display_name': strategy_config.get('display_name', name),
                'description': strategy_config.get('description', ''),
                'icon': strategy_config.get('icon', '📊'),
                'color': strategy_config.get('color', '#2563eb'),
                'params': original_params  # 使用原始参数，不是转换后的
            })
        
        return jsonify({'success': True, 'data': strategies})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/validate', methods=['POST'])
def validate_strategy_params(name):
    """验证策略参数 - 检查策略是否存在"""
    try:
        # 检查策略是否存在
        strategy = registry.strategies.get(name)
        
        if not strategy:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 获取待验证的参数
        params = request.get_json() or {}
        
        # 在新架构中，只需检查策略存在即可
        # 参数验证由前端或策略类自身处理
        return jsonify({'success': True, 'message': '参数验证通过'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/params', methods=['POST'])
def save_strategy_params(name):
    """
    保存策略参数 - 更新策略的参数配置并持久化到文件
    只更新前端发送的参数，保留其他参数不变
    :param name: 策略名称
    :return: JSON响应
    """
    global registry
    
    try:
        # 检查策略是否存在
        if name not in registry.strategies:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 获取待保存的参数
        params = request.get_json() or {}
        strategy = registry.strategies[name]
        
        # 将参数保存到配置文件
        import yaml
        config_path = Path("config/strategy_params.yaml")
        
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 确保 strategies 字段存在
        if 'strategies' not in config:
            config['strategies'] = {}
        
        # 确保该策略的配置存在
        if name not in config['strategies']:
            config['strategies'][name] = {}
        
        # 确保 params 字段存在
        if 'params' not in config['strategies'][name]:
            config['strategies'][name]['params'] = {}
        
        # 获取该策略的现有参数
        existing_params = config['strategies'][name]['params']
        
        # 只更新前端发送的参数，保留其他参数
        for param_name, param_value in params.items():
            # 获取原参数的类型进行转换
            if param_name in existing_params:
                param_type = type(existing_params[param_name])
            else:
                # 如果参数不存在，尝试从策略对象获取类型
                if param_name in strategy.params:
                    param_type = type(strategy.params[param_name])
                else:
                    param_type = type(param_value)
            
            try:
                if param_type == int:
                    existing_params[param_name] = int(param_value)
                elif param_type == float:
                    existing_params[param_name] = float(param_value)
                else:
                    existing_params[param_name] = param_value
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': f'参数{param_name}类型转换失败'})
        
        # 写回配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        # 记录参数保存
        func_logger = logging.getLogger(__name__)
        func_logger.info(f"参数已保存: {name}")
        func_logger.info(f"保存的参数: {params}")
        
        # 重新加载策略参数 - 使用global声明确保更新全局registry
        registry = get_registry("config/strategy_params.yaml")
        registry.auto_register_from_directory("strategy")
        
        return jsonify({'success': True, 'message': '参数保存成功'})
    except Exception as e:
        import traceback
        func_logger = logging.getLogger(__name__)
        func_logger.error(f"保存策略参数失败: {str(e)}")
        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/stats')
def get_stats():
    """获取系统统计信息"""
    try:
        # 从数据库获取所有股票代码
        stocks = db_manager.list_all_stocks()
        
        # 获取K线数据的最新日期（表示数据更新到了哪一天）
        # 使用SQL直接查询所有股票的最新日期
        sql = "SELECT MAX(date) as latest_date FROM stock_kline"
        result = db_manager.query_one(sql)
        latest_date = result['latest_date'] if result and result['latest_date'] else '-'
        
        return jsonify({
            'success': True,
            'data': {
                'total_stocks': len(stocks),
                'latest_date': latest_date,
                'strategies': len(registry.strategies)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    try:
        config_file = Path("config/strategy_params.yaml")
        if config_file.exists():
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return jsonify({'success': True, 'data': config})
        return jsonify({'success': False, 'error': '配置文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config', methods=['POST'])
def update_config():
    """
    更新配置 - 只更新指定的参数，保留其他参数
    """
    try:
        import yaml
        from pathlib import Path
        
        # 获取前端发送的配置更新
        update_data = request.json or {}
        
        # 读取现有配置
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 确保 strategies 字段存在
        if 'strategies' not in config:
            config['strategies'] = {}
        
        # 更新指定策略的参数
        # update_data 格式: {strategy_name: {param_name: value, ...}, ...}
        for strategy_name, params_update in update_data.items():
            if strategy_name not in config['strategies']:
                config['strategies'][strategy_name] = {}
            
            # 获取该策略的现有配置
            strategy_config = config['strategies'][strategy_name]
            
            # 确保 params 字段存在
            if 'params' not in strategy_config:
                strategy_config['params'] = {}
            
            # 只更新指定的参数，保留其他参数
            for param_name, param_value in params_update.items():
                strategy_config['params'][param_name] = param_value
        
        # 写回配置文件
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        # 记录配置更新
        func_logger = logging.getLogger(__name__)
        func_logger.info(f"配置已更新")
        func_logger.info(f"更新的数据: {update_data}")
        
        # 重新加载策略
        global registry
        registry = get_registry("config/strategy_params.yaml")
        registry.auto_register_from_directory("strategy")
        
        return jsonify({'success': True, 'message': '配置更新成功'})
    except Exception as e:
        import traceback
        func_logger = logging.getLogger(__name__)
        func_logger.error(f"更新配置失败: {str(e)}")
        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})


def emit_update_progress():
    """通过WebSocket发送更新进度"""
    socketio.emit('update_progress', {
        'running': update_status['running'],
        'progress': update_status['progress'],
        'total': update_status['total'],
        'success': update_status['success'],
        'failed': update_status['failed'],
        'message': update_status['message'],
        'start_time': update_status['start_time'],
        'end_time': update_status['end_time']
    }, namespace='/')


def emit_init_progress():
    """通过WebSocket发送初始化进度
    
    改进点：
    - 添加连接状态检查
    - 添加详细的日志记录
    - 添加异常处理
    """
    try:
        # 检查 socketio 是否可用
        if not socketio:
            logger.warning("socketio 不可用，无法发送初始化进度")
            return
        
        # 获取初始化进度
        progress = data_collection_service.get_init_progress()
        
        # 发送进度到所有连接的客户端
        socketio.emit('init_progress', progress, namespace='/')
        
        # 记录发送成功的日志（仅在进度变化时记录，避免日志过多）
        if progress.get('progress', 0) % 10 == 0 or progress.get('status') in ['completed', 'failed']:
            logger.debug(f"已发送初始化进度: {progress.get('progress', 0)}% - {progress.get('status', 'unknown')}")
    
    except Exception as e:
        logger.error(f"发送初始化进度失败: {str(e)}", exc_info=True)


@app.route('/api/update', methods=['POST'])
def trigger_update():
    """触发数据更新"""
    global update_status
    
    # 检查是否已有更新在运行
    if update_status['running']:
        return jsonify({'success': False, 'error': '已有更新任务在运行中'})
    
    # 获取参数
    max_stocks = request.json.get('max_stocks') if request.json else None
    
    # 在后台线程中执行更新
    def update_thread():
        global update_status
        try:
            update_status['running'] = True
            update_status['start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            update_status['message'] = '正在更新数据...'
            emit_update_progress()
            
            # 执行更新
            quant_system.update_data(max_stocks=max_stocks)
            
            update_status['success'] += 1
            update_status['message'] = '数据更新完成'
            update_status['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            emit_update_progress()
        except Exception as e:
            update_status['failed'] += 1
            update_status['message'] = f'更新失败: {str(e)}'
            update_status['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            emit_update_progress()
        finally:
            update_status['running'] = False
            emit_update_progress()
    
    # 启动后台线程
    thread = threading.Thread(target=update_thread, daemon=True)
    thread.start()
    
    return jsonify({
        'success': True,
        'message': '数据更新已启动',
        'status': update_status
    })


@app.route('/api/update/status', methods=['GET'])
def get_update_status():
    """获取更新状态"""
    return jsonify({
        'success': True,
        'status': update_status
    })


@app.route('/selection-history')
def selection_history_page():
    """
    选股历史查询页面
    """
    return render_template('selection_history.html')


@app.route('/test-select')
def test_select_page():
    """
    下拉框测试页面
    """
    return render_template('test_select.html')


@app.route('/api/selection-history', methods=['GET'])
def get_selection_history():
    """
    查询选股历史
    
    参数：
        strategy_name: 策略名称（可选）
        start_date: 开始日期 YYYY-MM-DD（可选）
        end_date: 结束日期 YYYY-MM-DD（可选）
        stock_code: 股票代码（可选）
        page: 分页页码，默认1
        limit: 每页数量，默认20
    
    返回：
        {
            'success': True,
            'total': 100,
            'page': 1,
            'limit': 20,
            'data': [...]
        }
    """
    try:
        # 获取查询参数
        strategy_name = request.args.get('strategy_name', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        stock_code = request.args.get('stock_code', '')
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        # 构建筛选条件
        filters = {}
        if strategy_name:
            filters['strategy_name'] = strategy_name
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date
        if stock_code:
            filters['stock_code'] = stock_code
        
        # 查询选股历史
        result = selection_record_manager.get_selection_history(
            filters=filters,
            page=page,
            limit=limit
        )
        
        # 转换 numpy 类型为 Python 原生类型
        if result.get('success') and result.get('data'):
            for record in result['data']:
                for key, value in record.items():
                    # 将 numpy 类型转换为 Python 原生类型
                    if hasattr(value, 'item'):
                        record[key] = value.item()
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"查询选股历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


# ==================== 股票分析相关路由 ====================




@app.route('/api/analyze-stock', methods=['POST'])
def analyze_stock():
    """
    分析股票
    
    参数：
        stock_code: 股票代码
        period: 分析周期
    
    返回：
        {
            'success': True,
            'data': 分析结果
        }
    """
    try:
        # 获取请求参数
        data = request.json or {}
        stock_code = data.get('stock_code', '')
        period = data.get('period', '30d')
        
        if not stock_code:
            return jsonify({'success': False, 'message': '股票代码不能为空'})
        
        # 分析股票
        analysis_result = stock_analyzer.analyze(stock_code, period=period)
        
        if not analysis_result:
            return jsonify({'success': False, 'message': '分析失败'})
        
        # 转换numpy类型为Python原生类型，同时清理NaN/Infinity
        def convert_numpy_types(obj):
            """递归转换numpy类型，将NaN/Infinity替换为None"""
            if isinstance(obj, dict):
                return {k: convert_numpy_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy_types(item) for item in obj]
            # 先检查float类型的NaN/Infinity（含numpy.floating）
            elif isinstance(obj, float):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            elif hasattr(obj, 'item'):
                # numpy标量类型，先转为Python原生类型再检查NaN
                val = obj.item()
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    return None
                return val
            elif isinstance(obj, np.ndarray):
                return convert_numpy_types(obj.tolist())
            elif isinstance(obj, pd.Timestamp):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            # 使用hasattr检查其他numpy类型
            elif hasattr(obj, 'dtype'):
                val = obj.item()
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    return None
                return val
            else:
                return obj
        
        # 转换分析结果
        analysis_result = convert_numpy_types(analysis_result)
        
        # 使用json.dumps并指定default参数来处理所有numpy类型
        import json
        def default_handler(obj):
            """处理json.dumps无法序列化的类型"""
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                # 检查NaN/Infinity
                val = float(obj)
                if math.isnan(val) or math.isinf(val):
                    return None
                return val
            elif isinstance(obj, np.ndarray):
                return convert_numpy_types(obj.tolist())
            elif isinstance(obj, pd.Timestamp):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            else:
                return obj
        
        response_data = {
            'success': True,
            'data': analysis_result
        }
        json_str = json.dumps(response_data, default=default_handler)
        return app.response_class(
            response=json_str,
            mimetype='application/json'
        )
        
    except Exception as e:
        logger.error(f"分析股票失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/analysis-history')
def get_analysis_history():
    """
    获取分析历史
    
    返回：
        {
            'success': True,
            'data': 分析历史列表
        }
    """
    try:
        # 这里简化处理，实际应该从数据库获取
        # 暂时返回模拟数据
        history = [
            {
                'id': 1,
                'stock_code': '600519',
                'stock_name': '贵州茅台',
                'analysis_time': '2026-03-23 10:00:00',
                'rating': '买入'
            },
            {
                'id': 2,
                'stock_code': '000858',
                'stock_name': '五粮液',
                'analysis_time': '2026-03-22 15:30:00',
                'rating': '中性'
            }
        ]
        
        return jsonify({
            'success': True,
            'data': history
        })
        
    except Exception as e:
        logger.error(f"获取分析历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/export-report')
def export_report():
    """
    导出分析报告
    
    参数：
        stock_code: 股票代码
    
    返回：
        报告文件
    """
    try:
        stock_code = request.args.get('stock_code', '')
        
        if not stock_code:
            return jsonify({'success': False, 'message': '股票代码不能为空'})
        
        # 生成报告
        report_content, report_path = stock_analyzer.generate_report(stock_code)
        
        # 返回报告文件
        return send_from_directory(
            directory=str(Path(report_path).parent),
            path=Path(report_path).name,
            as_attachment=True
        )
        
    except Exception as e:
        logger.error(f"导出报告失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/report/<int:report_id>')
def get_report(report_id):
    """
    获取分析报告
    
    参数：
        report_id: 报告ID
    
    返回：
        报告内容
    """
    try:
        # 这里简化处理，实际应该根据ID获取报告
        # 暂时返回模拟数据
        return jsonify({
            'success': True,
            'message': '报告获取功能暂未实现'
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


# ==================== K线初始化 API ====================

@app.route('/api/data/kline/init', methods=['POST'])
def init_kline_data():
    """
    手动触发K线数据初始化
    
    请求参数：
        stock_codes: 股票代码列表（可选，不提供则使用全部）
        years: 历史年份数（可选，默认3年）
        batch_size: 每批处理的股票数（可选，默认100）
    
    返回：
        初始化任务信息
    """
    # 获取请求参数
    try:
        data = request.json or {}
        stock_codes = data.get('stock_codes')
        years = data.get('years', 3)
        batch_size = data.get('batch_size', 100)
        
        logger.info(f"开始K线初始化: 股票数={len(stock_codes) if stock_codes else '全部'}, 年份={years}")
        
        # 先检查是否可以初始化（不启动线程）
        result = kline_initializer._check_kline_initialized()
        if result:
            return jsonify({
                'success': False,
                'message': 'K线数据初始化已经完成，无需再次初始化'
            })
        
        # 在后台线程中执行初始化
        def run_init():
            kline_initializer.initialize_kline_data(stock_codes, years, batch_size)
        
        # 启动后台线程
        init_thread = threading.Thread(target=run_init, daemon=True)
        init_thread.start()
        
        # 返回任务信息
        return jsonify({
            'success': True,
            'task_id': kline_initializer.progress['task_id'],
            'message': 'K线初始化已启动',
            'total_stocks': len(stock_codes) if stock_codes else '全部',
            'estimated_time': '30-60分钟'
        })
    
    except Exception as e:
        logger.error(f"启动K线初始化失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/data/kline/init/progress')
def get_kline_init_progress():
    """
    获取K线初始化进度
    
    查询参数：
        task_id: 任务ID（可选）
    
    返回：
        初始化进度信息
    """
    # 获取进度信息
    progress = kline_initializer.get_progress()
    
    return jsonify({
        'success': True,
        'data': progress
    })


# ==================== 数据采集 API ====================

@app.route('/api/data/init/config')
def get_init_config():
    """
    获取数据初始化配置
    
    返回：
        初始化配置信息
    """
    try:
        config = data_collection_service.get_init_config()
        return jsonify({
            'success': True,
            'data': config
        })
    except Exception as e:
        logger.error(f"获取初始化配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/init/start', methods=['POST'])
def start_initialization():
    """
    开始数据初始化
    
    请求体：
        {
            'type': 'full|structure_only|custom',
            'options': {...}
        }
    
    返回：
        初始化任务信息
    """
    try:
        data = request.get_json()
        init_type = data.get('type', 'full')
        options = data.get('options', {})
        
        # 启动初始化任务
        result = data_collection_service.start_initialization(init_type, options)
        
        return jsonify({
            'success': result['success'],
            'message': result['message'],
            'taskId': result.get('taskId')
        })
    except Exception as e:
        logger.error(f"启动初始化失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/init/progress')
def get_init_progress():
    """
    获取数据初始化进度
    
    返回：
        初始化进度信息
    """
    try:
        progress = data_collection_service.get_init_progress()
        # 返回测试期望的格式
        return jsonify({
            'success': True,
            'data': progress
        })
    except Exception as e:
        logger.error(f"获取初始化进度失败: {str(e)}")
        return jsonify({
            'success': False,
            'data': {
                'status': 'failed',
                'message': str(e),
                'logs': []
            }
        })


@app.route('/api/data/init/cancel', methods=['POST'])
def cancel_initialization():
    """
    取消数据初始化
    
    返回：
        取消结果
    """
    try:
        result = data_collection_service.cancel_initialization()
        return jsonify({
            'success': result['success'],
            'message': result['message']
        })
    except Exception as e:
        logger.error(f"取消初始化失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/init/pause', methods=['POST'])
def pause_initialization():
    """
    暂停数据初始化
    
    返回：
        暂停结果
    """
    try:
        result = data_collection_service.pause_initialization()
        return jsonify({
            'success': result['success'],
            'message': result['message']
        })
    except Exception as e:
        logger.error(f"暂停初始化失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/init/resume', methods=['POST'])
def resume_initialization():
    """
    恢复数据初始化
    
    返回：
        恢复结果
    """
    try:
        result = data_collection_service.resume_initialization()
        return jsonify({
            'success': result['success'],
            'message': result['message']
        })
    except Exception as e:
        logger.error(f"恢复初始化失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/config')
def get_update_config():
    """
    获取数据更新配置
    
    返回：
        更新配置信息
    """
    try:
        config = data_collection_service.get_update_config()
        return jsonify({
            'success': True,
            'data': config
        })
    except Exception as e:
        logger.error(f"获取更新配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/start', methods=['POST'])
def start_update():
    """
    开始数据更新
    
    请求体：
        {
            'updateTypes': ['basic_data', 'history_data', ...]
        }
    
    返回：
        更新任务信息
    """
    try:
        data = request.get_json()
        update_types = data.get('updateTypes', None)
        
        # 启动更新任务
        result = data_collection_service.start_update(update_types)
        
        return jsonify({
            'success': result['success'],
            'message': result['message'],
            'taskId': result.get('taskId')
        })
    except Exception as e:
        logger.error(f"启动更新失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/progress')
def get_update_progress():
    """
    获取数据更新进度
    
    返回：
        更新进度信息
    """
    try:
        progress = data_collection_service.get_update_progress()
        return jsonify({
            'success': True,
            'data': progress
        })
    except Exception as e:
        logger.error(f"获取更新进度失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/cancel', methods=['POST'])
def cancel_update():
    """
    取消数据更新
    
    返回：
        取消结果
    """
    try:
        result = data_collection_service.cancel_update()
        return jsonify({
            'success': result['success'],
            'message': result['message']
        })
    except Exception as e:
        logger.error(f"取消更新失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/pause', methods=['POST'])
def pause_update():
    """
    暂停数据更新
    
    返回：
        暂停结果
    """
    try:
        result = data_collection_service.pause_update()
        return jsonify({
            'success': result['success'],
            'message': result['message']
        })
    except Exception as e:
        logger.error(f"暂停更新失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/resume', methods=['POST'])
def resume_update():
    """
    恢复数据更新
    
    返回：
        恢复结果
    """
    try:
        result = data_collection_service.resume_update()
        return jsonify({
            'success': result['success'],
            'message': result['message']
        })
    except Exception as e:
        logger.error(f"恢复更新失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/update/last-update-time')
def get_last_update_time():
    """
    获取上次更新时间
    
    返回：
        {
            'success': bool,
            'data': {
                'lastUpdateTime': '2026-04-02 15:30:00',
                'lastUpdateDate': '2026-04-02'
            }
        }
    """
    try:
        # 获取交易时间验证器
        from utils.trading_time_validator import TradingTimeValidator
        from utils.db_manager import DBManager
        
        # 创建数据库管理器
        from utils.global_db import get_global_db
        db_manager = get_global_db()
        validator = TradingTimeValidator(db_manager)
        
        # 获取上次更新日期
        last_update_date = validator.get_last_update_date()
        
        if not last_update_date:
            # 如果没有更新记录，返回默认值
            return jsonify({
                'success': True,
                'data': {
                    'lastUpdateTime': '未更新',
                    'lastUpdateDate': ''
                }
            })
        
        # 查询该日期的更新时间
        sql = "SELECT update_time FROM update_log WHERE update_date = ?"
        result = db_manager.query_one(sql, (last_update_date,))
        
        if result:
            last_update_time = result['update_time']
        else:
            last_update_time = f"{last_update_date} 00:00:00"
        
        return jsonify({
            'success': True,
            'data': {
                'lastUpdateTime': last_update_time,
                'lastUpdateDate': last_update_date
            }
        })
    
    except Exception as e:
        logger.error(f"获取上次更新时间失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/tables/info')
def get_tables_info():
    """
    获取新增表的信息
    
    返回：
        新增表的信息
    """
    try:
        info = data_collection_service.get_tables_info()
        return jsonify({
            'success': True,
            'data': info
        })
    except Exception as e:
        logger.error(f"获取表信息失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/data/tables/stats')
def get_tables_stats():
    """
    获取表数据统计
    
    返回：
        表数据统计信息
    """
    try:
        stats = data_collection_service.get_tables_stats()
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        logger.error(f"获取表统计失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


# ==================== 排名相关API ====================

@app.route('/api/ranking/dates')
def get_ranking_dates():
    """
    获取可用的选股日期
    
    返回：
        可用选股日期列表
    """
    try:
        dates = ranking_manager.get_available_dates()
        return jsonify({
            'success': True,
            'data': dates
        })
    except Exception as e:
        logger.error(f"获取可用日期失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/ranking/generate', methods=['POST'])
def generate_ranking():
    """
    生成排名
    
    参数：
        selection_date: 选股日期，格式为YYYY-MM-DD
    
    返回：
        排名结果
    """
    try:
        data = request.get_json()
        selection_date = data.get('selection_date')
        
        if not selection_date:
            return jsonify({
                'success': False,
                'message': '缺少选股日期参数'
            })
        
        results = ranking_manager.generate_ranking(selection_date)
        # 清理数据，确保可以正确序列化为JSON
        cleaned_results = clean_data_for_json(results)
        
        return jsonify({
            'success': True,
            'data': cleaned_results
        })
    except Exception as e:
        logger.error(f"生成排名失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/ranking/track', methods=['GET'])
def track_ranking():
    """
    跟踪排名
    
    参数：
        selection_date: 选股日期，格式为YYYY-MM-DD
        top_n: 返回前N条记录，默认5
    
    返回：
        排名跟踪结果
    """
    try:
        selection_date = request.args.get('selection_date')
        top_n = int(request.args.get('top_n', 5))
        
        if not selection_date:
            return jsonify({
                'success': False,
                'message': '缺少选股日期参数'
            })
        
        results = ranking_manager.track_ranking(selection_date, top_n)
        # 清理数据，确保可以正确序列化为JSON
        cleaned_results = clean_data_for_json(results)
        
        return jsonify({
            'success': True,
            'data': cleaned_results
        })
    except Exception as e:
        logger.error(f"跟踪排名失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })




def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """启动Web服务器"""
    # 初始化日志系统
    from utils.log_config import LogConfig
    LogConfig.setup_logging()
    
    # 打印所有注册的路由
    print("\n注册的路由:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule}")
    
    print(f"\n启动Web服务器: http://{host}:{port}")
    # 启动 socketio 服务器
    socketio.run(
        app, 
        host=host, 
        port=port, 
        debug=debug
    )


if __name__ == '__main__':
    run_web_server(debug=False, port=5001)
