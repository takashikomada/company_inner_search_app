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
from langchain_community.retrievers import BM25Retriever  # ★ 追加: フォールバック用
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import CharacterTextSplitter
from langchain_core.documents import Document  # ★ 追加: 手動生成用
import csv  # ★ 追加: CSV統合用

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
# =================================================================
# ★ 課題6対策: CSVを1ドキュメントに統合して読み込むヘルパー
# =================================================================
def _csv_to_merged_document(file_path: str) -> Document:
    """
    CSVの各行を「- キー: 値 / ...」の箇条書きに整形し、
    1つの大きなテキスト（Document）に統合して返す。
    列名は固定せず、存在する全カラムを連結するため任意のCSVに対応。
    """
    rows_out = []
    try:
        # UTF-8/BOM どちらでも開けるよう utf-8-sig
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parts = []
                for k, v in (row or {}).items():
                    if v is None:
                        continue
                    v = str(v).strip()
                    if v:
                        parts.append(f"{k}: {v}")
                if parts:
                    rows_out.append("- " + " / ".join(parts))
    except Exception:
        # 失敗しても呼び出し元でフォールバック可
        pass

    merged_text = "【社員名簿（統合）】\n" + "\n".join(rows_out)
    return Document(
        page_content=merged_text,
        metadata={
            "source": file_path.replace("\\", "/"),
            "is_csv_merged": True,  # 後段の分割スキップ判定に使用
        },
    )


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
                # ★ CSVだけは1ドキュメントに統合して取り込む（課題6）
                if ext == ".csv":
                    try:
                        docs = [_csv_to_merged_document(file_path)]
                    except Exception as e:
                        logger.warning(f"CSV統合読み込みに失敗: {file_path} ({e})")
                        loader = loader_cls(file_path)
                        docs = loader.load()
                else:
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

    # [PATCH] 永続化データが存在 → そのままロード
    if has_chroma_files(persist_path):
        logger.info(f"永続化済 Chroma をロード: {persist_dir}")
        try:
            db = Chroma(
                persist_directory=persist_dir,
                embedding_function=embeddings,
            )
            st.session_state.retriever = db.as_retriever(search_kwargs={"k": ct.TOP_K})
            return
        except Exception:
            # ロード失敗 → フォールバック
            logger.error("永続化済Chromaのロードに失敗 → BM25にフォールバックします。", exc_info=True)
            docs_all = load_data_sources()
            for doc in docs_all:
                doc.page_content = adjust_string(doc.page_content)
                doc.metadata = {k: adjust_string(v) for k, v in (doc.metadata or {}).items()}
            splitter = CharacterTextSplitter(
                chunk_size=ct.CHUNK_SIZE,
                chunk_overlap=ct.CHUNK_OVERLAP,
                separator="\n",
            )
            # ★ 統合CSVは分割しない
            splitted_docs = []
            for d in docs_all:
                if isinstance(d.metadata, dict) and d.metadata.get("is_csv_merged"):
                    splitted_docs.append(d)
                else:
                    splitted_docs.extend(splitter.split_documents([d]))

            bm25 = BM25Retriever.from_documents(splitted_docs)
            bm25.k = ct.TOP_K
            st.session_state.retriever = bm25
            st.session_state["vector_fallback"] = "bm25"
            st.warning(
                "永続化ベクターストアの読み込みに失敗したため、暫定的に **BM25（キーワード検索）** で稼働します。\n"
                "後で『ベクターストア再初期化』を実行すると Chroma を再構築できます。",
                icon="⚠️",
            )
            return

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

    # ★ 統合CSVは分割しない
    splitted_docs = []
    for d in docs_all:
        if isinstance(d.metadata, dict) and d.metadata.get("is_csv_merged"):
            splitted_docs.append(d)
        else:
            splitted_docs.extend(splitter.split_documents([d]))

    try:
        db = Chroma.from_documents(
            splitted_docs,
            embedding=embeddings,
            persist_directory=persist_dir,  # [PATCH] 永続化
        )
        db.persist()
        logger.info("Chroma 永続化完了")
        st.session_state.retriever = db.as_retriever(search_kwargs={"k": ct.TOP_K})
        return
    except Exception:
        logger.error("埋め込み生成に失敗 → BM25 リトリーバにフォールバックします。", exc_info=True)
        bm25 = BM25Retriever.from_documents(splitted_docs)
        bm25.k = ct.TOP_K
        st.session_state.retriever = bm25
        st.session_state["vector_fallback"] = "bm25"
        st.warning(
            "埋め込み作成に失敗したため、暫定的に **BM25（キーワード検索）** で稼働します。\n"
            "課金・クォータ復旧後に『ベクターストア再初期化』で Chroma を再構築してください。",
            icon="⚠️",
        )
        return


############################################################
# 初期化メイン
############################################################
def initialize():
    """
    Streamlit アプリ起動時に呼ばれる初期化処理
    """
    try:
        initialize_retriever()
    except Exception as e:
        st.error(ct.INITIALIZE_ERROR_MESSAGE)
        with st.expander("初期化エラー（詳細）"):
            st.exception(e)
        return
