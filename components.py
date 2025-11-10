"""
このファイルは、画面表示に特化した関数定義のファイルです。
"""

############################################################
# ライブラリの読み込み
############################################################
import os
import streamlit as st
import utils
import constants as ct
# 追加ヘルパー用
from typing import Any, Dict, List


############################################################
# ヘルパー
############################################################
def _fmt_with_page(path: str, page: int | None) -> str:
    """
    # 問題4: PDF のときだけページ番号を後ろに付与して表示する
    例) ./data/foo/bar.pdf （ページNo.3）

    Args:
        path: 表示するファイルパス
        page: ページ番号 (取得できない/対象外なら None)

    Returns:
        表示用の文字列
    """
    try:
        ext = os.path.splitext(path)[1].lower()
    except Exception:
        ext = ""

    if page is not None and ext == ".pdf":
        return f"{path}（ページNo.{page}）"
    return path


# 追加ヘルパー：さまざまな形のソース配列を正規化
def _coerce_sources(obj: Any) -> List[Dict[str, Any]]:
    """
    Document配列 / dict配列 / 文字列配列などを
    [{"source": str | None, "page": int | None}] に正規化する
    """
    out: List[Dict[str, Any]] = []
    if not obj:
        return out

    def pick_meta(d):
        meta = getattr(d, "metadata", None)
        if meta is None and isinstance(d, dict):
            meta = d.get("metadata", {})
        if meta is None:
            meta = {}
        page = meta.get("page")
        src = meta.get("source") or meta.get("file_path") or meta.get("path")
        return {"source": src, "page": page}

    if isinstance(obj, (list, tuple)):
        # 文字列配列にも対応
        if obj and isinstance(obj[0], str):
            return [{"source": s, "page": None} for s in obj]
        for d in obj:
            out.append(pick_meta(d))
    else:
        out.append({"source": str(obj), "page": None})
    return out


############################################################
# 関数定義
############################################################
def display_app_title():
    """
    タイトル表示
    """
    st.markdown(f"## {ct.APP_NAME}")


def display_select_mode():
    """
    回答モードのラジオボタンを表示
    """
    # 回答モードを選択する用のラジオボタンを表示
    col1, col2 = st.columns([100, 1])
    with col1:
        # 「label_visibility="collapsed"」とすることで、ラジオボタンを非表示にする
        st.session_state.mode = st.radio(
            label="",
            options=[ct.ANSWER_MODE_1, ct.ANSWER_MODE_2],
            label_visibility="collapsed"
        )


def display_initial_ai_message():
    """
    AIメッセージの初期表示
    """
    with st.chat_message("assistant"):
        st.markdown("こんにちは。私は社内文書の情報をもとに回答する生成AIチャットボットです。上記で利用目的を選択し、画面下部のチャット欄からメッセージを送信してください。")

        # 「社内文書検索」の機能説明
        st.markdown("**【「社内文書検索」を選択した場合】**")
        st.info("入力内容と関連性が高い社内文書のありかを検索できます。")
        st.code("【入力例】\n社員の育成方針に関するMTGの議事録", wrap_lines=True, language=None)

        # 「社内問い合わせ」の機能説明
        st.markdown("**【「社内問い合わせ」を選択した場合】**")
        st.info("質問・要望に対して、社内文書の情報をもとに回答を得られます。")
        st.code("【入力例】\n人事部に所属している従業員情報を一覧化して", wrap_lines=True, language=None)


def display_conversation_log():
    """
    会話ログの一覧表示
    """
    # 会話ログのループ処理
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):

            # ユーザー入力値
            if message["role"] == "user":
                st.markdown(message["content"])

            # LLMからの回答
            else:
                if message["content"]["mode"] == ct.ANSWER_MODE_1:
                    # 社内文書検索
                    if "no_file_path_flg" not in message["content"]:
                        # メイン
                        st.markdown(message["content"]["main_message"])

                        icon = utils.get_source_icon(message['content']['main_file_path'])
                        # # 問題4: ログ再表示時もページ番号付きで表示
                        if "main_page_number" in message["content"]:
                            disp = _fmt_with_page(
                                message['content']['main_file_path'],
                                message['content']['main_page_number']
                            )
                        else:
                            disp = message['content']['main_file_path']
                        st.success(disp, icon=icon)

                        # サブ
                        if "sub_message" in message["content"]:
                            st.markdown(message["content"]["sub_message"])
                            for sub_choice in message["content"]["sub_choices"]:
                                icon = utils.get_source_icon(sub_choice['source'])
                                # # 問題4: サブもページ番号付きで表示
                                if "page_number" in sub_choice:
                                    disp = _fmt_with_page(sub_choice['source'], sub_choice['page_number'])
                                else:
                                    disp = sub_choice['source']
                                st.info(disp, icon=icon)
                    else:
                        st.markdown(message["content"]["answer"])

                else:
                    # 社内問い合わせ
                    st.markdown(message["content"]["answer"])

                    if "file_info_list" in message["content"]:
                        st.divider()
                        st.markdown(f"##### {message['content']['message']}")
                        # # 問題4: file_info_list はすでに整形済文字列
                        for file_info in message["content"]["file_info_list"]:
                            icon = utils.get_source_icon(file_info)
                            st.info(file_info, icon=icon)


