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

            keyboard.add_hotkey('ctrl+h', on_ctrl_h)
            keyboard.add_hotkey('ctrl+enter', on_ctrl_enter)
            keyboard.add_hotkey('ctrl+g', on_ctrl_g)
            keyboard.add_hotkey('ctrl+b', on_ctrl_b)
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
                    elif event.type == pygame.MOUSEWHEEL:
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

                # Draw help menu overlay if enabled
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
