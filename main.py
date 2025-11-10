"""
このファイルは、Webアプリのメイン処理が記述されたファイルです。
"""

import logging, os, sys, traceback, datetime, pathlib
pathlib.Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

############################################################
# 1. ライブラリの読み込み
############################################################
# 「.env」ファイルから環境変数を読み込むための関数
from dotenv import load_dotenv
# ログ出力を行うためのモジュール
import logging
# streamlitアプリの表示を担当するモジュール
import streamlit as st
# （自作）画面表示以外の様々な関数が定義されているモジュール
import utils
# （自作）アプリ起動時に実行される初期化処理が記述された関数
from initialize import initialize
# （自作）画面表示系の関数が定義されているモジュール
import components as cn
# （自作）変数（定数）がまとめて定義・管理されているモジュール
import constants as ct

# 追加：ユーティリティで使用（社員名簿の直接表示）
from pathlib import Path

############################################################
# 2. 設定関連
############################################################
# ブラウザタブの表示文言を設定
st.set_page_config(
    page_title=ct.APP_NAME
)

# ログ出力を行うためのロガーの設定
logger = logging.getLogger(ct.LOGGER_NAME)


############################################################
# 3. 初期化処理
############################################################
try:
    # 初期化処理（「initialize.py」の「initialize」関数を実行）
    initialize()
except Exception as e:
    # エラーログの出力
    logger.error(f"{ct.INITIALIZE_ERROR_MESSAGE}\n{e}", exc_info=True)
    # エラーメッセージの画面表示
    st.error(utils.build_error_message(ct.INITIALIZE_ERROR_MESSAGE), icon=ct.ERROR_ICON)
    # 追加：詳細トレースをUIで展開表示
    with st.expander("詳細エラーメッセージ（開発者向け）"):
        st.code(traceback.format_exc())
    # 後続の処理を中断
    st.stop()

# アプリ起動時のログファイルへの出力
if not "initialized" in st.session_state:
    st.session_state.initialized = True
    logger.info(ct.APP_BOOT_MESSAGE)


############################################################
# 4. 初期表示
############################################################
# タイトル表示
cn.display_app_title()   # ← これを追加

# ================================
# 【問題3】説明と利用目的をサイドバーに移動
# ================================
with st.sidebar:
    st.markdown("### 利用目的")

    # 初期値の用意（未設定なら 文書検索 を選ぶ）
    if "mode" not in st.session_state:
        st.session_state.mode = ct.ANSWER_MODE_1  # ← 初期モード

    # ラジオ（利用目的）
    mode = st.radio(
        " ", (ct.ANSWER_MODE_1, ct.ANSWER_MODE_2),
        index=(0 if st.session_state.mode == ct.ANSWER_MODE_1 else 1),
        label_visibility="collapsed",
    )
    st.session_state.mode = mode  # ← セッションに反映（重要）

    st.markdown("---")

    # ==== Undo（直前の1ターン取り消し） ====
    # ※ セッションのメッセージ配列が無ければ初期化（安全策）
    st.session_state.setdefault("messages", [])

    def _undo_last_turn():
        msgs = st.session_state.get("messages", [])
        # 直前が assistant / 直前の直前が user の並びだけ取り消す
        if len(msgs) >= 2 and msgs[-1].get("role") == "assistant" and msgs[-2].get("role") == "user":
            msgs.pop(); msgs.pop()
            st.session_state.messages = msgs
            st.success("直前の1ターンを取り消しました。")
        else:
            st.info("取り消せる履歴が見つかりませんでした。")

    if st.button("直前の1ターンを取り消す", use_container_width=True):
        _undo_last_turn()
        st.rerun()

    # 案内文（サイドバー表示）
    st.info(
        "こんにちは。私は社内文書の情報をもとに回答する生成AIチャットボットです。\n"
        "サイドバーで利用目的を選択し、画面下部のチャット欄からメッセージを送信してください。"
    )
    st.warning("具体的に入力したほうが期待通りの回答を得やすいです。")

    st.markdown("#### 【『社内文書検索』を選択した場合】")
    st.success("入力内容と関連性が高い社内文書のありかを検索できます。")
    st.markdown("**【入力例】**\n社員の育成方針に関するMTGの議事録")

    st.markdown("#### 【『社内問い合わせ』を選択した場合】")
    st.success("質問・要望に対して、社内文書の情報をもとに回答を得られます。")
    st.markdown("**【入力例】**\n人事部に所属している従業員情報を一覧化して")


############################################################
# 5. 会話ログの表示
############################################################
try:
    # 会話ログの表示
    cn.display_conversation_log()
except Exception as e:
    # エラーログの出力
    logger.error(f"{ct.CONVERSATION_LOG_ERROR_MESSAGE}\n{e}", exc_info=True)
    # エラーメッセージの画面表示
    st.error(utils.build_error_message(ct.CONVERSATION_LOG_ERROR_MESSAGE), icon=ct.ERROR_ICON)
    # 追加：詳細トレースをUIで展開表示
    with st.expander("詳細エラーメッセージ（開発者向け）"):
        st.code(traceback.format_exc())
    # 後続の処理を中断
    st.stop()


############################################################
# 6. チャット入力の受け付け
############################################################
chat_message = st.chat_input(ct.CHAT_INPUT_HELPER_TEXT)

# ★ 追記：社員名簿の直接表示は utils 側に集約（既存関数は温存）
def _ensure_staff_csv_available() -> str | None:
    return utils.ensure_staff_csv_available()

def _show_staff_table(dept_query: str | None = None, csv_path: str | None = None):
    return utils.show_staff_table(dept_query=dept_query, csv_path=csv_path)

