import os
import time
import json
import requests

from flask import Flask, request, abort
from dotenv import load_dotenv

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration


# ============================================================
# 環境変数
# ============================================================

load_dotenv()

GOURMET_LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    "GOURMET_LINE_CHANNEL_ACCESS_TOKEN"
)

GOURMET_LINE_CHANNEL_SECRET = os.getenv(
    "GOURMET_LINE_CHANNEL_SECRET"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY"
)

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY"
)

TAVILY_API_KEY = os.getenv(
    "TAVILY_API_KEY"
)


# ============================================================
# API URL
# ============================================================

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/gemini-3.8-flash:generateContent"
)

GROQ_URL = (
    "https://api.groq.com/openai/v1/chat/completions"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

TAVILY_URL = (
    "https://api.tavily.com/search"
)


# ============================================================
# LINE設定
# ============================================================

configuration = Configuration(
    access_token=GOURMET_LINE_CHANNEL_ACCESS_TOKEN
)

parser = WebhookParser(
    GOURMET_LINE_CHANNEL_SECRET
)


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)


# ============================================================
# ファイルパス
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

SYSTEM_PROMPT_FILE = os.path.join(
    BASE_DIR,
    "prompts",
    "gourmet_system_prompt.txt"
)


# ============================================================
# 会話履歴
# ============================================================

conversation_histories = {}


# ============================================================
# 会話履歴の最大保持数
# ============================================================

MAX_HISTORY_MESSAGES = 20


# ============================================================
# システムプロンプト読み込み
# ============================================================

