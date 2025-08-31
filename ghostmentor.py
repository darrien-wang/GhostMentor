import os
import asyncio
import numpy as np
import cv2
from PIL import Image, ImageGrab
import pygame
import win32gui
import win32con
from threading import Thread
from queue import Queue
import time
import ctypes
import keyboard
from datetime import datetime
import textwrap
import argparse
import re
import tkinter as tk
from tkinter import scrolledtext
import tkinter.font as tkFont

# Import our custom managers
try:
    from config_manager import config
    from logger_manager import get_logger, log_manager
    from api_manager import api_manager
    from audio_manager import initialize_audio_manager, get_audio_manager
except ImportError as e:
    print(f"❌ Error importing modules: {e}")
    print("Make sure all module files are in the same directory as ghostmentor.py")
    exit(1)

# Initialize logger
logger = get_logger(__name__)

# Load configuration settings
window_settings = config.get_window_settings()
audio_settings = config.get_audio_settings()
ui_settings = config.get_ui_settings()

# Command-line arguments
parser = argparse.ArgumentParser(description="GhostMentor - Ultra Stealth AI Assistant")
parser.add_argument('-f', '--full', action='store_true', help="Run in full mode with speech input (default)")
parser.add_argument('-s', '--silent', action='store_true', help="Run in silent mode without speech input (for noisy/outdoor usage)")
parser.add_argument('--config', type=str, help="Path to config file")
args = parser.parse_args()

# Validate arguments
if args.full and args.silent:
    logger.error("Cannot use both -f and -s parameters simultaneously")
    exit(1)

# Determine speech mode
use_speech = not args.silent  # Use speech unless -s is specified

# Log system info
log_manager.log_system_info()
logger.info(f"🎤 Speech mode: {'Enabled' if use_speech else 'Disabled (Silent Mode)'}")

# Global variables - initialized from config
current_transcript = ""
overlay_text = "Ready..."
screen = None
font = None
title_font = None
subtitle_font = None
text_queue = Queue()
last_response_time = time.time()
hwnd = None
loop = None
scroll_offset = 0  # Track scroll position
window_x = window_settings['x']  # Track window X position from config
window_y = window_settings['y']  # Track window Y position from config
move_step = window_settings['move_step']  # Pixels to move per key press from config
show_help_menu = False  # Toggle for help menu display
help_menu_alpha = 0  # Animation alpha for help menu
window_opacity = window_settings['opacity']  # Current window opacity from config
notification_alpha = 0  # Notification animation alpha
notification_text = ""  # Current notification text
notification_timer = 0  # Notification display timer
app_state = "ready"  # App states: ready, processing, listening, error
state_animation = 0  # State indicator animation
running = True  # Main loop control
screenshot_files = []  # Track created screenshot files for cleanup
window_hidden = False  # Track window visibility state
recording_active = False  # Track recording state - starts OFF
has_recent_screenshot = False  # 🆕 Track if there's a recent screenshot for analysis
# 🆕 窗口尺寸管理
normal_window_size = (window_settings['width'], window_settings['height'])
code_window_size = (window_settings['code_mode_width'], window_settings['code_mode_height'])
current_window_mode = "normal"  # "normal" or "code"
# Pygame代码窗口相关变量
code_window_visible = False  # 代码窗口可见性
code_window_screen = None   # Pygame代码窗口surface
code_window_hwnd = None     # 代码窗口句柄
code_scroll_offset = 0      # 代码窗口滚动偏移
code_font = None           # 代码字体
line_number_font = None    # 行号字体
current_highlighted_code = []  # 当前高亮代码数据
current_code = ""  # Current code to display
# 📸 多张截图管理相关变量
screenshot_preview_visible = False  # 截图预览窗口可见性
screenshot_preview_screen = None    # 截图预览窗口surface
screenshot_preview_hwnd = None      # 截图预览窗口句柄
current_screenshot = None          # 当前预览的截图
screenshot_preview_timer = 0       # 预览窗口自动关闭计时器
screenshot_preview_filename = ""   # 当前截图文件名

# 🆕 多张截图管理
screenshot_collection = []          # 存储多张截图的列表 [(Image, filename, timestamp), ...]
current_screenshot_index = 0       # 当前查看的截图索引
max_screenshots = 5               # 最大截图数量

# Monokai主题颜色配置
SYNTAX_COLORS = {
    'keyword': (249, 38, 114),      # 关键字 - 品红  
    'string': (230, 219, 116),      # 字符串 - 黄色
    'comment': (117, 113, 94),      # 注释 - 灰色
    'number': (174, 129, 255),      # 数字 - 紫色
    'function': (166, 226, 46),     # 函数名 - 绿色
    'builtin': (102, 217, 239),     # 内置函数 - 青色
    'operator': (248, 248, 242),    # 操作符
    'background': (25, 30, 36),     # 背景色
    'text': (248, 248, 242),        # 默认文本
    'line_number': (117, 113, 94),  # 行号颜色
}

def show_notification(message, duration=3.0):
    """Show a user-friendly notification with Apple-style animation."""
    global notification_text, notification_alpha, notification_timer
    notification_text = message
    notification_alpha = 0
    notification_timer = time.time() + duration
    logger.info(f"📢 Notification: {message}")

def show_context_status():
    """显示当前上下文状态，帮助用户了解可用的分析内容"""
    global current_transcript, has_recent_screenshot, screenshot_collection
    
    # 分析当前状态
    has_voice = bool(current_transcript.strip())
    has_screen = has_recent_screenshot
    screenshot_count = len(screenshot_collection)
    
    if has_voice and has_screen:
        if screenshot_count > 1:
            status = f"🎤📸 语音+{screenshot_count}张截图 已准备 (按Ctrl+Enter多模态分析)"
        else:
            status = "🎤📸 语音+截图 已准备 (按Ctrl+Enter多模态分析)"
    elif has_voice:
        status = "🎤 语音内容 已准备 (按Ctrl+Enter语音对话)"
    elif has_screen:
        if screenshot_count > 1:
            status = f"📸 {screenshot_count}张截图 已准备 (按Ctrl+Enter屏幕分析)"
        else:
            status = "📸 截图 已准备 (按Ctrl+Enter屏幕分析)"
    else:
        status = "⭕ 暂无内容 (按Ctrl+V录音 或 Ctrl+H截图)"
    
    show_notification(status, 2.5)
    logger.info(f"📊 上下文状态: voice={has_voice}, screen={has_screen}, screenshots={screenshot_count}")

def set_app_state(state):
    """Set application state with visual feedback."""
    global app_state, state_animation
    app_state = state
    state_animation = 0
    
    state_messages = {
        "ready": "🟢 Ready to assist",
        "processing": "🤖 Analyzing...",
        "listening": "🎤 Listening...",
        "error": "❌ Error occurred"
    }
    
    if state in state_messages:
        show_notification(state_messages[state], 2.0)

def wrap_text(text, width, font):
    """Wrap text to fit within the given pixel width with improved spacing."""
    lines = []
    # Use UI settings for text wrapping
    wrap_width = ui_settings.get('text_wrap_width', 65)
    
    for paragraph in text.split('\n'):
        if paragraph.strip():
            wrapped_lines = textwrap.wrap(paragraph, width=wrap_width)
            lines.extend(wrapped_lines)
        else:
            lines.append('')  # Preserve empty lines
    return lines

def capture_screen():
    """Capture the screen and return as a PIL Image."""
    try:
        screenshot = ImageGrab.grab()
        logger.debug("Screen captured successfully")
        return screenshot
    except Exception as e:
        logger.error(f"Screen capture error: {e}")
        return None

def save_screenshot():
    """Save a screenshot to the local directory and add to collection."""
    global screenshot_files, current_screenshot, screenshot_preview_filename, has_recent_screenshot
    global screenshot_collection, current_screenshot_index, max_screenshots
    try:
        screenshot = capture_screen()
        if screenshot:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            screenshot.save(filename)
            screenshot_files.append(filename)  # Track for cleanup
            
            # 🆕 添加到截图集合
            screenshot_data = (screenshot.copy(), filename, timestamp)
            screenshot_collection.append(screenshot_data)
            
            # 如果超过最大数量，删除最旧的截图
            if len(screenshot_collection) > max_screenshots:
                old_data = screenshot_collection.pop(0)
                try:
                    if old_data[1] in screenshot_files:
                        screenshot_files.remove(old_data[1])
                    if os.path.exists(old_data[1]):
                        os.remove(old_data[1])
                        logger.debug(f"🗑️ 删除旧截图: {old_data[1]}")
                except Exception as e:
                    logger.warning(f"删除旧截图失败: {e}")
            
            # 设置当前截图为最新的
            current_screenshot_index = len(screenshot_collection) - 1
            current_screenshot = screenshot.copy()
            screenshot_preview_filename = filename
            has_recent_screenshot = True  # 🆕 标记有最新截图可用
            
            # 🔧 不再清空语音转录，保持上下文连续性
            logger.info(f"📸 截图已保存: {filename} (第{len(screenshot_collection)}/{max_screenshots}张)")
            
            # 显示截图预览窗口
            show_screenshot_preview()
            
            # 🆕 显示智能状态提示（包含多张截图信息）
            show_context_status()
            
            return filename
        else:
            logger.warning("Failed to capture screenshot")
            return None
    except Exception as e:
        logger.error(f"Error saving screenshot: {e}")
        return None

def cleanup_screenshots():
    """清理所有创建的截图文件"""
    global screenshot_files, screenshot_collection, current_screenshot, has_recent_screenshot
    try:
        deleted_count = 0
        for filename in screenshot_files:
            try:
                if os.path.exists(filename):
                    os.remove(filename)
                    deleted_count += 1
                    logger.debug(f"🗑️ 已删除截图: {filename}")
            except Exception as e:
                logger.warning(f"无法删除截图文件 {filename}: {e}")
        
        if deleted_count > 0:
            logger.info(f"🧹 已清理 {deleted_count} 个截图文件")
        screenshot_files.clear()
        # 🆕 清理截图集合
        screenshot_collection.clear()
        current_screenshot = None
        has_recent_screenshot = False
    except Exception as e:
        logger.error(f"清理截图文件时出错: {e}")

def clear_all_screenshots():
    """清除所有截图（用户手动操作）"""
    global screenshot_collection, current_screenshot, has_recent_screenshot, current_screenshot_index
    try:
        screenshot_count = len(screenshot_collection)
        if screenshot_count == 0:
            show_notification("📸 暂无截图可清除", 2.0)
            return
        
        # 删除文件
        for screenshot_data in screenshot_collection:
            try:
                filename = screenshot_data[1]
                if os.path.exists(filename):
                    os.remove(filename)
                    logger.debug(f"🗑️ 删除截图文件: {filename}")
            except Exception as e:
                logger.warning(f"删除截图文件失败: {e}")
        
        # 清理内存
        screenshot_collection.clear()
        current_screenshot = None
        has_recent_screenshot = False
        current_screenshot_index = 0
        
        logger.info(f"🧹 已手动清除 {screenshot_count} 张截图")
        show_notification(f"🧹 已清除 {screenshot_count} 张截图", 2.0)
        show_context_status()
        
    except Exception as e:
        logger.error(f"清除截图失败: {e}")
        show_notification("❌ 清除截图失败", 2.0)

