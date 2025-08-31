#!/usr/bin/env python3
"""
GhostMentor API Manager
处理OpenAI API相关功能
"""

import asyncio
import base64
import io
import numpy as np
import cv2
import openai
from PIL import Image
from typing import Optional, List, Tuple, AsyncGenerator
from config_manager import config
from logger_manager import get_logger

logger = get_logger(__name__)

class APIManager:
    """OpenAI API管理器"""
    
    def __init__(self):
        self.client = None
        self.model = config.get('openai_model', 'gpt-4o')
        self.conversation_history: List[Tuple[str, str]] = []
        self.setup_client()
    
    def setup_client(self):
        """初始化OpenAI客户端"""
        try:
            api_key = config.get('openai_api_key')
            if not api_key:
                raise ValueError("OpenAI API key not found")
            
            self.client = openai.OpenAI(api_key=api_key)
            logger.info(f"🤖 OpenAI client initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise
    
    def image_to_base64(self, image: Image.Image) -> str:
        """将PIL图像转换为base64编码"""
        try:
            # 转换为numpy数组
            img_array = np.array(image)
            # 转换颜色空间（PIL使用RGB，OpenCV使用BGR）
            img_rgb = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            # 编码为PNG
            _, buffer = cv2.imencode('.png', img_rgb)
            # 转换为base64
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            logger.debug(f"Image converted to base64, size: {len(img_base64)} chars")
            return img_base64
        except Exception as e:
            logger.error(f"Error converting image to base64: {e}")
            raise
    
    def create_analysis_prompt(self, user_text: str = "") -> str:
        """创建分析提示词"""
        if user_text.strip():
            prompt = f"""请分析屏幕上的题目，按以下格式输出：

【解题思路】
1. 问题分析 - 理解题目要求和约束条件
2. 核心思路 - 选择最优算法或解决方案
3. 算法步骤 - 具体实现步骤

【复杂度分析】
• 时间复杂度：O(?)
• 空间复杂度：O(?)

【代码实现】
```python
# 提供完整的代码解决方案
def solution():
    pass
```

【关键点提示】
• 重要的实现细节
• 易错点提醒
• 优化建议

用户问题: {user_text}"""
        else:
            prompt = """请分析屏幕上的题目，按以下格式输出：

【解题思路】
1. 问题分析 - 理解题目要求和约束条件
2. 核心思路 - 选择最优算法或解决方案  
3. 算法步骤 - 具体实现步骤

【复杂度分析】
• 时间复杂度：O(?)
• 空间复杂度：O(?)

【代码实现】
```python
# 提供完整的代码解决方案
def solution():
    pass
```

【关键点提示】
• 重要的实现细节
• 易错点提醒
• 优化建议"""
        
        return prompt
    
    async def analyze_screen(self, image: Image.Image, user_text: str = "") -> Optional[str]:
        """分析屏幕图像并返回AI响应"""
        if not self.client:
            logger.error("OpenAI client not initialized")
            return None
        
        try:
            # 转换图像为base64
            img_base64 = self.image_to_base64(image)
            
            # 创建提示词
            prompt = self.create_analysis_prompt(user_text)
            
            logger.info(f"🧠 Sending analysis request to OpenAI...")
            logger.debug(f"Prompt preview: {prompt[:100]}...")
            
            # 准备消息
            messages = [
                {
                    "role": "system",
                    "content": "You are an expert coding assistant specialized in problem analysis and solution guidance. Provide clear, structured responses in Chinese."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_base64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ]
            
            # 发送请求
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=1000,
                stream=True,
                temperature=0.3  # 降低随机性，提高准确性
            )
            
            # 收集流式响应
            full_response = ""
            async for chunk in self._process_stream_response(response):
                full_response += chunk
            
            if full_response.strip():
                # 存储到对话历史
                self.conversation_history.append((user_text or "[Screen Analysis]", full_response))
                logger.info(f"✅ Received response from OpenAI ({len(full_response)} chars)")
                return full_response
            else:
                logger.warning("Empty response from OpenAI")
                return None
                
        except Exception as e:
            logger.error(f"Error in screen analysis: {e}")
            return f"分析出错: {str(e)}"
    
    async def _process_stream_response(self, response) -> AsyncGenerator[str, None]:
        """处理流式响应"""
        try:
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield content
        except Exception as e:
            logger.error(f"Error processing stream response: {e}")
            yield f"响应处理出错: {str(e)}"
    
    def get_conversation_history(self) -> str:
        """获取格式化的对话历史"""
        if not self.conversation_history:
            return "Ready..."
        
        history_text = "\n---\n".join(
            f"Q: {q if q.strip() else '[No question]'}\nA: {a}" 
            for q, a in self.conversation_history
        )
        return history_text
    
    def clear_history(self):
        """清除对话历史"""
        self.conversation_history.clear()
        logger.info("🧹 Conversation history cleared")
    
    def get_history_count(self) -> int:
        """获取对话历史数量"""
        return len(self.conversation_history)
    
    def export_history(self, filename: str = None) -> str:
        """导出对话历史到文件"""
        if not filename:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ghostmentor_history_{timestamp}.txt"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("GhostMentor Conversation History\n")
                f.write("=" * 50 + "\n\n")
                
                for i, (question, answer) in enumerate(self.conversation_history, 1):
                    f.write(f"Session {i}\n")
                    f.write("-" * 20 + "\n")
                    f.write(f"Question: {question}\n\n")
                    f.write(f"Answer:\n{answer}\n\n")
                    f.write("=" * 50 + "\n\n")
            
            logger.info(f"📄 History exported to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Failed to export history: {e}")
            return None

# 全局API管理器实例
api_manager = APIManager()

