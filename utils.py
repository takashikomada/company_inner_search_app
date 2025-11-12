"""
このファイルは、画面表示以外の様々な関数定義のファイルです。
"""

############################################################
# ライブラリの読み込み
############################################################
from __future__ import annotations

import os
from typing import Any, Dict, List

from dotenv import load_dotenv
import streamlit as st
from tenacity import retry, wait_exponential, stop_after_attempt

# LC3対応モジュール（v0.3 互換）
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

import constants as ct


############################################################
# 設定関連
############################################################
# 「.env」ファイルで定義した環境変数の読み込み
load_dotenv()


# ★ 追加: セッションキーの初期化（抜け防止）
def _ensure_session_keys() -> None:
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("retriever", None)
    st.session_state.setdefault("bm25_retriever", None)  # initialize 側で設定されていれば使用


_ensure_session_keys()


# ★ 追加: LLM インスタンスのキャッシュ（過剰生成を防ぐ）
@st.cache_resource(show_spinner=False)
def _get_llm() -> ChatOpenAI:
    """
    ChatOpenAI のインスタンスをキャッシュ。
    - tenacity 側で指数バックオフするため max_retries=0。
    - constants.MODEL / TEMPERATURE が無ければ安全値を使用。
    """
    try:
        model_name = getattr(ct, "MODEL", "gpt-4o-mini")
        temp = getattr(ct, "TEMPERATURE", 0.2)
        return ChatOpenAI(model=model_name, temperature=temp, max_retries=0)
    except Exception:
        return ChatOpenAI(model="gpt-4o-mini", temperature=getattr(ct, "TEMPERATURE", 0.2), max_retries=0)


############################################################
# 追加: OpenAI 呼び出しの指数バックオフ（429/一時失敗対策）
############################################################
@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
def _invoke_with_retry(runnable, inputs: dict):
    return runnable.invoke(inputs)


############################################################
# 既存ユーティリティ（フォーマッタ等）
############################################################
def get_source_icon(source: str) -> str:
    """参照元のURIに応じたアイコン種別を返す"""
    return ct.LINK_SOURCE_ICON if isinstance(source, str) and source.startswith("http") else ct.DOC_SOURCE_ICON


def build_error_message(message: str) -> str:
    """エラーメッセージと問い合わせテンプレートを連結"""
    return "\n".join([message, ct.COMMON_ERROR_MESSAGE])


def _format_docs(docs) -> str:
    """取得ドキュメントをプロンプト文脈用に結合"""
    if not docs:
        return ""
    return "\n\n".join(getattr(d, "page_content", str(d)) for d in docs)


############################################################
# ★ 追加: デバッグ/フォールバック描画（components側と非依存で最低限表示）
############################################################
def debug_dump_llm_response(llm_response: Any) -> None:
    with st.expander("LLM生レスポンス（デバッグ）", expanded=False):
        try:
            st.json(llm_response)
        except Exception:
            st.code(repr(llm_response))


def render_fallback(llm_response: Any) -> str:
    """
    components.py 側の想定と異なる戻り値でも最低限の表示をする簡易描画。
    """
    text = None
    sources = []

    # テキスト抽出
    if isinstance(llm_response, dict):
        for k in ("result", "answer", "output_text", "text", "content"):
            if k in llm_response and llm_response[k]:
                text = llm_response[k]
                break
        # 代表的サブ構造
        if not text and "answer" in llm_response:
            text = llm_response["answer"]
    elif isinstance(llm_response, (list, tuple)):
        if llm_response and isinstance(llm_response[0], str):
            text = llm_response[0]
        elif llm_response and isinstance(llm_response[0], dict):
            text = llm_response[0].get("text") or llm_response[0].get("answer")
    else:
        text = str(llm_response)

    # ソース抽出
    def _coerce_docs(obj):
        out = []
        if not obj:
            return out
        for d in obj:
            meta = getattr(d, "metadata", None) or (d.get("metadata", {}) if isinstance(d, dict) else {})
            page = meta.get("page")
            src = meta.get("source") or meta.get("file_path") or meta.get("path")
            out.append({"source": src, "page": page})
        return out

    if isinstance(llm_response, dict):
        if "source_documents" in llm_response and llm_response["source_documents"]:
            sources = _coerce_docs(llm_response["source_documents"])
        elif "sources" in llm_response and llm_response["sources"]:
            val = llm_response["sources"]
            if val and isinstance(val, list) and isinstance(val[0], str):
                sources = [{"source": s, "page": None} for s in val]
            else:
                sources = _coerce_docs(val)
        elif "context" in llm_response and llm_response["context"]:
            sources = _coerce_docs(llm_response["context"])

    st.markdown(text or "（回答テキストを抽出できませんでした）")
    if sources:
        st.markdown("**参照元**")
        for i, s in enumerate(sources, 1):
            label = s.get("source") or "（パス不明）"
            page = s.get("page")
            st.write(f"- {i}. {label}" + (f"（p.{page}）" if page is not None else ""))
    return text or ""


