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
# Pygame代码窗口相关变量
code_window_visible = False  # 代码窗口可见性
code_window_screen = None   # Pygame代码窗口surface
code_window_hwnd = None     # 代码窗口句柄
code_scroll_offset = 0      # 代码窗口滚动偏移
code_font = None           # 代码字体
line_number_font = None    # 行号字体
current_highlighted_code = []  # 当前高亮代码数据
current_code = ""  # Current code to display

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
    """Save a screenshot to the local directory."""
    global screenshot_files
    try:
        screenshot = capture_screen()
        if screenshot:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            screenshot.save(filename)
            screenshot_files.append(filename)  # Track for cleanup
            logger.info(f"📸 截图已保存: {filename}")
            return filename
        else:
            logger.warning("Failed to capture screenshot")
            return None
    except Exception as e:
        logger.error(f"Error saving screenshot: {e}")
        return None

def cleanup_screenshots():
    """清理所有创建的截图文件"""
    global screenshot_files
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
    except Exception as e:
        logger.error(f"清理截图文件时出错: {e}")

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
        # 匹配 ```python 到 ``` 之间的代码
        code_pattern = r'```(?:python)?\s*\n(.*?)\n```'
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



def create_code_window():
    """创建代码查看模式（集成到主窗口）"""
    global code_window_visible, code_font, line_number_font
    
    try:
        if code_window_visible:
            return
        
        if not current_code.strip():
            show_notification("📝 暂无代码可显示", 2.0)
            return
        
        # 初始化代码字体
        try:
            code_font = pygame.font.SysFont('consolas', 12)
            line_number_font = pygame.font.SysFont('consolas', 11)
        except:
            # 备用字体
            code_font = pygame.font.SysFont('courier new', 12)
            line_number_font = pygame.font.SysFont('courier new', 11)
        
        code_window_visible = True
        logger.info("🎨 代码查看模式已激活")
        show_notification("🎨 代码查看模式 (按Esc退出)", 2.0)
        
    except Exception as e:
        logger.error(f"激活代码查看模式失败: {e}")
        code_window_visible = False

def render_pygame_code_window():
    """在主窗口上渲染代码内容"""
    global screen, current_highlighted_code, code_scroll_offset, current_code
    
    if not code_window_visible or not screen:
        return
    
    try:
        # 解析当前代码的语法高亮
        if current_code:
            current_highlighted_code = parse_code_syntax_pygame(current_code)
        
        # 清空屏幕并设置代码查看背景
        screen.fill(SYNTAX_COLORS['background'])
        
        # 渲染参数
        line_height = 16
        line_number_width = 40
        text_start_x = line_number_width + 8
        margin_top = 10
        margin_left = 5
        visible_lines = (screen.get_height() - margin_top * 2) // line_height
        
        # 标题
        title_text = f"🎨 代码查看器 - {len(current_highlighted_code)} 行 (Esc退出, ↑↓滚动)"
        title_surface = font.render(title_text, True, (255, 255, 255))
        screen.blit(title_surface, (margin_left, 5))
        
        # 渲染可见的代码行
        if current_highlighted_code:
            end_line = min(len(current_highlighted_code), code_scroll_offset + visible_lines - 2)  # -2 for title space
            
            for i, line_idx in enumerate(range(code_scroll_offset, end_line)):
                line_data = current_highlighted_code[line_idx]
                y_pos = margin_top + 25 + i * line_height  # +25 for title space
                
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
                    if x_pos > screen.get_width() - 20:
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
                            # 最后的备用方案
                            pass
            
            # 渲染滚动指示器
            if len(current_highlighted_code) > visible_lines - 2:
                render_code_scrollbar(visible_lines - 2)
                
            # 底部状态栏
            status_text = f"第 {code_scroll_offset + 1}-{min(code_scroll_offset + visible_lines - 2, len(current_highlighted_code))} 行 / 共 {len(current_highlighted_code)} 行"
            status_surface = line_number_font.render(status_text, True, (180, 180, 180))
            screen.blit(status_surface, (margin_left, screen.get_height() - 20))
        
    except Exception as e:
        logger.error(f"渲染代码内容失败: {e}")

