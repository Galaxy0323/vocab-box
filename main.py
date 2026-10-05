# 标准库
import os, re, difflib
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

# 读取 .env 里的敏感配置（密码不放代码、不进 Git）
from dotenv import load_dotenv
load_dotenv()

# 第三方
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, Text,Integer, Float, DateTime, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

ASYNC_ENGINE = os.getenv("DATABASE_URL")
async_engine = create_async_engine(ASYNC_ENGINE, pool_size=10, max_overflow=20)

class Base(DeclarativeBase):
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    update_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

class Word(Base):
    __tablename__ = "word"
    id : Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word : Mapped[str] = mapped_column(String(50), unique=True)
    phonetic : Mapped[Optional[str]] = mapped_column(String(50))
    
class DictBase(DeclarativeBase):
    pass

class Dict(DictBase):
    __tablename__ = "dict"
    id : Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word : Mapped[str] = mapped_column(String(50))
    phonetic : Mapped[Optional[str]] = mapped_column(String(50))
    pos : Mapped[str] = mapped_column(String(50))
    translation : Mapped[str] = mapped_column(Text)
    definition : Mapped[str] = mapped_column(Text)
    frq : Mapped[Optional[float]] = mapped_column(Float)   

class WordCreate(BaseModel):
    word : str
   


class WordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id : int
    word : str
    phonetic : Optional[str] = None
 
class DictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id : int
    word : Optional[str] = None
    phonetic :  Optional[str] = None
    translation :  Optional[str] = None
    definition :  Optional[str] = None

async def create_table():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# 用 lifespan 替代 on_event
@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_table()   # 启动时建表
    yield                   # 应用运行期间（这里不做关闭清理）


from fastapi_cdn_host import patch_docs

app = FastAPI(lifespan=lifespan)
patch_docs(app)   


class Input(BaseModel):
    text: str

@app.post("/word/clean/")
async def words_clean(payload: Input):
    raw = re.findall(r"[A-Za-z][A-Za-z'-]*", payload.text)
    seen = set()
    result = []
    for w in raw:
        word = w.lower()
        if word not in seen:
            seen.add(word)
            result.append(word)
    return result

AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

async def get_database():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()   
        except Exception:
            await session.rollback()
            raise

@app.post("/word/save/", response_model=WordOut)
async def add_word(new_word: WordCreate, db: AsyncSession = Depends(get_database)):
    word = Word(**new_word.model_dump())
    db.add(word)
    await db.flush()
    await db.refresh(word)
    return word

@app.get("/word/all_words/", response_model=list[WordOut])
async def get_all(db: AsyncSession = Depends(get_database)):
    res = await db.execute(select(Word).order_by(Word.create_time.desc()))
    words = res.scalars().all()
    if not words:
        raise HTTPException(status_code=404, detail="未找到单词本")
    return words


@app.get("/word/look_up_by_En/", response_model=list[DictOut])
async def look_up_by_En(look_up_English : str,db: AsyncSession = Depends(get_database)):
    res = await db.execute(select(Dict).where(Dict.word == look_up_English))
    return res.scalars().all()



@app.get("/word/look_up_by_Ch/", response_model=list[DictOut])
async def look_up_by_Ch(look_up_Chinese : str,db: AsyncSession = Depends(get_database)):
    res = await db.execute(select(Dict).where(Dict.translation.contains(look_up_Chinese)).order_by(Dict.word.like('% %'),Dict.frq.is_(None),Dict.frq == 0,Dict.frq).limit(10))
    return res.scalars().all()


@app.delete("/word/delete/{needless_id}")
async def delete_word(needless_id : int , db: AsyncSession = Depends(get_database)):
    needless_word = await db.get(Word,needless_id)
    if needless_word is None:
        raise HTTPException(status_code=404,detail="单词表中无该单词")
    await db.delete(needless_word)
    return {"msg":f"已删除{needless_word.word}"}

@app.get("/word/difflib_look_up/", response_model=list[DictOut])
async def difflib_look_up(fragment : str , db: AsyncSession = Depends(get_database)):
    stmt1 = select(Dict).where(Dict.word.startswith(fragment)).order_by(Dict.word.like('% %'),Dict.frq.is_(None),Dict.frq == 0,Dict.frq).limit(10)
    res = (await db.execute(stmt1)).scalars().all()
    
    if not res:
        stmt2 = select(Dict).where(func.soundex(Dict.word ) == func.soundex(fragment)).limit(200) 
        candidates = (await db.execute(stmt2)).scalars().all()
        rows = sorted(candidates,
        key = lambda d : difflib.SequenceMatcher(None,fragment,d.word).ratio(),
        reverse = True)[:10]
        return rows
        
    return res