############################################################
# 7. チャット送信時の処理
############################################################
if chat_message:
    # ==========================================
    # 7-1. ユーザーメッセージの表示
    # ==========================================
    # ユーザーメッセージのログ出力（★ ログは現UIモードで記録）
    logger.info({"message": chat_message, "application_mode": st.session_state.mode})

    # ユーザーメッセージを表示
    with st.chat_message("user"):
        st.markdown(chat_message)

    # ==========================================
    # 7-1.5. 社員名簿ダイレクト表示の分岐（LLMを経由しない安全ルート）
    # ==========================================
    # ★ 追記：誤判定対策—「一覧**を見せて/表示して/表で見せて**」のみ直描画
    if st.session_state.mode == ct.ANSWER_MODE_2 and utils.wants_staff_table_direct(chat_message):
        ensured_csv = _ensure_staff_csv_available()
        if not ensured_csv:
            st.stop()

        dept = utils.extract_dept(chat_message)  # 例：「人事」
        with st.chat_message("assistant"):
            try:
                _show_staff_table(dept_query=dept, csv_path=ensured_csv)
                content = f"社員名簿を表示しました（部署フィルタ: {dept or '指定なし'}）。"
            except Exception as e:
                # エラーログの出力
                logger.error(f"{ct.DISP_ANSWER_ERROR_MESSAGE}\n{e}", exc_info=True)
                # エラーメッセージの画面表示
                st.error(utils.build_error_message(ct.DISP_ANSWER_ERROR_MESSAGE), icon=ct.ERROR_ICON)
                # 追加：詳細トレースをUIで展開表示
                with st.expander("詳細エラーメッセージ（開発者向け）"):
                    st.code(traceback.format_exc())
                content = "社員名簿の表示に失敗しました。"
        # 7-4. 会話ログへの追加（ここで終了）
        st.session_state.messages.append({"role": "user", "content": chat_message})
        st.session_state.messages.append({"role": "assistant", "content": content})
        st.stop()

    # ==========================================
    # 7-2. LLMからの回答取得
    # ==========================================
    res_box = st.empty()
    # LLMによる回答生成（回答生成が完了するまでグルグル回す）
    with st.spinner(ct.SPINNER_TEXT):
        try:
            # === ★ 5-3: 自動モード推定を utils に集約して堅牢化 ===
            auto_mode = utils.infer_mode(chat_message, current_mode=st.session_state.mode)
            if auto_mode != st.session_state.mode:
                st.info(f"質問内容からモードを『{auto_mode}』に自動切替して処理しました。", icon="ℹ️")

            # 画面読み込み時に作成したRetrieverを使い、Chainを実行
            llm_response = utils.get_llm_response(chat_message, mode=auto_mode)

            # ★ 追加：生レスポンスのデバッグ表示
            utils.debug_dump_llm_response(llm_response)
        except Exception as e:
            # エラーログの出力
            logger.error(f"{ct.GET_LLM_RESPONSE_ERROR_MESSAGE}\n{e}", exc_info=True)
            # エラーメッセージの画面表示
            st.error(utils.build_error_message(ct.GET_LLM_RESPONSE_ERROR_MESSAGE), icon=ct.ERROR_ICON)
            # 追加：詳細トレースをUIで展開表示
            with st.expander("詳細エラーメッセージ（開発者向け）"):
                st.code(traceback.format_exc())
            # 後続の処理を中断
            st.stop()
    
    # ==========================================
    # 7-3. LLMからの回答表示
    # ==========================================
    with st.chat_message("assistant"):
        try:
            # モード別描画
            if auto_mode == ct.ANSWER_MODE_1:
                content = cn.display_search_llm_response(llm_response)
            elif auto_mode == ct.ANSWER_MODE_2:
                content = cn.display_contact_llm_response(llm_response)
            else:
                content = {"mode": st.session_state.mode, "answer": "モード判定に失敗しました。"}

            # AIメッセージのログ出力（★ 実際に処理した auto_mode で記録）
            logger.info({"message": content, "application_mode": auto_mode})
        except Exception as e:
            # エラーログの出力
            logger.error(f"{ct.DISP_ANSWER_ERROR_MESSAGE}\n{e}", exc_info=True)
            # まずは通常のエラー表示
            st.error(utils.build_error_message(ct.DISP_ANSWER_ERROR_MESSAGE), icon=ct.ERROR_ICON)
            # 追加：詳細トレースをUIで展開表示
            with st.expander("詳細エラーメッセージ（開発者向け）"):
                st.code(traceback.format_exc())
            # ★ フォールバック描画に切替（components.py 側の想定とズレても最低限は表示）
            st.info("一時的にフォールバック表示（簡易レンダリング）で回答を表示します。")
            content_text = utils.render_fallback(llm_response)
            # ★★★ 追記（ここから）: フォールバックをログ再描画互換の dict 形式にラップ
            if isinstance(content_text, str):
                if auto_mode == ct.ANSWER_MODE_1:
                    content = {"mode": ct.ANSWER_MODE_1, "answer": content_text, "no_file_path_flg": True}
                else:
                    content = {"mode": ct.ANSWER_MODE_2, "answer": content_text}
            # ★★★ 追記（ここまで） 
            # AIメッセージのログ出力（フォールバック）
            logger.info({"message": content, "application_mode": auto_mode})

    # ==========================================
    # 7-4. 会話ログへの追加
    # ==========================================
    # 表示用の会話ログにユーザーメッセージを追加
    st.session_state.messages.append({"role": "user", "content": chat_message})
    # 表示用の会話ログにAIメッセージを追加
    st.session_state.messages.append({"role": "assistant", "content": content})
