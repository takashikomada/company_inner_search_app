# initialize.py
"""
RAGの初期化：データ読み込み→分割→ベクタDB作成→retriever格納
Chroma失敗や文書0件でもBM25に自動フォールバックして必ず動く
"""

from __future__ import annotations
import os
import logging
from pathlib import Path
from typing import List

import streamlit as st
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_text_splitters import CharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_community.document_loaders import TextLoader, PyMuPDFLoader, Docx2txtLoader
from langchain_community.document_loaders.csv_loader import CSVLoader

import constants as ct

load_dotenv()
logger = logging.getLogger(ct.LOGGER_NAME)

# ─────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────
SUPPORTED = {
    ".txt":  lambda p: TextLoader(p, encoding="utf-8", autodetect_encoding=True),
    ".pdf":  PyMuPDFLoader,
    ".docx": Docx2txtLoader,
    ".csv":  lambda p: CSVLoader(p, encoding="utf-8"),
}

def _safe_load_file(path: str) -> List[Document]:
    ext = os.path.splitext(path)[1].lower()
    loader_fn = SUPPORTED.get(ext)
    if not loader_fn:
        return []
    try:
        loader = loader_fn(path) if callable(loader_fn) else loader_fn(path)  # type: ignore
        return loader.load()
    except Exception as e:
        logger.warning(f"load failed: {path} ({type(e).__name__}: {e})")
        return []

def _walk_and_load(topdir: str) -> List[Document]:
    docs: List[Document] = []
    for root, _, files in os.walk(topdir):
        for f in files:
            p = os.path.join(root, f)
            docs.extend(_safe_load_file(p))
    return docs

def _split_docs(docs: List[Document]) -> List[Document]:
    if not docs:
        return []
    splitter = CharacterTextSplitter(
        chunk_size=getattr(ct, "CHUNK_SIZE", 500),
        chunk_overlap=getattr(ct, "CHUNK_OVERLAP", 50),
        separator="\n"
    )
    return splitter.split_documents(docs)

# ─────────────────────────────────────────────────────────────
# メイン初期化
# ─────────────────────────────────────────────────────────────
def initialize() -> None:
    """Retrievers を session_state に必ずセットする"""
    st.session_state.setdefault("retriever", None)
    st.session_state.setdefault("bm25_retriever", None)

    top = Path(getattr(ct, "RAG_TOP_FOLDER_PATH", "./data")).resolve()
    chroma_dir = Path(getattr(ct, "CHROMA_DIR", "./chroma_store")).resolve()
    chroma_dir.mkdir(parents=True, exist_ok=True)
    Path(getattr(ct, "LOG_DIR_PATH", "./logs")).mkdir(parents=True, exist_ok=True)

    logger.info(f"RAG init start: top={top}")

    # 1) ドキュメント読み込み
    docs = _walk_and_load(str(top))
    if not docs:
        logger.warning("no documents loaded; will rely on BM25 fallback")
    else:
        logger.info(f"documents loaded: {len(docs)}")

    # 2) 分割
    chunks = _split_docs(docs)
    logger.info(f"split into chunks: {len(chunks)}")

    # 3) ベクタDB（Chroma）作成 or ロード
    retriever = None
    try:
        embeddings = OpenAIEmbeddings()  # APIキーは.envから
        if len(list(chroma_dir.glob("*"))) == 0 and chunks:
            # まだ永続化がない → 新規作成
            vectordb = Chroma.from_documents(
                documents=chunks,
                embedding=embeddings,
                persist_directory=str(chroma_dir),
            )
            vectordb.persist()
            logger.info("chroma built & persisted")
        else:
            # 既存をロード（空でも例外ではないので下でBM25保険）
            vectordb = Chroma(
                embedding_function=embeddings,
                persist_directory=str(chroma_dir),
            )
            logger.info("chroma loaded")

        # retriever 生成
        retriever = vectordb.as_retriever(search_kwargs={"k": getattr(ct, "TOP_K", 5)})

    except Exception as e:
        logger.warning(f"chroma error: {type(e).__name__}: {e}")
        retriever = None

    # 4) BM25 フォールバック（文書0件やChroma失敗時）
    bm25 = None
    try:
        if chunks:
            bm25 = BM25Retriever.from_documents(chunks)
        elif docs:
            bm25 = BM25Retriever.from_documents(docs)
        if bm25:
            bm25.k = getattr(ct, "TOP_K", 5)
            logger.info("bm25 ready")
    except Exception as e:
        logger.warning(f"bm25 error: {type(e).__name__}: {e}")

    # 5) 最終確定（必ず retriever を入れる）
    if retriever is not None:
        st.session_state["retriever"] = retriever
        logger.info("retriever set: chroma")
    elif bm25 is not None:
        st.session_state["retriever"] = bm25
        st.session_state["bm25_retriever"] = bm25
        logger.warning("retriever set: bm25 fallback")
    else:
        # 最後の保険（空でもクラッシュしないようにNoneで終わるよりマシ）
        st.session_state["retriever"] = BM25Retriever.from_documents([Document(page_content="")])
        logger.error("no documents available; set empty bm25 to avoid crash")

    logger.info("RAG init done")
