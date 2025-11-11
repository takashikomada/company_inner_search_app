"""
このファイルは、RAGの初期化処理（データ読み込み、分割、ベクトルDB作成）を担当するファイルです。
"""

############################################################
# ライブラリの読み込み
############################################################
import os
import logging
import streamlit as st

from dotenv import load_dotenv

from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import CharacterTextSplitter

from langchain_community.document_loaders import (
    PyMuPDFLoader,
    Docx2txtLoader,
    TextLoader,
    CSVLoader,
)

from langchain_community.document_loaders import WebBaseLoader

import constants as ct

# [PATCH] Chroma 永続化チェック用
from pathlib import Path


############################################################
# 設定関連
############################################################
load_dotenv()

logger = logging.getLogger(ct.LOGGER_NAME)


############################################################
# データ読み込み（docx/pdf/txt/csv）
############################################################
def recursive_file_check(target_dir: str, docs_all: list):
    """
    指定フォルダ配下のファイルをすべて再帰的に探索し、対応するローダーで読み込む
    """
    for root, _, files in os.walk(target_dir):
        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()

            loader_cls = ct.SUPPORTED_EXTENSIONS.get(ext)
            if not loader_cls:
                continue

            try:
                loader = loader_cls(file_path)
                docs = loader.load()
                # source を固定化
                for d in docs:
                    d.metadata = dict(d.metadata or {})
                    d.metadata["source"] = file_path.replace("\\", "/")
                docs_all.extend(docs)
            except Exception as e:
                logger.warning(f"ファイル読み込み失敗: {file_path} ({e})")


############################################################
# Webページ読み込み
############################################################
def load_web_sources():
    """
    事前に指定した URL からデータを読み込む（WebBaseLoader）
    """
    web_docs = []

    # [PATCH] Web取り込みはフラグで制御
    if not getattr(ct, "ENABLE_WEB_SCRAPE", False):
        return []

    for url in ct.WEB_URL_LOAD_TARGETS:
        try:
            loader = WebBaseLoader(url)
            docs = loader.load()
            for d in docs:
                d.metadata = dict(d.metadata or {})
                d.metadata["source"] = url
            web_docs.extend(docs)
        except Exception as e:
            logger.warning(f"Web読み込み失敗: {url} ({e})")

    return web_docs


############################################################
# 全データ読み込み
############################################################
def load_data_sources():
    """
    RAG が参照するすべてのドキュメントを読み込む
    """
    docs_all = []
    recursive_file_check(ct.RAG_TOP_FOLDER_PATH, docs_all)

    # [PATCH] Web 取り込みON/OFF
    web_docs = load_web_sources()
    docs_all.extend(web_docs)

    return docs_all


############################################################
# 文字コードの調整
############################################################
def adjust_string(text: str) -> str:
    """
    Windows 由来の文字（ファイル名など）を整形する
    """
    if not isinstance(text, str):
        return text
    return text.replace("\x00", "").strip()


############################################################
# Retriever の初期化
############################################################
def initialize_retriever():
    """
    ベクターストア（Chroma）を初期化する
    初回 → 埋め込み生成して Chroma 永続化
    2回目以降 → 永続化済データをロードして高速起動
    """
    if "retriever" in st.session_state:
        return

    embeddings = OpenAIEmbeddings()

    # [PATCH] Chroma 永続化パス
    persist_dir = getattr(ct, "CHROMA_DIR", "./chroma_store")
    persist_path = Path(persist_dir)

    persist_path.mkdir(parents=True, exist_ok=True)

    def has_chroma_files(path: Path) -> bool:
        try:
            return any(path.iterdir())
        except Exception:
            return False

    try:
        # [PATCH] 永続化データが存在 → そのままロード
        if has_chroma_files(persist_path):
            logger.info(f"永続化済 Chroma をロード: {persist_dir}")

            db = Chroma(
                persist_directory=persist_dir,
                embedding_function=embeddings,
            )

        else:
            # [PATCH] 初回のみ埋め込み生成
            logger.info("初回起動 → 全文書を読み込み、埋め込み生成します")

            docs_all = load_data_sources()

            for doc in docs_all:
                doc.page_content = adjust_string(doc.page_content)
                doc.metadata = {k: adjust_string(v) for k, v in (doc.metadata or {}).items()}

            splitter = CharacterTextSplitter(
                chunk_size=ct.CHUNK_SIZE,
                chunk_overlap=ct.CHUNK_OVERLAP,
                separator="\n",
            )
            splitted_docs = splitter.split_documents(docs_all)

            db = Chroma.from_documents(
                splitted_docs,
                embedding=embeddings,
                persist_directory=persist_dir,  # [PATCH] 永続化
            )
            db.persist()
            logger.info("Chroma 永続化完了")

        # retriever 化
        st.session_state.retriever = db.as_retriever(
            search_kwargs={"k": ct.TOP_K}
        )

    except Exception as e:
        logger.error("初期化エラー", exc_info=True)
        raise e


############################################################
# 初期化メイン
############################################################
def initialize():
    """
    Streamlit アプリ起動時に呼ばれる初期化処理
    """
    try:
        initialize_retriever()
    except Exception:
        st.error(ct.INITIALIZE_ERROR_MESSAGE)
        raise
