"""
このファイルは、画面表示以外の様々な関数定義のファイルです。
"""

############################################################
# ライブラリの読み込み
############################################################
import os
from operator import itemgetter

from dotenv import load_dotenv
import streamlit as st

# LC3対応モジュール
# 置き換え後（v0.3 以降の正しいインポート）
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda

import constants as ct


############################################################
# 設定関連
############################################################
# 「.env」ファイルで定義した環境変数の読み込み
load_dotenv()


############################################################
# 関数定義
############################################################

def get_source_icon(source: str) -> str:
    """参照元のURIに応じたアイコン種別を返す"""
    return ct.LINK_SOURCE_ICON if source.startswith("http") else ct.DOC_SOURCE_ICON


def build_error_message(message: str) -> str:
    """エラーメッセージと問い合わせテンプレートを連結"""
    return "\n".join([message, ct.COMMON_ERROR_MESSAGE])


def _format_docs(docs) -> str:
    """取得ドキュメントをプロンプト文脈用に結合"""
    if not docs:
        return ""
    return "\n\n".join(getattr(d, "page_content", str(d)) for d in docs)


def get_llm_response(chat_message: str, *, mode: str | None = None):
    """
    LLMからの回答取得（RunnableベースのRAG）
    Args:
        chat_message: ユーザー入力値
        mode:  None の場合は st.session_state.mode を使用
               （★ 自動モード移行で推定したモードを main.py から渡せるように）
    Returns:
        dict 例: {"answer": str, "context": [...]} ← ★ context を返すように強化
    """
    # === ★ 5-3対応: 受け取った mode を優先、無ければセッションの mode を使う ===
    use_mode = mode or st.session_state.get("mode", ct.ANSWER_MODE_1)

    # LC3: model_name -> model
    llm = ChatOpenAI(model=ct.MODEL, temperature=ct.TEMPERATURE)

    # 1) 履歴を踏まえた「独立質問」生成プロンプト
    question_generator_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", ct.SYSTEM_PROMPT_CREATE_INDEPENDENT_TEXT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    # 「質問テキスト」を取り出す Runnable（文字列）
    question_generator = question_generator_prompt | llm | StrOutputParser()

    # 2) モードに応じた回答プロンプト
    qa_system_prompt = (
        ct.SYSTEM_PROMPT_DOC_SEARCH
        if use_mode == ct.ANSWER_MODE_1
        else ct.SYSTEM_PROMPT_INQUIRY
    )
    question_answer_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", qa_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            # context はテンプレ変数として参照される（stuffパターン）
            ("system", "参考情報:\n{context}"),
        ]
    )

    # === ★ ここから「段階的に実行して context を確保する方式」に変更 ===

    # 1) 独立質問の生成
    question_text = question_generator.invoke(
        {"input": chat_message, "chat_history": st.session_state.chat_history}
    )

    # 2) retriever による関連ドキュメント取得（Document のまま保持）
    retriever = st.session_state.retriever
    if retriever is None:
        # 念のためのフォールバック（初期化漏れ対策）
        return {"answer": "検索用リトリーバが初期化されていません。initialize を確認してください。", "context": []}
    ctx_docs = retriever.invoke(question_text)   # ← ★ これが後で components.py で使われる

    # 3) LLM のプロンプトに渡す “文脈テキスト” を作成
    ctx_text = _format_docs(ctx_docs)

    # 4) LLM に回答生成させる
    result_msg = (question_answer_prompt | llm).invoke(
        {
            "input": chat_message,
            "chat_history": st.session_state.chat_history,
            "context": ctx_text,  # ← ★ 文脈テキストを渡す
        }
    )

    # LLM応答本文
    answer_text = getattr(result_msg, "content", str(result_msg))

    # 履歴へ追加（BaseMessage型で）
    st.session_state.chat_history.extend(
        [HumanMessage(content=chat_message), AIMessage(content=answer_text)]
    )

    # === ★ context（Document配列）も返す ===
    # components.py 側で「ファイルパス」「ページ番号」を表示できる
    return {
        "answer": answer_text,
        "context": ctx_docs,   # ← ★ これが今回重要
    }
