"""
VaR计算核心模块 - 历史VaR计算
"""
import numpy as np
import logging
from typing import Optional, Tuple

# 配置日志
logger = logging.getLogger(__name__)


class HistoricalVaRCalculator:
    """历史VaR计算器 - 基于历史分位数计算VaR"""
    
    def __init__(self):
        """初始化历史VaR计算器"""
        logger.info("HistoricalVaRCalculator 初始化完成")
    
    def calculate_var(self, returns: np.ndarray, 
                     confidence: float = 0.99) -> Optional[float]:
        """
        计算历史VaR（简单分位数方法）
        
        参数：
            returns: 收益率序列（负数表示亏损）
            confidence: 置信水平，默认99%
            
        返回：
            VaR值（负数表示亏损），数据不足返回None
        """
        # 数据质量检查
        if returns is None or len(returns) == 0:
            logger.warning("计算VaR失败: 数据为空")
            return None
        
        if len(returns) < 100:
            logger.warning(f"计算VaR失败: 数据点不足（{len(returns)} < 100）")
            return None
        
        # 置信水平检查
        if confidence <= 0 or confidence >= 1:
            logger.error(f"计算VaR失败: 置信水平无效（{confidence}）")
            return None
        
        try:
            # 取左侧尾部（亏损）的百分位数
            alpha = 1 - confidence
            var = np.percentile(returns, alpha * 100)
            
            logger.info(f"计算VaR成功: 置信水平={confidence:.0%}, VaR={var:.4f}")
            return float(var)
            
        except Exception as e:
            logger.error(f"计算VaR失败: {str(e)}")
            return None
    
    def calculate_multi_day_var(self, var_1day: float, days: int) -> Optional[float]:
        """
        使用平方根法则计算多日VaR
        
        参数：
            var_1day: 单日VaR
            days: 天数
            
        返回：
            多日VaR，失败返回None
        """
        # 参数检查
        if var_1day is None:
            logger.warning("计算多日VaR失败: 单日VaR为空")
            return None
        
        if days <= 0:
            logger.error(f"计算多日VaR失败: 天数无效（{days}）")
            return None
        
        try:
            # 平方根法则: VaR_n = VaR_1 * sqrt(n)
            var_nday = var_1day * np.sqrt(days)
            
            logger.info(f"计算多日VaR成功: {days}日VaR={var_nday:.4f}")
            return float(var_nday)
            
        except Exception as e:
            logger.error(f"计算多日VaR失败: {str(e)}")
            return None
    
    def calculate_var_and_es(self, returns: np.ndarray,
                            confidence: float = 0.99) -> Tuple[Optional[float], Optional[float]]:
        """
        计算历史VaR和ES（期望损失）
        
        参数：
            returns: 收益率序列（负数表示亏损）
            confidence: 置信水平，默认99%
            
        返回：
            (VaR, ES) 元组，失败返回 (None, None)
        """
        # 计算VaR
        var = self.calculate_var(returns, confidence)
        
        if var is None:
            return None, None
        
        # 计算ES（期望损失）：超过VaR的平均损失
        try:
            # 找出所有小于VaR的收益率
            tail_losses = returns[returns < var]
            
            if len(tail_losses) == 0:
                logger.warning("计算ES失败: 尾部数据为空")
                return var, None
            
            # ES = 尾部损失的平均值
            es = np.mean(tail_losses)
            
            logger.info(f"计算ES成功: 置信水平={confidence:.0%}, ES={es:.4f}")
            return var, float(es)
            
        except Exception as e:
            logger.error(f"计算ES失败: {str(e)}")
            return var, None
    
    def validate_returns(self, returns: np.ndarray) -> Tuple[bool, str]:
        """
        验证收益率数据质量
        
        参数：
            returns: 收益率序列
            
        返回：
            (是否有效, 错误信息) 元组
        """
        if returns is None:
            return False, "收益率数据为空"
        
        if len(returns) == 0:
            return False, "收益率数据长度为0"
        
        if len(returns) < 100:
            return False, f"收益率数据点不足（{len(returns)} < 100）"
        
        # 检查是否有NaN或Inf
        if np.any(np.isnan(returns)):
            return False, "收益率数据包含NaN"
        
        if np.any(np.isinf(returns)):
            return False, "收益率数据包含Inf"
        
        # 检查收益率范围是否合理（-20% ~ 20%）
        if np.any(returns < -0.2):
            return False, "收益率数据包含异常小值（<-20%）"
        
        if np.any(returns > 0.2):
            return False, "收益率数据包含异常大值（>20%）"
        
        return True, ""
    
    def get_var_statistics(self, returns: np.ndarray) -> dict:
        """
        获取收益率统计信息
        
        参数：
            returns: 收益率序列
            
        返回：
            统计信息字典
        """
        if returns is None or len(returns) == 0:
            return {}
        
        try:
            stats = {
                'count': len(returns),
                'mean': float(np.mean(returns)),
                'std': float(np.std(returns)),
                'min': float(np.min(returns)),
                'max': float(np.max(returns)),
                'median': float(np.median(returns)),
                'percentile_1': float(np.percentile(returns, 1)),
                'percentile_5': float(np.percentile(returns, 5)),
                'percentile_10': float(np.percentile(returns, 10)),
                'percentile_90': float(np.percentile(returns, 90)),
                'percentile_95': float(np.percentile(returns, 95)),
                'percentile_99': float(np.percentile(returns, 99)),
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {str(e)}")
            return {}


# 测试代码
if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 生成测试数据
    np.random.seed(42)
    test_returns = np.random.normal(loc=0.0005, scale=0.02, size=500)
    
    # 创建计算器
    calculator = HistoricalVaRCalculator()
    
    # 验证数据
    is_valid, msg = calculator.validate_returns(test_returns)
    print(f"数据验证: {'通过' if is_valid else '失败'} - {msg}")
    
    # 获取统计信息
    stats = calculator.get_var_statistics(test_returns)
    print(f"\n收益率统计:")
    print(f"  数据点数: {stats['count']}")
    print(f"  均值: {stats['mean']:.4f}")
    print(f"  标准差: {stats['std']:.4f}")
    print(f"  最小值: {stats['min']:.4f}")
    print(f"  最大值: {stats['max']:.4f}")
    print(f"  1%分位数: {stats['percentile_1']:.4f}")
    print(f"  99%分位数: {stats['percentile_99']:.4f}")
    
    # 计算VaR
    var = calculator.calculate_var(test_returns, confidence=0.99)
    print(f"\n99%置信水平下的VaR: {var:.4f} ({var*100:.2f}%)")
    
    # 计算5日VaR
    var_5d = calculator.calculate_multi_day_var(var, 5)
    print(f"5日VaR: {var_5d:.4f} ({var_5d*100:.2f}%)")
    
    # 计算VaR和ES
    var, es = calculator.calculate_var_and_es(test_returns, confidence=0.99)
    print(f"\n99%置信水平:")
    print(f"  VaR: {var:.4f} ({var*100:.2f}%)")
    print(f"  ES: {es:.4f} ({es*100:.2f}%)")