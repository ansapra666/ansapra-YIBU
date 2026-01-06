import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, DateTime, Boolean, Text, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.future import select
from passlib.context import CryptContext

Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 异步数据库引擎
DATABASE_URL = "sqlite+aiosqlite:///./ansapra.db"  # 使用SQLite，可替换为PostgreSQL
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_guest = Column(Boolean, default=False)
    settings = Column(JSON, default=lambda: {})
    questionnaire = Column(JSON, default=lambda: {})
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    @classmethod
    async def create(cls, db: AsyncSession, email: str, username: str, password: str, is_guest: bool = False):
        user = cls(
            email=email,
            username=username,
            password_hash=pwd_context.hash(password),
            is_guest=is_guest,
            settings={
                'reading': {
                    'preparation': 'B',
                    'purpose': 'B',
                    'time': 'B',
                    'style': 'C',
                    'depth': 'B',
                    'test_type': 'B',
                    'chart_types': ['A']
                },
                'visual': {
                    'theme': 'B',
                    'font_size': '18',
                    'font_family': 'Microsoft YaHei',
                    'custom_background': None
                },
                'language': 'zh'
            }
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
    
    @classmethod
    async def get_by_email(cls, db: AsyncSession, email: str) -> Optional['User']:
        result = await db.execute(
            select(cls).where(cls.email == email)
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_by_id(cls, db: AsyncSession, user_id: str) -> Optional['User']:
        result = await db.execute(
            select(cls).where(cls.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def save(self, db: AsyncSession):
        await db.commit()
        await db.refresh(self)

class AsyncTask(Base):
    __tablename__ = "async_tasks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(100), unique=True, nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    task_type = Column(String(50), nullable=False)  # "interpretation", "search", etc.
    status = Column(String(20), nullable=False, default="pending")  # pending, processing, completed, failed
    input_data = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", backref="tasks")
    
    @classmethod
    async def create(cls, db: AsyncSession, **kwargs):
        task = cls(**kwargs)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task
    
    @classmethod
    async def get_by_id(cls, db: AsyncSession, task_id: str) -> Optional['AsyncTask']:
        result = await db.execute(
            select(cls).where(cls.task_id == task_id)
        )
        return result.scalar_one_or_none()
    
    async def update_status(self, db: AsyncSession, status: str, result: Optional[Dict] = None, error: Optional[str] = None):
        self.status = status
        self.updated_at = datetime.utcnow()
        if result is not None:
            self.result = result
        if error is not None:
            self.error = error
        await db.commit()

class InterpretationHistory(Base):
    __tablename__ = "interpretation_history"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String(100), nullable=True, index=True)
    content_preview = Column(Text, nullable=True)
    interpretation_preview = Column(Text, nullable=True)
    full_content = Column(Text, nullable=True)
    full_interpretation = Column(Text, nullable=True)
    recommendations = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="interpretation_history")
    
    @classmethod
    async def create_from_result(cls, db: AsyncSession, user_id: str, task_id: str, result: Dict[str, Any]):
        history = cls(
            user_id=user_id,
            task_id=task_id,
            content_preview=result.get("original_content", "")[:500],
            interpretation_preview=result.get("interpretation", "")[:500],
            full_content=result.get("original_content"),
            full_interpretation=result.get("interpretation"),
            recommendations=result.get("recommendations", [])
        )
        db.add(history)
        await db.commit()
        return history
    
    @classmethod
    async def get_by_user(cls, db: AsyncSession, user_id: str, limit: int = 20, offset: int = 0):
        result = await db.execute(
            select(cls)
            .where(cls.user_id == user_id)
            .order_by(cls.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

# 依赖注入
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# 初始化数据库
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
