import os
import tempfile
import asyncio
from datetime import datetime
from io import BytesIO
from typing import Optional, Dict, Any

from celery import Celery
from PyPDF2 import PdfReader
import docx
import requests
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncTask, AsyncSessionLocal, InterpretationHistory

# Celery配置
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
celery_app = Celery(
    "ansapra_tasks",
    broker=redis_url,
    backend=redis_url
)

# API配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
SPRINGER_API_KEY = os.getenv("SPRINGER_API_KEY")

@celery_app.task(bind=True, name="process_paper_task", max_retries=3, default_retry_delay=30)
def process_paper_task(self, task_id: str, user_id: str, file_path: Optional[str] = None, text: Optional[str] = None):
    """处理论文解读的Celery任务"""
    try:
        # 更新任务状态为处理中
        update_task_status(task_id, "processing")
        
        # 提取文本内容
        content = extract_content(file_path, text)
        
        if not content:
            update_task_status(task_id, "failed", error="无法提取文本内容")
            return None
        
        # 调用DeepSeek API
        interpretation = call_deepseek_api(content)
        
        # 搜索相关论文
        recommendations = search_related_papers(content)
        
        # 构建结果
        result = {
            "interpretation": interpretation,
            "original_content": content[:2000] + "..." if len(content) > 2000 else content,
            "recommendations": recommendations,
            "processed_at": datetime.utcnow().isoformat(),
            "content_length": len(content)
        }
        
        # 更新任务状态为完成
        update_task_status(task_id, "completed", result=result)
        
        # 保存到历史记录（异步）
        save_to_history.delay(user_id, task_id, result)
        
        return result
        
    except Exception as e:
        # 更新任务状态为失败
        update_task_status(task_id, "failed", error=str(e))
        
        # 重试机制
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return None

@celery_app.task(name="search_related_papers_task")
def search_related_papers_task(query: str, count: int = 5):
    """搜索相关论文任务"""
    try:
        if not SPRINGER_API_KEY:
            return []
        
        params = {
            'q': query,
            'api_key': SPRINGER_API_KEY,
            'p': count,
            's': 1
        }
        
        response = requests.get(
            "https://api.springernature.com/meta/v2/json",
            params=params,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        papers = []
        if 'records' in data:
            for record in data['records'][:count]:
                paper = {
                    'title': record.get('title', ''),
                    'authors': ', '.join([creator.get('creator', '') for creator in record.get('creators', [])]),
                    'publication': record.get('publicationName', ''),
                    'year': record.get('publicationDate', '')[:4] if record.get('publicationDate') else '',
                    'url': record.get('url', [{}])[0].get('value', '') if record.get('url') else '',
                    'abstract': record.get('abstract', '')[:200] + '...' if record.get('abstract') else ''
                }
                papers.append(paper)
        
        return papers
        
    except Exception as e:
        print(f"搜索论文失败: {e}")
        return []

@celery_app.task(name="save_to_history")
def save_to_history(user_id: str, task_id: str, result: Dict[str, Any]):
    """保存到历史记录任务"""
    try:
        async def async_save():
            async with AsyncSessionLocal() as session:
                await InterpretationHistory.create_from_result(
                    session,
                    user_id=user_id,
                    task_id=task_id,
                    result=result
                )
        
        # 运行异步函数
        asyncio.run(async_save())
        
    except Exception as e:
        print(f"保存历史记录失败: {e}")

def extract_content(file_path: Optional[str], text: Optional[str]) -> str:
    """提取文本内容"""
    if text:
        return text[:10000]  # 限制长度
    
    if not file_path or not os.path.exists(file_path):
        return ""
    
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        
        # 尝试PDF
        try:
            pdf_reader = PdfReader(BytesIO(file_bytes))
            content = ""
            for page_num, page in enumerate(pdf_reader.pages[:5]):  # 最多5页
                page_text = page.extract_text()
                if page_text:
                    content += f"第{page_num+1}页:\n{page_text}\n\n"
            if content:
                return content
        except:
            pass
        
        # 尝试DOCX
        try:
            doc = docx.Document(BytesIO(file_bytes))
            content = ""
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    content += paragraph.text + "\n"
            if content:
                return content
        except:
            pass
        
        # 尝试文本文件
        try:
            for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                try:
                    return file_bytes.decode(encoding, errors='ignore')
                except:
                    continue
        except:
            pass
        
        return "无法提取文本内容，文件可能是扫描件或包含图像文字。"
        
    finally:
        # 清理临时文件
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

def call_deepseek_api(content: str) -> str:
    """调用DeepSeek API"""
    if not DEEPSEEK_API_KEY:
        return "API密钥未配置"
    
    # 限制内容长度
    content = content[:5000] + "\n[注：内容过长，已截断]" if len(content) > 5000 else content
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    system_prompt = "你是一位专业的自然科学论文解读助手，专门帮助高中生理解学术论文。请用通俗易懂的语言解读。"
    
    user_prompt = f"""请解读以下自然科学论文内容（用中文回答）：
    
{content}

要求：
1. 用通俗易懂的语言解释专业术语
2. 分析研究方法和实验设计
3. 总结主要发现和意义
4. 联系高中自然科学知识
5. 在解读最后附上"术语解读区"

请在末尾添加："解读内容由DeepSeek AI生成，仅供参考" """
    
    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        'temperature': 0.7,
        'max_tokens': 2000,
        'stream': False
    }
    
    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            json=payload,
            headers=headers,
            timeout=60  # 60秒超时
        )
        response.raise_for_status()
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            return result['choices'][0]['message']['content']
        else:
            return "未能获取解读结果"
            
    except Exception as e:
        return f"API调用失败: {str(e)}"

def search_related_papers(content: str) -> list:
    """搜索相关论文"""
    if not SPRINGER_API_KEY or not content:
        return []
    
    # 提取关键词
    words = content.split()[:3]
    query = ' '.join(words) if words else "natural science"
    
    # 调用Celery子任务
    result = search_related_papers_task.apply_async(args=[query, 3])
    
    try:
        return result.get(timeout=10)
    except:
        return []

def update_task_status(task_id: str, status: str, result: Optional[Dict] = None, error: Optional[str] = None):
    """更新任务状态"""
    try:
        async def async_update():
            async with AsyncSessionLocal() as session:
                task = await AsyncTask.get_by_id(session, task_id)
                if task:
                    await task.update_status(session, status, result, error)
        
        asyncio.run(async_update())
        
    except Exception as e:
        print(f"更新任务状态失败: {e}")
