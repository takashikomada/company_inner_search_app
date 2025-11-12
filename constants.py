"""
このファイルは、固定の文字列や数値などのデータを変数として一括管理するファイルです。
"""

############################################################
# ライブラリの読み込み
############################################################
from langchain_community.document_loaders import (
    PyMuPDFLoader,        # PDF 用（pymupdf が必要）
    Docx2txtLoader,       # DOCX 用（docx2txt が必要）
    TextLoader,           # TXT 用
)
from langchain_community.document_loaders.csv_loader import CSVLoader

############################################################
# 共通変数の定義
############################################################

# 画面表示系
APP_NAME = "社内情報特化型生成AI検索アプリ"
ANSWER_MODE_1 = "社内文書検索"
ANSWER_MODE_2 = "社内問い合わせ"
CHAT_INPUT_HELPER_TEXT = "こちらからメッセージを送信してください。"
DOC_SOURCE_ICON = ":material/description: "
LINK_SOURCE_ICON = ":material/link: "
WARNING_ICON = ":material/warning:"
ERROR_ICON = ":material/error:"
SPINNER_TEXT = "回答生成中..."

# ログ出力系
LOG_DIR_PATH = "./logs"
LOGGER_NAME = "ApplicationLog"
LOG_FILE = "application.log"
APP_BOOT_MESSAGE = "アプリが起動されました。"

# LLM設定系
MODEL = "gpt-4o-mini"
TEMPERATURE = 0.5

# RAG参照用のデータソース系
DATA_DIR = "data"
RAG_TOP_FOLDER_PATH = "./data"

# 社員名簿CSVのパス（存在しない場合は utils 側のアップロード導線で対応）
STAFF_CSV = r"data/社員について/社員名簿.csv"

# 拡張子マップ（課題5のTXT取り込みに対応 / 文字コードは自動判定）
SUPPORTED_EXTENSIONS = {
    ".pdf":  PyMuPDFLoader,
    ".docx": Docx2txtLoader,
    ".csv":  lambda path: CSVLoader(path, encoding="utf-8"),  # 必要なら 'utf-8-sig' に変更可
    ".txt":  lambda path: TextLoader(path, encoding="utf-8", autodetect_encoding=True),
}

WEB_URL_LOAD_TARGETS = [
    "https://generative-ai.web-camp.io/"
]

# 分割・検索パラメータ
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 5
CHUNK_SIZE_WEB = 2000
FOLDER_KEYWORDS = ("顧客","営業","マーケ","マーケティング","教育","人事","総務")

# プロンプトテンプレート
SYSTEM_PROMPT_CREATE_INDEPENDENT_TEXT = "会話履歴と最新の入力をもとに、会話履歴なしでも理解できる独立した入力テキストを生成してください。"

# 修正: 関連がある場合は文脈に基づいて回答する（空文字を返さない）
SYSTEM_PROMPT_DOC_SEARCH = """
あなたは社内の文書検索アシスタントです。以下の条件に従って回答してください。

【条件】
1. ユーザー入力と以下の文脈に関連がある場合、文脈に基づいて簡潔かつ正確に回答してください。
2. 関連性が低い場合は、「該当資料なし」と回答してください。
3. 回答の最後に、参照したファイルパス（必要ならページ番号）を列挙してください。

【文脈】
{context}
"""

SYSTEM_PROMPT_INQUIRY = """
あなたは社内情報特化型のアシスタントです。以下の条件に従って回答してください。

【条件】
1. ユーザー入力と以下の文脈に関連がある場合は、文脈に基づいて回答してください。
2. 関連が明らかに低い場合は、「回答に必要な情報が見つかりませんでした。」と回答してください。
3. 憶測で断定せず、分かる範囲で根拠を示してください。
4. できる限り詳細に、マークダウン記法を使って回答してください（最も大きい見出しは h3）。
5. 複雑な質問は項目ごとに整理して回答してください。

{context}
"""

# レスポンス一致判定用
INQUIRY_NO_MATCH_ANSWER = "回答に必要な情報が見つかりませんでした。"
NO_DOC_MATCH_ANSWER = "該当資料なし"

# エラー・警告メッセージ
COMMON_ERROR_MESSAGE = "このエラーが繰り返し発生する場合は、管理者にお問い合わせください。"
INITIALIZE_ERROR_MESSAGE = "初期化処理に失敗しました。"
NO_DOC_MATCH_MESSAGE = """
入力内容と関連する社内文書が見つかりませんでした。\n
入力内容を変更してください。
"""
CONVERSATION_LOG_ERROR_MESSAGE = "過去の会話履歴の表示に失敗しました。"
GET_LLM_RESPONSE_ERROR_MESSAGE = "回答生成に失敗しました。"
DISP_ANSWER_ERROR_MESSAGE = "回答表示に失敗しました。"

# ベクターストア・Web取り込みフラグ
CHROMA_DIR = "./chroma_store"
ENABLE_WEB_SCRAPE = False
