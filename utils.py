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
from langchain_openai import ChatOpenAI   # ←← これを必ず入れる

import constants as ct


############################################################
# 設定関連
############################################################
# 「.env」ファイルで定義した環境変数の読み込み
load_dotenv()


############################################################
# 既存関数（変更なし or 追記のみ）
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
# ★ 追記：デバッグ/フォールバック描画ヘルパーを外出し
############################################################
def debug_dump_llm_response(llm_response):
    with st.expander("LLM生レスポンス（デバッグ）"):
        try:
            import json
            if isinstance(llm_response, (dict, list)):
                st.json(llm_response)
            else:
                st.code(str(llm_response))
        except Exception:
            st.code(repr(llm_response))


def render_fallback(llm_response):
    """
    components.py 側の想定と異なる戻り値でも最低限の表示をする簡易描画。
    """
    text = None
    sources = []

    # 1) テキスト候補
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

    # 2) ソース候補抽出
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

    # 3) 描画
    st.markdown(text or "（回答テキストを抽出できませんでした）")
    if sources:
        st.markdown("**参照元**")
        for i, s in enumerate(sources, 1):
            label = s.get("source") or "（パス不明）"
            page = s.get("page")
            st.write(f"- {i}. {label}" + (f"（p.{page}）" if page is not None else ""))
    return text or ""


############################################################
# ★ 追記：社員名簿の“直表示”系（main から外出し）
############################################################
from pathlib import Path

def extract_dept(q: str) -> str | None:
    # よく使う部署名の簡易抽出（必要に応じて拡張）
    import re
    m = re.search(r"(人事|総務|経理|財務|法務|営業|販売|開発|生産|製造|品質|広報|企画|マーケ|マーケティング|情報|情シス|IT|CS|サポート)", q)
    return m.group(1) if m else None

def wants_staff_table_direct(q: str) -> bool:
    """
    「表（テーブル）を**直接表示**したい」場合のみ True。
    “一覧化して/要約して/一覧にして” は **False**（LLMへ）。
    """
    if not q:
        return False
    kw_want_table = ("一覧を見せて", "表で見せて", "表で表示", "表で出して", "表示して", "見せて")
    return any(k in q for k in kw_want_table)

def _find_staff_csv(default_path: str = "data/社員名簿.csv") -> str | None:
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

def ensure_staff_csv_available() -> str | None:
    """見つからなければアップロードして data/ に保存して使えるようにする"""
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

def show_staff_table(dept_query: str | None = None, csv_path: str | None = None):
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


############################################################
# ★ 追記：自動モード推定を厳密化（“一覧化して”は問い合わせ、”表で見せて”は直表示）
############################################################
def infer_mode(q: str, *, current_mode: str) -> str:
    """
    入力文のキーワードから回答モードを推定する簡易ルールベース。
    ※ ファイル名や「参照」「探して」などは文書検索モードにする
    """
    if not q:
        return current_mode
    ql = q.lower()

    # 1) ファイル拡張子/参照系 → 文書検索
    if any(ext in ql for ext in (".pdf", ".docx", ".txt", ".csv")) \
       or any(k in q for k in ("参照", "参照箇所", "探して", "ありか", "場所", "ファイル", "path", "where")):
        return ct.ANSWER_MODE_1

    # 2) “表で見せて/表示して” → 問い合わせ（直描画は main 側で分岐）
    if wants_staff_table_direct(q):
        return ct.ANSWER_MODE_2

    # 3) “一覧化して/一覧にして/要約して/説明して” → 問い合わせ
    inquiry_kw = ("一覧化して","一覧にして","要約して","説明して","まとめて","ポイント","とは","作り方","手順","計画","方針","役割","メリット","デメリット","how","why","what")
    if any(k in q for k in inquiry_kw):
        return ct.ANSWER_MODE_2

    # 4) 検索語 → 文書検索
    search_kw = ("どこ","ありか","場所","ファイル","議事録","パス","path","where","存在","保存先","探して","フォルダ","ディレクトリ")
    if any(k in q for k in search_kw):
        return ct.ANSWER_MODE_1

    return current_mode


############################################################
# 既存：LLM応答（★ 並び替えロジックを強化）
############################################################
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

    # ← 先に None チェック（初期化漏れ対策）
    if retriever is None:
        return {
            "answer": "検索用リトリーバが初期化されていません。initialize を確認してください。",
            "context": [],
        }

    ctx_docs = retriever.invoke(question_text)   # ← ★ これが後で components.py で使われる

    # === ★ 追加：ファイル名/フォルダ名優先の並び替え =========================
    try:
        import re
        q_lower = chat_message.lower()

        # 例：「採用.pdf」「議事録.docx」「rules.txt」などを抽出
        wanted_file = None
        for ext in (".pdf", ".docx", ".txt", ".csv"):
            m = re.search(r"([^\s/\\]+%s)" % re.escape(ext), q_lower)
            if m:
                wanted_file = m.group(1)
                break

        folder_hits = []
        for fw in getattr(ct, "FOLDER_KEYWORDS", ("顧客","営業","マーケ","マーケティング","教育","人事","総務")):
            if fw in chat_message:
                folder_hits.append(fw)

        def _score(doc):
            meta = getattr(doc, "metadata", {}) or {}
            src = (meta.get("source") or meta.get("file_path") or meta.get("path") or "")
            srl = str(src).lower()

            # ファイル名一致を最優先（0）
            if wanted_file and wanted_file in srl:
                return (0, srl)
            # フォルダ語を含むものを次点（1）
            if folder_hits and any(k in src for k in folder_hits):
                return (1, srl)
            # URL は最後（2）― T6 のようなケースではそもそもURLも可
            if srl.startswith("http"):
                return (2, srl)
            # それ以外（3）
            return (3, srl)

        if ctx_docs:
            ctx_docs = sorted(ctx_docs, key=_score)
    except Exception:
        pass
    # =======================================================================

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
    return {
        "answer": answer_text,
        "context": ctx_docs,
    }
