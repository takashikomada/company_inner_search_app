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

# 追加：社員名簿を安全に“直接表示”するヘルパー（LLMを通さない）
def _show_staff_table(dept_query: str | None = None, csv_path: str | None = None):
    # デフォルトのCSVパスは constants.STAFF_CSV → 無ければ data/社員名簿.csv
    if csv_path is None:
        csv_path = getattr(ct, "STAFF_CSV", "data/社員名簿.csv")

    try:
        import pandas as pd
    except Exception:
        st.error(
            "社員名簿の表示に必要な pandas が見つかりません。ターミナルで `pip install -U pandas` を実行してください。",
            icon=ct.ERROR_ICON,
        )
        return

    p = Path(csv_path)
    if not p.exists():
        st.warning(f"社員名簿が見つかりませんでした: {csv_path}")
        return

    # 文字コードの保険（UTF-8/CP932/UTF-8-SIG を順に試す）
    df = None
    last_err = None
    for enc in ("utf-8", "cp932", "utf-8-sig"):
        try:
            df = pd.read_csv(p, encoding=enc)
            break
        except Exception as err:
            last_err = err
            df = None
    if df is None:
        st.error(f"社員名簿の読み込みに失敗しました（encoding候補: utf-8, cp932, utf-8-sig）。\n{last_err}")
        return

    # 列名の候補（環境に合わせて増やしてOK）
    dept_candidates = ["部署", "部門", "Department", "部署名", "所属部門", "配属", "部"]
    # 実カラム名（オブジェクト）を取得できるようにマップ化
    col_map = {str(c): c for c in df.columns}
    dept_col = None
    for name in dept_candidates:
        if name in col_map:
            dept_col = col_map[name]
            break

    # 部署フィルタ（例：「人事」）
    if dept_query and dept_col is not None:
        df = df[df[dept_col].astype(str).str.contains(dept_query, case=False, na=False)]

    st.subheader("従業員一覧（社員名簿）")
    st.caption(f"ソース: {csv_path}")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.info(f"表示件数: {len(df)} 件")

    # 表の下にダウンロードボタン（CSV/Excel）
    import io
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSVでダウンロード", data=csv_bytes, file_name="社員名簿_表示中.csv", mime="text/csv")
    try:
        from io import BytesIO
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="名簿")
        st.download_button("Excelでダウンロード", data=bio.getvalue(), file_name="社員名簿_表示中.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        pass

def _wants_staff_table(q: str) -> bool:
    if not q:
        return False
    # 「従業員/社員/スタッフ」×「一覧/リスト/表」が含まれるときに直接表示
    kw = ("従業員", "社員", "スタッフ")
    lst = ("一覧", "リスト", "表")
    return any(k in q for k in kw) and any(l in q for l in lst)

def _extract_dept(q: str) -> str | None:
    # よく使う部署名の簡易抽出（必要に応じて拡張）
    import re
    m = re.search(r"(人事|総務|経理|財務|法務|営業|販売|開発|生産|製造|品質|広報|企画|マーケ|マーケティング|情報|情シス|IT|CS|サポート)", q)
    return m.group(1) if m else None

# === 追加：社員名簿CSVの自動検出＆アップロード保険 ===
def _find_staff_csv(default_path: str = "data/社員名簿.csv") -> str | None:
    from pathlib import Path
    try:
        import pandas as pd  # noqa
    except Exception:
        return None

    # 1) constants.py に STAFF_CSV があれば最優先
    if hasattr(ct, "STAFF_CSV"):
        p = Path(ct.STAFF_CSV)
        if p.exists():
            return str(p)

    # 2) 既定パス
    p = Path(default_path)
    if p.exists():
        return str(p)

    # 3) data/ 配下を総当り（列名とファイル名で推定）
    data_dir = Path(getattr(ct, "DATA_DIR", "data"))
    if not data_dir.exists():
        return None

    candidates = list(data_dir.rglob("*.csv"))
    scored = []
    for c in candidates:
        df = None
        for enc in ("utf-8", "cp932", "utf-8-sig"):
            try:
                import pandas as pd
                df = pd.read_csv(c, nrows=5, encoding=enc)
                break
            except Exception:
                df = None
        if df is None:
            continue

        cols = set(map(str, df.columns))
        pts = 0
        for k in ("氏名","名前","従業員名","社員名","FullName","Name"):
            if k in cols: pts += 2
        for k in ("部署","部門","部署名","Department"):
            if k in cols: pts += 3
        for k in ("社員番号","従業員番号","EmployeeID","ID"):
            if k in cols: pts += 1
        if any(s in c.stem for s in ("名簿","社員","従業員","staff","employee")):
            pts += 2

        if pts > 0:
            scored.append((pts, c))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return str(scored[0][1])
    return None

def _ensure_staff_csv_available() -> str | None:
    """見つからなければアップロードして data/ に保存して使えるようにする"""
    from pathlib import Path
    path = _find_staff_csv()
    if path:
        return path

    st.warning("社員名簿CSVが見つかりません。ファイルをアップロードしてください。")
    up = st.file_uploader("社員名簿CSV（UTF-8またはCP932）を選択", type=["csv"], key="upload_staff_csv")
    if up is None:
        return None

    data_dir = Path(getattr(ct, "DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "社員名簿.csv"
    target.write_bytes(up.getvalue())
    st.success(f"保存しました: {target}")
    return str(target)
# === ここまで追加 ===

# === 追加：LLMレスポンスのデバッグ表示＆フォールバック描画 ===
def _debug_dump_llm_response(llm_response):
    with st.expander("LLM生レスポンス（デバッグ）"):
        try:
            import json
            if isinstance(llm_response, (dict, list)):
                st.json(llm_response)
            else:
                st.code(str(llm_response))
        except Exception:
            st.code(repr(llm_response))

def _render_fallback(llm_response):
    """
    components.py が想定していない戻り値でも最低限の表示を行う保険。
    - 代表的なキー: 'result', 'answer', 'output_text', 'text', 'content'
    - 代表的なソース: 'source_documents', 'sources', 'context'
    """
    text = None
    sources = []

    # 1) テキスト候補を抽出
    if isinstance(llm_response, dict):
        for k in ("result", "answer", "output_text", "text", "content"):
            if k in llm_response and llm_response[k]:
                text = llm_response[k]
                break
        if not text and "chat_history" in llm_response and "answer" in llm_response:
            text = llm_response["answer"]
    elif isinstance(llm_response, (list, tuple)):
        if llm_response and isinstance(llm_response[0], str):
            text = llm_response[0]
        elif llm_response and isinstance(llm_response[0], dict):
            text = llm_response[0].get("text") or llm_response[0].get("answer")
    else:
        text = str(llm_response)

    # 2) ソース候補を抽出
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

    # 3) 画面に描画
    st.markdown(text or "（回答テキストを抽出できませんでした）")
    if sources:
        st.markdown("**参照元**")
        for i, s in enumerate(sources, 1):
            label = s.get("source") or "（パス不明）"
            page = s.get("page")
            st.write(f"- {i}. {label}" + (f"（p.{page}）" if page is not None else ""))
    return text or ""
# === ここまで追加 ===


# === ★ 5-3: 自動モード推定器（検索⇄問い合わせ）改良版 ===
def _infer_mode(q: str) -> str:
    """
    入力文のキーワードから回答モードを推定する簡易ルールベース。
    ※ ファイル名や「参照」「探して」などは必ず文書検索モードにする
    """
    if not q:
        return st.session_state.mode

    ql = q.lower()

    # 1) PDF/docx/txt などのファイル指定 → 文書検索モード固定
    if any(ext in ql for ext in (".pdf", ".docx", ".txt", ".csv")) \
       or any(k in q for k in ("参照", "参照箇所", "探して", "ありか", "場所", "ファイル", "path", "where")):
        return ct.ANSWER_MODE_1

    # 2) 問い合わせ（説明/要約/方針/まとめなど）
    inquiry_kw = (
        "教えて","まとめて","ポイント","とは","一覧化",
        "作り方","手順","計画","方針","役割",
        "メリット","デメリット","まとめ","how","why","what"
    )
    if any(k in q for k in inquiry_kw):
        return ct.ANSWER_MODE_2

    # 3) 検索語 → 文書検索
    search_kw = (
        "どこ","ありか","場所","ファイル","議事録",
        "パス","path","where","存在","保存先","探して"
    )
    if any(k in q for k in search_kw):
        return ct.ANSWER_MODE_1

    # 4) 判定できなければ現モード維持
    return st.session_state.mode
# === 5-3 ここまで ===


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
    # 「社内問い合わせ」モード かつ “一覧を見せて”系の問い合わせなら
    if st.session_state.mode == ct.ANSWER_MODE_2 and _wants_staff_table(chat_message):
        # まず存在確認 → 無ければアップロードUIで保存してから進む
        ensured_csv = _ensure_staff_csv_available()
        if not ensured_csv:
            st.stop()

        dept = _extract_dept(chat_message)  # 例：「人事」
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
    # 「st.spinner」でグルグル回っている間、表示の不具合が発生しないよう空のエリアを表示
    res_box = st.empty()
    # LLMによる回答生成（回答生成が完了するまでグルグル回す）
    with st.spinner(ct.SPINNER_TEXT):
        try:
            # === ★ 5-3: 自動モード推定 → 通知 → 指定モードで実行 ===
            auto_mode = _infer_mode(chat_message)
            if auto_mode != st.session_state.mode:
                st.info(f"質問内容からモードを『{auto_mode}』に自動切替して処理しました。", icon="ℹ️")

            # 画面読み込み時に作成したRetrieverを使い、Chainを実行
            llm_response = utils.get_llm_response(chat_message, mode=auto_mode)

            # ★ 追加：生レスポンスのデバッグ表示
            _debug_dump_llm_response(llm_response)
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
            # ==========================================
            # モードが「社内文書検索」の場合（★ auto_mode で分岐）
            # ==========================================
            if auto_mode == ct.ANSWER_MODE_1:
                # 入力内容と関連性が高い社内文書のありかを表示
                content = cn.display_search_llm_response(llm_response)

            # ==========================================
            # モードが「社内問い合わせ」の場合
            # ==========================================
            elif auto_mode == ct.ANSWER_MODE_2:
                # 入力に対しての回答と、参照した文書のありかを表示
                content = cn.display_contact_llm_response(llm_response)
            else:
                # 未知値の保険（現状到達しない想定）
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
            content = _render_fallback(llm_response)
            # ★★★ 追記（ここから）: フォールバックをログ再描画互換の dict 形式にラップ
            if isinstance(content, str):
                if auto_mode == ct.ANSWER_MODE_1:
                    content = {"mode": ct.ANSWER_MODE_1, "answer": content, "no_file_path_flg": True}
                else:
                    content = {"mode": ct.ANSWER_MODE_2, "answer": content}
            # ★★★ 追記（ここまで） 
            # AIメッセージのログ出力（フォールバック）
            logger.info({"message": content, "application_mode": auto_mode})
            # stop() はしない（以降のログ追加まで進める）


    # ==========================================
    # 7-4. 会話ログへの追加
    # ==========================================
    # 表示用の会話ログにユーザーメッセージを追加
    st.session_state.messages.append({"role": "user", "content": chat_message})
    # 表示用の会話ログにAIメッセージを追加
    st.session_state.messages.append({"role": "assistant", "content": content})
