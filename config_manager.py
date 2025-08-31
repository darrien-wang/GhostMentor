#!/usr/bin/env python3
"""
GhostMentor Configuration Manager
处理配置文件加载、环境变量和用户设置
"""

import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigManager:
    """统一配置管理器"""
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self) -> None:
        """加载配置文件和环境变量"""
        # 默认配置
        self.config = {
            "openai_api_key": None,
            "openai_model": "gpt-4o",
            "window_settings": {
                "width": 600,
                "height": 320,
                "opacity": 200,
                "x": 100,
                "y": 100,
                "move_step": 20
            },
            "audio_settings": {
                "sampling_rate": 16000,
                "chunk_size": 1024,
                "buffer_duration": 5,
                "whisper_model": "base"
            },
            "ui_settings": {
                "font_size": 16,
                "title_font_size": 20,
                "subtitle_font_size": 14,
                "max_visible_lines": 8
            },
            "logging": {
                "level": "INFO",
                "format": "%(asctime)s - %(levelname)s - %(message)s",
                "file_output": False,
                "log_file": "ghostmentor.log"
            }
        }
        
        # 尝试加载配置文件
        try:
            config_path = os.path.join(os.path.dirname(__file__), self.config_file)
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                    self._merge_config(self.config, file_config)
                logger.info(f"Configuration loaded from {config_path}")
            else:
                logger.info(f"Config file {config_path} not found, using defaults")
        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
        
        # 环境变量覆盖
        self._load_env_variables()
        
        # 验证必要配置
        self._validate_config()
    
    def _merge_config(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """递归合并配置"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._merge_config(target[key], value)
            else:
                target[key] = value
    
    def _load_env_variables(self) -> None:
        """从环境变量加载配置"""
        env_mappings = {
            'OPENAI_API_KEY': 'openai_api_key',
            'OPENAI_MODEL': 'openai_model',
            'GHOSTMENTOR_LOG_LEVEL': 'logging.level',
            'GHOSTMENTOR_WINDOW_OPACITY': 'window_settings.opacity'
        }
        
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value:
                self._set_nested_config(config_path, value)
                logger.debug(f"Loaded {config_path} from environment variable {env_var}")
    
    def _set_nested_config(self, path: str, value: Any) -> None:
        """设置嵌套配置值"""
        keys = path.split('.')
        current = self.config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        # 尝试转换类型
        if isinstance(current.get(keys[-1]), int):
            try:
                value = int(value)
            except ValueError:
                pass
        elif isinstance(current.get(keys[-1]), float):
            try:
                value = float(value)
            except ValueError:
                pass
        elif isinstance(current.get(keys[-1]), bool):
            value = value.lower() in ('true', '1', 'yes', 'on')
        
        current[keys[-1]] = value
    
    def _validate_config(self) -> None:
        """验证配置有效性"""
        if not self.config.get('openai_api_key'):
            logger.error("OpenAI API key not found in configuration")
            print("\n❌ Error: OpenAI API key not configured!")
            print("Please set your API key using one of these methods:")
            print("1. Environment variable: set OPENAI_API_KEY=your_api_key_here")
            print("2. Create config.json file with: {\"openai_api_key\": \"your_api_key_here\"}")
            print("3. Copy config.example.json to config.json and edit it")
            raise ValueError("OpenAI API key not configured")
        
        # 验证窗口设置
        window_settings = self.config['window_settings']
        if window_settings['opacity'] < 0 or window_settings['opacity'] > 255:
            logger.warning("Invalid opacity value, using default 200")
            window_settings['opacity'] = 200
        
        # 验证音频设置
        audio_settings = self.config['audio_settings']
        if audio_settings['sampling_rate'] <= 0:
            logger.warning("Invalid sampling rate, using default 16000")
            audio_settings['sampling_rate'] = 16000
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的嵌套键"""
        keys = key.split('.')
        current = self.config
        try:
            for k in keys:
                current = current[k]
            return current
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """设置配置值"""
        self._set_nested_config(key, value)
    
    def save_config(self) -> None:
        """保存配置到文件"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), self.config_file)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            logger.info(f"Configuration saved to {config_path}")
        except Exception as e:
            logger.error(f"Failed to save config file: {e}")
    
    def get_window_settings(self) -> Dict[str, Any]:
        """获取窗口设置"""
        return self.config['window_settings'].copy()
    
    def get_audio_settings(self) -> Dict[str, Any]:
        """获取音频设置"""
        return self.config['audio_settings'].copy()
    
    def get_ui_settings(self) -> Dict[str, Any]:
        """获取UI设置"""
        return self.config['ui_settings'].copy()
    
    def get_logging_settings(self) -> Dict[str, Any]:
        """获取日志设置"""
        return self.config['logging'].copy()

# 全局配置实例
config = ConfigManager()