def render_code_scrollbar(visible_lines):
    """渲染代码窗口滚动条"""
    global screen, current_highlighted_code, code_scroll_offset
    
    total_lines = len(current_highlighted_code)
    if total_lines <= visible_lines:
        return
    
    # 滚动条参数
    scrollbar_width = 6
    scrollbar_x = screen.get_width() - scrollbar_width - 5
    scrollbar_height = screen.get_height() - 60  # 留出标题和状态栏空间
    scrollbar_y = 35
    
    # 滚动条背景
    pygame.draw.rect(screen, (50, 50, 50), 
                    (scrollbar_x, scrollbar_y, scrollbar_width, scrollbar_height))
    
    # 滚动条thumb
    thumb_height = max(15, (visible_lines / total_lines) * scrollbar_height)
    if total_lines > visible_lines:
        thumb_y = scrollbar_y + (code_scroll_offset / (total_lines - visible_lines)) * (scrollbar_height - thumb_height)
    else:
        thumb_y = scrollbar_y
    
    pygame.draw.rect(screen, (120, 120, 120), 
                    (scrollbar_x, thumb_y, scrollbar_width, thumb_height))

def close_code_window():
    """关闭代码查看模式"""
    global code_window_visible, code_scroll_offset
    
    try:
        if code_window_visible:
            code_window_visible = False
            code_scroll_offset = 0  # 重置滚动位置
            logger.info("🎨 代码查看模式已关闭")
            show_notification("🎨 代码查看模式已关闭", 1.5)
    except Exception as e:
        logger.error(f"关闭代码查看模式失败: {e}")

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
            global current_code
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

async def process_openai():
    """Process transcription and screenshot."""
    global current_transcript
    try:
        image = capture_screen()
        await send_to_openai(image, current_transcript)
    except Exception as e:
        logger.error(f"OpenAI processing error: {e}")
        text_queue.put(f"Processing error: {str(e)}")

def on_transcript_updated(transcript: str):
    """Callback function for when audio transcript is updated."""
    global current_transcript
    current_transcript = transcript
    set_app_state("listening")
    show_notification(f"🎤 Heard: {transcript[:30]}{'...' if len(transcript) > 30 else ''}", 2.0)

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

last_keep_on_top_log = 0