def display_search_llm_response(llm_response):
    """
    「社内文書検索」モードにおけるLLMレスポンスを表示
    ※ 'context' が無いケースでも 'source_documents' / 'sources' をフォールバック
    """
    # --- 本文抽出（answer/result/output_text/text/content の順で拾う）---
    text = None
    if isinstance(llm_response, dict):
        for k in ("answer", "result", "output_text", "text", "content"):
            if llm_response.get(k):
                text = llm_response[k]
                break
        if not text and llm_response.get("chat_history") and llm_response.get("answer"):
            text = llm_response["answer"]
    else:
        text = str(llm_response)

    # “該当資料なし”の扱いは従来どおり
    if text == ct.NO_DOC_MATCH_ANSWER:
        st.markdown(ct.NO_DOC_MATCH_MESSAGE)
        return {
            "mode": ct.ANSWER_MODE_1,
            "answer": ct.NO_DOC_MATCH_MESSAGE,
            "no_file_path_flg": True,
        }

    # --- ソース抽出（context → source_documents → sources）---
    if isinstance(llm_response, dict):
        raw_ctx = llm_response.get("context") or llm_response.get("source_documents") or llm_response.get("sources")
    else:
        raw_ctx = None

    # ソースがなければ、従来の「該当なし」扱いに準ずる
    sources = _coerce_sources(raw_ctx)
    if not sources:
        if text:
            st.markdown(text)
        st.markdown(ct.NO_DOC_MATCH_MESSAGE)
        return {
            "mode": ct.ANSWER_MODE_1,
            "answer": ct.NO_DOC_MATCH_MESSAGE,
            "no_file_path_flg": True,
        }

    # ここから従来の表示と互換を保ちつつ描画
    main_file_path = sources[0]["source"]
    main_page_number = sources[0]["page"]
    main_message = "入力内容に関する情報は、以下のファイルに含まれている可能性があります。"

    if text:
        st.markdown(text)
    st.markdown(main_message)

    icon = utils.get_source_icon(main_file_path or "")
    disp = _fmt_with_page(main_file_path or "（不明）", main_page_number)
    st.success(disp, icon=icon)

    # サブ候補（重複除去）
    sub_choices = []
    duplicate_check = set([main_file_path])
    for s in sources[1:]:
        src = s.get("source")
        if not src or src in duplicate_check:
            continue
        duplicate_check.add(src)
        ent = {"source": src}
        if s.get("page") is not None:
            ent["page_number"] = s["page"]
        sub_choices.append(ent)

    if sub_choices:
        sub_message = "その他、ファイルありかの候補を提示します。"
        st.markdown(sub_message)
        for sub in sub_choices:
            icon = utils.get_source_icon(sub["source"] or "")
            disp = _fmt_with_page(sub["source"] or "（不明）", sub.get("page_number"))
            st.info(disp, icon=icon)

    # 画面再描画用のログ（従来形式にできる限り合わせる）
    content = {
        "mode": ct.ANSWER_MODE_1,
        "main_message": main_message,
        "main_file_path": main_file_path or "",
    }
    if main_page_number is not None:
        content["main_page_number"] = main_page_number
    if sub_choices:
        content["sub_message"] = sub_message
        content["sub_choices"] = sub_choices
    return content


def display_contact_llm_response(llm_response):
    """
    「社内問い合わせ」モードにおけるLLMレスポンスを表示
    ※ 'context' が無いケースでも 'source_documents' / 'sources' をフォールバック
    """
    # 本文
    if isinstance(llm_response, dict):
        answer = (
            llm_response.get("answer")
            or llm_response.get("result")
            or llm_response.get("output_text")
            or llm_response.get("text")
            or llm_response.get("content")
        )
    else:
        answer = str(llm_response)
    if not answer:
        answer = "（回答テキストを抽出できませんでした）"

    st.markdown(answer)

    # 参照情報の抽出
    if isinstance(llm_response, dict):
        raw_ctx = llm_response.get("context") or llm_response.get("source_documents") or llm_response.get("sources")
    else:
        raw_ctx = None
    sources = _coerce_sources(raw_ctx)

    # 5-1: “該当なし”は情報源を出さない（INQUIRY_NO_MATCH も NO_DOC_MATCH も）
    if answer in (ct.INQUIRY_NO_MATCH_ANSWER, ct.NO_DOC_MATCH_ANSWER) or not sources:
        return {"mode": ct.ANSWER_MODE_2, "answer": answer}

    # 情報源の表示（ページ番号込み）
    st.divider()
    message = "情報源"
    st.markdown(f"##### {message}")

    file_info_list = []
    seen = set()
    for s in sources:
        src = s.get("source")
        if not src or src in seen:
            continue
        seen.add(src)

        file_info = _fmt_with_page(src, s.get("page"))
        icon = utils.get_source_icon(src)
        st.info(file_info, icon=icon)
        file_info_list.append(file_info)

    content = {"mode": ct.ANSWER_MODE_2, "answer": answer, "message": message, "file_info_list": file_info_list}
    return content