############################################################
# ★ 追加: 自動モード推定（main側での自動切替用）
############################################################
def infer_mode(q: str, *, current_mode: str) -> str:
    if not q:
        return current_mode
    ql = q.lower()

    # 1) ファイル名/参照系 → 文書検索
    if any(ext in ql for ext in (".pdf", ".docx", ".txt", ".csv")) \
       or any(k in q for k in ("参照", "参照箇所", "探して", "ありか", "場所", "ファイル", "path", "where")):
        return ct.ANSWER_MODE_1

    # 2) “一覧化/要約/説明” → 問い合わせ
    inquiry_kw = ("一覧化して","一覧にして","要約して","説明して","まとめて","ポイント","とは","作り方","手順","計画","方針","役割","メリット","デメリット","how","why","what")
    if any(k in q for k in inquiry_kw):
        return ct.ANSWER_MODE_2

    # 3) 検索語 → 文書検索
    search_kw = ("どこ","ありか","場所","ファイル","議事録","パス","path","where","存在","保存先","探して","フォルダ","ディレクトリ")
    if any(k in q for k in search_kw):
        return ct.ANSWER_MODE_1

    return current_mode


############################################################
# LLM応答（RAG）
############################################################
def get_llm_response(chat_message: str, *, mode: str | None = None) -> Dict[str, Any]:
    """
    LLMからの回答取得（RunnableベースのRAG）
    Returns:
        dict 例: {"answer": str, "context": [...]}
    """
    use_mode = mode or st.session_state.get("mode", ct.ANSWER_MODE_1)
    llm = _get_llm()

    # 1) 独立質問（履歴を踏まえて要約したクエリ）
    qgen_prompt = ChatPromptTemplate.from_messages(
        [("system", ct.SYSTEM_PROMPT_CREATE_INDEPENDENT_TEXT),
         MessagesPlaceholder("chat_history"),
         ("human", "{input}")]
    )
    qgen = qgen_prompt | llm | StrOutputParser()
    try:
        question_text = _invoke_with_retry(qgen, {"input": chat_message, "chat_history": st.session_state.get("chat_history", [])})
    except Exception:
        question_text = chat_message

    # 2) retriever による関連ドキュメント取得
    retriever = st.session_state.get("retriever", None)
    if retriever is None:
        return {"answer": "検索用リトリーバが初期化されていません。initialize を確認してください。", "context": []}

    ctx_docs = []
    # ② 通常検索
    try:
        ctx_docs = retriever.invoke(question_text) or []
    except Exception:
        ctx_docs = []

    # ②’ 0件なら k を広げて再検索
    if not ctx_docs:
        try:
            if hasattr(retriever, "search_kwargs"):
                current_k = int(retriever.search_kwargs.get("k", 4))
                retriever.search_kwargs["k"] = max(8, current_k)
        except Exception:
            pass
        try:
            ctx_docs = retriever.invoke(question_text) or []
        except Exception:
            ctx_docs = []

    # ③ まだ0件なら HYDE でクエリ拡張
    if not ctx_docs:
        try:
            hyde_prompt = (
                "次の問い合わせに答えるための社内文書の一部のような短い説明を日本語で3〜5文書いてください。"
                "部署名・方針・施策など、検索にかかりやすい語を自然に含めてください。\n\n"
                f"問い合わせ: {question_text}"
            )
            hyde_msg = llm.invoke(hyde_prompt)
            hyde_text = getattr(hyde_msg, "content", str(hyde_msg))
        except Exception:
            hyde_text = question_text
        try:
            ctx_docs = retriever.invoke(hyde_text) or []
        except Exception:
            ctx_docs = []

    # ④ それでも0件なら BM25 があれば使用
    if not ctx_docs:
        bm25 = st.session_state.get("bm25_retriever", None)
        if bm25 is not None:
            try:
                ctx_docs = (bm25.get_relevant_documents(question_text) or [])[: max(5, getattr(ct, "TOP_K", 5))]
            except Exception:
                pass

    # 3) LLM回答生成（モード別システム文）
    qa_sys = ct.SYSTEM_PROMPT_DOC_SEARCH if use_mode == ct.ANSWER_MODE_1 else ct.SYSTEM_PROMPT_INQUIRY
    qa_prompt = ChatPromptTemplate.from_messages(
        [("system", qa_sys),
         MessagesPlaceholder("chat_history"),
         ("human", "{input}"),
         ("system", "参考情報:\n{context}\n\n出力の最後に必ず「参照元: <ファイルパス>（必要ならページ番号）」を列挙してください。")]
    )

    ctx_text = _format_docs(ctx_docs)
    try:
        result_msg = (qa_prompt | llm).invoke({"input": chat_message, "chat_history": st.session_state.get("chat_history", []), "context": ctx_text})
        answer_text = getattr(result_msg, "content", str(result_msg))
    except Exception as e:
        answer_text = f"回答生成に失敗しました。時間をおいて再試行してください。\n詳細: {type(e).__name__}: {e}"

    # 4) 履歴に追加
    try:
        st.session_state["chat_history"] = st.session_state.get("chat_history", [])
        st.session_state.chat_history.extend([HumanMessage(content=chat_message), AIMessage(content=answer_text)])
    except Exception:
        pass

    return {"answer": answer_text, "context": ctx_docs}


__all__ = [
    "get_source_icon",
    "build_error_message",
    "debug_dump_llm_response",
    "render_fallback",
    "infer_mode",
    "get_llm_response",
]
