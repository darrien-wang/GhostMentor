#!/usr/bin/env python3
"""
GhostMentor Audio Manager
处理音频录制和语音识别功能
"""

import numpy as np
import threading
import time
from typing import Optional, Callable
from queue import Queue
from config_manager import config
from logger_manager import get_logger

logger = get_logger(__name__)

class AudioManager:
    """音频管理器"""
    
    def __init__(self, use_speech: bool = True):
        self.use_speech = use_speech
        self.audio = None
        self.stream = None
        self.whisper_model = None
        self.audio_buffer = []
        self.current_transcript = ""
        self.is_recording = False
        self.transcription_thread = None
        self.transcript_callback: Optional[Callable[[str], None]] = None
        
        if self.use_speech:
            self.setup_audio()
    
    def setup_audio(self):
        """初始化音频系统"""
        if not self.use_speech:
            logger.info("🔇 Audio disabled - running in silent mode")
            return
        
        try:
            # 动态导入音频相关库
            import pyaudio
            from faster_whisper import WhisperModel
            
            # 获取音频配置
            audio_settings = config.get_audio_settings()
            
            # 初始化Whisper模型
            model_size = audio_settings['whisper_model']
            logger.info(f"🧠 Loading Whisper model: {model_size}")
            self.whisper_model = WhisperModel(
                model_size, 
                device="cpu", 
                compute_type="int8"
            )
            logger.info(f"✅ Whisper model '{model_size}' loaded successfully")
            
            # 初始化PyAudio
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=audio_settings['sampling_rate'],
                input=True,
                frames_per_buffer=audio_settings['chunk_size']
            )
            
            logger.info(f"🎤 Audio stream initialized:")
            logger.info(f"   Sample rate: {audio_settings['sampling_rate']} Hz")
            logger.info(f"   Chunk size: {audio_settings['chunk_size']}")
            logger.info(f"   Buffer duration: {audio_settings['buffer_duration']}s")
            
        except ImportError as e:
            logger.error(f"Audio libraries not available: {e}")
            self.use_speech = False
        except Exception as e:
            logger.error(f"Audio setup error: {e}")
            self.use_speech = False
            raise
    
    def set_transcript_callback(self, callback: Callable[[str], None]):
        """设置转录结果回调函数"""
        self.transcript_callback = callback
    
    def start_recording(self):
        """开始录音和转录"""
        if not self.use_speech or self.is_recording:
            return
        
        try:
            self.is_recording = True
            self.stream.start_stream()
            
            # 启动转录线程
            self.transcription_thread = threading.Thread(
                target=self._transcription_worker,
                daemon=True
            )
            self.transcription_thread.start()
            
            logger.info("🎤 Audio recording started")
            
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self.is_recording = False
    
    def stop_recording(self):
        """停止录音"""
        if not self.use_speech or not self.is_recording:
            return
        
        try:
            self.is_recording = False
            
            if self.stream and self.stream.is_active():
                self.stream.stop_stream()
            
            logger.info("🔇 Audio recording stopped")
            
        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
    
    def _transcription_worker(self):
        """转录工作线程"""
        if not self.use_speech or not self.whisper_model:
            return
        
        audio_settings = config.get_audio_settings()
        sampling_rate = audio_settings['sampling_rate']
        chunk_size = audio_settings['chunk_size']
        buffer_duration = audio_settings['buffer_duration']
        buffer_frames = sampling_rate * buffer_duration
        
        logger.info("🎯 Transcription worker started")
        
        try:
            while self.is_recording:
                try:
                    # 读取音频数据
                    data = self.stream.read(chunk_size, exception_on_overflow=False)
                    audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    self.audio_buffer.append(audio_np)
                    
                    # 当缓冲区达到指定时长时进行转录
                    total_frames = len(self.audio_buffer) * chunk_size
                    if total_frames >= buffer_frames:
                        self._process_audio_buffer(sampling_rate)
                        
                except Exception as e:
                    logger.error(f"Transcription error: {e}")
                    time.sleep(0.1)  # 短暂休息后继续
                    
        except Exception as e:
            logger.error(f"Transcription worker error: {e}")
        finally:
            logger.info("🏁 Transcription worker stopped")
    
    def _process_audio_buffer(self, sampling_rate: int):
        """处理音频缓冲区"""
        if not self.audio_buffer:
            return
        
        try:
            # 合并音频数据
            full_audio = np.concatenate(self.audio_buffer)
            self.audio_buffer = []  # 清空缓冲区
            
            duration = len(full_audio) / sampling_rate
            logger.debug(f"🎵 Processing audio buffer: {duration:.2f}s")
            
            # 使用Whisper进行转录
            segments, info = self.whisper_model.transcribe(
                full_audio, 
                beam_size=5,
                language='en',  # 可以设为None让模型自动检测
                condition_on_previous_text=False  # 避免重复
            )
            
            # 合并转录结果
            text = " ".join(segment.text for segment in segments).strip()
            
            if text and len(text) > 2:  # 过滤太短的转录结果
                confidence = info.language_probability
                logger.info(f"🎯 Transcribed: '{text}' (confidence: {confidence:.2f})")
                
                self.current_transcript = text
                
                # 调用回调函数
                if self.transcript_callback:
                    self.transcript_callback(text)
            else:
                logger.debug("🔇 No meaningful transcription")
                
        except Exception as e:
            logger.error(f"Audio buffer processing error: {e}")
    
    def get_current_transcript(self) -> str:
        """获取当前转录文本"""
        return self.current_transcript
    
    def clear_transcript(self):
        """清除当前转录文本"""
        self.current_transcript = ""
        logger.debug("🧹 Transcript cleared")
    
    def cleanup(self):
        """清理音频资源"""
        try:
            self.stop_recording()
            
            if self.stream:
                self.stream.close()
                self.stream = None
            
            if self.audio:
                self.audio.terminate()
                self.audio = None
            
            logger.info("🧹 Audio resources cleaned up")
            
        except Exception as e:
            logger.error(f"Error cleaning up audio resources: {e}")
    
    def is_available(self) -> bool:
        """检查音频功能是否可用"""
        return self.use_speech and self.whisper_model is not None
    
    def get_status(self) -> dict:
        """获取音频状态信息"""
        return {
            "enabled": self.use_speech,
            "available": self.is_available(),
            "recording": self.is_recording,
            "transcript": self.current_transcript,
            "buffer_size": len(self.audio_buffer)
        }

# 全局音频管理器实例（在main中初始化）
audio_manager: Optional[AudioManager] = None

def initialize_audio_manager(use_speech: bool = True) -> AudioManager:
    """初始化全局音频管理器"""
    global audio_manager
    audio_manager = AudioManager(use_speech)
    return audio_manager

def get_audio_manager() -> Optional[AudioManager]:
    """获取音频管理器实例"""
    return audio_manager