def keep_on_top():
    """Ensure the window stays on top and maintains transparency."""
    global last_keep_on_top_log
    try:
        if hwnd:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            # Ensure transparency is maintained
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, window_opacity, 2)
            # Only log once every 5 seconds to avoid spam
            current_time = time.time()
            if current_time - last_keep_on_top_log > 5:
                logger.debug("Reasserted HWND_TOPMOST with transparency")
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
        # Apple-style layered window with tool window behavior
        ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW
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
        show_notification("🍎 GhostMentor Ultra 准备就绪", 2.0)
        
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
    menu_height = 410  # Increased height for more shortcuts
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
    title_text = title_font.render("🎮 键盘快捷键", True, (255, 255, 255))
    title_rect = title_text.get_rect(center=(menu_width // 2, 30))
    help_surface.blit(title_text, title_rect)
    
    # Shortcuts data
    shortcuts = [
        ("截取屏幕", "Ctrl", "H"),
        ("AI分析", "Ctrl", "Enter"),
        ("清除历史", "Ctrl", "G"),
        ("切换显示/隐藏", "Ctrl", "B"),
        ("代码窗口", "Ctrl", "C"),
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
    footer_text = font.render("🥷 GhostMentor Ultra Stealth Edition", True, (130, 150, 170))
    footer_rect = footer_text.get_rect(center=(menu_width // 2, footer_y))
    help_surface.blit(footer_text, footer_rect)
    
    # Version info
    version_text = font.render("v2.0 - OpenAI Powered", True, (100, 120, 140))
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
            
            # Debug: Log all Ctrl key combinations to help with troubleshooting
            if keyboard.is_pressed('ctrl'):
                logger.debug(f"🔧 DEBUG: Ctrl + '{event.name}' detected")
            
            # Check for our specific key combinations and block them
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
                    logger.info("🥷 HIGH PRIORITY: Ctrl + G pressed (Clear History)")
                    global current_transcript
                    current_transcript = ""
                    api_manager.clear_history()
                    text_queue.put("Ready...")
                    show_notification("🧹 History cleared", 2.0)
                    return False  # Block browser find shortcut
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
            
            elif keyboard.is_pressed('alt') and event.name == 'f4':
                logger.info("🥷 HIGH PRIORITY: Alt + F4 pressed (Exit GhostMentor)")
                global running
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
                logger.info("🧹 Fallback: Ctrl + G pressed (Clear History)")
                global current_transcript
                current_transcript = ""
                api_manager.clear_history()
                text_queue.put("Ready...")
                show_notification("🧹 History cleared", 2.0)

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

            keyboard.add_hotkey('ctrl+h', on_ctrl_h)
            keyboard.add_hotkey('ctrl+enter', on_ctrl_enter)
            keyboard.add_hotkey('ctrl+g', on_ctrl_g)
            keyboard.add_hotkey('ctrl+b', on_ctrl_b)
            keyboard.add_hotkey('ctrl+c', on_ctrl_c)
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
        
        # Initialize audio manager if speech is enabled
        audio_mgr = None
        if use_speech:
            try:
                audio_mgr = initialize_audio_manager(use_speech=True)
                audio_mgr.set_transcript_callback(on_transcript_updated)
                audio_mgr.start_recording()
                logger.info("🎤 音频管理器已初始化，录音已开始")
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
        dragging = False
        offset = (0, 0)
        clock = pygame.time.Clock()
        running = True
        
        logger.info("🎮 进入主游戏循环...")
        
        while running:
            try:
                # Handle pygame events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        logger.info("❌ 检测到窗口关闭事件")
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 1:
                            mouse_x, mouse_y = event.pos
                            window_width = window_settings['width']
                            window_height = window_settings['height']
                            if 0 <= mouse_x <= window_width and 0 <= mouse_y <= window_height:
                                dragging = True
                                offset = (mouse_x, mouse_y)
                                logger.debug("👆 Started dragging HUD")
                    elif event.type == pygame.MOUSEBUTTONUP:
                        if event.button == 1:
                            dragging = False
                            logger.debug("✋ Stopped dragging HUD")
                    elif event.type == pygame.MOUSEMOTION and dragging:
                        mouse_x, mouse_y = event.pos
                        current_x, current_y = map(int, os.environ.get('SDL_VIDEO_WINDOW_POS', f'{window_x},{window_y}').split(','))
                        new_x = current_x + (mouse_x - offset[0])
                        new_y = current_y + (mouse_y - offset[1])
                        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{new_x},{new_y}"
                        
                        window_width = window_settings['width']
                        window_height = window_settings['height']
                        pygame.display.set_mode((window_width, window_height), pygame.NOFRAME | pygame.SRCALPHA)
                        logger.debug(f"🎯 Dragged HUD to ({new_x}, {new_y})")
                    elif event.type == pygame.KEYDOWN:
                        # 处理键盘事件
                        if code_window_visible:
                            # 代码查看模式下的键盘控制
                            if event.key == pygame.K_ESCAPE:
                                close_code_window()
                            elif event.key == pygame.K_UP:
                                # 向上滚动
                                code_scroll_offset = max(0, code_scroll_offset - 1)
                            elif event.key == pygame.K_DOWN:
                                # 向下滚动
                                if current_highlighted_code:
                                    visible_lines = (screen.get_height() - 60) // 16
                                    max_scroll = max(0, len(current_highlighted_code) - visible_lines)
                                    code_scroll_offset = min(max_scroll, code_scroll_offset + 1)
                            elif event.key == pygame.K_PAGEUP:
                                # 向上翻页
                                visible_lines = (screen.get_height() - 60) // 16
                                code_scroll_offset = max(0, code_scroll_offset - visible_lines)
                            elif event.key == pygame.K_PAGEDOWN:
                                # 向下翻页
                                if current_highlighted_code:
                                    visible_lines = (screen.get_height() - 60) // 16
                                    max_scroll = max(0, len(current_highlighted_code) - visible_lines)
                                    code_scroll_offset = min(max_scroll, code_scroll_offset + visible_lines)
                            elif event.key == pygame.K_HOME:
                                # 跳到开头
                                code_scroll_offset = 0
                            elif event.key == pygame.K_END:
                                # 跳到结尾
                                if current_highlighted_code:
                                    visible_lines = (screen.get_height() - 60) // 16
                                    code_scroll_offset = max(0, len(current_highlighted_code) - visible_lines)
                    elif event.type == pygame.MOUSEWHEEL:
                        # 优先处理代码窗口滚动
                        if code_window_visible:
                            handle_pygame_code_window_events(event)
                        else:
                            # 主窗口滚动
                            mouse_x, mouse_y = pygame.mouse.get_pos()
                            window_width = window_settings['width']
                            window_height = window_settings['height']
                            if 0 <= mouse_x <= window_width and 0 <= mouse_y <= window_height:
                                scroll_offset -= event.y  # Scroll up: +1, down: -1
                                wrapped_lines = wrap_text(overlay_text, window_width - 20, font)
                                max_lines = ui_settings['max_visible_lines']
                                scroll_offset = max(0, min(scroll_offset, len(wrapped_lines) - max_lines))
                                logger.debug(f"📜 Scrolled HUD, offset={scroll_offset}")

                # Update overlay text
                update_overlay()
                keep_on_top()
                
                # Render based on current mode
                if code_window_visible:
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