def load_gourmet_system_prompt():

    if not os.path.exists(
        SYSTEM_PROMPT_FILE
    ):
        raise FileNotFoundError(
            f"システムプロンプトが見つかりません："
            f"{SYSTEM_PROMPT_FILE}"
        )

    with open(
        SYSTEM_PROMPT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        prompt = f.read().strip()

    if not prompt:

        raise RuntimeError(
            "gourmet_system_prompt.txt が空です。"
        )

    return prompt


# ============================================================
# 会話履歴取得
# ============================================================

def get_conversation_history(
    user_id
):

    if user_id not in conversation_histories:

        conversation_histories[user_id] = []

    return conversation_histories[user_id]


# ============================================================
# 会話履歴追加
# ============================================================

def add_conversation_message(
    user_id,
    role,
    content
):

    history = get_conversation_history(
        user_id
    )

    history.append(
        {
            "role": role,
            "content": content
        }
    )

    if len(history) > MAX_HISTORY_MESSAGES:

        conversation_histories[user_id] = (
            history[-MAX_HISTORY_MESSAGES:]
        )


# ============================================================
# 会話履歴をテキスト化
# ============================================================

def format_conversation_history(
    user_id
):

    history = get_conversation_history(
        user_id
    )

    if not history:

        return "まだ過去の会話はありません。"

    lines = []

    for message in history:

        role = message.get(
            "role"
        )

        content = message.get(
            "content",
            ""
        )

        if role == "user":

            lines.append(
                "ユーザー："
                + content
            )

        elif role == "assistant":

            lines.append(
                "AI："
                + content
            )

    return "\n".join(
        lines
    )


# ============================================================
# HTTP POST リトライ
# ============================================================

def post_with_retry(
    url,
    headers=None,
    json=None,
    params=None,
    timeout=60,
    retries=1
):

    last_error = None

    for attempt in range(
        retries + 1
    ):

        try:

            response = requests.post(
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=timeout
            )

            return response

        except requests.RequestException as e:

            last_error = e

            print(
                "HTTP通信エラー：",
                e
            )

            if attempt < retries:

                print(
                    "HTTPリトライ：",
                    attempt + 1
                )

                time.sleep(1)

    raise last_error


# ============================================================
# Tavily Web検索
# ============================================================

def search_tavily(
    query
):

    print(
        "Tavily検索開始：",
        query
    )

    if not TAVILY_API_KEY:

        print(
            "TAVILY_API_KEY が設定されていません。"
        )

        return []

    data = {

        "api_key":
            TAVILY_API_KEY,

        "query":
            query,

        "search_depth":
            "basic",

        "topic":
            "general",

        "max_results":
            5,

        "include_answer":
            False,

        "include_raw_content":
            False

    }

    try:

        response = post_with_retry(
            TAVILY_URL,
            headers={
                "Content-Type":
                    "application/json"
            },
            json=data,
            timeout=30,
            retries=1
        )

    except Exception as e:

        print(
            "Tavily通信エラー：",
            e
        )

        return []

    print(
        "Tavily HTTPステータス：",
        response.status_code
    )

    if response.status_code >= 400:

        print(
            "Tavily HTTPエラー："
        )

        print(
            response.text[:3000]
        )

        return []

    try:

        result = response.json()

    except ValueError:

        print(
            "TavilyレスポンスがJSONではありません。"
        )

        return []

    results = result.get(
        "results",
        []
    )

    print(
        "Tavily検索件数：",
        len(results)
    )

    return results


# ============================================================
# Tavily検索が必要か判定
# ============================================================

def should_search_tavily(
    user_text
):

    keywords = [

        "店",
        "店舗",
        "レストラン",
        "飲食店",
        "食事",
        "グルメ",
        "ラーメン",
        "つけ麺",
        "そば",
        "うどん",
        "寿司",
        "すし",
        "焼肉",
        "焼き肉",
        "居酒屋",
        "焼き鳥",
        "カレー",
        "中華",
        "イタリアン",
        "フレンチ",
        "ハンバーグ",
        "とんかつ",
        "天ぷら",
        "しゃぶしゃぶ",
        "ステーキ",
        "ピザ",
        "パスタ",
        "閉店",
        "営業",
        "営業時間",
        "予約",
        "おすすめ",
        "人気",
        "近く",
        "近所",
        "堀之内",
        "南大沢",
        "八王子",
        "多摩",
        "聖蹟桜ヶ丘"

    ]

    return any(
        keyword in user_text
        for keyword in keywords
    )


# ============================================================
# Tavily検索結果をAI用テキストに変換
# ============================================================

def format_tavily_results(
    results
):

    if not results:

        return (
            "今回のWeb検索では、"
            "有力な情報を取得できませんでした。"
        )

    lines = []

    for index, result in enumerate(
        results,
        start=1
    ):

        title = result.get(
            "title",
            ""
        )

        url = result.get(
            "url",
            ""
        )

        content = result.get(
            "content",
            ""
        )

        lines.append(
            f"{index}. {title}\n"
            f"URL: {url}\n"
            f"内容: {content}"
        )

    return "\n\n".join(
        lines
    )


# ============================================================
# レストラン情報のWeb検索
# ============================================================

def get_tavily_context(
    user_text
):

    if not should_search_tavily(
        user_text
    ):

        return ""

    query = (
        user_text
        + " 店舗 営業 閉店 最新情報"
    )

    results = search_tavily(
        query
    )

    formatted = format_tavily_results(
        results
    )

    return formatted


# ============================================================
# AI用プロンプト作成
# ============================================================

def build_gourmet_prompt(
    user_id,
    user_text
):

    system_prompt = (
        load_gourmet_system_prompt()
    )

    conversation_history = (
        format_conversation_history(
            user_id
        )
    )

    tavily_context = get_tavily_context(
        user_text
    )

    prompt = (
        system_prompt

        + "\n\n"
        + "【過去の会話】\n"
        + conversation_history

        + "\n\n"
        + "【今回のユーザー依頼】\n"
        + user_text
    )

    if tavily_context:

        prompt += (

            "\n\n"
            + "【Web検索による最新情報】\n"
            + tavily_context

            + "\n\n"

            + "【Web情報の利用ルール】\n"

            + "上記のWeb検索結果は、"
            + "店舗の営業状況、閉店情報、"
            + "営業時間、店舗情報などを"
            + "確認するための参考情報です。"

            + "特に閉店・移転・営業終了などの情報が"
            + "見つかった場合は重要視してください。"

            + "ユーザーに店舗をおすすめする場合、"
            + "閉店した店舗を営業中の店舗として"
            + "おすすめしないでください。"

            + "Web検索結果だけで断定できない場合は、"
            + "断定を避けてください。"

            + "Web検索結果とユーザーの依頼を踏まえて、"
            + "現在利用できる可能性が高い店舗を"
            + "優先してください。"
        )

    prompt += (

        "\n\n"
        + "【回答】\n"
        + "過去の会話を踏まえて、"
        + "今回のユーザーの発言に直接答えてください。"

        + "すでにユーザーが答えた情報を、"
        + "もう一度質問しないでください。"
    )

    print(
        "APIプロンプト文字数：",
        len(prompt)
    )

    return prompt


# ============================================================
# Gemini
# ============================================================

def ask_gemini(
    prompt
):

    print(
        "Gemini処理開始..."
    )

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "GEMINI_API_KEY が設定されていません。"
        )

    headers = {
        "Content-Type": "application/json"
    }

    params = {
        "key": GEMINI_API_KEY
    }

    data = {

        "contents": [

            {
                "parts": [

                    {
                        "text": prompt
                    }

                ]
            }

        ],

        "generationConfig": {

            "temperature": 0.7,

            "maxOutputTokens": 2500

        }

    }

    response = post_with_retry(
        GEMINI_URL,
        headers=headers,
        params=params,
        json=data,
        timeout=60,
        retries=0
    )

    if response.status_code >= 400:

        print(
            "HTTPエラー：",
            response.status_code
        )

        print(
            response.text[:3000]
        )

        response.raise_for_status()

    result = response.json()

    try:

        answer = (
            result["candidates"][0]
            ["content"]
            ["parts"][0]
            ["text"]
        )

    except (
        KeyError,
        IndexError,
        TypeError
    ):

        print(
            "Geminiレスポンス："
        )

        print(
            response.text[:3000]
        )

        raise RuntimeError(
            "Geminiの回答本文を取得できませんでした。"
        )

    if not answer.strip():

        raise RuntimeError(
            "Geminiの回答本文が空です。"
        )

    print(
        "Gemini成功"
    )

    return answer


