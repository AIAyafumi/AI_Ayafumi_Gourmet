import os
import time
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

            if attempt < retries:

                time.sleep(1)

    raise last_error


# ============================================================
# AI用プロンプト作成
# ============================================================

def build_gourmet_prompt(
    user_text
):

    system_prompt = (
        load_gourmet_system_prompt()
    )

    prompt = (
        system_prompt
        + "\n\n【今回のユーザー依頼】\n"
        + user_text
        + "\n\n【回答】\n"
        + "ユーザーの依頼に直接答えてください。"
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

    # --------------------------------------------------------
    # Groq HTTPステータス確認
    # --------------------------------------------------------

    print(
        "Groq HTTPステータス：",
        response.status_code
    )

    # --------------------------------------------------------
    # Groqレート制限情報
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # HTTPエラーの場合
    # --------------------------------------------------------

    if response.status_code >= 400:

        print(
            "Groq HTTPエラー："
        )

        print(
            response.text[:3000]
        )

        response.raise_for_status()

    # --------------------------------------------------------
    # 生レスポンス確認
    # --------------------------------------------------------

    print(
        "Groqレスポンス："
    )

    print(
        response.text[:5000]
    )

    # --------------------------------------------------------
    # JSON解析
    # --------------------------------------------------------

    try:

        result = response.json()

    except ValueError:

        raise RuntimeError(
            "GroqのレスポンスがJSONではありません。"
        )

    # --------------------------------------------------------
    # choices確認
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # message確認
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # content取得
    # --------------------------------------------------------

    answer = message.get(
        "content",
        ""
    )

    # --------------------------------------------------------
    # finish_reason確認
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # contentが空の場合
    # --------------------------------------------------------

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
    user_text
):

    print(
        "グルメAI処理開始：",
        user_text
    )

    # --------------------------------------------------------
    # プロンプト作成
    # --------------------------------------------------------

    prompt = build_gourmet_prompt(
        user_text
    )

    # --------------------------------------------------------
    # 1. Groq
    # --------------------------------------------------------

    try:

        answer = ask_groq(
            prompt
        )

        return clean_answer(
            answer
        )

    except Exception as e:

        print(
            "Groq失敗：",
            e
        )

    # --------------------------------------------------------
    # 2. Gemini
    # --------------------------------------------------------

    try:

        answer = ask_gemini(
            prompt
        )

        return clean_answer(
            answer
        )

    except Exception as e:

        print(
            "Gemini失敗：",
            e
        )

    # --------------------------------------------------------
    # 3. OpenRouter
    # --------------------------------------------------------

    try:

        answer = ask_openrouter(
            prompt
        )

        return clean_answer(
            answer
        )

    except Exception as e:

        print(
            "OpenRouter失敗：",
            e
        )

    # --------------------------------------------------------
    # 全API失敗
    # --------------------------------------------------------

    return (
        "申し訳ありません。"
        "現在、グルメAIの処理に失敗しています。"
        "少し時間をおいてもう一度試してください。"
    )


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

        print(
            "LINE受信：",
            user_text
        )

        try:

            answer = ask_gourmet_ai(
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

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )
    )