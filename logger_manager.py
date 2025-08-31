#!/usr/bin/env python3
"""
GhostMentor Logger Manager
统一的日志管理系统
"""

import logging
import os
import sys
from datetime import datetime
from typing import Optional
from config_manager import config

class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""
    
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色  
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }
    
    def format(self, record):
        # 添加颜色
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        
        # 添加emoji图标
        emoji_map = {
            'DEBUG': '🔧',
            'INFO': '📝', 
            'WARNING': '⚠️',
            'ERROR': '❌',
            'CRITICAL': '💀'
        }
        
        level_name = record.levelname.replace(self.COLORS['RESET'], '').replace('\033[32m', '').replace('\033[33m', '').replace('\033[31m', '').replace('\033[35m', '').replace('\033[36m', '')
        emoji = emoji_map.get(level_name, '📝')
        record.emoji = emoji
        
        return super().format(record)

class LoggerManager:
    """日志管理器"""
    
    def __init__(self):
        self.loggers = {}
        self.setup_logging()
    
    def setup_logging(self):
        """设置日志系统"""
        # 确保控制台支持UTF-8编码
        import io
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            except:
                pass
        
        logging_config = config.get_logging_settings()
        
        # 设置根日志级别
        log_level = getattr(logging, logging_config['level'].upper(), logging.INFO)
        
        # 创建根logger
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        
        # 清除现有handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 控制台处理器，确保UTF-8编码
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        
        # 彩色格式化器
        console_formatter = ColoredFormatter(
            '%(emoji)s %(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # 文件处理器（如果启用）
        if logging_config.get('file_output', False):
            log_file = logging_config.get('log_file', 'ghostmentor.log')
            self.setup_file_logging(root_logger, log_file, log_level)
        
        # 设置第三方库日志级别
        self.setup_third_party_loggers()
    
    def setup_file_logging(self, logger: logging.Logger, log_file: str, level: int):
        """设置文件日志"""
        try:
            # 创建logs目录
            os.makedirs('logs', exist_ok=True)
            log_path = os.path.join('logs', log_file)
            
            # 文件处理器
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setLevel(level)
            
            # 文件格式化器（无颜色）
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            
            logger.info(f"📁 File logging enabled: {log_path}")
        except Exception as e:
            logger.error(f"Failed to setup file logging: {e}")
    
    def setup_third_party_loggers(self):
        """设置第三方库日志级别"""
        # 降低第三方库的日志级别以减少噪音
        third_party_loggers = [
            'pygame',
            'PIL',
            'openai',
            'faster_whisper',
            'pyaudio',
            'keyboard'
        ]
        
        for logger_name in third_party_loggers:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    def get_logger(self, name: str) -> logging.Logger:
        """获取命名logger"""
        if name not in self.loggers:
            self.loggers[name] = logging.getLogger(name)
        return self.loggers[name]
    
    def log_system_info(self):
        """记录系统信息"""
        logger = self.get_logger('system')
        logger.info("🍎 GhostMentor Ultra Stealth Edition")
        logger.info(f"🐍 Python version: {sys.version}")
        logger.info(f"💻 Platform: {sys.platform}")
        logger.info(f"📅 Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 记录配置信息
        window_settings = config.get_window_settings()
        logger.info(f"🪟 Window size: {window_settings['width']}x{window_settings['height']}")
        logger.info(f"🎨 Window opacity: {window_settings['opacity']}/255 ({round(window_settings['opacity']/255*100)}%)")
        
        audio_settings = config.get_audio_settings()
        logger.info(f"🎤 Audio sampling rate: {audio_settings['sampling_rate']} Hz")
        logger.info(f"🧠 Whisper model: {audio_settings['whisper_model']}")

# 全局日志管理器实例
log_manager = LoggerManager()

def get_logger(name: str) -> logging.Logger:
    """便捷函数获取logger"""
    return log_manager.get_logger(name)