def next_screenshot():
    """切换到下一张截图预览"""
    global current_screenshot_index, screenshot_collection, current_screenshot, screenshot_preview_filename
    try:
        if not screenshot_collection:
            show_notification("📸 暂无截图可浏览", 2.0)
            return
        
        current_screenshot_index = (current_screenshot_index + 1) % len(screenshot_collection)
        screenshot_data = screenshot_collection[current_screenshot_index]
        current_screenshot = screenshot_data[0].copy()
        screenshot_preview_filename = screenshot_data[1]
        
        show_notification(f"📸 切换到第 {current_screenshot_index + 1}/{len(screenshot_collection)} 张截图", 2.0)
        logger.info(f"📸 切换到截图 {current_screenshot_index + 1}/{len(screenshot_collection)}: {screenshot_preview_filename}")
        
        # 如果预览窗口开着，刷新显示
        if screenshot_preview_visible:
            show_screenshot_preview()
            
    except Exception as e:
        logger.error(f"切换截图失败: {e}")
        show_notification("❌ 切换截图失败", 2.0)

def prev_screenshot():
    """切换到上一张截图预览"""
    global current_screenshot_index, screenshot_collection, current_screenshot, screenshot_preview_filename
    try:
        if not screenshot_collection:
            show_notification("📸 暂无截图可浏览", 2.0)
            return
        
        current_screenshot_index = (current_screenshot_index - 1) % len(screenshot_collection)
        screenshot_data = screenshot_collection[current_screenshot_index]
        current_screenshot = screenshot_data[0].copy()
        screenshot_preview_filename = screenshot_data[1]
        
        show_notification(f"📸 切换到第 {current_screenshot_index + 1}/{len(screenshot_collection)} 张截图", 2.0)
        logger.info(f"📸 切换到截图 {current_screenshot_index + 1}/{len(screenshot_collection)}: {screenshot_preview_filename}")
        
        # 如果预览窗口开着，刷新显示
        if screenshot_preview_visible:
            show_screenshot_preview()
            
    except Exception as e:
        logger.error(f"切换截图失败: {e}")
        show_notification("❌ 切换截图失败", 2.0)

def toggle_window_visibility():
    """切换窗口显示/隐藏状态"""
    global window_hidden, hwnd
    try:
        if hwnd:
            if window_hidden:
                # 显示窗口
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 
                                    window_x, window_y, 0, 0, 
                                    win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
                set_window_opacity(window_opacity)
                window_hidden = False
                logger.info("👁️ 窗口已显示")
                show_notification("👁️ 窗口已显示", 1.5)
            else:
                # 隐藏窗口
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                window_hidden = True
                logger.info("🙈 窗口已隐藏")
                # 注意：隐藏时无法显示通知，因为窗口不可见
    except Exception as e:
        logger.error(f"切换窗口可见性时出错: {e}")

def extract_code_from_response(response_text):
    """从AI响应中提取代码块"""
    try:
        # 简单匹配 ``` 代码块，不管什么语言
        code_pattern = r'```.*?\n(.*?)\n```'
        matches = re.findall(code_pattern, response_text, re.DOTALL)
        
        if matches:
            # 合并所有代码块
            all_code = '\n\n# ========== 下一个代码块 ==========\n\n'.join(matches)
            return all_code.strip()
        return ""
    except Exception as e:
        logger.error(f"提取代码时出错: {e}")
        return ""

def parse_code_syntax_pygame(code_text):
    """Pygame版本的语法解析"""
    if not code_text.strip():
        return []
    
    lines = code_text.split('\n')
    highlighted_lines = []
    
    # Python关键字和内置函数
    keywords = {
        'def', 'class', 'if', 'else', 'elif', 'while', 'for', 'in', 'return',
        'import', 'from', 'as', 'try', 'except', 'finally', 'with', 'pass',
        'break', 'continue', 'and', 'or', 'not', 'is', 'lambda', 'yield',
        'global', 'nonlocal', 'assert', 'del', 'raise', 'async', 'await'
    }
    
    constants = {'None', 'True', 'False'}
    builtins = {
        'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set',
        'tuple', 'bool', 'enumerate', 'zip', 'map', 'filter', 'sum', 'max', 'min'
    }
    
    for line_num, line in enumerate(lines, 1):
        tokens = []
        
        # 处理注释
        comment_match = re.search(r'#.*$', line)
        if comment_match:
            pre_comment = line[:comment_match.start()]
            comment_text = line[comment_match.start():]
            
            # 处理注释前的内容
            if pre_comment.strip():
                tokens.extend(parse_line_tokens_pygame(pre_comment, keywords, constants, builtins))
            
            # 添加注释
            tokens.append(('comment', comment_text))
        else:
            tokens.extend(parse_line_tokens_pygame(line, keywords, constants, builtins))
        
        highlighted_lines.append({
            'line_number': line_num,
            'tokens': tokens
        })
    
    return highlighted_lines

def parse_line_tokens_pygame(line, keywords, constants, builtins):
    """解析单行的tokens"""
    tokens = []
    
    # 简化版token解析
    i = 0
    while i < len(line):
        char = line[i]
        
        if char.isspace():
            # 空白字符
            tokens.append(('text', char))
            i += 1
        elif char in '"\'':
            # 字符串处理
            quote = char
            string_start = i
            i += 1
            while i < len(line) and line[i] != quote:
                if line[i] == '\\' and i + 1 < len(line):
                    i += 2  # 跳过转义字符
                else:
                    i += 1
            if i < len(line):
                i += 1  # 包含结束引号
            tokens.append(('string', line[string_start:i]))
        elif char.isdigit():
            # 数字处理
            num_start = i
            while i < len(line) and (line[i].isdigit() or line[i] == '.'):
                i += 1
            tokens.append(('number', line[num_start:i]))
        elif char.isalpha() or char == '_':
            # 标识符处理
            word_start = i
            while i < len(line) and (line[i].isalnum() or line[i] == '_'):
                i += 1
            word = line[word_start:i]
            
            if word in keywords:
                tokens.append(('keyword', word))
            elif word in constants:
                tokens.append(('keyword', word))  # 常量用关键字颜色
            elif word in builtins:
                tokens.append(('builtin', word))
            else:
                tokens.append(('text', word))
        else:
            # 操作符和其他字符
            tokens.append(('operator', char))
            i += 1
    
    return tokens