# ============================================================
# Groq
# ============================================================

def ask_groq(
    prompt
):

    print(
        "Groq処理開始..."
    )

    if not GROQ_API_KEY:

        raise RuntimeError(
            "GROQ_API_KEY が設定されていません。"
        )

    headers = {

        "Authorization":
            f"Bearer {GROQ_API_KEY}",

        "Content-Type":
            "application/json"

    }

    data = {

        "model":
            "openai/gpt-oss-20b",

        "messages": [

            {
                "role": "user",
                "content": prompt
            }

        ],

        "temperature":
            0.7,

        "max_tokens":
            2500

    }

    response = post_with_retry(
        GROQ_URL,
        headers=headers,
        json=data,
        timeout=60,
        retries=0
    )

    print(
        "Groq HTTPステータス：",
        response.status_code
    )

    print(
        "Groq RateLimit残りリクエスト：",
        response.headers.get(
            "x-ratelimit-remaining-requests"
        )
    )

    print(
        "Groq RateLimit残りトークン：",
        response.headers.get(
            "x-ratelimit-remaining-tokens"
        )
    )

    print(
        "Groq RateLimitリセット：",
        response.headers.get(
            "x-ratelimit-reset-tokens"
        )
    )

    if response.status_code >= 400:

        print(
            "Groq HTTPエラー："
        )

        print(
            response.text[:3000]
        )

        response.raise_for_status()

    print(
        "Groqレスポンス："
    )

    print(
        response.text[:5000]
    )

    try:

        result = response.json()

    except ValueError:

        raise RuntimeError(
            "GroqのレスポンスがJSONではありません。"
        )

    choices = result.get(
        "choices"
    )

    if not choices:

        print(
            "Groq choices が存在しません。"
        )

        print(
            "Groq JSON：",
            result
        )

        raise RuntimeError(
            "Groqのchoicesが空です。"
        )

    message = choices[0].get(
        "message"
    )

    if not message:

        print(
            "Groq message が存在しません。"
        )

        print(
            "Groq choice：",
            choices[0]
        )

        raise RuntimeError(
            "Groqのmessageがありません。"
        )

    answer = message.get(
        "content",
        ""
    )

    print(
        "Groq finish_reason：",
        choices[0].get(
            "finish_reason"
        )
    )

    print(
        "Groq content文字数：",
        len(answer)
        if isinstance(answer, str)
        else "文字列ではありません"
    )

    if not isinstance(
        answer,
        str
    ):

        raise RuntimeError(
            "Groqの回答contentが文字列ではありません。"
        )

    if not answer.strip():

        print(
            "Groq message 全体：",
            message
        )

        raise RuntimeError(
            "Groqの回答本文が空です。"
        )

    print(
        "Groq成功"
    )

    return answer


