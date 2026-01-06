import os
import aiofiles
import tempfile
from fastapi import UploadFile
from typing import Optional

async def save_upload_file(upload_file: UploadFile) -> str:
    """保存上传的文件到临时位置"""
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, upload_file.filename)
    
    async with aiofiles.open(file_path, 'wb') as f:
        content = await upload_file.read()
        await f.write(content)
    
    return file_path

def extract_text_from_pdf(file_path: str) -> str:
    """从PDF提取文本"""
    try:
        from PyPDF2 import PdfReader
        with open(file_path, 'rb') as f:
            pdf_reader = PdfReader(f)
            text = ""
            for page in pdf_reader.pages[:10]:  # 最多10页
                text += page.extract_text() + "\n\n"
            return text
    except Exception as e:
        return f"PDF解析失败: {str(e)}"

def extract_text_from_docx(file_path: str) -> str:
    """从DOCX提取文本"""
    try:
        import docx
        doc = docx.Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text += paragraph.text + "\n"
        return text
    except Exception as e:
        return f"DOCX解析失败: {str(e)}"
