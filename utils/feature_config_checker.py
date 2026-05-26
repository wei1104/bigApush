#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能配置检查器 - 验证功能配置文件是否存在且未过期
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

class FeatureConfigChecker:
    """功能配置检查器"""
    
    def __init__(self, config_manager_path: str = "config/87659999.json"):
        """初始化配置检查器
        
        Args:
            config_manager_path: 配置管理文件路径
        """
        self.config_manager_path = Path(config_manager_path)
        self._crypto_utils = None
        
    def _import_crypto_utils(self):
        """尝试导入加密工具"""
        if self._crypto_utils is None:
            try:
                from utils.crypto_utils import CryptoUtils
                self._crypto_utils = CryptoUtils
            except ImportError:
                self._crypto_utils = None
        return self._crypto_utils
    
    def _decrypt_filename(self, encrypted_filename: str, encryption_key: bytes = None) -> str:
        """解密文件名
        
        Args:
            encrypted_filename: 加密的文件名
            encryption_key: 加密密钥
            
        Returns:
            解密后的文件名（如果解密失败返回原始值）
        """
        if not encrypted_filename:
            return encrypted_filename
            
        crypto_utils = self._import_crypto_utils()
        if crypto_utils and encryption_key:
            try:
                return crypto_utils.decrypt(encrypted_filename, encryption_key)
            except Exception:
                pass
        
        return encrypted_filename
    
    def _find_current_config(self, config_files: List[Dict], today: datetime) -> Tuple[Optional[str], Optional[datetime], int]:
        """查找当前期配置文件
        
        Args:
            config_files: 配置文件列表
            today: 当前日期
            
        Returns:
            (当前配置文件名, 过期日期, 当前索引)
        """
        current_file = None
        current_expire_date = None
        current_index = 0
        
        for i, config_item in enumerate(config_files):
            encrypted_filename = config_item.get('filename', '')
            expire_date_str = config_item.get('expire_date', '')
            
            if not encrypted_filename or not expire_date_str:
                continue
            
            expire_date = datetime.strptime(expire_date_str, '%Y-%m-%d')
            
            # 找到当前期文件（未过期且是最新的）
            if today < expire_date:
                if current_file is None or expire_date < current_expire_date:
                    current_file = encrypted_filename
                    current_expire_date = expire_date
                    current_index = i
        
        return current_file, current_expire_date, current_index
    
    def check_config(self, today: datetime = None) -> Tuple[List[Tuple[str, Optional[datetime]]], Optional[datetime]]:
        """检查功能配置
        
        Args:
            today: 当前日期，默认为当前时间
            
        Returns:
            (有效配置文件列表, 当前配置过期日期)
            有效配置文件列表中每个元素为 (文件名, 过期日期)，下期文件过期日期为None
        """
        if today is None:
            today = datetime.now()
        
        # 检查配置管理文件是否存在
        if not self.config_manager_path.exists():
            logger.warning("功能配置管理文件不存在")
            return [], None
        
        try:
            with open(self.config_manager_path, 'r', encoding='utf-8') as f:
                config_manager = json.load(f)
            
            config_files = config_manager.get('config_files', [])
            early_renewal_days = config_manager.get('early_renewal_days', 5)
            encryption_key = config_manager.get('encryption_key', '')
            
            if not config_files:
                logger.warning("功能配置管理文件中未找到配置文件列表")
                return [], None
            
            # 如果有加密密钥，转换为bytes
            if encryption_key:
                crypto_utils = self._import_crypto_utils()
                if crypto_utils:
                    encryption_key = encryption_key.encode('utf-8')
                else:
                    encryption_key = None
            
            valid_files = []
            
            # 查找当前期配置文件
            encrypted_current_file, current_expire_date, current_index = self._find_current_config(config_files, today)
            
            if not encrypted_current_file:
                logger.warning("未找到有效的功能配置文件")
                return [], None
            
            # 解密当前文件名
            current_file = self._decrypt_filename(encrypted_current_file, encryption_key)
            
            # 检查当前期文件是否存在
            current_path = self.config_manager_path.parent / current_file
            if current_path.exists():
                valid_files.append((current_file, current_expire_date))
            else:
                logger.warning("当前期配置文件不存在")
            
            # 检查是否需要提前启用下期文件
            if current_expire_date:
                renewal_date = current_expire_date - timedelta(days=early_renewal_days)
                if today >= renewal_date and current_index < len(config_files) - 1:
                    next_item = config_files[current_index + 1]
                    encrypted_next_filename = next_item.get('filename', '')
                    if encrypted_next_filename:
                        # 解密下期文件名
                        next_filename = self._decrypt_filename(encrypted_next_filename, encryption_key)
                        
                        next_path = self.config_manager_path.parent / next_filename
                        if next_path.exists():
                            valid_files.append((next_filename, None))
                            logger.info("即将到期，下期配置文件已启用")
            
            # 输出到期提醒
            if current_expire_date:
                days_remaining = (current_expire_date - today).days
                if days_remaining <= early_renewal_days and days_remaining > 0:
                    logger.warning(f"功能配置文件即将到期（剩余{days_remaining}天），建议提前更新")
                elif days_remaining <= 0:
                    logger.warning(f"功能配置文件已过期")
            
            if valid_files:
                logger.info("功能配置文件已加载")
            
            return valid_files, current_expire_date
            
        except Exception as e:
            logger.error(f"检查功能配置失败: {str(e)}")
            return [], None
    
    def get_days_remaining(self, today: datetime = None) -> int:
        """获取当前配置剩余天数
        
        Args:
            today: 当前日期，默认为当前时间
            
        Returns:
            剩余天数，未找到配置返回-1
        """
        if today is None:
            today = datetime.now()
        
        try:
            with open(self.config_manager_path, 'r', encoding='utf-8') as f:
                config_manager = json.load(f)
            
            config_files = config_manager.get('config_files', [])
            encrypted_current_file, current_expire_date, _ = self._find_current_config(config_files, today)
            
            if current_expire_date:
                return (current_expire_date - today).days
            
            return -1
        except Exception as e:
            logger.error(f"获取剩余天数失败: {str(e)}")
            return -1