# ============================================================
# OpenRouter
# ============================================================

def ask_openrouter(
    prompt
):

    print(
        "OpenRouter処理開始..."
    )

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY が設定されていません。"
        )

    headers = {

        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json",

        "HTTP-Referer":
            "https://github.com/",

        "X-Title":
            "AI Ayafumi Gourmet"

    }

    data = {

        "model":
            "openai/gpt-oss-20b",

        "messages": [

            {
                "role": "user",
                "content": prompt
            }

        ],

        "temperature":
            0.7,

        "max_tokens":
            2500

    }

    response = post_with_retry(
        OPENROUTER_URL,
        headers=headers,
        json=data,
        timeout=90,
        retries=0
    )

    if response.status_code >= 400:

        print(
            "OpenRouter HTTPエラー：",
            response.status_code
        )

        print(
            response.text[:3000]
        )

        response.raise_for_status()

    result = response.json()

    try:

        answer = (
            result["choices"][0]
            ["message"]
            ["content"]
        )

    except (
        KeyError,
        IndexError,
        TypeError
    ):

        print(
            "OpenRouterレスポンス："
        )

        print(
            response.text[:3000]
        )

        raise RuntimeError(
            "OpenRouterの回答本文を取得できませんでした。"
        )

    if not answer.strip():

        raise RuntimeError(
            "OpenRouterの回答本文が空です。"
        )

    print(
        "OpenRouter成功"
    )

    return answer


# ============================================================
# 回答クリーニング
# ============================================================

def clean_answer(
    answer
):

    if not answer:

        return ""

    answer = answer.strip()

    return answer


# ============================================================
# AIグルメ処理
# ============================================================

def ask_gourmet_ai(
    user_id,
    user_text
):

    print(
        "グルメAI処理開始：",
        user_text
    )

    print(
        "会話ユーザーID：",
        user_id
    )

    history = get_conversation_history(
        user_id
    )

    print(
        "現在の会話履歴件数：",
        len(history)
    )

    prompt = build_gourmet_prompt(
        user_id,
        user_text
    )

    answer = None

    # --------------------------------------------------------
    # 1. Groq
    # --------------------------------------------------------

    try:

        answer = ask_groq(
            prompt
        )

    except Exception as e:

        print(
            "Groq失敗：",
            e
        )

    # --------------------------------------------------------
    # 2. Gemini
    # --------------------------------------------------------

    if not answer:

        try:

            answer = ask_gemini(
                prompt
            )

        except Exception as e:

            print(
                "Gemini失敗：",
                e
            )

    # --------------------------------------------------------
    # 3. OpenRouter
    # --------------------------------------------------------

    if not answer:

        try:

            answer = ask_openrouter(
                prompt
            )

        except Exception as e:

            print(
                "OpenRouter失敗：",
                e
            )

    # --------------------------------------------------------
    # 全API失敗
    # --------------------------------------------------------

    if not answer:

        return (
            "申し訳ありません。"
            "現在、グルメAIの処理に失敗しています。"
            "少し時間をおいてもう一度試してください。"
        )

    answer = clean_answer(
        answer
    )

    add_conversation_message(
        user_id,
        "user",
        user_text
    )

    add_conversation_message(
        user_id,
        "assistant",
        answer
    )

    print(
        "会話履歴更新後の件数：",
        len(
            get_conversation_history(
                user_id
            )
        )
    )

    return answer


