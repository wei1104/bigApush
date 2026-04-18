"""
回测API路由 - 提供RESTful接口
"""
from flask import Blueprint, request, jsonify
from trading.backtest_dao import BacktestDAO
from trading.backtest_engine import BacktestEngine
from utils.db_manager import DBManager
from utils.akshare_fetcher import AKShareFetcher
import logging

# 获取日志记录器
logger = logging.getLogger(__name__)

# 创建蓝图
trading_bp = Blueprint('trading', __name__, url_prefix='/api/trading')

# ==================== 回测相关接口 ====================

# 初始化回测相关组件
backtest_dao = BacktestDAO()
from utils.global_db import get_global_db
db_manager = get_global_db()
akshare_fetcher = AKShareFetcher("data")


@trading_bp.route('/backtest/configs', methods=['GET'])
def get_backtest_configs():
    """
    获取回测配置列表接口
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "configs": [
                    {
                        "id": 1,
                        "config_name": "测试配置",
                        "strategy_name": "多方炮策略",
                        "score_threshold": 60,
                        "hold_period": 10,
                        "stop_loss": -5,
                        "take_profit": 15,
                        "initial_capital": 1000000,
                        "buy_amount": 100000,
                        "max_daily_buys": 5,
                        "support_level_method": "ma20",
                        "buy_point_lower": -1,
                        "buy_point_upper": 3,
                        "start_date": "2024-01-01",
                        "end_date": "2024-06-30",
                        "created_at": "2024-01-01 12:00:00"
                    }
                ],
                "total_count": 1
            }
        }
    """
    try:
        # 调用DAO获取所有配置
        configs = backtest_dao.get_all_configs()
        
        return jsonify({
            'success': True,
            'message': '获取回测配置列表成功',
            'data': {
                'configs': configs,
                'total_count': len(configs)
            }
        }), 200
    
    except Exception as e:
        logger.error(f"获取回测配置列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取回测配置列表失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/configs/<int:config_id>', methods=['GET'])
def get_backtest_config(config_id):
    """
    获取单个回测配置详情接口
    
    参数:
        config_id: 配置ID (路径参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "id": 1,
                "config_name": "测试配置",
                "strategy_name": "多方炮策略",
                "score_threshold": 60,
                "hold_period": 10,
                "stop_loss": -5,
                "take_profit": 15,
                "initial_capital": 1000000,
                "buy_amount": 100000,
                "max_daily_buys": 5,
                "support_level_method": "ma20",
                "buy_point_lower": -1,
                "buy_point_upper": 3,
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
                "created_at": "2024-01-01 12:00:00"
            }
        }
    """
    try:
        # 获取回测配置
        config = backtest_dao.get_config(config_id)
        if not config:
            return jsonify({
                'success': False,
                'message': '配置不存在',
                'data': None
            }), 404
        
        return jsonify({
            'success': True,
            'message': '获取回测配置详情成功',
            'data': config
        }), 200
    
    except Exception as e:
        logger.error(f"获取回测配置详情失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取回测配置详情失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/configs', methods=['POST'])
def create_backtest_config():
    """
    创建回测配置接口
    
    请求体:
        {
            "config_name": "测试配置",
            "strategy_name": "多方炮策略",
            "score_threshold": 60,
            "hold_period": 10,
            "stop_loss": -5,
            "take_profit": 15,
            "initial_capital": 1000000,
            "buy_amount": 100000,
            "max_daily_buys": 5,
            "support_level_method": "ma20",
            "buy_point_lower": -1,
            "buy_point_upper": 3,
            "start_date": "2024-01-01",
            "end_date": "2024-06-30"
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "config_id": 1
            }
        }
    """
    try:
        # 获取请求数据
        data = request.get_json() or {}
        
        # 验证必需参数（只验证config_name）
        if 'config_name' not in data or data['config_name'] is None:
            return jsonify({
                'success': False,
                'message': '缺少必需参数: config_name',
                'data': None
            }), 400
        
        # 调用DAO保存配置
        config_id = backtest_dao.save_config(data)
        
        if config_id == 0:
            return jsonify({
                'success': False,
                'message': '创建回测配置失败',
                'data': None
            }), 400
        
        return jsonify({
            'success': True,
            'message': '创建回测配置成功',
            'data': {
                'config_id': config_id
            }
        }), 200
    
    except Exception as e:
        logger.error(f"创建回测配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'创建回测配置失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/configs/<int:config_id>', methods=['PUT'])
def update_backtest_config(config_id):
    """
    更新回测配置接口
    
    参数:
        config_id: 配置ID (路径参数)
    
    请求体:
        {
            "config_name": "测试配置",
            "strategy_name": "多方炮策略",
            "score_threshold": 60,
            "hold_period": 10,
            "stop_loss": -5,
            "take_profit": 15,
            "initial_capital": 1000000,
            "buy_amount": 100000,
            "max_daily_buys": 5,
            "support_level_method": "ma20",
            "buy_point_lower": -1,
            "buy_point_upper": 3,
            "start_date": "2024-01-01",
            "end_date": "2024-06-30"
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "config_id": 1
            }
        }
    """
    try:
        # 获取请求数据
        data = request.get_json() or {}
        
        # 调用DAO更新配置
        success = backtest_dao.update_config(config_id, data)
        
        if not success:
            return jsonify({
                'success': False,
                'message': '更新回测配置失败',
                'data': None
            }), 400
        
        return jsonify({
            'success': True,
            'message': '更新回测配置成功',
            'data': {
                'config_id': config_id
            }
        }), 200
    
    except Exception as e:
        logger.error(f"更新回测配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'更新回测配置失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/configs/<int:config_id>', methods=['DELETE'])
def delete_backtest_config(config_id):
    """
    删除回测配置接口
    
    参数:
        config_id: 配置ID (路径参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "config_id": 1
            }
        }
    """
    try:
        # 调用DAO删除配置
        success = backtest_dao.delete_config(config_id)
        
        if not success:
            return jsonify({
                'success': False,
                'message': '删除回测配置失败',
                'data': None
            }), 400
        
        return jsonify({
            'success': True,
            'message': '删除回测配置成功',
            'data': {
                'config_id': config_id
            }
        }), 200
    
    except Exception as e:
        logger.error(f"删除回测配置失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'删除回测配置失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/run', methods=['POST'])
def run_backtest():
    """
    运行回测接口
    
    请求体:
        {
            "strategy_name": "多方炮策略",
            "support_level_method": "ma20",
            "start_date": "2024-01-01",
            "end_date": "2024-06-30"
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "result_id": 1,
                "total_return": 10.5,
                "win_rate": 65.0,
                "max_drawdown": 8.2,
                "sharpe_ratio": 1.2
            }
        }
    """
    try:
        # 获取请求数据
        data = request.get_json() or {}
        
        # 提取执行条件和回测配置
        strategy_name = data.get('strategy_name', '')
        support_level_method = data.get('support_level_method', 'ma20')
        start_date = data.get('start_date', '')
        end_date = data.get('end_date', '')
        
        # 提取回测配置参数
        score_threshold = data.get('score_threshold', 60)
        max_hold_days = data.get('max_hold_days', 10)
        stop_loss = data.get('stop_loss', -5)
        take_profit = data.get('take_profit', 15)
        initial_capital = data.get('initial_capital', 1000000)
        buy_amount = data.get('buy_amount', 100000)
        max_daily_buys = data.get('max_daily_buys', 5)
        
        # 验证参数
        if not strategy_name or not start_date or not end_date:
            return jsonify({
                'success': False,
                'message': '缺少必要的执行条件（策略名称、开始日期、结束日期）',
                'data': None
            }), 400
        
        # 构建回测配置
        config = {
            'config_name': data.get('config_name', '默认配置'),
            'score_threshold': score_threshold,
            'hold_period': max_hold_days,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'initial_capital': initial_capital,
            'buy_amount': buy_amount,
            'max_daily_buys': max_daily_buys,
            'support_level_method': support_level_method,
            'buy_point_lower': -1,
            'buy_point_upper': 3,
            'start_date': start_date,
            'end_date': end_date
        }
        
        # 使用原有的回测引擎
        logger.info("使用原有回测引擎")
        engine = BacktestEngine()
        
        # 运行回测
        result = engine.run_backtest(strategy_name, config)
        
        # 构建保存到数据库的结果格式
        # 计算final_capital
        final_capital = config.get('initial_capital', 1000000)
        if 'capital_history' in result and result['capital_history']:
            final_capital = result['capital_history'][-1]
        
        save_result = {
            'strategy_name': strategy_name,
            'support_level_method': support_level_method,
            'backtest_name': f"{strategy_name}_{start_date}_{end_date}",
            'start_date': start_date,
            'end_date': end_date,
            'total_trades': result.get('performance', {}).get('total_trades', 0),
            'win_trades': result.get('performance', {}).get('win_trades', 0),
            'loss_trades': result.get('performance', {}).get('loss_trades', 0),
            'win_rate': result.get('performance', {}).get('win_rate', 0),
            'avg_return': result.get('performance', {}).get('avg_return', 0),
            'total_return': result.get('performance', {}).get('total_return', 0),
            'max_return': result.get('performance', {}).get('max_return', 0),
            'min_return': result.get('performance', {}).get('min_return', 0),
            'profit_factor': result.get('performance', {}).get('profit_factor', 0),
            'max_drawdown': result.get('performance', {}).get('max_drawdown', 0),
            'sharpe_ratio': result.get('performance', {}).get('sharpe_ratio', 0),
            'initial_capital': config.get('initial_capital', 1000000),
            'final_capital': final_capital
        }
        
        # 检查是否已存在相同参数的回测结果
        # 检查条件：策略名称、开始日期、结束日期相同
        existing_result = backtest_dao.get_result_by_strategy_and_dates(
            strategy_name, start_date, end_date
        )
        
        if existing_result:
            # 如果存在，则更新该记录而不是创建新记录
            result_id = existing_result['id']
            logger.info(f"发现已存在的回测结果，result_id: {result_id}，准备更新")
            
            # 更新回测结果主记录
            backtest_dao.update_result(result_id, save_result)
            logger.info(f"更新回测结果完成，result_id: {result_id}")
            
            # 清除旧的交易记录和收益曲线数据，避免重复保存
            logger.info(f"清除旧的交易记录和收益曲线数据，result_id: {result_id}")
            backtest_dao.delete_trades(result_id)
            backtest_dao.delete_equity_curve(result_id)
        else:
            # 如果不存在，则创建新记录
            logger.info(f"开始保存回测结果，数据: {save_result}")
            result_id = backtest_dao.save_result(save_result)
            logger.info(f"保存回测结果完成，result_id: {result_id}")
        
        # 保存交易记录
        if 'trades' in result:
            trades = result['trades']
            for trade in trades:
                trade['result_id'] = result_id
                # 确保交易记录包含所有必要字段
                trade.setdefault('stock_code', '')
                trade.setdefault('stock_name', '')
                # selection_date 是必填字段，不能为空，使用 buy_date 作为默认值
                if not trade.get('selection_date'):
                    trade['selection_date'] = trade.get('buy_date', start_date)
                trade.setdefault('buy_date', '')
                trade.setdefault('buy_price', 0)
                trade.setdefault('sell_date', '')
                trade.setdefault('sell_price', 0)
                trade.setdefault('buy_amount', 0)
                trade.setdefault('sell_amount', 0)
                trade.setdefault('profit', trade.get('profit_loss', 0))
                trade.setdefault('profit_rate', trade.get('return_rate', 0))
                trade.setdefault('trade_type', 'normal')
            backtest_dao.save_trades_batch(trades)
        
        # 保存收益曲线数据
        if 'capital_history' in result and 'dates' in result:
            capital_history = result['capital_history']
            dates = result['dates']
            equity_curve = []
            initial_capital = config.get('initial_capital', 1000000)
            
            # capital_history 是数字列表，每个元素是总资产值
            # dates 是对应的日期列表
            # 注意：capital_history[0] 是初始资金，capital_history[1:] 对应 dates 中的日期
            
            # 添加初始数据点（初始日期、初始资金、收益率0）
            if capital_history:
                equity_curve.append({
                    'date': config.get('start_date', ''),
                    'capital': capital_history[0],
                    'return_rate': 0.0
                })
            
            # 添加后续数据点（确保日期和资金对应正确）
            # capital_history[1:] 对应 dates 中的所有日期
            for i, date_value in enumerate(dates):
                try:
                    # capital_history 中的索引是 i+1（因为第一个元素是初始资金）
                    if i + 1 < len(capital_history):
                        capital_value = capital_history[i + 1]
                    else:
                        # 如果索引超出范围，使用最后一个值
                        capital_value = capital_history[-1] if capital_history else 0
                    
                    # 计算收益率：(当日总资产 / 初始资金 - 1) * 100
                    if capital_value > 0 and initial_capital > 0:
                        return_rate = ((capital_value / initial_capital) - 1) * 100
                    else:
                        return_rate = 0.0
                    
                    # 格式化日期
                    if isinstance(date_value, str):
                        date_str = date_value
                    else:
                        date_str = str(date_value)
                    
                    equity_curve.append({
                        'date': date_str,
                        'capital': capital_value,
                        'return_rate': return_rate
                    })
                except Exception as e:
                    logger.warning(f"处理资金历史记录时出错: {str(e)}")
                    continue
            
            logger.info(f"生成收益曲线数据点数: {len(equity_curve)}")
            backtest_dao.save_equity_curve(result_id, equity_curve)
        
        # 获取完整的回测结果（包括equity_curve）
        full_result = backtest_dao.get_result_by_id(result_id)
        trades = backtest_dao.get_trades_by_result(result_id)
        equity_curve_data = backtest_dao.get_equity_curve(result_id)
        
        # 处理结果中的Infinity值
        def handle_infinity(value):
            if isinstance(value, (int, float)):
                if value == float('inf') or value == float('-inf') or value != value:
                    return None
            return value
        
        # 处理结果中的Infinity值
        processed_result = {}
        for key, value in full_result.items():
            processed_result[key] = handle_infinity(value)
        
        # 处理交易记录中的Infinity值
        processed_trades = []
        for trade in trades:
            processed_trade = {}
            for key, value in trade.items():
                processed_trade[key] = handle_infinity(value)
            processed_trades.append(processed_trade)
        
        # 处理收益曲线中的Infinity值
        processed_equity_curve = []
        for item in equity_curve_data:
            processed_item = {}
            for key, value in item.items():
                processed_item[key] = handle_infinity(value)
            processed_equity_curve.append(processed_item)
        
        # 添加交易记录和收益曲线到结果中
        processed_result['trades'] = processed_trades
        processed_result['equity_curve'] = processed_equity_curve
        
        return jsonify({
            'success': True,
            'message': '回测运行成功',
            'data': processed_result
        }), 200
    
    except Exception as e:
        logger.error(f"运行回测失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'运行回测失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/results', methods=['GET'])
def get_backtest_results():
    """
    获取回测结果列表接口
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "results": [
                    {
                        "id": 1,
                        "strategy_name": "多方炮策略",
                        "config_id": 1,
                        "start_date": "2024-01-01",
                        "end_date": "2024-06-30",
                        "initial_capital": 1000000,
                        "final_capital": 1105000,
                        "total_return": 10.5,
                        "win_rate": 65.0,
                        "avg_win": 8.2,
                        "avg_loss": -4.1,
                        "profit_factor": 2.0,
                        "max_drawdown": 8.2,
                        "sharpe_ratio": 1.2,
                        "volatility": 15.0,
                        "sortino_ratio": 1.5,
                        "total_trades": 20,
                        "winning_trades": 13,
                        "losing_trades": 7,
                        "holding_period": 10,
                        "created_at": "2024-01-01 12:00:00"
                    }
                ],
                "total_count": 1
            }
        }
    """
    try:
        # 调用DAO获取所有结果
        results = backtest_dao.get_all_results()
        
        # 处理结果中的Infinity值，将其转换为null
        def handle_infinity(value):
            if isinstance(value, (int, float)):
                if value == float('inf') or value == float('-inf') or value != value:  # 处理Infinity和NaN
                    return None
            return value
        
        # 处理每个结果
        processed_results = []
        for result in results:
            processed_result = {}
            for key, value in result.items():
                processed_result[key] = handle_infinity(value)
            
            # 确保返回的字段名与前端期望的一致
            processed_result['winning_trades'] = processed_result.get('win_trades', 0)
            processed_result['losing_trades'] = processed_result.get('loss_trades', 0)
            processed_result['profit_loss_ratio'] = processed_result.get('profit_factor', 0)
            processed_result['avg_hold_days'] = processed_result.get('hold_period', 0)
            processed_result['volatility'] = processed_result.get('volatility', 0)
            processed_result['sortino_ratio'] = processed_result.get('sortino_ratio', 0)
            
            # 确保初始资金和最终资金不为0
            if processed_result.get('initial_capital', 0) == 0:
                processed_result['initial_capital'] = 1000000
            if processed_result.get('final_capital', 0) == 0:
                # 根据总收益率计算最终资金
                total_return = processed_result.get('total_return', 0)
                initial_capital = processed_result.get('initial_capital', 1000000)
                processed_result['final_capital'] = initial_capital * (1 + total_return / 100)
            
            processed_results.append(processed_result)
        
        return jsonify({
            'success': True,
            'message': '获取回测结果列表成功',
            'data': {
                'results': processed_results,
                'total_count': len(processed_results)
            }
        }), 200
    
    except Exception as e:
        logger.error(f"获取回测结果列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取回测结果列表失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/results/<int:result_id>', methods=['GET'])
def get_backtest_result(result_id):
    """
    获取单个回测结果详情接口
    
    参数:
        result_id: 结果ID (路径参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "id": 1,
                "strategy_name": "多方炮策略",
                "config_id": 1,
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
                "initial_capital": 1000000,
                "final_capital": 1105000,
                "total_return": 10.5,
                "win_rate": 65.0,
                "avg_win": 8.2,
                "avg_loss": -4.1,
                "profit_factor": 2.0,
                "max_drawdown": 8.2,
                "sharpe_ratio": 1.2,
                "volatility": 15.0,
                "sortino_ratio": 1.5,
                "total_trades": 20,
                "winning_trades": 13,
                "losing_trades": 7,
                "holding_period": 10,
                "created_at": "2024-01-01 12:00:00",
                "trades": [...],
                "equity_curve": [...]
            }
        }
    """
    try:
        # 调用DAO获取结果详情
        result = backtest_dao.get_result_by_id(result_id)
        
        if not result:
            return jsonify({
                'success': False,
                'message': '结果不存在',
                'data': None
            }), 404
        
        # 获取交易记录
        trades = backtest_dao.get_trades_by_result(result_id)
        
        # 从数据库获取收益曲线数据
        equity_curve = backtest_dao.get_equity_curve(result_id)
        
        # 转换交易记录的日期格式
        for trade in trades:
            if trade.get('buy_date'):
                trade['buy_date'] = str(trade['buy_date'])
            if trade.get('sell_date'):
                trade['sell_date'] = str(trade['sell_date'])
        
        # 处理结果中的Infinity值，将其转换为null
        def handle_infinity(value):
            if isinstance(value, (int, float)):
                if value == float('inf') or value == float('-inf') or value != value:  # 处理Infinity和NaN
                    return None
            return value
        
        # 处理结果中的Infinity值
        processed_result = {}
        for key, value in result.items():
            processed_result[key] = handle_infinity(value)
        
        # 确保返回的字段名与前端期望的一致
        processed_result['winning_trades'] = processed_result.get('win_trades', 0)
        processed_result['losing_trades'] = processed_result.get('loss_trades', 0)
        processed_result['profit_loss_ratio'] = processed_result.get('profit_factor', 0)
        processed_result['avg_hold_days'] = processed_result.get('hold_period', 0)
        processed_result['volatility'] = processed_result.get('volatility', 0)
        processed_result['sortino_ratio'] = processed_result.get('sortino_ratio', 0)
        
        # 确保初始资金和最终资金不为0
        if processed_result.get('initial_capital', 0) == 0:
            processed_result['initial_capital'] = 1000000
        if processed_result.get('final_capital', 0) == 0:
            # 根据总收益率计算最终资金
            total_return = processed_result.get('total_return', 0)
            initial_capital = processed_result.get('initial_capital', 1000000)
            processed_result['final_capital'] = initial_capital * (1 + total_return / 100)
        
        # 处理交易记录中的Infinity值
        processed_trades = []
        for trade in trades:
            processed_trade = {}
            for key, value in trade.items():
                processed_trade[key] = handle_infinity(value)
            processed_trades.append(processed_trade)
        
        # 处理收益曲线中的Infinity值
        processed_equity_curve = []
        for item in equity_curve:
            processed_item = {}
            for key, value in item.items():
                processed_item[key] = handle_infinity(value)
            processed_equity_curve.append(processed_item)
        
        # 添加交易记录和收益曲线到结果中
        processed_result['trades'] = processed_trades
        processed_result['equity_curve'] = processed_equity_curve
        
        return jsonify({
            'success': True,
            'message': '获取回测结果详情成功',
            'data': processed_result
        }), 200
    
    except Exception as e:
        logger.error(f"获取回测结果详情失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取回测结果详情失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/results/<int:result_id>/trades', methods=['GET'])
def get_backtest_trades(result_id):
    """
    获取回测交易记录接口
    
    参数:
        result_id: 结果ID (路径参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "trades": [
                    {
                        "id": 1,
                        "result_id": 1,
                        "stock_code": "000001",
                        "stock_name": "平安银行",
                        "buy_date": "2024-01-02",
                        "buy_price": 10.0,
                        "sell_date": "2024-01-12",
                        "sell_price": 10.8,
                        "buy_amount": 100000,
                        "sell_amount": 108000,
                        "profit": 8000,
                        "profit_rate": 8.0,
                        "trade_type": "normal"
                    }
                ],
                "total_count": 1
            }
        }
    """
    try:
        # 调用DAO获取交易记录
        trades = backtest_dao.get_trades_by_result_id(result_id)
        
        return jsonify({
            'success': True,
            'message': '获取回测交易记录成功',
            'data': {
                'trades': trades,
                'total_count': len(trades)
            }
        }), 200
    
    except Exception as e:
        logger.error(f"获取回测交易记录失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取回测交易记录失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/backtest/strategies', methods=['GET'])
def get_strategies():
    """
    获取可用策略列表接口
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "strategies": [
                    {
                        "name": "多方炮策略",
                        "display_name": "多方炮策略"
                    }
                ]
            }
        }
    """
    try:
        # 从策略注册表获取策略列表
        from strategy.strategy_registry import get_registry
        registry = get_registry("config/strategy_params.yaml")
        registry.auto_register_from_directory("strategy")
        
        strategies = []
        for strategy_name in registry.list_strategies():
            # 获取策略对象，以便获取其display_name
            strategy = registry.get_strategy(strategy_name)
            # 尝试从metadata中获取display_name，如果没有则使用策略对象的name属性
            display_name = strategy_name
            if strategy:
                if hasattr(strategy, 'metadata') and 'display_name' in strategy.metadata:
                    display_name = strategy.metadata['display_name']
                elif hasattr(strategy, 'name'):
                    display_name = strategy.name
            strategies.append({
                'name': strategy_name,
                'display_name': display_name
            })
        
        return jsonify({
            'success': True,
            'message': '获取策略列表成功',
            'data': {
                'strategies': strategies
            }
        }), 200
    
    except Exception as e:
        logger.error(f"获取策略列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取策略列表失败: {str(e)}',
            'data': None
        }), 500


# ==================== KHunter 狩猎场相关接口 ====================

# 创建 KHunter 蓝图
khunter_bp = Blueprint('khunter', __name__, url_prefix='/api/khunter')

# 初始化 KHunter 相关组件
from trading.khunter_api import KHunterAPI
from trading.khunter_data_processor import KHunterDataProcessor
from trading.khunter_dao import KHunterDAO
from trading.khunter_support_calculator import KHunterSupportCalculator
from trading.khunter_buy_point_judge import KHunterBuyPointJudge
from utils.strategy_config_manager import StrategyConfigManager

# 1. 初始化策略配置管理器
strategy_config_manager = StrategyConfigManager()

# 2. 初始化 KHunter DAO
khunter_dao = KHunterDAO(db_manager)

# 3. 初始化支撑位计算器（传入配置管理器）
khunter_support_calculator = KHunterSupportCalculator(db_manager, strategy_config_manager)

# 4. 初始化买点判断器
khunter_buy_point_judge = KHunterBuyPointJudge(db_manager)

# 5. 初始化数据处理器
khunter_data_processor = KHunterDataProcessor(db_manager, khunter_support_calculator, khunter_buy_point_judge)

# 6. 初始化 API
khunter_api = KHunterAPI(db_manager, khunter_data_processor, khunter_dao)


@khunter_bp.route('/calculate', methods=['POST'])
def khunter_calculate():
    """
    计算狩猎场数据接口
    
    请求体:
        {
            "hunting_date": "2024-04-15",
            "tracking_days": 10
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "hunting_date": "2024-04-15",
                "tracking_days": 10,
                "from_cache": false,
                "total_count": 8,
                "calculation_time": 2.5,
                "results": [...]
            }
        }
    """
    try:
        # 1. 获取请求数据
        data = request.get_json() or {}
        hunting_date = data.get('hunting_date')
        tracking_days = data.get('tracking_days', 10)
        
        # 2. 调用 API 计算
        result = khunter_api.calculate(hunting_date, tracking_days)
        
        # 3. 返回结果
        return jsonify(result), 200 if result.get('success') else 400
    
    except Exception as e:
        logger.error(f"计算狩猎场数据失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'计算失败：{str(e)}',
            'data': None
        }), 500


@khunter_bp.route('/save', methods=['POST'])
def khunter_save():
    """
    保存计算结果接口
    
    请求体:
        {
            "hunting_date": "2024-04-15",
            "tracking_days": 10
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "saved_count": 8,
                "hunting_date": "2024-04-15"
            }
        }
    """
    try:
        # 1. 获取请求数据
        data = request.get_json() or {}
        hunting_date = data.get('hunting_date')
        tracking_days = data.get('tracking_days', 10)
        
        # 2. 调用 API 保存
        result = khunter_api.save(hunting_date, tracking_days)
        
        # 3. 返回结果
        return jsonify(result), 200 if result.get('success') else 400
    
    except Exception as e:
        logger.error(f"保存狩猎场数据失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'保存失败：{str(e)}',
            'data': None
        }), 500


@khunter_bp.route('/query', methods=['GET'])
def khunter_query():
    """
    查询狩猎场数据接口
    
    查询参数:
        hunting_date: 狩猎日期 (必填)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "total_count": 25,
                "results": [...]
            }
        }
    """
    try:
        # 1. 获取查询参数
        hunting_date = request.args.get('hunting_date')
        
        # 2. 调用 API 查询
        result = khunter_api.query(hunting_date)
        
        # 3. 返回结果
        return jsonify(result), 200 if result.get('success') else 400
    
    except Exception as e:
        logger.error(f"查询狩猎场数据失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'查询失败：{str(e)}',
            'data': None
        }), 500


@khunter_bp.route('/check-cache', methods=['GET'])
def khunter_check_cache():
    """
    检查缓存接口
    
    查询参数:
        hunting_date: 狩猎日期 (必填)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "has_cache": true,
                "record_count": 8,
                "hunting_date": "2024-04-15"
            }
        }
    """
    try:
        # 1. 获取查询参数
        hunting_date = request.args.get('hunting_date')
        
        # 2. 调用 API 检查缓存
        result = khunter_api.check_cache(hunting_date)
        
        # 3. 返回结果
        return jsonify(result), 200 if result.get('success') else 400
    
    except Exception as e:
        logger.error(f"检查狩猎场缓存失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'检查失败：{str(e)}',
            'data': None
        }), 500


@khunter_bp.route('/track', methods=['GET'])
def khunter_track():
    """
    狩猎跟踪接口 - 获取指定日期的全部狩猎数据
    
    查询参数:
        hunting_date: 狩猎日期 (必填)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": [
                {
                    "rank_position": 1,
                    "stock_code": "000001",
                    "stock_name": "平安银行",
                    "score": 85.5,
                    "industry": "银行",
                    "sector": "金融",
                    "selection_price": 10.5,
                    "current_price": 10.8,
                    "current_yield": 2.86,
                    "highest_price": 11.2,
                    "highest_yield": 6.67
                }
            ]
        }
    """
    try:
        # 1. 获取查询参数
        hunting_date = request.args.get('hunting_date')
        
        # 2. 调用 API 获取跟踪数据（获取全部数据）
        result = khunter_api.track(hunting_date)
        
        # 3. 返回结果
        return jsonify(result), 200 if result.get('success') else 400
    
    except Exception as e:
        logger.error(f"狩猎跟踪失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'跟踪失败：{str(e)}',
            'data': None
        }), 500
