"""
このファイルは、最初の画面読み込み時にのみ実行される初期化処理が記述されたファイルです。
"""

from dotenv import load_dotenv
load_dotenv()  # これより上で OpenAI クライアント等を作らない

############################################################
# ライブラリの読み込み（置き換え）
############################################################
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from uuid import uuid4
import sys
import unicodedata
from dotenv import load_dotenv
import streamlit as st

from docx import Document

# LangChain（最新）
from langchain_community.document_loaders import WebBaseLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
# from langchain_community.vectorstores import Chroma  # ← 旧（v0.3 では非推奨/不可のことがある）
from langchain_community.vectorstores import Chroma

# ★ ドキュメント生成用（CSV統合で使用）
from langchain_core.documents import Document as LCDocument  # 【問題6】追加

import constants as ct


############################################################
# 関数定義
############################################################

def initialize():
    """
    画面読み込み時に実行する初期化処理
    """
    initialize_session_state()
    initialize_session_id()
    initialize_logger()
    initialize_retriever()


def initialize_logger():
    """
    ログ出力の設定
    """
    os.makedirs(ct.LOG_DIR_PATH, exist_ok=True)
    logger = logging.getLogger(ct.LOGGER_NAME)

    if logger.hasHandlers():
        return

    log_handler = TimedRotatingFileHandler(
        os.path.join(ct.LOG_DIR_PATH, ct.LOG_FILE),
        when="D",
        encoding="utf8"
    )
    formatter = logging.Formatter(
        f"[%(levelname)s] %(asctime)s line %(lineno)s, in %(funcName)s, session_id={{st.session_state.session_id}}: %(message)s"
    )
    log_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(log_handler)


def initialize_session_id():
    """
    セッションIDの作成
    """
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid4().hex


def initialize_retriever():
    """
    画面読み込み時にRAGのRetriever（ベクターストアから検索するオブジェクト）を作成
    """
    logger = logging.getLogger(ct.LOGGER_NAME)

    # ★ 追記：毎回安定して再構築（セッションの不整合を避ける）
    # if "retriever" in st.session_state:
    #     return
    
    docs_all = load_data_sources()

    # Windows向けの文字調整
    for doc in docs_all:
        doc.page_content = adjust_string(doc.page_content)
        for key in list(doc.metadata.keys()):
            doc.metadata[key] = adjust_string(doc.metadata[key])

        # ★ 追記：必ず source を絶対パス or URL で持つ（並び替えに効かせる）
        src = doc.metadata.get("source")
        if isinstance(src, str) and not src.startswith("http"):
            try:
                doc.metadata["source"] = os.path.normpath(os.path.abspath(src))
            except Exception:
                pass
    
    embeddings = OpenAIEmbeddings()
    
    # ============================
    # 【問題2】マジックナンバー除去
    # ============================
    text_splitter = CharacterTextSplitter(
        chunk_size=ct.CHUNK_SIZE,          # ← constants.py から参照
        chunk_overlap=ct.CHUNK_OVERLAP,    # ← constants.py から参照
        separator="\n",
    )

    splitted_docs = text_splitter.split_documents(docs_all)

    db = Chroma.from_documents(splitted_docs, embedding=embeddings)

    # ============================
    # 【問題1】TOP_K を変数化
    # ============================
    st.session_state.retriever = db.as_retriever(
        search_kwargs={"k": ct.TOP_K}      # ← constants.py の TOP_K を使用
    )


def initialize_session_state():
    """
    初期化データの用意
    """
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.chat_history = []


def load_data_sources():
    """
    RAGの参照先となるデータソースの読み込み
    """
    docs_all = []
    recursive_file_check(ct.RAG_TOP_FOLDER_PATH, docs_all)

    # Webページの取り込み
    web_docs_all = []
    for web_url in ct.WEB_URL_LOAD_TARGETS:
        try:
            loader = WebBaseLoader(web_url)
            web_docs = loader.load()
            # ★ 追加：Web 由来ドキュメントにも必ず source（URL）を付与
            for d in web_docs:
                d.metadata = dict(d.metadata or {})
                d.metadata.setdefault("source", web_url)  # ← ここでURLを明示
            # ★ 追記：Web は大きめに分割（ヒット率向上）
            splitter_web = CharacterTextSplitter(
                chunk_size=getattr(ct, "CHUNK_SIZE_WEB", ct.CHUNK_SIZE * 4),
                chunk_overlap=ct.CHUNK_OVERLAP,
                separator="\n",
            )
            web_docs = splitter_web.split_documents(web_docs)
            web_docs_all.extend(web_docs)
        except Exception as e:
            logging.getLogger(ct.LOGGER_NAME).warning(f"Web読み込みに失敗: {web_url} / {e}")
    docs_all.extend(web_docs_all)

    return docs_all


def recursive_file_check(path, docs_all):
    """
    RAGの参照先となるデータソースの読み込み
    """
    if os.path.isdir(path):
        for file in os.listdir(path):
            full_path = os.path.join(path, file)
            recursive_file_check(full_path, docs_all)
    else:
        file_load(path, docs_all)


def file_load(path, docs_all):
    """
    ファイル内のデータ読み込み
    """
    file_extension = os.path.splitext(path)[1]
    file_name = os.path.basename(path)

    if file_extension in ct.SUPPORTED_EXTENSIONS:
        loader = ct.SUPPORTED_EXTENSIONS[file_extension](path)

        # =========================================================
        # 【問題6】CSVの各行を1ドキュメントへ「統合」して検索精度を上げる
        # ---------------------------------------------------------
        # （既存コメントを保持）
        # =========================================================
        if file_extension == ".csv":
            row_docs = loader.load()  # 1行 = 1 Document
            lines_all = []
            lines_hr = []  # 人事部抽出（ヒント語彙として保持）

            for d in row_docs:
                # 行の見やすさ調整：改行→“, ” へ整形
                line = d.page_content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", ", ")
                # 余計な連続空白を軽減
                line = " ".join(line.split())
                lines_all.append(f"- {line}")
                if "人事部" in d.page_content:
                    lines_hr.append(f"- {line}")

            combined_text = "【社員名簿（統合ドキュメント）】\n" \
                            "※ 各レコードは「, 」区切りで1行表示\n" \
                            + "\n".join(lines_all)

            # 人事部の抜粋セクションを追記（クエリとの一致性を高めるヒント）
            if lines_hr:
                combined_text += "\n\n【部署フィルタ: 人事部 抜粋】\n" + "\n".join(lines_hr)

            # 単一ドキュメントとして追加（source は元CSVのパスを維持）
            # ★ 追記：絶対パス格納
            src_abs = os.path.normpath(os.path.abspath(path))
            docs_all.append(
                LCDocument(page_content=combined_text, metadata={"source": src_abs})
            )
            return  # ← ここで終了（CSVは統合版だけを使う）

        # CSV以外（pdf/docx/txt など）は従来通り
        docs = loader.load()

        # ★ 追加：すべての Document に source（ファイルの絶対/相対パス）を強制付与
        for d in docs:
            d.metadata = dict(d.metadata or {})
            try:
                d.metadata.setdefault("source", os.path.normpath(os.path.abspath(path)))  # ← ここで必ず絶対パス
            except Exception:
                d.metadata.setdefault("source", path)

        docs_all.extend(docs)


def adjust_string(s):
    """
    Windows環境でRAGが正常動作するよう調整
    """
    if type(s) is not str:
        return s
    if sys.platform.startswith("win"):
        s = unicodedata.normalize('NFC', s)
        s = s.encode("cp932", "ignore").decode("cp932")
        return s
    return s