# ============================================================
# LINE返信
# ============================================================

def reply_to_line(
    reply_token,
    text
):

    with ApiClient(
        configuration
    ) as api_client:

        messaging_api = MessagingApi(
            api_client
        )

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,

                messages=[
                    TextMessage(
                        text=text
                    )
                ]
            )
        )


# ============================================================
# Health Check
# ============================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health():

    print(
        "HEALTH CHECK"
    )

    return {
        "status": "ok"
    }, 200


# ============================================================
# PowerShell / API テスト用
# ============================================================

@app.route(
    "/test",
    methods=["POST"]
)
def test():

    print(
        "TEST ROUTE START"
    )

    raw_body = request.get_data(
        as_text=True
    )

    print(
        "TEST Content-Type：",
        request.content_type
    )

    print(
        "TEST Raw Body：",
        raw_body
    )

    print(
        "TEST Request Headers：",
        dict(request.headers)
    )

    data = request.get_json(
        silent=True
    )

    print(
        "TEST Parsed JSON：",
        data
    )

    if data is None and raw_body:

        try:

            data = json.loads(
                raw_body
            )

            print(
                "TEST Manual JSON Parse：",
                data
            )

        except json.JSONDecodeError as e:

            print(
                "TEST Manual JSON Parse Error：",
                e
            )

            return {
                "error": "JSON解析に失敗しました。",
                "content_type": request.content_type,
                "raw_body": raw_body,
                "parse_error": str(e)
            }, 400

    if not data:

        return {
            "error": "JSONを取得できませんでした。",
            "content_type": request.content_type,
            "raw_body": raw_body
        }, 400

    if "message" not in data:

        return {
            "error": "message が指定されていません。",
            "received_data": data
        }, 400

    user_text = data["message"]

    if not isinstance(
        user_text,
        str
    ):

        return {
            "error": "message は文字列で指定してください。"
        }, 400

    user_text = user_text.strip()

    if not user_text:

        return {
            "error": "message が空です。"
        }, 400

    print(
        "テスト受信：",
        user_text
    )

    test_user_id = "powershell-test"

    try:

        answer = ask_gourmet_ai(
            test_user_id,
            user_text
        )

        print(
            "テスト回答：",
            answer
        )

        return {
            "message": user_text,
            "answer": answer
        }

    except Exception as e:

        print(
            "テスト処理エラー：",
            e
        )

        return {
            "error": str(e)
        }, 500


# ============================================================
# LINE Webhook
# ============================================================

@app.route(
    "/callback",
    methods=["POST"]
)
def callback():

    signature = request.headers.get(
        "X-Line-Signature"
    )

    body = request.get_data(
        as_text=True
    )

    try:

        events = parser.parse(
            body,
            signature
        )

    except InvalidSignatureError:

        abort(400)

    for event in events:

        if not isinstance(
            event,
            MessageEvent
        ):

            continue

        if not isinstance(
            event.message,
            TextMessageContent
        ):

            continue

        user_text = (
            event.message.text
        )

        user_id = event.source.user_id

        print(
            "LINE受信：",
            user_text
        )

        print(
            "LINEユーザーID：",
            user_id
        )

        try:

            answer = ask_gourmet_ai(
                user_id,
                user_text
            )

            reply_to_line(
                event.reply_token,
                answer
            )

        except Exception as e:

            print(
                "LINE処理エラー：",
                e
            )

            reply_to_line(
                event.reply_token,
                "申し訳ありません。"
                "処理中にエラーが発生しました。"
            )

    return "OK"


# ============================================================
# 起動
# ============================================================

if __name__ == "__main__":

    print(
        "AIアヤフミ（レストラン）起動開始"
    )

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )
    )