def calculate_adaptive_code_display():
    """🆕 计算自适应代码显示参数"""
    global screen, current_highlighted_code
    
    if not screen or not current_highlighted_code:
        # 默认参数
        return {
            'line_height': 16,
            'font_size': 14,
            'line_number_font_size': 12,
            'line_number_width': 40,
            'margin_top': 10,
            'visible_lines': 20
        }
    
    try:
        window_width = screen.get_width()
        window_height = screen.get_height()
        total_code_lines = len(current_highlighted_code)
        
        # 保留空间：标题(35px) + 状态栏(25px) + 边距(20px)
        reserved_height = 80
        available_height = window_height - reserved_height
        
        # 🎯 核心自适应逻辑
        if total_code_lines <= 10:
            # 少量代码：使用较大字体，舒适阅读
            font_size = min(16, max(12, available_height // 15))
            line_height = font_size + 4
        elif total_code_lines <= 30:
            # 中等代码：平衡字体大小和显示行数
            target_lines = min(total_code_lines + 2, available_height // 12)
            line_height = available_height // target_lines
            font_size = max(10, min(14, line_height - 2))
        else:
            # 大量代码：优先显示更多行，紧凑模式
            target_lines = min(total_code_lines + 5, available_height // 10)
            line_height = available_height // target_lines
            font_size = max(8, min(12, line_height - 1))
        
        # 确保最小可读性
        font_size = max(8, min(20, font_size))
        line_height = max(10, min(25, line_height))
        line_number_font_size = max(6, font_size - 2)
        
        # 根据代码行数调整行号宽度
        if total_code_lines >= 1000:
            line_number_width = 50
        elif total_code_lines >= 100:
            line_number_width = 45
        else:
            line_number_width = 35
        
        # 计算实际可见行数
        visible_lines = available_height // line_height
        
        # 自适应边距
        margin_top = max(5, min(15, available_height // 40))
        
        logger.debug(f"🎯 自适应代码显示: {total_code_lines}行 -> 字体{font_size}px, 行高{line_height}px, 可见{visible_lines}行")
        
        return {
            'line_height': line_height,
            'font_size': font_size,
            'line_number_font_size': line_number_font_size,
            'line_number_width': line_number_width,
            'margin_top': margin_top,
            'visible_lines': visible_lines,
            'total_lines': total_code_lines,
            'adaptation_info': f"字体{font_size}px | 显示{visible_lines}/{total_code_lines}行"
        }
        
    except Exception as e:
        logger.error(f"计算自适应参数失败: {e}")
        # 返回安全的默认值
        return {
            'line_height': 16,
            'font_size': 12,
            'line_number_font_size': 10,
            'line_number_width': 40,
            'margin_top': 10,
            'visible_lines': 20
        }



def create_code_window():
    """创建代码查看模式（集成到主窗口）"""
    global code_window_visible, code_font, line_number_font, code_window_size, current_code
    
    try:
        logger.info("🔍 DEBUG: create_code_window 开始执行")
        
        if code_window_visible:
            logger.info("🔍 DEBUG: 代码窗口已可见，直接返回")
            return
        
        # 🔧 更详细的代码检查和处理
        logger.info(f"🔍 DEBUG: current_code 内容检查: {len(current_code) if current_code else 0} 字符")
        if not current_code or not current_code.strip():
            logger.warning("🔍 DEBUG: 当前没有代码内容，创建测试代码")
            # 🆕 如果没有代码，创建一个测试代码示例
            current_code = """# GhostMentor 代码查看模式测试
def hello_ghostmentor():
    \"\"\"这是一个测试函数\"\"\"
    print("👻 GhostMentor 代码查看模式正常工作！")
    return "✅ 代码显示功能已激活"

# 测试不同的语法高亮
class TestClass:
    def __init__(self, name="测试"):
        self.name = name
        self.numbers = [1, 2, 3, 4, 5]
    
    def display_info(self):
        for i, num in enumerate(self.numbers):
            print(f"索引 {i}: 值 {num}")

# 创建实例并测试
test_instance = TestClass()
test_instance.display_info()
hello_ghostmentor()"""
            logger.info("✅ 测试代码已创建")
            show_notification("📝 显示测试代码 - 代码查看模式演示", 3.0)
        
        # 🆕 切换到代码模式窗口大小 - 已禁用，保持当前窗口尺寸
        # logger.info("🖥️ 开始切换到代码查看模式窗口尺寸")
        # try:
        #     resize_window(code_window_size, "code")
        #     logger.info("✅ 窗口调整完成，继续初始化")
        # except Exception as resize_error:
        #     logger.error(f"❌ 窗口调整失败: {resize_error}")
        #     show_notification("❌ 窗口调整失败", 2.0)
        #     return
        
        # 初始化代码字体（适应更大窗口）
        logger.info("🔤 开始初始化代码字体")
        try:
            code_font = pygame.font.SysFont('consolas', 14)  # 字体稍大一些
            line_number_font = pygame.font.SysFont('consolas', 12)
            logger.info("✅ Consolas 字体初始化成功")
        except Exception as font_error:
            logger.warning(f"⚠️ Consolas 字体失败: {font_error}, 使用备用字体")
            try:
                # 备用字体
                code_font = pygame.font.SysFont('courier new', 14)
                line_number_font = pygame.font.SysFont('courier new', 12)
                logger.info("✅ Courier New 字体初始化成功")
            except Exception as backup_font_error:
                logger.error(f"❌ 备用字体也失败: {backup_font_error}")
                show_notification("❌ 字体初始化失败", 2.0)
                return
        
        # 设置代码窗口可见
        code_window_visible = True
        logger.info("🎨 代码查看模式已激活")
        show_notification("🎨 代码查看模式 (按Esc退出)", 3.0)
        
        logger.info("✅ create_code_window 成功完成")
        
    except Exception as e:
        logger.error(f"❌ 激活代码查看模式失败: {e}")
        logger.error(f"❌ 异常详情: {type(e).__name__}: {str(e)}")
        code_window_visible = False
        show_notification("❌ 代码查看模式启动失败", 2.0)

def render_pygame_code_window():
    """在主窗口上渲染代码内容 - 自适应大小版本"""
    global screen, current_highlighted_code, code_scroll_offset, current_code, code_font, line_number_font
    
    if not code_window_visible or not screen:
        return
    
    try:
        # 解析当前代码的语法高亮
        if current_code:
            current_highlighted_code = parse_code_syntax_pygame(current_code)
        
        # 清空屏幕并设置代码查看背景
        screen.fill(SYNTAX_COLORS['background'])
        
        # 🆕 自适应渲染参数计算
        adaptive_params = calculate_adaptive_code_display()
        line_height = adaptive_params['line_height']
        font_size = adaptive_params['font_size']
        line_number_font_size = adaptive_params['line_number_font_size']
        line_number_width = adaptive_params['line_number_width']
        text_start_x = line_number_width + 8
        margin_top = adaptive_params['margin_top']
        margin_left = 5
        visible_lines = adaptive_params['visible_lines']
        
        # 🆕 根据自适应参数重新创建字体
        try:
            code_font = pygame.font.SysFont('consolas', font_size)
            line_number_font = pygame.font.SysFont('consolas', line_number_font_size)
        except:
            code_font = pygame.font.SysFont('courier new', font_size)
            line_number_font = pygame.font.SysFont('courier new', line_number_font_size)
        
        # 🆕 自适应标题显示
        title_text = f"🎨 代码查看器 - {adaptive_params['total_lines']} 行 | {adaptive_params['adaptation_info']} (Esc退出)"
        try:
            title_surface = font.render(title_text, True, (255, 255, 255))
            screen.blit(title_surface, (margin_left, 5))
        except:
            # 标题渲染失败的备用方案
            simple_title = f"🎨 代码查看器 - {adaptive_params['total_lines']} 行"
            title_surface = font.render(simple_title, True, (255, 255, 255))
            screen.blit(title_surface, (margin_left, 5))
        
        # 渲染可见的代码行
        if current_highlighted_code:
            title_space = 30  # 为标题预留的空间
            content_start_y = margin_top + title_space
            
            # 🆕 基于自适应参数计算显示范围
            display_lines = min(visible_lines, len(current_highlighted_code) - code_scroll_offset)
            end_line = min(len(current_highlighted_code), code_scroll_offset + display_lines)
            
            for i, line_idx in enumerate(range(code_scroll_offset, end_line)):
                line_data = current_highlighted_code[line_idx]
                y_pos = content_start_y + i * line_height
                
                # 确保不超出窗口底部
                if y_pos + line_height > screen.get_height() - 25:  # 预留状态栏空间
                    break
                
                # 渲染行号
                line_num_text = line_number_font.render(
                    f"{line_data['line_number']:3d}", 
                    True, 
                    SYNTAX_COLORS['line_number']
                )
                screen.blit(line_num_text, (margin_left, y_pos))
                
                # 渲染代码tokens
                x_pos = text_start_x
                for token_type, token_text in line_data['tokens']:
                    if not token_text:  # 跳过空token
                        continue
                        
                    # 确保不超出屏幕右边界
                    if x_pos > screen.get_width() - 30:  # 预留滚动条空间
                        break
                        
                    color = SYNTAX_COLORS.get(token_type, SYNTAX_COLORS['text'])
                    try:
                        token_surface = code_font.render(token_text, True, color)
                        screen.blit(token_surface, (x_pos, y_pos))
                        x_pos += token_surface.get_width()
                    except:
                        # 如果渲染失败，使用默认颜色
                        try:
                            token_surface = code_font.render(token_text, True, SYNTAX_COLORS['text'])
                            screen.blit(token_surface, (x_pos, y_pos))
                            x_pos += token_surface.get_width()
                        except:
                            # 最后的备用方案 - 跳过这个token
                            pass
            
            # 🆕 智能滚动指示器显示
            total_lines = len(current_highlighted_code)
            if total_lines > visible_lines:
                render_adaptive_code_scrollbar(adaptive_params)
                
            # 🆕 自适应底部状态栏
            actual_visible = min(display_lines, end_line - code_scroll_offset)
            status_text = f"第 {code_scroll_offset + 1}-{code_scroll_offset + actual_visible} 行 / 共 {total_lines} 行"
            if total_lines <= visible_lines:
                status_text += " | 全部显示 ✅"
            
            try:
                status_surface = line_number_font.render(status_text, True, (180, 180, 180))
                screen.blit(status_surface, (margin_left, screen.get_height() - 20))
            except:
                # 状态栏渲染失败的备用方案
                simple_status = f"{code_scroll_offset + 1}/{total_lines}"
                status_surface = line_number_font.render(simple_status, True, (180, 180, 180))
                screen.blit(status_surface, (margin_left, screen.get_height() - 20))
        
    except Exception as e:
        logger.error(f"渲染代码内容失败: {e}")

def render_adaptive_code_scrollbar(adaptive_params):
    """🆕 渲染自适应代码窗口滚动条"""
    global screen, current_highlighted_code, code_scroll_offset
    
    total_lines = adaptive_params['total_lines']
    visible_lines = adaptive_params['visible_lines']
    
    if total_lines <= visible_lines:
        return
    
    try:
        # 🎯 自适应滚动条参数
        scrollbar_width = 8 if screen.get_width() > 1000 else 6
        scrollbar_x = screen.get_width() - scrollbar_width - 5
        
        # 根据窗口高度调整滚动条区域
        title_space = 35
        status_space = 25
        scrollbar_height = screen.get_height() - title_space - status_space
        scrollbar_y = title_space
        
        # 滚动条背景
        bg_color = (40, 45, 50)
        pygame.draw.rect(screen, bg_color, 
                        (scrollbar_x, scrollbar_y, scrollbar_width, scrollbar_height))
        
        # 滚动条thumb
        thumb_ratio = visible_lines / total_lines
        thumb_height = max(20, thumb_ratio * scrollbar_height)
        
        # 计算thumb位置
        scroll_ratio = code_scroll_offset / max(1, total_lines - visible_lines)
        thumb_y = scrollbar_y + scroll_ratio * (scrollbar_height - thumb_height)
        
        # 根据滚动位置改变thumb颜色
        if code_scroll_offset == 0:
            thumb_color = (80, 150, 80)  # 顶部 - 绿色
        elif code_scroll_offset >= total_lines - visible_lines:
            thumb_color = (150, 80, 80)  # 底部 - 红色
        else:
            thumb_color = (120, 120, 150)  # 中间 - 蓝色
        
        pygame.draw.rect(screen, thumb_color, 
                        (scrollbar_x, thumb_y, scrollbar_width, thumb_height))
        
        # 滚动条边框
        pygame.draw.rect(screen, (80, 80, 80), 
                        (scrollbar_x, scrollbar_y, scrollbar_width, scrollbar_height), 1)
        
        # 显示滚动进度百分比（小字体）
        if total_lines > 0:
            progress = int((code_scroll_offset / max(1, total_lines - visible_lines)) * 100)
            try:
                progress_font = pygame.font.SysFont('arial', 10)
                progress_text = progress_font.render(f"{progress}%", True, (160, 160, 160))
                progress_x = scrollbar_x - progress_text.get_width() - 3
                progress_y = thumb_y + (thumb_height // 2) - (progress_text.get_height() // 2)
                screen.blit(progress_text, (progress_x, progress_y))
            except:
                pass  # 进度显示失败不影响主要功能
                
    except Exception as e:
        logger.error(f"渲染自适应滚动条失败: {e}")

def render_code_scrollbar(visible_lines):
    """渲染代码窗口滚动条 - 兼容性保留"""
    # 为向后兼容保留，但使用新的自适应版本
    try:
        adaptive_params = calculate_adaptive_code_display()
        render_adaptive_code_scrollbar(adaptive_params)
    except:
        # 如果自适应失败，使用简化版本
        global screen, current_highlighted_code, code_scroll_offset
        
        total_lines = len(current_highlighted_code)
        if total_lines <= visible_lines:
            return
        
        scrollbar_width = 6
        scrollbar_x = screen.get_width() - scrollbar_width - 5
        scrollbar_height = screen.get_height() - 60
        scrollbar_y = 35
        
        pygame.draw.rect(screen, (50, 50, 50), 
                        (scrollbar_x, scrollbar_y, scrollbar_width, scrollbar_height))
        
        thumb_height = max(15, (visible_lines / total_lines) * scrollbar_height)
        if total_lines > visible_lines:
            thumb_y = scrollbar_y + (code_scroll_offset / (total_lines - visible_lines)) * (scrollbar_height - thumb_height)
        else:
            thumb_y = scrollbar_y
        
        pygame.draw.rect(screen, (120, 120, 120), 
                        (scrollbar_x, thumb_y, scrollbar_width, thumb_height))

def close_code_window():
    """关闭代码查看模式"""
    global code_window_visible, code_scroll_offset, normal_window_size
    
    try:
        if code_window_visible:
            code_window_visible = False
            code_scroll_offset = 0  # 重置滚动位置
            
            # 🆕 恢复到正常窗口大小 - 已禁用，保持当前窗口尺寸
            # logger.info("🖥️ 恢复到正常窗口尺寸")
            # resize_window(normal_window_size, "normal")
            
            logger.info("🎨 代码查看模式已关闭")
            show_notification("🎨 代码查看模式已关闭", 2.0)
    except Exception as e:
        logger.error(f"关闭代码查看模式失败: {e}")

def show_screenshot_preview():
    """显示截图预览窗口"""
    global screenshot_preview_visible, screenshot_preview_timer, current_screenshot
    
    try:
        if not current_screenshot:
            logger.warning("没有可预览的截图")
            return
        
        screenshot_preview_visible = True
        screenshot_preview_timer = time.time() + 5.0  # 5秒后自动关闭
        
        logger.info("📷 截图预览窗口已显示")
        show_notification("📷 截图成功！预览窗口已显示 (按 P 关闭)", 3.0)
        
    except Exception as e:
        logger.error(f"显示截图预览失败: {e}")
        screenshot_preview_visible = False

def close_screenshot_preview():
    """关闭截图预览窗口"""
    global screenshot_preview_visible, current_screenshot
    
    try:
        if screenshot_preview_visible:
            screenshot_preview_visible = False
            current_screenshot = None  # 释放内存
            logger.info("📷 截图预览窗口已关闭")
            show_notification("📷 截图预览已关闭", 1.5)
    except Exception as e:
        logger.error(f"关闭截图预览失败: {e}")

def toggle_screenshot_preview():
    """切换截图预览窗口显示/隐藏"""
    if not current_screenshot:
        show_notification("📷 暂无截图可预览", 2.0)
        return
    
    if screenshot_preview_visible:
        close_screenshot_preview()
    else:
        show_screenshot_preview()

def toggle_recording():
    """切换录音开始/停止"""
    global recording_active, use_speech
    
    logger.info(f"🔍 DEBUG: toggle_recording called - use_speech={use_speech}, recording_active={recording_active}")
    
    if not use_speech:
        show_notification("❌ 语音功能已禁用", 2.0)
        return
    
    try:
        audio_mgr = get_audio_manager()
        logger.info(f"🔍 DEBUG: get_audio_manager returned: {audio_mgr is not None}")
        
        if not audio_mgr:
            show_notification("❌ 音频管理器未初始化", 3.0)
            logger.error("❌ 音频管理器为None，可能初始化失败")
            return
        
        # 检查音频管理器状态
        logger.info(f"🔍 DEBUG: 音频管理器状态: use_speech={audio_mgr.use_speech}, is_recording={audio_mgr.is_recording}")
        
        if recording_active:
            # 停止录音
            logger.info("🔇 准备停止录音...")
            audio_mgr.stop_recording()
            recording_active = False
            logger.info("🔇 录音已停止")
            show_notification("🔇 录音已停止", 2.0)
            set_app_state("ready")
        else:
            # 开始录音
            logger.info("🎤 准备开始录音...")
            result = audio_mgr.start_recording()
            if result:
                recording_active = True
                logger.info("🎤 录音已开始")
                show_notification("🎤 录音已开始 - 开始说话", 3.0)
                set_app_state("listening")
            else:
                logger.error("❌ 录音启动失败")
                show_notification("❌ 录音启动失败，请检查麦克风", 3.0)
            
    except Exception as e:
        logger.error(f"切换录音状态失败: {e}")
        show_notification(f"❌ 录音切换失败: {str(e)}", 3.0)

def render_screenshot_preview():
    """渲染截图预览窗口"""
    global screen, current_screenshot, screenshot_preview_timer, screenshot_preview_filename
    
    if not screenshot_preview_visible or not current_screenshot or not screen:
        return
    
    try:
        # 检查自动关闭计时器
        if time.time() > screenshot_preview_timer:
            close_screenshot_preview()
            return
        
        # 清空屏幕背景
        preview_bg_color = (20, 25, 30)  # 深色背景
        screen.fill(preview_bg_color)
        
        # 计算预览图像尺寸和位置
        window_width = window_settings['width']
        window_height = window_settings['height']
        
        # 预留标题和按钮区域
        title_height = 40
        button_height = 30
        available_height = window_height - title_height - button_height - 20
        available_width = window_width - 20
        
        # 计算缩放比例以适应窗口
        img_width, img_height = current_screenshot.size
        scale_x = available_width / img_width
        scale_y = available_height / img_height
        scale = min(scale_x, scale_y, 0.3)  # 最大缩放到30%
        
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        
        # 调整截图尺寸
        resized_screenshot = current_screenshot.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 转换为pygame surface
        img_string = resized_screenshot.tobytes()
        img_surface = pygame.image.fromstring(img_string, (new_width, new_height), resized_screenshot.mode)
        
        # 计算居中位置
        img_x = (window_width - new_width) // 2
        img_y = title_height + 10
        
        # 绘制预览图像边框
        border_rect = (img_x - 2, img_y - 2, new_width + 4, new_height + 4)
        pygame.draw.rect(screen, (100, 150, 200), border_rect, 2)
        
        # 绘制预览图像
        screen.blit(img_surface, (img_x, img_y))
        
        # 绘制标题
        title_text = f"📷 截图预览 - {screenshot_preview_filename}"
        title_surface = font.render(title_text, True, (255, 255, 255))
        title_x = (window_width - title_surface.get_width()) // 2
        screen.blit(title_surface, (title_x, 5))
        
        # 绘制状态信息
        remaining_time = max(0, screenshot_preview_timer - time.time())
        size_text = f"尺寸: {img_width}x{img_height} | 预览: {new_width}x{new_height} | {remaining_time:.1f}s后自动关闭"
        status_surface = font.render(size_text, True, (180, 180, 180))
        status_x = (window_width - status_surface.get_width()) // 2
        screen.blit(status_surface, (status_x, 25))
        
        # 绘制操作提示
        hint_text = "按 P 关闭预览 | 按 H 重新截图"
        hint_surface = font.render(hint_text, True, (150, 200, 255))
        hint_x = (window_width - hint_surface.get_width()) // 2
        hint_y = window_height - 20
        screen.blit(hint_surface, (hint_x, hint_y))
        
    except Exception as e:
        logger.error(f"渲染截图预览失败: {e}")
        close_screenshot_preview()

def toggle_code_window():
    """切换代码窗口显示/隐藏"""
    global current_code
    
    if not current_code.strip():
        show_notification("📝 暂无代码可显示", 2.0)
        return
    
    if code_window_visible:
        close_code_window()
    else:
        create_code_window()

def update_code_window():
    """更新代码查看模式"""
    if code_window_visible:
        try:
            # 代码查看模式不需要特殊更新，会在主渲染循环中处理
            pass
        except Exception as e:
            logger.error(f"更新代码查看模式失败: {e}")

def handle_pygame_code_window_events(event):
    """处理Pygame代码窗口事件"""
    global code_scroll_offset, current_highlighted_code
    
    if not code_window_visible:
        return
    
    if event.type == pygame.MOUSEWHEEL:
        if current_highlighted_code:
            visible_lines = (code_window_screen.get_height() - 20) // 18
            max_scroll = max(0, len(current_highlighted_code) - visible_lines)
            
            code_scroll_offset -= event.y * 3  # 滚动方向
            code_scroll_offset = max(0, min(code_scroll_offset, max_scroll))
            
            render_pygame_code_window()

async def send_to_openai(image, text):
    """Send screen image and transcribed text to OpenAI API using API manager."""
    global current_code
    try:
        if image is None:
            logger.warning("No screen capture available")
            text_queue.put("Error: No screen capture available")
            return None
        
        set_app_state("processing")
        
        # Use API manager for analysis
        response = await api_manager.analyze_screen(image, text)
        
        if response:
            # 提取代码块
            extracted_code = extract_code_from_response(response)
            if extracted_code:
                current_code = extracted_code
                logger.info(f"🎨 已提取代码，共 {len(extracted_code.split(chr(10)))} 行")
                show_notification("🎨 检测到代码，按 Ctrl+C 查看", 3.0)
            
            # Get formatted history for display
            history_text = api_manager.get_conversation_history()
            text_queue.put(history_text)
            set_app_state("ready")
            return response
        else:
            text_queue.put("No response from OpenAI")
            set_app_state("error")
            return None
            
    except Exception as e:
        logger.error(f"Error in OpenAI processing: {e}")
        text_queue.put(f"Processing error: {str(e)}")
        set_app_state("error")
        return None

async def send_text_to_openai(text):
    """Send only text to OpenAI API for pure conversation."""
    global current_code
    try:
        if not text.strip():
            logger.warning("No text to send")
            text_queue.put("Error: No text provided")
            return None
        
        logger.info(f"🔍 DEBUG: 调用纯文本API，输入内容: '{text}'")
        set_app_state("processing")
        
        # 检查API manager是否有analyze_text_only方法
        if hasattr(api_manager, 'analyze_text_only'):
            logger.info("✅ 使用analyze_text_only方法")
            response = await api_manager.analyze_text_only(text)
        else:
            logger.error("❌ API manager没有analyze_text_only方法，使用analyze_screen方法")
            # 如果没有text_only方法，传None作为image参数
            response = await api_manager.analyze_screen(None, text)
        
        if response:
            logger.info(f"🔍 DEBUG: 收到回复: '{response[:100]}...'")
            # 提取代码块
            extracted_code = extract_code_from_response(response)
            if extracted_code:
                current_code = extracted_code
                logger.info(f"🎨 已提取代码，共 {len(extracted_code.split(chr(10)))} 行")
                show_notification("🎨 检测到代码，按 Ctrl+C 查看", 3.0)
            
            # Get formatted history for display
            history_text = api_manager.get_conversation_history()
            text_queue.put(history_text)
            set_app_state("ready")
            return response
        else:
            logger.warning("🔍 DEBUG: 没有收到有效回复")
            text_queue.put("No response from OpenAI")
            set_app_state("error")
            return None
            
    except Exception as e:
        logger.error(f"Error in text-only OpenAI processing: {e}")
        text_queue.put(f"Processing error: {str(e)}")
        set_app_state("error")
        return None

async def send_multiple_screenshots_to_openai(user_text: str = ""):
    """Send multiple screenshots to OpenAI API for comprehensive analysis."""
    global screenshot_collection, current_code
    try:
        if not screenshot_collection:
            logger.warning("No screenshots in collection")
            text_queue.put("Error: No screenshots available")
            return None
        
        set_app_state("processing")
        
        # Extract all images from screenshot collection
        images = [screenshot_data[0] for screenshot_data in screenshot_collection]
        
        logger.info(f"🖼️ Sending {len(images)} screenshots to OpenAI for analysis...")
        
        # Use API manager for multi-screen analysis
        response = await api_manager.analyze_multiple_screens(images, user_text)
        
        if response:
            # 提取代码块
            extracted_code = extract_code_from_response(response)
            if extracted_code:
                current_code = extracted_code
                logger.info(f"🎨 已从多图分析中提取代码，共 {len(extracted_code.split(chr(10)))} 行")
                show_notification("🎨 检测到代码，按 Ctrl+C 查看", 3.0)
            
            # Get formatted history for display
            history_text = api_manager.get_conversation_history()
            text_queue.put(history_text)
            set_app_state("ready")
            return response
        else:
            text_queue.put("No response from OpenAI")
            set_app_state("error")
            return None
            
    except Exception as e:
        logger.error(f"Error in multi-screenshot OpenAI processing: {e}")
        text_queue.put(f"Multi-screenshot processing error: {str(e)}")
        set_app_state("error")
        return None

async def process_openai():
    """智能多模态分析处理器"""
    global current_transcript, has_recent_screenshot, screenshot_collection
    try:
        # 🚀 立即关闭截图预览窗口（如果打开着的话）
        if screenshot_preview_visible:
            close_screenshot_preview()
            logger.info("📷 自动关闭截图预览窗口，开始分析")
        
        # 🎯 智能分析当前上下文状态
        user_text = current_transcript.strip()
        has_voice = bool(user_text)
        has_screen = has_recent_screenshot
        screenshot_count = len(screenshot_collection)
        
        logger.info(f"🧠 智能分析开始: voice={has_voice}, screen={has_screen}, screenshots={screenshot_count}")
        logger.info(f"🔍 语音内容: '{user_text}' (长度: {len(user_text)})")
        
        # 🚀 智能选择最佳分析模式
        if has_voice and has_screen:
            # 多模态分析：语音 + 屏幕
            if screenshot_count > 1:
                logger.info(f"🎤📸 多模态分析: 语音内容 + {screenshot_count}张截图")
                show_notification(f"🧠 多模态分析中... ({screenshot_count}张截图)", 2.0)
                # 🆕 使用多张截图分析
                await send_multiple_screenshots_to_openai(user_text)
            else:
                logger.info("🎤📸 多模态分析: 语音内容 + 最新截图")
                show_notification("🧠 多模态分析中...", 2.0)
                # 使用最新截图
                if current_screenshot:
                    await send_to_openai(current_screenshot, user_text)
                else:
                    # 如果没有保存的截图，重新截取
                    image = capture_screen()
                    if image:
                        await send_to_openai(image, user_text)
                    else:
                        logger.error("截图失败，降级为纯语音分析")
                        await send_text_to_openai(user_text)
                    
        elif has_voice:
            # 纯语音对话
            logger.info("🎤 纯语音对话模式")
            show_notification("💬 语音对话分析中...", 2.0)
            await send_text_to_openai(user_text)
            
        elif has_screen:
            # 纯屏幕分析
            if screenshot_count > 1:
                logger.info(f"📸 纯屏幕分析模式: {screenshot_count}张截图")
                show_notification(f"🖼️ 分析{screenshot_count}张截图中...", 2.0)
                # 🆕 使用多张截图分析（无语音）
                await send_multiple_screenshots_to_openai("")
            else:
                logger.info("📸 纯屏幕分析模式")
                show_notification("🖼️ 屏幕分析中...", 2.0)
                
                if current_screenshot:
                    await send_to_openai(current_screenshot, "")
                else:
                    # 重新截图
                    image = capture_screen()
                    if image:
                        await send_to_openai(image, "")
                    else:
                        logger.error("❌ 无法获取屏幕内容")
                        text_queue.put("错误：无法截取屏幕")
                        set_app_state("error")
                        return
        else:
            # 无可用内容
            logger.warning("⭕ 无可分析内容")
            text_queue.put("提示：请先录音(Ctrl+V)或截图(Ctrl+H)，然后按Ctrl+Enter分析")
            show_context_status()  # 显示当前状态
            set_app_state("ready")
            return
            
    except Exception as e:
        logger.error(f"智能分析处理错误: {e}")
        text_queue.put(f"分析错误: {str(e)}")
        set_app_state("error")

def on_transcript_updated(transcript: str):
    """Callback function for when audio transcript is updated."""
    global current_transcript
    current_transcript = transcript
    set_app_state("listening")
    
    # 显示听到的内容
    truncated = transcript[:30] + ('...' if len(transcript) > 30 else '')
    show_notification(f"🎤 听到: {truncated}", 2.0)
    
    # 显示当前上下文状态
    show_context_status()

def update_overlay():
    """Update overlay text from the queue."""
    global overlay_text, last_response_time, scroll_offset
    try:
        while not text_queue.empty():
            overlay_text = text_queue.get()
            # Calculate wrapped lines to set scroll_offset to show latest response
            wrapped_lines = wrap_text(overlay_text, 480, font)
            max_lines = 8  # Maximum lines visible in HUD
            scroll_offset = max(0, len(wrapped_lines) - max_lines)  # Show latest lines
            last_response_time = time.time()
            logger.info(f"Overlay updated with: {overlay_text}, scroll_offset={scroll_offset}")
    except Exception as e:
        logger.error(f"Overlay update error: {e}")

def set_window_opacity(opacity_value):
    """Set window opacity (0-255, where 255 is fully opaque)."""
    global window_opacity, hwnd
    try:
        if hwnd:
            window_opacity = max(0, min(255, opacity_value))  # Clamp between 0-255
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, window_opacity, 2)
            percentage = round((window_opacity / 255) * 100)
            logger.info(f"🎨 Window opacity set to {window_opacity}/255 ({percentage}%)")
    except Exception as e:
        logger.error(f"Error setting window opacity: {e}")

def resize_window(new_size: tuple, mode: str = "normal"):
    """动态调整窗口大小"""
    global screen, hwnd, window_x, window_y, current_window_mode
    
    try:
        new_width, new_height = new_size
        logger.info(f"🔄 开始调整窗口大小到: {new_width}x{new_height} (模式: {mode})")
        
        # 重新创建pygame显示
        logger.info("🔄 重新创建pygame显示...")
        try:
            screen = pygame.display.set_mode((new_width, new_height), pygame.NOFRAME | pygame.SRCALPHA)
            logger.info("✅ pygame显示创建成功")
        except Exception as pygame_error:
            logger.error(f"❌ pygame显示创建失败: {pygame_error}")
            raise
        
        # 更新窗口句柄
        logger.info("🔄 更新窗口句柄...")
        try:
            hwnd = pygame.display.get_wm_info()['window']
            logger.info(f"✅ 窗口句柄获取成功: {hwnd}")
        except Exception as hwnd_error:
            logger.error(f"❌ 窗口句柄获取失败: {hwnd_error}")
            raise
        
        # 重新应用窗口属性 - 真正的幽灵窗口
        logger.info("🔄 应用幽灵窗口属性...")
        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style |= (win32con.WS_EX_LAYERED | 
                        win32con.WS_EX_NOACTIVATE | 
                        win32con.WS_EX_TOOLWINDOW |
                        win32con.WS_EX_TRANSPARENT)  # 🆕 鼠标点击穿透
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            logger.info("✅ 幽灵窗口属性设置成功")
        except Exception as style_error:
            logger.error(f"❌ 窗口属性设置失败: {style_error}")
            raise

        # 屏幕捕获保护
        logger.info("🔄 设置屏幕捕获保护...")
        try:
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            logger.info("✅ 屏幕捕获保护设置成功")
        except Exception as capture_error:
            logger.warning(f"⚠️ 屏幕捕获保护设置失败: {capture_error}")

        # 调整窗口位置（代码模式时可能需要居中）
        logger.info("🔄 计算窗口位置...")
        if mode == "code":
            # 代码模式时居中显示
            try:
                import tkinter as tk
                root = tk.Tk()
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                root.destroy()
                logger.info(f"✅ 屏幕尺寸: {screen_width}x{screen_height}")
            except:
                # 备用方案
                screen_width = 1920
                screen_height = 1080
                logger.warning("⚠️ 使用默认屏幕尺寸: 1920x1080")
            
            window_x = (screen_width - new_width) // 2
            window_y = (screen_height - new_height) // 2
            logger.info(f"✅ 代码模式居中位置: ({window_x}, {window_y})")
        
        # 设置窗口位置和保持置顶
        logger.info("🔄 设置窗口位置和置顶...")
        try:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, window_x, window_y, 
                                 new_width, new_height, 0)
            logger.info("✅ 窗口位置和置顶设置成功")
        except Exception as pos_error:
            logger.error(f"❌ 窗口位置设置失败: {pos_error}")
            raise
        
        # 恢复透明度
        logger.info("🔄 恢复窗口透明度...")
        try:
            set_window_opacity(window_opacity)
            logger.info("✅ 窗口透明度恢复成功")
        except Exception as opacity_error:
            logger.warning(f"⚠️ 透明度设置失败: {opacity_error}")
        
        # 更新全局状态
        current_window_mode = mode
        
        logger.info(f"✅ 窗口调整完成: {new_width}x{new_height} at ({window_x}, {window_y})")
        
        # 显示通知
        if mode == "code":
            show_notification(f"👻🖥️ 代码模式: {new_width}x{new_height} (幽灵窗口)", 2.0)
        else:
            show_notification(f"👻🖥️ 普通模式: {new_width}x{new_height} (幽灵窗口)", 2.0)
        
    except Exception as e:
        logger.error(f"❌ 窗口调整失败: {e}")
        logger.error(f"❌ 异常详情: {type(e).__name__}: {str(e)}")
        show_notification("❌ 窗口调整失败", 2.0)
        raise  # 重新抛出异常，让上层函数处理

def enlarge_window():
    """增大窗口尺寸"""
    global normal_window_size, code_window_size, current_window_mode
    
    try:
        if current_window_mode == "code":
            current_size = code_window_size
        else:
            current_size = normal_window_size
        
        # 增大20%
        new_width = int(current_size[0] * 1.2)
        new_height = int(current_size[1] * 1.2)
        new_size = (new_width, new_height)
        
        # 更新对应的尺寸变量
        if current_window_mode == "code":
            code_window_size = new_size
        else:
            normal_window_size = new_size
        
        resize_window(new_size, current_window_mode)
        show_notification(f"🔍 窗口已放大: {new_width}x{new_height}", 2.0)
        
    except Exception as e:
        logger.error(f"窗口放大失败: {e}")

def shrink_window():
    """缩小窗口尺寸"""
    global normal_window_size, code_window_size, current_window_mode
    
    try:
        if current_window_mode == "code":
            current_size = code_window_size
        else:
            current_size = normal_window_size
        
        # 缩小到80%
        new_width = int(current_size[0] * 0.8)
        new_height = int(current_size[1] * 0.8)
        # 确保不会太小
        new_width = max(400, new_width)
        new_height = max(300, new_height)
        new_size = (new_width, new_height)
        
        # 更新对应的尺寸变量
        if current_window_mode == "code":
            code_window_size = new_size
        else:
            normal_window_size = new_size
        
        resize_window(new_size, current_window_mode)
        show_notification(f"🔍 窗口已缩小: {new_width}x{new_height}", 2.0)
        
    except Exception as e:
        logger.error(f"窗口缩小失败: {e}")

def reset_window_size():
    """重置窗口到默认大小"""
    global normal_window_size, code_window_size, current_window_mode
    
    try:
        # 重置到配置文件中的默认值
        default_normal = (window_settings['width'], window_settings['height'])
        default_code = (window_settings['code_mode_width'], window_settings['code_mode_height'])
        
        normal_window_size = default_normal
        code_window_size = default_code
        
        if current_window_mode == "code":
            resize_window(default_code, "code")
            show_notification(f"🔄 重置到代码模式默认尺寸: {default_code[0]}x{default_code[1]}", 2.0)
        else:
            resize_window(default_normal, "normal")
            show_notification(f"🔄 重置到普通模式默认尺寸: {default_normal[0]}x{default_normal[1]}", 2.0)
        
    except Exception as e:
        logger.error(f"窗口重置失败: {e}")

last_keep_on_top_log = 0

def keep_on_top():
    """Ensure the window stays on top and maintains ghost properties."""
    global last_keep_on_top_log
    try:
        if hwnd:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            
            # 🆕 确保幽灵窗口属性保持不变
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style |= (win32con.WS_EX_LAYERED | 
                        win32con.WS_EX_NOACTIVATE | 
                        win32con.WS_EX_TOOLWINDOW |
                        win32con.WS_EX_TRANSPARENT)  # 保持鼠标穿透
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            
            # Ensure transparency is maintained
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, window_opacity, 2)
            
            # Only log once every 5 seconds to avoid spam
            current_time = time.time()
            if current_time - last_keep_on_top_log > 5:
                logger.debug("Reasserted HWND_TOPMOST with ghost window properties")
                last_keep_on_top_log = current_time
    except Exception as e:
        logger.error(f"Keep on top error: {e}")

def create_hud():
    """Create a floating HUD window with Apple-inspired design using config settings."""
    global screen, font, title_font, subtitle_font, hwnd, window_x, window_y
    try:
        # Hide console window for clean experience
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if console_hwnd:
            ctypes.windll.user32.ShowWindow(console_hwnd, 0)  # SW_HIDE
            logger.info("💻 Console window hidden for clean experience")

        pygame.init()
        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{window_x},{window_y}"
        
        # Use window settings from config
        window_width = window_settings['width']
        window_height = window_settings['height']
        
        screen = pygame.display.set_mode((window_width, window_height), pygame.NOFRAME | pygame.SRCALPHA)
        pygame.display.set_caption("🍎 GhostMentor Ultra")
        logger.info(f"🎮 Pygame window initialized: {window_width}x{window_height}")

        hwnd = pygame.display.get_wm_info()['window']
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        # 🆕 真正的幽灵窗口 - 悬浮显示，鼠标穿透，无焦点
        ex_style |= (win32con.WS_EX_LAYERED | 
                    win32con.WS_EX_NOACTIVATE | 
                    win32con.WS_EX_TOOLWINDOW |
                    win32con.WS_EX_TRANSPARENT)  # 🆕 鼠标点击穿透
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

        # Screen capture protection (privacy feature)
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)

        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, window_x, window_y, 
                             window_width, window_height, 0)
        logger.info("🍎 Apple-style window positioning applied")

        # Initialize fonts using UI settings
        try:
            font_size = ui_settings['font_size']
            title_font_size = ui_settings['title_font_size'] 
            subtitle_font_size = ui_settings['subtitle_font_size']
            
            # Try to use system fonts that support Chinese characters
            # List of fonts that support Chinese, in order of preference
            chinese_fonts = ['microsoft yahei', 'simsun', 'simhei', 'dengxian', 'segoe ui', 'arial unicode ms']
            font_found = False
            
            for font_name in chinese_fonts:
                try:
                    font = pygame.font.SysFont(font_name, font_size)
                    title_font = pygame.font.SysFont(font_name, title_font_size, bold=True)
                    subtitle_font = pygame.font.SysFont(font_name, subtitle_font_size)
                    font_found = True
                    logger.info(f"🎨 Using font: {font_name}")
                    break
                except:
                    continue
            
            if not font_found:
                # Fallback to default fonts
                font = pygame.font.SysFont('segoe ui', font_size)
                title_font = pygame.font.SysFont('segoe ui', title_font_size, bold=True)
                subtitle_font = pygame.font.SysFont('segoe ui', subtitle_font_size)
            logger.info(f"🎨 Fonts initialized: body={font_size}px, title={title_font_size}px, subtitle={subtitle_font_size}px")
        except Exception as font_error:
            # Fallback to standard fonts
            font = pygame.font.SysFont('arial', 16)
            title_font = pygame.font.SysFont('arial', 20, bold=True)
            subtitle_font = pygame.font.SysFont('arial', 14)
            logger.warning(f"Font initialization error, using fallback: {font_error}")

        # Set window opacity from config
        set_window_opacity(window_opacity)
        
        # Initialize with ready state
        set_app_state("ready")
        show_notification("👻 GhostMentor Ultra 幽灵模式 - 鼠标穿透，键盘操控", 3.0)
        
        logger.info(f"🍎 Apple-inspired HUD created at ({window_x}, {window_y}) - {window_width}x{window_height}px")
    except Exception as e:
        logger.error(f"HUD creation error: {e}")
        set_app_state("error")
        raise

def move_window(dx, dy):
    """Move the HUD window with smooth Apple-style positioning using config values."""
    global window_x, window_y, hwnd
    try:
        window_x += dx
        window_y += dy
        
        # Get window dimensions from config
        window_width = window_settings['width']
        window_height = window_settings['height']
        
        # Ensure window stays within screen bounds
        # TODO: Get actual screen resolution instead of hardcoded values
        screen_width = 1920  # Could be made configurable
        screen_height = 1080
        
        window_x = max(0, min(window_x, screen_width - window_width))
        window_y = max(0, min(window_y, screen_height - window_height))
        
        if hwnd:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 
                                window_x, window_y, 0, 0, 
                                win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
            # Maintain transparency after moving
            set_window_opacity(window_opacity)
            show_notification(f"📍 Moved to ({window_x}, {window_y})", 1.0)
            logger.info(f"🍎 Window moved to ({window_x}, {window_y}) with transparency maintained")
            
            # Update config with new position
            config.set('window_settings.x', window_x)
            config.set('window_settings.y', window_y)
    except Exception as e:
        logger.error(f"Error moving window: {e}")
        set_app_state("error")

def draw_help_menu():
    """Draw a beautiful help menu showing keyboard shortcuts."""
    global help_menu_alpha, title_font, font, show_help_menu
    
    if not show_help_menu:
        if help_menu_alpha > 0:
            help_menu_alpha = max(0, help_menu_alpha - 10)  # Fade out
        else:
            return
    else:
        help_menu_alpha = min(255, help_menu_alpha + 15)  # Fade in
    
    # Help menu dimensions and position
    menu_width = 420
    menu_height = 500  # Increased height for more shortcuts
    menu_x = (500 - menu_width) // 2  # Center horizontally
    menu_y = 20
    
    # Create semi-transparent surface for the help menu
    help_surface = pygame.Surface((menu_width, menu_height), pygame.SRCALPHA)
    
    # Background with gradient effect
    bg_color = (25, 35, 45, int(help_menu_alpha * 0.95))  # Dark blue-gray
    border_color = (70, 130, 180, help_menu_alpha)  # Steel blue
    
    # Draw background
    pygame.draw.rect(help_surface, bg_color, (0, 0, menu_width, menu_height), border_radius=12)
    pygame.draw.rect(help_surface, border_color, (0, 0, menu_width, menu_height), width=2, border_radius=12)
    
    # Title
    title_color = (255, 255, 255, help_menu_alpha)
    title_text = title_font.render("👻 幽灵窗口 - 键盘快捷键", True, (255, 255, 255))
    title_rect = title_text.get_rect(center=(menu_width // 2, 30))
    help_surface.blit(title_text, title_rect)
    
    # Shortcuts data
    shortcuts = [
        ("截取屏幕", "Ctrl", "H"),
        ("截图预览", "Ctrl", "P"),
        ("清除所有截图", "Ctrl", "X"),
        ("下一张截图", "Ctrl", "N"),
        ("上一张截图", "Ctrl", "M"),
        ("开始/停止录音", "Ctrl", "V"),
        ("智能AI分析", "Ctrl", "Enter"),
        ("查看上下文状态", "Ctrl", "I"),
        ("清除所有内容", "Ctrl", "G"),
        ("切换显示/隐藏", "Ctrl", "B"),
        ("代码窗口", "Ctrl", "C"),
        ("放大窗口", "Ctrl+Shift", "="),
        ("缩小窗口", "Ctrl+Shift", "-"),
        ("重置窗口大小", "Ctrl+Shift", "R"),
        ("上移窗口", "Ctrl", "↑"),
        ("下移窗口", "Ctrl", "↓"),
        ("左移窗口", "Ctrl", "←"),
        ("右移窗口", "Ctrl", "→"),
        ("增加透明度", "Ctrl", "PgUp/="),
        ("减少透明度", "Ctrl", "PgDn/-"),
        ("显示/隐藏帮助", "Ctrl", "?"),
        ("退出程序", "Alt", "F4")
    ]
    
    # Draw shortcuts
    y_offset = 70
    for i, (description, mod_key, key) in enumerate(shortcuts):
        # Description
        desc_color = (220, 220, 220) if i % 2 == 0 else (200, 200, 200)
        desc_text = font.render(description, True, desc_color)
        help_surface.blit(desc_text, (20, y_offset))
        
        # Key combination background
        key_bg_width = 80
        key_bg_height = 24
        key_bg_x = menu_width - key_bg_width - 15
        key_bg_y = y_offset - 2
        
        # Draw key background
        key_bg_color = (50, 60, 70, help_menu_alpha)
        key_border_color = (100, 120, 140, help_menu_alpha)
        pygame.draw.rect(help_surface, key_bg_color, 
                        (key_bg_x, key_bg_y, key_bg_width, key_bg_height), border_radius=4)
        pygame.draw.rect(help_surface, key_border_color, 
                        (key_bg_x, key_bg_y, key_bg_width, key_bg_height), width=1, border_radius=4)
        
        # Key text
        key_text = f"{mod_key} + {key}"
        key_surface = font.render(key_text, True, (255, 255, 255))
        key_rect = key_surface.get_rect(center=(key_bg_x + key_bg_width // 2, key_bg_y + key_bg_height // 2))
        help_surface.blit(key_surface, key_rect)
        
        y_offset += 30
    
    # Footer
    footer_y = menu_height - 40
    footer_text = font.render("👻 GhostMentor Ultra - 真·幽灵模式", True, (130, 150, 170))
    footer_rect = footer_text.get_rect(center=(menu_width // 2, footer_y))
    help_surface.blit(footer_text, footer_rect)
    
    # Version info
    version_text = font.render("v2.1 - 鼠标穿透·无焦点·键盘操控", True, (100, 120, 140))
    version_rect = version_text.get_rect(center=(menu_width // 2, footer_y + 15))
    help_surface.blit(version_text, version_rect)
    
    # Apply alpha to the entire surface
    if help_menu_alpha < 255:
        help_surface.set_alpha(help_menu_alpha)
    
    # Blit to main screen
    screen.blit(help_surface, (menu_x, menu_y))

def setup_keybindings():
    """Set up HIGH PRIORITY universal key bindings using keyboard library."""
    
    def global_key_handler(event):
        """High priority global key handler that blocks other applications."""
        try:
            # Only process key down events
            if event.event_type != keyboard.KEY_DOWN:
                return True
            
            # 🔍 检查窗口隐藏状态 - 如果窗口隐藏，只处理显示窗口和退出的快捷键
            global window_hidden, running
            
            # Debug: Log all Ctrl key combinations to help with troubleshooting
            if keyboard.is_pressed('ctrl'):
                logger.debug(f"🔧 DEBUG: Ctrl + '{event.name}' detected (window_hidden: {window_hidden})")
            
            # 如果窗口隐藏，只允许显示窗口和退出程序的快捷键
            if window_hidden:
                if keyboard.is_pressed('ctrl') and event.name == 'b':
                    # Ctrl + B 显示窗口（这个必须保留，否则无法重新显示窗口）
                    logger.info("🥷 HIGH PRIORITY: Ctrl + B pressed (Show Window from Hidden)")
                    toggle_window_visibility()
                    return False
                elif keyboard.is_pressed('alt') and event.name == 'f4':
                    # Alt + F4 退出程序（这个也保留，允许在隐藏状态退出）
                    logger.info("🥷 HIGH PRIORITY: Alt + F4 pressed (Exit from Hidden)")
                    running = False
                    return False
                else:
                    # 窗口隐藏时，其他所有快捷键都让系统正常处理
                    logger.debug(f"🙈 Window hidden - passing through: Ctrl + {event.name}")
                    return True
            
            # 窗口显示状态下，处理所有快捷键
            if keyboard.is_pressed('ctrl'):
                if event.name == 'h':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + H pressed (Screenshot)")
                    save_screenshot()
                    return False  # Block browser history shortcut
                elif event.name == 'enter':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Enter pressed (AI Analysis)")
                    text_queue.put("Processing...")
                    asyncio.run_coroutine_threadsafe(process_openai(), loop)
                    return False  # Block other Ctrl+Enter actions
                elif event.name == 'g':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + G pressed (Clear All)")
                    global current_transcript, has_recent_screenshot
                    current_transcript = ""
                    has_recent_screenshot = False
                    # 🆕 清除所有截图
                    clear_all_screenshots()
                    api_manager.clear_history()
                    text_queue.put("Ready...")
                    show_notification("🧹 已清除所有内容和截图", 2.0)
                    show_context_status()  # 显示清除后的状态
                    return False  # Block browser find shortcut
                elif event.name == 'i':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + I pressed (Show Context Status)")
                    show_context_status()
                    return False  # Block other Ctrl+I actions
                elif event.name == 'up':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Up pressed (Move Window Up)")
                    move_window(0, -move_step)
                    return False  # Block other Ctrl+Up actions
                elif event.name == 'down':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Down pressed (Move Window Down)")
                    move_window(0, move_step)
                    return False  # Block other Ctrl+Down actions
                elif event.name == 'left':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Left pressed (Move Window Left)")
                    move_window(-move_step, 0)
                    return False  # Block other Ctrl+Left actions
                elif event.name == 'right':
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Right pressed (Move Window Right)")
                    move_window(move_step, 0)
                    return False  # Block other Ctrl+Right actions
                elif event.name == '/' or event.name == '?':  # Ctrl + ? to toggle help
                    logger.info("🥷 HIGH PRIORITY: Ctrl + ? pressed (Toggle Help)")
                    global show_help_menu
                    show_help_menu = not show_help_menu
                    return False  # Block other Ctrl+? actions
                elif event.name in ['page up', 'page_up', 'pgup']:  # Ctrl + Page Up to increase opacity
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Page Up pressed (Increase Opacity)")
                    new_opacity = min(255, window_opacity + 25)  # Increase by ~10%
                    set_window_opacity(new_opacity)
                    return False
                elif event.name in ['page down', 'page_down', 'pgdn']:  # Ctrl + Page Down to decrease opacity
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Page Down pressed (Decrease Opacity)")
                    new_opacity = max(13, window_opacity - 25)  # Decrease by ~10%, min 5%
                    set_window_opacity(new_opacity)
                    return False
                elif event.name == '=' or event.name == '+':  # Ctrl + = to increase opacity (alternative)
                    logger.info("🥷 HIGH PRIORITY: Ctrl + = pressed (Increase Opacity)")
                    new_opacity = min(255, window_opacity + 25)  # Increase by ~10%
                    set_window_opacity(new_opacity)
                    return False
                elif event.name == '-' or event.name == '_':  # Ctrl + - to decrease opacity (alternative)
                    logger.info("🥷 HIGH PRIORITY: Ctrl + - pressed (Decrease Opacity)")
                    new_opacity = max(13, window_opacity - 25)  # Decrease by ~10%, min 5%
                    set_window_opacity(new_opacity)
                    return False
                elif event.name == 'b':  # Ctrl + B to toggle window visibility
                    logger.info("🥷 HIGH PRIORITY: Ctrl + B pressed (Toggle Window Visibility)")
                    toggle_window_visibility()
                    return False
                elif event.name == 'c':  # Ctrl + C to toggle code window
                    logger.info("🥷 HIGH PRIORITY: Ctrl + C pressed (Toggle Code Window)")
                    toggle_code_window()
                    return False
                elif event.name == 'p':  # Ctrl + P to toggle screenshot preview
                    logger.info("🥷 HIGH PRIORITY: Ctrl + P pressed (Toggle Screenshot Preview)")
                    toggle_screenshot_preview()
                    return False
                elif event.name == 'v':  # Ctrl + V to toggle recording
                    logger.info("🥷 HIGH PRIORITY: Ctrl + V pressed (Toggle Recording)")
                    toggle_recording()
                    return False
                elif event.name == 'x':  # Ctrl + X to clear all screenshots
                    logger.info("🥷 HIGH PRIORITY: Ctrl + X pressed (Clear All Screenshots)")
                    clear_all_screenshots()
                    return False
                elif event.name == 'n':  # Ctrl + N to next screenshot
                    logger.info("🥷 HIGH PRIORITY: Ctrl + N pressed (Next Screenshot)")
                    next_screenshot()
                    return False
                elif event.name == 'm':  # Ctrl + M to previous screenshot
                    logger.info("🥷 HIGH PRIORITY: Ctrl + M pressed (Previous Screenshot)")
                    prev_screenshot()
                    return False
                elif keyboard.is_pressed('shift') and event.name == '=':  # Ctrl + Shift + = to enlarge window
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Shift + = pressed (Enlarge Window)")
                    enlarge_window()
                    return False
                elif keyboard.is_pressed('shift') and event.name == '-':  # Ctrl + Shift + - to shrink window
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Shift + - pressed (Shrink Window)")
                    shrink_window()
                    return False
                elif keyboard.is_pressed('shift') and event.name == 'r':  # Ctrl + Shift + R to reset window size
                    logger.info("🥷 HIGH PRIORITY: Ctrl + Shift + R pressed (Reset Window Size)")
                    reset_window_size()
                    return False
            
            elif keyboard.is_pressed('alt') and event.name == 'f4':
                logger.info("🥷 HIGH PRIORITY: Alt + F4 pressed (Exit GhostMentor)")
                running = False
                return False  # Block system Alt+F4
        
        except Exception as e:
            logger.error(f"Error in global key handler: {e}")
        
        # Let all other key events pass through normally
        return True

    try:
        # Set up global hook with suppression capability
        keyboard.hook(global_key_handler, suppress=True)
        logger.info("🥷 HIGH PRIORITY global key hook set up - OVERRIDES system shortcuts!")
        
    except Exception as e:
        logger.error(f"Error setting up high priority key bindings: {e}")
        # Fallback to normal hotkeys if high priority fails
        try:
            def on_ctrl_h():
                logger.info("📸 Fallback: Ctrl + H pressed (Screenshot)")
                save_screenshot()

            def on_ctrl_enter():
                logger.info("🤖 Fallback: Ctrl + Enter pressed (AI Analysis)")
                text_queue.put("Processing...")
                asyncio.run_coroutine_threadsafe(process_openai(), loop)

            def on_ctrl_g():
                logger.info("🧹 Fallback: Ctrl + G pressed (Clear All)")
                global current_transcript, has_recent_screenshot
                current_transcript = ""
                has_recent_screenshot = False
                api_manager.clear_history()
                text_queue.put("Ready...")
                show_notification("🧹 已清除所有内容", 2.0)
                show_context_status()
            
            def on_ctrl_i():
                logger.info("📊 Fallback: Ctrl + I pressed (Show Context Status)")
                show_context_status()

            def on_alt_f4():
                logger.info("❌ Fallback: Alt + F4 pressed (Exit)")
                global running
                running = False

            def on_ctrl_up():
                logger.info("⬆️ Fallback: Ctrl + Up pressed")
                move_window(0, -move_step)

            def on_ctrl_down():
                logger.info("⬇️ Fallback: Ctrl + Down pressed")
                move_window(0, move_step)

            def on_ctrl_left():
                logger.info("⬅️ Fallback: Ctrl + Left pressed")
                move_window(-move_step, 0)

            def on_ctrl_right():
                logger.info("➡️ Fallback: Ctrl + Right pressed")
                move_window(move_step, 0)

            def on_ctrl_question():
                logger.info("❓ Fallback: Ctrl + ? pressed (Toggle Help)")
                global show_help_menu
                show_help_menu = not show_help_menu

            def on_ctrl_page_up():
                logger.info("🔆 Fallback: Ctrl + Page Up pressed (Increase Opacity)")
                new_opacity = min(255, window_opacity + 25)
                set_window_opacity(new_opacity)

            def on_ctrl_page_down():
                logger.info("🔅 Fallback: Ctrl + Page Down pressed (Decrease Opacity)")
                new_opacity = max(13, window_opacity - 25)
                set_window_opacity(new_opacity)

            def on_ctrl_plus():
                logger.info("🔆 Fallback: Ctrl + = pressed (Increase Opacity)")
                new_opacity = min(255, window_opacity + 25)
                set_window_opacity(new_opacity)

            def on_ctrl_minus():
                logger.info("🔅 Fallback: Ctrl + - pressed (Decrease Opacity)")
                new_opacity = max(13, window_opacity - 25)
                set_window_opacity(new_opacity)

            def on_ctrl_b():
                logger.info("👁️ Fallback: Ctrl + B pressed (Toggle Window Visibility)")
                toggle_window_visibility()

            def on_ctrl_c():
                logger.info("🎨 Fallback: Ctrl + C pressed (Toggle Code Window)")
                toggle_code_window()

            def on_ctrl_p():
                logger.info("📷 Fallback: Ctrl + P pressed (Toggle Screenshot Preview)")
                toggle_screenshot_preview()

            def on_ctrl_v():
                logger.info("🎤 Fallback: Ctrl + V pressed (Toggle Recording)")
                toggle_recording()

            keyboard.add_hotkey('ctrl+h', on_ctrl_h)
            keyboard.add_hotkey('ctrl+enter', on_ctrl_enter)
            keyboard.add_hotkey('ctrl+g', on_ctrl_g)
            keyboard.add_hotkey('ctrl+i', on_ctrl_i)
            keyboard.add_hotkey('ctrl+b', on_ctrl_b)
            keyboard.add_hotkey('ctrl+c', on_ctrl_c)
            keyboard.add_hotkey('ctrl+p', on_ctrl_p)
            keyboard.add_hotkey('ctrl+v', on_ctrl_v)
            keyboard.add_hotkey('alt+f4', on_alt_f4)
            keyboard.add_hotkey('ctrl+up', on_ctrl_up)
            keyboard.add_hotkey('ctrl+down', on_ctrl_down)
            keyboard.add_hotkey('ctrl+left', on_ctrl_left)
            keyboard.add_hotkey('ctrl+right', on_ctrl_right)
            keyboard.add_hotkey('ctrl+/', on_ctrl_question)  # Ctrl + ? for help
            # Try multiple key variations for Page Up/Down
            try:
                keyboard.add_hotkey('ctrl+page up', on_ctrl_page_up)
            except:
                try:
                    keyboard.add_hotkey('ctrl+page_up', on_ctrl_page_up)
                except:
                    keyboard.add_hotkey('ctrl+pgup', on_ctrl_page_up)
            
            try:
                keyboard.add_hotkey('ctrl+page down', on_ctrl_page_down)
            except:
                try:
                    keyboard.add_hotkey('ctrl+page_down', on_ctrl_page_down)
                except:
                    keyboard.add_hotkey('ctrl+pgdn', on_ctrl_page_down)
            
            # Add alternative shortcuts for opacity control
            keyboard.add_hotkey('ctrl+=', on_ctrl_plus)
            keyboard.add_hotkey('ctrl+-', on_ctrl_minus)
            logger.info("⚠️ Using fallback normal priority key bindings with alternatives")
        except Exception as e2:
            logger.error(f"Fallback key binding setup failed: {e2}")

def run_asyncio_loop(loop):
    """Run asyncio event loop in a separate thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()

def main():
    """Main function to start HUD with improved modular architecture."""
    global loop, running, scroll_offset, use_speech
    
    try:
        # 设置控制台编码为UTF-8
        if os.name == 'nt':  # Windows
            os.system('chcp 65001 > nul')
        
        # 初始化tkinter根窗口（隐藏）
        root = tk.Tk()
        root.withdraw()  # 隐藏主tkinter窗口
        
        logger.info("🚀 正在启动 GhostMentor Ultra Stealth Edition...")
        
        # Initialize audio manager if speech is enabled (but don't start recording)
        audio_mgr = None
        if use_speech:
            try:
                audio_mgr = initialize_audio_manager(use_speech=True)
                audio_mgr.set_transcript_callback(on_transcript_updated)
                # 🔇 不自动开始录音 - 等待用户按 Ctrl+V
                logger.info("🎤 音频管理器已初始化 (录音未开始 - 按 Ctrl+V 开始)")
                show_notification("🎤 按 Ctrl+V 开始/停止录音", 3.0)
            except Exception as e:
                logger.error(f"音频初始化失败: {e}")
                logger.warning("🔇 继续运行，但不使用语音识别")
                use_speech = False
        else:
            logger.info("🔇 运行在静音模式 - 语音识别已禁用")

        # Create HUD window
        create_hud()

        # Initialize asyncio loop for OpenAI
        loop = asyncio.new_event_loop()
        asyncio_thread = Thread(target=run_asyncio_loop, args=(loop,), daemon=True)
        asyncio_thread.start()
        logger.info("🔄 OpenAI API异步循环已启动")

        # Set up universal key bindings
        setup_keybindings()

        # Main Pygame loop with enhanced error handling
        # 🆕 移除鼠标拖拽功能 - 窗口现在是鼠标穿透的
        clock = pygame.time.Clock()
        running = True
        
        logger.info("🎮 进入主游戏循环...")
        
        while running:
            try:
                # Handle pygame events (幽灵窗口模式 - 只处理系统事件和键盘)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        logger.info("❌ 检测到窗口关闭事件")
                    # 🆕 移除所有鼠标事件处理 - 窗口现在是鼠标穿透的
                    elif event.type == pygame.KEYDOWN:
                        # ⚠️ 限制性键盘事件处理 - 只处理特定键，保证全局快捷键正常工作
                        handled = False
                        
                        if screenshot_preview_visible:
                            # 截图预览模式下的键盘控制
                            if event.key == pygame.K_ESCAPE:
                                close_screenshot_preview()
                                handled = True
                            # 注意：移除 K_p 和 K_h 处理，让全局快捷键处理
                        
                        elif code_window_visible:
                            # 代码查看模式下的键盘控制 - 只处理导航键
                            if event.key == pygame.K_ESCAPE:
                                close_code_window()
                                handled = True
                            elif event.key == pygame.K_UP:
                                # 向上滚动
                                code_scroll_offset = max(0, code_scroll_offset - 1)
                                handled = True
                            elif event.key == pygame.K_DOWN:
                                # 向下滚动
                                if current_highlighted_code:
                                    adaptive_params = calculate_adaptive_code_display()
                                    visible_lines = adaptive_params['visible_lines']
                                    max_scroll = max(0, len(current_highlighted_code) - visible_lines)
                                    code_scroll_offset = min(max_scroll, code_scroll_offset + 1)
                                handled = True
                            elif event.key == pygame.K_PAGEUP:
                                # 向上翻页
                                if current_highlighted_code:
                                    adaptive_params = calculate_adaptive_code_display()
                                    visible_lines = adaptive_params['visible_lines']
                                    code_scroll_offset = max(0, code_scroll_offset - visible_lines)
                                handled = True
                            elif event.key == pygame.K_PAGEDOWN:
                                # 向下翻页
                                if current_highlighted_code:
                                    adaptive_params = calculate_adaptive_code_display()
                                    visible_lines = adaptive_params['visible_lines']
                                    max_scroll = max(0, len(current_highlighted_code) - visible_lines)
                                    code_scroll_offset = min(max_scroll, code_scroll_offset + visible_lines)
                                handled = True
                            elif event.key == pygame.K_HOME:
                                # 跳到开头
                                code_scroll_offset = 0
                                handled = True
                            elif event.key == pygame.K_END:
                                # 跳到结尾
                                if current_highlighted_code:
                                    adaptive_params = calculate_adaptive_code_display()
                                    visible_lines = adaptive_params['visible_lines']
                                    code_scroll_offset = max(0, len(current_highlighted_code) - visible_lines)
                                handled = True
                        
                        # 🆕 明确记录未处理的键盘事件，确保全局快捷键能正常工作
                        if not handled:
                            logger.debug(f"🔧 Pygame键盘事件未处理，交由全局钩子: {event.key}")
                            # 不阻塞，让全局键盘钩子继续处理
                    # 🆕 移除鼠标滚轮事件处理 - 窗口现在是鼠标穿透的
                    # elif event.type == pygame.MOUSEWHEEL: - 已禁用鼠标交互

                # Update overlay text
                update_overlay()
                keep_on_top()
                
                # Render based on current mode
                if screenshot_preview_visible:
                    # 截图预览模式 (最高优先级)
                    render_screenshot_preview()
                elif code_window_visible:
                    # 代码查看模式
                    render_pygame_code_window()
                else:
                    # 正常HUD模式
                    # Render HUD with wrapped text and scroll
                    screen.fill((0, 0, 0))  # Black background (transparency controlled by Windows API)
                    wrapped_lines = wrap_text(overlay_text, window_settings['width'] - 20, font)
                    max_lines = ui_settings['max_visible_lines']
                    visible_lines = wrapped_lines[scroll_offset:scroll_offset + max_lines]
                    
                    for i, line in enumerate(visible_lines):
                        try:
                            # 确保文本渲染支持中文字符
                            text_surface = font.render(line, True, (255, 255, 255))
                            screen.blit(text_surface, (10, 10 + i * 22))
                        except Exception as e:
                            # 如果渲染失败，尝试使用ASCII兼容的方式
                            logger.debug(f"文本渲染错误: {e}")
                            try:
                                # 尝试编码转换
                                safe_line = line.encode('utf-8', errors='replace').decode('utf-8')
                                text_surface = font.render(safe_line, True, (255, 255, 255))
                                screen.blit(text_surface, (10, 10 + i * 22))
                            except:
                                # 最后的备用方案
                                text_surface = font.render("文本显示错误", True, (255, 100, 100))
                                screen.blit(text_surface, (10, 10 + i * 22))

                    # Draw help menu overlay if enabled (only in normal mode)
                    draw_help_menu()

                pygame.display.flip()
                clock.tick(60)  # 60 FPS for smooth animations
                
            except Exception as e:
                logger.error(f"Pygame loop error: {e}")
                # Continue running instead of crashing
                time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("⚠️ Keyboard interrupt received")
        running = False
    except Exception as e:
        logger.error(f"Critical main error: {e}")
        set_app_state("error")
        raise
    finally:
        # Cleanup resources
        logger.info("🧹 正在清理资源...")
        
        # Clean up screenshots first
        cleanup_screenshots()
        
        # Clean up code window
        if code_window_visible:
            close_code_window()
        
        # Clean up screenshot preview window
        if screenshot_preview_visible:
            close_screenshot_preview()
        
        # Clean up audio
        if audio_mgr:
            audio_mgr.cleanup()
        
        # Clean up pygame
        if 'pygame' in globals():
            pygame.quit()
            logger.info("🎮 Pygame资源已清理")
        
        # Clean up keyboard hooks
        try:
            keyboard.unhook_all()
            logger.info("⌨️ 键盘绑定已移除")
        except:
            pass
        
        # Save final config state
        try:
            config.save_config()
            logger.info("💾 配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
        
        logger.info("✅ GhostMentor 已完全关闭")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
