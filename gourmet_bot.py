import os
import time
import json
import requests

from flask import Flask, request, jsonify
from dotenv import load_dotenv

from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError


# =========================================================
# 環境変数
# =========================================================

load_dotenv()

GOURMET_LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    "GOURMET_LINE_CHANNEL_ACCESS_TOKEN"
)

GOURMET_LINE_CHANNEL_SECRET = os.getenv(
    "GOURMET_LINE_CHANNEL_SECRET"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
HOTPEPPER_API_KEY = os.getenv("HOTPEPPER_API_KEY")


# =========================================================
# API URL
# =========================================================

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/gemini-3.8-flash:generateContent"
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

TAVILY_URL = "https://api.tavily.com/search"

HOTPEPPER_URL = (
    "https://webservice.recruit.co.jp/"
    "hotpepper/gourmet/v1/"
)


# =========================================================
# LINE設定
# =========================================================

line_configuration = Configuration(
    access_token=GOURMET_LINE_CHANNEL_ACCESS_TOKEN
)

line_parser = WebhookParser(
    GOURMET_LINE_CHANNEL_SECRET
)


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)


# =========================================================
# プロンプト
# =========================================================

SYSTEM_PROMPT_FILE = os.path.join(
    os.path.dirname(__file__),
    "prompts",
    "gourmet_system_prompt.txt"
)


# =========================================================
# 会話履歴
# =========================================================

conversation_histories = {}

MAX_HISTORY_MESSAGES = 20


def load_gourmet_system_prompt():
    try:
        with open(
            SYSTEM_PROMPT_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return f.read()

    except Exception as e:
        print("システムプロンプト読み込みエラー：", e)

        return """
あなたはAIアヤフミのレストラン検索AIです。

ユーザーの希望条件をもとに、実在する飲食店を探してください。

店舗情報は推測で作らないでください。
検索結果にない店舗を勝手に作らないでください。
営業時間や閉店情報が確認できる場合は、それを考慮してください。
"""


def get_conversation_history(user_id):
    return conversation_histories.get(user_id, [])


def add_conversation_message(user_id, role, content):

    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_histories[user_id].append({
        "role": role,
        "content": content
    })

    conversation_histories[user_id] = (
        conversation_histories[user_id][-MAX_HISTORY_MESSAGES:]
    )


# =========================================================
# HTTPリトライ
# =========================================================

def post_with_retry(
    url,
    headers=None,
    json_data=None,
    params=None,
    timeout=30,
    retries=3
):

    last_error = None

    for attempt in range(retries):

        try:

            response = requests.post(
                url,
                headers=headers,
                json=json_data,
                params=params,
                timeout=timeout
            )

            return response

        except Exception as e:

            last_error = e

            print(
                f"HTTPエラー attempt={attempt + 1}/{retries}:",
                e
            )

            if attempt < retries - 1:
                time.sleep(2)

    raise last_error


# =========================================================
# LINE Quick Reply
# =========================================================

def make_quick_reply(items):

    quick_reply_items = []

    for item in items:

        quick_reply_items.append(
            QuickReplyItem(
                action=MessageAction(
                    label=item,
                    text=item
                )
            )
        )

    return QuickReply(
        items=quick_reply_items
    )


def reply_to_line(
    reply_token,
    text,
    quick_reply_items=None
):

    with ApiClient(line_configuration) as api_client:

        messaging_api = MessagingApi(api_client)

        if quick_reply_items:

            message = TextMessage(
                text=text,
                quick_reply=make_quick_reply(
                    quick_reply_items
                )
            )

        else:

            message = TextMessage(
                text=text
            )

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[message]
            )
        )


# =========================================================
# LINE 選択状態
# =========================================================

gourmet_search_states = {}


def create_new_search_state():

    return {
        "step": "location",
        "location": None,
        "genre": None,
        "people": None,
        "budget": None,
        "time": None,
    }


def start_gourmet_search(user_id):

    gourmet_search_states[user_id] = (
        create_new_search_state()
    )


def get_gourmet_search_state(user_id):

    if user_id not in gourmet_search_states:

        gourmet_search_states[user_id] = (
            create_new_search_state()
        )

    return gourmet_search_states[user_id]


# =========================================================
# 選択肢
# =========================================================

LOCATION_OPTIONS = [
    "京王堀之内駅",
    "南大沢駅",
    "多摩センター駅",
    "八王子駅",
]

GENRE_OPTIONS = [
    "ラーメン",
    "焼肉",
    "寿司",
    "居酒屋",
    "イタリアン",
    "その他",
]

PEOPLE_OPTIONS = [
    "1人",
    "2人",
    "3人",
    "4人",
    "5人以上",
]

BUDGET_OPTIONS = [
    "～1,000円",
    "1,000～1,500円",
    "1,500～2,000円",
    "2,000～3,000円",
    "3,000円～",
]

TIME_OPTIONS = [
    "今から",
    "昼",
    "夜",
]


# =========================================================
# LINE選択画面
# =========================================================

def send_location_selection(reply_token):

    reply_to_line(
        reply_token,
        "📍 お店を探す場所を選んでください。",
        LOCATION_OPTIONS
    )


def send_genre_selection(reply_token):

    reply_to_line(
        reply_token,
        "🍴 ジャンルを選んでください。",
        GENRE_OPTIONS
    )


def send_people_selection(reply_token):

    reply_to_line(
        reply_token,
        "👤 利用人数を選んでください。",
        PEOPLE_OPTIONS
    )


def send_budget_selection(reply_token):

    reply_to_line(
        reply_token,
        "💰 予算を選んでください。",
        BUDGET_OPTIONS
    )


def send_time_selection(reply_token):

    reply_to_line(
        reply_token,
        "⏰ 利用する時間を選んでください。",
        TIME_OPTIONS
    )


def send_confirmation(
    reply_token,
    state
):

    text = (
        "🔎 検索条件を確認してください。\n\n"
        f"📍 場所：{state['location']}\n"
        f"🍴 ジャンル：{state['genre']}\n"
        f"👤 人数：{state['people']}\n"
        f"💰 予算：{state['budget']}\n"
        f"⏰ 時間：{state['time']}\n\n"
        "この条件でお店を探しますか？"
    )

    reply_to_line(
        reply_token,
        text,
        [
            "この条件で検索",
            "最初から"
        ]
    )


# =========================================================
# Hot Pepper検索判定
# =========================================================

def should_search_hotpepper(user_text):

    keywords = [
        "店",
        "お店",
        "飲食店",
        "レストラン",
        "ラーメン",
        "焼肉",
        "寿司",
        "居酒屋",
        "イタリアン",
        "カフェ",
        "バー",
        "食事",
        "ランチ",
        "ディナー",
        "探して",
        "検索",
        "おすすめ",
    ]

    return any(
        keyword in user_text
        for keyword in keywords
    )


# =========================================================
# Hot Pepper検索用キーワード抽出
# =========================================================

def build_hotpepper_keyword(user_text):

    """
    LINEの選択条件から、
    Hot Pepper検索に必要な「場所＋ジャンル」だけを抽出する。

    例：

    京王堀之内駅でラーメンを探す。
    予算は～1,000円。
    1人で利用。
    利用時間は今から。

    ↓

    京王堀之内駅 ラーメン
    """

    location = ""
    genre = ""

    # -----------------------------------------------------
    # 選択式フローから作られた文章
    # -----------------------------------------------------

    if "で" in user_text and "を探す" in user_text:

        try:

            before = user_text.split("で", 1)[0].strip()

            if before:
                location = before

        except Exception:
            pass

    # -----------------------------------------------------
    # ジャンル
    # -----------------------------------------------------

    genres = [
        "ラーメン",
        "焼肉",
        "寿司",
        "居酒屋",
        "イタリアン",
        "カフェ",
        "バー",
        "中華",
        "焼き鳥",
        "韓国料理",
        "しゃぶしゃぶ",
        "うどん",
        "そば",
    ]

    for g in genres:

        if g in user_text:

            genre = g
            break

    # -----------------------------------------------------
    # structured selection fallback
    # -----------------------------------------------------

    if not location:

        for candidate in LOCATION_OPTIONS:

            if candidate in user_text:

                location = candidate
                break

    # -----------------------------------------------------
    # location + genre
    # -----------------------------------------------------

    if location and genre:

        keyword = f"{location} {genre}"

    elif location:

        keyword = location

    elif genre:

        keyword = genre

    else:

        # 従来の自然言語検索用 fallback
        keyword = user_text

        remove_words = [
            "で",
            "を探して",
            "を探す",
            "探して",
            "検索して",
            "おすすめ",
            "お店",
            "店舗",
            "レストラン",
            "予算",
            "人数",
            "利用時間",
            "今から",
            "昼",
            "夜",
        ]

        for word in remove_words:

            keyword = keyword.replace(
                word,
                " "
            )

    keyword = " ".join(
        keyword.split()
    ).strip()

    return keyword


# =========================================================
# Hot Pepper検索
# =========================================================

def search_hotpepper(user_text):

    if not HOTPEPPER_API_KEY:

        print("HOTPEPPER_API_KEYが設定されていません")

        return []

    keyword = build_hotpepper_keyword(
        user_text
    )

    print(
        "Hot Pepper検索キーワード：",
        keyword
    )

    params = {
        "key": HOTPEPPER_API_KEY,
        "keyword": keyword,
        "format": "json",
        "count": 10,
        "order": 4,
    }

    try:

        response = requests.get(
            HOTPEPPER_URL,
            params=params,
            timeout=30
        )

        print(
            "Hot Pepper HTTPステータス：",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "Hot Pepperエラー：",
                response.text[:1000]
            )

            return []

        data = response.json()

        results = (
            data
            .get("results", {})
            .get("shop", [])
        )

        print(
            "Hot Pepper検索件数：",
            len(results)
        )

        candidates = []

        for shop in results:

            budget = shop.get(
                "budget",
                {}
            )

            genre = shop.get(
                "genre",
                {}
            )

            station = ""

            station_data = shop.get(
                "station",
                []
            )

            if station_data:

                try:

                    station = station_data[0].get(
                        "name",
                        ""
                    )

                except Exception:
                    station = ""

            candidate = {

                "name": shop.get(
                    "name",
                    ""
                ),

                "genre": genre.get(
                    "name",
                    ""
                ),

                "address": shop.get(
                    "address",
                    ""
                ),

                "station": station,

                "budget_average": budget.get(
                    "average",
                    ""
                ),

                "lunch": budget.get(
                    "lunch",
                    ""
                ),

                "url": shop.get(
                    "urls",
                    {}
                ).get(
                    "pc",
                    ""
                ),
            }

            candidates.append(
                candidate
            )

        print(
            "Hot Pepper取得件数：",
            len(candidates)
        )

        # -------------------------------------------------
        # Tavilyで店舗ごとの営業状況確認
        # -------------------------------------------------

        candidates = verify_hotpepper_shops_with_tavily(
            candidates
        )

        return candidates

    except Exception as e:

        print(
            "Hot Pepper検索エラー：",
            e
        )

        return []


# =========================================================
# Hot Pepper候補フォーマット
# =========================================================

def format_hotpepper_results(candidates):

    if not candidates:

        return "Hot Pepperから該当店舗は見つかりませんでした。"

    lines = []

    for index, shop in enumerate(
        candidates,
        start=1
    ):

        lines.append(
            f"{index}. {shop.get('name', '')}"
        )

        lines.append(
            f"   ジャンル：{shop.get('genre', '')}"
        )

        lines.append(
            f"   住所：{shop.get('address', '')}"
        )

        if shop.get("station"):

            lines.append(
                f"   最寄駅：{shop.get('station')}"
            )

        if shop.get("budget_average"):

            lines.append(
                f"   予算：{shop.get('budget_average')}"
            )

        if shop.get("lunch"):

            lines.append(
                f"   ランチ：{shop.get('lunch')}"
            )

        lines.append(
            f"   Hot Pepper：{shop.get('url', '')}"
        )

        if shop.get("tavily_status"):

            lines.append(
                f"   営業確認：{shop.get('tavily_status')}"
            )

        if shop.get("tavily_reason"):

            lines.append(
                f"   確認内容：{shop.get('tavily_reason')}"
            )

        lines.append("")

    return "\n".join(lines)


# =========================================================
# Tavily
# =========================================================

def search_tavily(query):

    if not TAVILY_API_KEY:

        print(
            "TAVILY_API_KEYが設定されていません"
        )

        return []

    print(
        "Tavily検索開始：",
        query
    )

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
    }

    try:

        response = requests.post(
            TAVILY_URL,
            json=payload,
            timeout=30
        )

        print(
            "Tavily HTTPステータス：",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "Tavilyエラー：",
                response.text[:1000]
            )

            return []

        data = response.json()

        results = data.get(
            "results",
            []
        )

        print(
            "Tavily検索件数：",
            len(results)
        )

        return results

    except Exception as e:

        print(
            "Tavily検索エラー：",
            e
        )

        return []


# =========================================================
# Hot Pepper店舗をTavilyで営業確認
# =========================================================

def check_hotpepper_shop_with_tavily(shop):

    shop_name = shop.get(
        "name",
        ""
    )

    if not shop_name:

        return (
            "unknown",
            "店舗名が取得できませんでした"
        )

    query = (
        f'"{shop_name}" '
        "営業時間 営業中 閉店 移転 最新情報"
    )

    results = search_tavily(
        query
    )

    if not results:

        return (
            "unknown",
            "Tavilyで確認情報を取得できませんでした"
        )

    closed_score = 0
    open_score = 0

    evidence = []

    closed_keywords = [
        "閉店",
        "営業終了",
        "閉業",
        "廃業",
        "閉鎖",
        "移転",
        "営業していない",
    ]

    open_keywords = [
        "営業中",
        "営業しています",
        "営業",
        "営業時間",
        "営業再開",
        "営業開始",
    ]

    for result in results:

        title = result.get(
            "title",
            ""
        )

        content = result.get(
            "content",
            ""
        )

        text = (
            f"{title} {content}"
        )

        for keyword in closed_keywords:

            if keyword in text:

                closed_score += 1

                evidence.append(
                    f"閉店系：{keyword}"
                )

        for keyword in open_keywords:

            if keyword in text:

                open_score += 1

                evidence.append(
                    f"営業系：{keyword}"
                )

    reason = " / ".join(
        evidence[:5]
    )

    if (
        closed_score >= 3
        and closed_score > open_score
    ):

        return (
            "closed",
            reason or "閉店情報が複数確認されました"
        )

    if open_score > 0:

        return (
            "open",
            reason or "営業情報を確認しました"
        )

    return (
        "unknown",
        reason or "営業状況を確定できませんでした"
    )


def verify_hotpepper_shops_with_tavily(
    candidates
):

    if not candidates:

        print(
            "Hot Pepper店舗候補なし"
        )

        return []

    verified = []

    for shop in candidates:

        name = shop.get(
            "name",
            ""
        )

        print(
            "----------------------------------------"
        )

        print(
            "Tavily店舗確認：",
            name
        )

        status, reason = (
            check_hotpepper_shop_with_tavily(
                shop
            )
        )

        shop["tavily_status"] = status
        shop["tavily_reason"] = reason

        print(
            "Tavily判定：",
            status
        )

        print(
            "Tavily理由：",
            reason
        )

        if status == "closed":

            print(
                "閉店店舗として除外：",
                name
            )

            continue

        verified.append(
            shop
        )

    for index, shop in enumerate(
        verified,
        start=1
    ):

        shop["number"] = index

    print(
        "Tavily確認後の店舗数：",
        len(verified)
    )

    return verified


# =========================================================
# Tavily一般検索
# =========================================================

def should_search_tavily(user_text):

    keywords = [
        "最新",
        "営業",
        "閉店",
        "営業時間",
        "今",
        "現在",
        "おすすめ",
        "店",
        "お店",
        "レストラン",
        "ラーメン",
        "焼肉",
        "寿司",
        "居酒屋",
    ]

    return any(
        keyword in user_text
        for keyword in keywords
    )


def format_tavily_results(results):

    if not results:

        return ""

    lines = []

    for index, result in enumerate(
        results,
        start=1
    ):

        title = result.get(
            "title",
            ""
        )

        content = result.get(
            "content",
            ""
        )

        url = result.get(
            "url",
            ""
        )

        lines.append(
            f"{index}. {title}"
        )

        if content:

            lines.append(
                f"   {content[:500]}"
            )

        if url:

            lines.append(
                f"   URL: {url}"
            )

        lines.append("")

    return "\n".join(lines)


def get_tavily_context(user_text):

    if not should_search_tavily(
        user_text
    ):

        return ""

    query = (
        f"{user_text} "
        "店舗 営業 閉店 最新情報"
    )

    results = search_tavily(
        query
    )

    return format_tavily_results(
        results
    )


# =========================================================
# グルメAIプロンプト
# =========================================================

def build_gourmet_prompt(
    user_id,
    user_text
):

    system_prompt = (
        load_gourmet_system_prompt()
    )

    history = get_conversation_history(
        user_id
    )

    # -----------------------------------------------------
    # Hot Pepper
    #
    # ここが今回の重要修正。
    #
    # user_text全体ではなく、
    # build_hotpepper_keyword() で
    # 「場所＋ジャンル」だけを検索する。
    # -----------------------------------------------------

    hotpepper_results = []

    if should_search_hotpepper(
        user_text
    ):

        print(
            "Hot Pepper検索開始：",
            user_text
        )

        hotpepper_results = search_hotpepper(
            user_text
        )

    hotpepper_context = (
        format_hotpepper_results(
            hotpepper_results
        )
    )

    # -----------------------------------------------------
    # Tavily
    # -----------------------------------------------------

    tavily_context = (
        get_tavily_context(
            user_text
        )
    )

    # -----------------------------------------------------
    # 会話履歴
    # -----------------------------------------------------

    history_text = ""

    if history:

        history_lines = []

        for message in history:

            role = message.get(
                "role",
                ""
            )

            content = message.get(
                "content",
                ""
            )

            if role == "user":

                history_lines.append(
                    f"ユーザー：{content}"
                )

            elif role == "assistant":

                history_lines.append(
                    f"AIアヤフミ：{content}"
                )

        history_text = "\n".join(
            history_lines
        )

    # -----------------------------------------------------
    # 最終プロンプト
    # -----------------------------------------------------

    prompt = f"""
{system_prompt}

========================================
今回のユーザー検索条件
========================================

{user_text}

========================================
会話履歴
========================================

{history_text}

========================================
Hot Pepper検索結果
========================================

{hotpepper_context}

========================================
Tavily検索結果
========================================

{tavily_context}

========================================
今回の回答ルール
========================================

1. ユーザーが指定した検索条件を最優先してください。

2. 今回は場所・ジャンル・人数・予算・時間が
   すでに選択されています。

3. 条件が足りないからといって、
   予算・人数・時間などをユーザーに
   もう一度質問しないでください。

4. Hot Pepperの店舗情報がある場合は、
   その情報を優先して候補を提示してください。

5. Hot Pepper検索は
   「場所＋ジャンル」で実施されています。
   人数・予算・時間はAI側で候補を判断する条件です。

6. 選択された予算に合わない店舗は、
   できるだけ候補から外してください。

7. 選択された人数に適しているか、
   利用しやすい店舗かを考慮してください。

8. 選択された時間に営業している可能性が
   低い店舗は候補から外してください。

9. Tavilyで閉店が確認された店舗は
   絶対に候補として提示しないでください。

10. 検索結果に存在しない店舗を
    推測で作らないでください。

11. 店舗が見つからなかった場合は、
    「見つかりませんでした」と正直に伝えてください。

12. 店舗候補がある場合は、
    店名・場所・予算などを分かりやすく整理してください。

13. ユーザーが選択した条件を
    回答の中でも簡潔に確認してください。

14. 不要に長い説明は避けてください。

========================================
ユーザーの今回の入力
========================================

{user_text}
"""

    print(
        "APIプロンプト文字数：",
        len(prompt)
    )

    return prompt


# =========================================================
# Gemini
# =========================================================

def ask_gemini(prompt):

    if not GEMINI_API_KEY:

        print(
            "GEMINI_API_KEYがありません"
        )

        return None

    print(
        "Gemini処理開始..."
    )

    headers = {
        "Content-Type": "application/json"
    }

    params = {
        "key": GEMINI_API_KEY
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    try:

        response = requests.post(
            GEMINI_URL,
            headers=headers,
            params=params,
            json=payload,
            timeout=60
        )

        print(
            "Gemini HTTPステータス：",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "Geminiエラー：",
                response.text[:1000]
            )

            return None

        data = response.json()

        return (
            data
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text")
        )

    except Exception as e:

        print(
            "Gemini例外：",
            e
        )

        return None


# =========================================================
# Groq
# =========================================================

def ask_groq(prompt):

    if not GROQ_API_KEY:

        print(
            "GROQ_API_KEYがありません"
        )

        return None

    print(
        "Groq処理開始..."
    )

    headers = {
        "Authorization":
            f"Bearer {GROQ_API_KEY}",
        "Content-Type":
            "application/json"
    }

    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:

        response = post_with_retry(
            GROQ_URL,
            headers=headers,
            json_data=payload,
            timeout=60
        )

        print(
            "Groq HTTPステータス：",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "Groqエラー：",
                response.text[:2000]
            )

            return None

        data = response.json()

        # Rate Limit情報
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

        answer = (
            data
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

        if answer:

            print(
                "Groqレスポンス："
            )

            print(
                json.dumps(
                    data,
                    ensure_ascii=False
                )
            )

        return answer

    except Exception as e:

        print(
            "Groq例外：",
            e
        )

        return None


# =========================================================
# OpenRouter
# =========================================================

def ask_openrouter(prompt):

    if not OPENROUTER_API_KEY:

        print(
            "OPENROUTER_API_KEYがありません"
        )

        return None

    print(
        "OpenRouter処理開始..."
    )

    headers = {
        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":
            "application/json",
        "HTTP-Referer":
            "https://ai-ayafumi-gourmet.onrender.com",
        "X-Title":
            "AI Ayafumi Gourmet",
    }

    payload = {
        "model": "openai/gpt-oss-20b:free",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:

        response = post_with_retry(
            OPENROUTER_URL,
            headers=headers,
            json_data=payload,
            timeout=60
        )

        print(
            "OpenRouter HTTPステータス：",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "OpenRouterエラー：",
                response.text[:2000]
            )

            return None

        data = response.json()

        return (
            data
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

    except Exception as e:

        print(
            "OpenRouter例外：",
            e
        )

        return None


# =========================================================
# AI回答整形
# =========================================================

def clean_answer(answer):

    if not answer:

        return answer

    answer = answer.strip()

    # JSONで返ってきた場合の簡易処理
    if answer.startswith("{"):

        try:

            data = json.loads(
                answer
            )

            if isinstance(data, dict):

                if "answer" in data:

                    return str(
                        data["answer"]
                    )

                if "content" in data:

                    return str(
                        data["content"]
                    )

        except Exception:
            pass

    return answer


# =========================================================
# グルメAI
# =========================================================

def ask_gourmet_ai(
    user_id,
    user_text
):

    print(
        "========================================"
    )

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

    # -----------------------------------------------------
    # Gemini
    # -----------------------------------------------------

    if GEMINI_API_KEY:

        answer = ask_gemini(
            prompt
        )

    # -----------------------------------------------------
    # Groq
    # -----------------------------------------------------

    if not answer and GROQ_API_KEY:

        answer = ask_groq(
            prompt
        )

    # -----------------------------------------------------
    # OpenRouter
    # -----------------------------------------------------

    if not answer and OPENROUTER_API_KEY:

        answer = ask_openrouter(
            prompt
        )

    # -----------------------------------------------------
    # 完全失敗
    # -----------------------------------------------------

    if not answer:

        answer = (
            "申し訳ありません。\n"
            "現在、店舗検索AIに接続できませんでした。"
        )

    answer = clean_answer(
        answer
    )

    # -----------------------------------------------------
    # 会話履歴
    # -----------------------------------------------------

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

    print(
        "========================================"
    )

    return answer


# =========================================================
# 選択フロー処理
# =========================================================

def handle_gourmet_selection(
    user_id,
    user_text,
    reply_token
):

    state = get_gourmet_search_state(
        user_id
    )

    step = state["step"]

    print(
        "========================================"
    )

    print(
        "LINE選択フロー：",
        step
    )

    print(
        "LINE選択内容：",
        user_text
    )

    # =====================================================
    # 最初から
    # =====================================================

    if user_text == "最初から":

        start_gourmet_search(
            user_id
        )

        send_location_selection(
            reply_token
        )

        return

    # =====================================================
    # 検索開始
    # =====================================================

    if (
        step == "confirm"
        and user_text == "この条件で検索"
    ):

        final_text = (
            f"{state['location']}で"
            f"{state['genre']}を探す。"
            f"予算は{state['budget']}。"
            f"{state['people']}で利用。"
            f"利用時間は{state['time']}。"
        )

        print(
            "LINE選択条件完成"
        )

        print()

        print(
            final_text
        )

        print()

        answer = ask_gourmet_ai(
            user_id,
            final_text
        )

        # 検索終了後は次回の入力で
        # 新しい検索を開始できるようにする
        gourmet_search_states.pop(
            user_id,
            None
        )

        reply_to_line(
            reply_token,
            answer
        )

        return

    # =====================================================
    # location
    # =====================================================

    if step == "location":

        if user_text in LOCATION_OPTIONS:

            state["location"] = user_text
            state["step"] = "genre"

            send_genre_selection(
                reply_token
            )

            return

        # 「開始」などが来た場合
        start_gourmet_search(
            user_id
        )

        send_location_selection(
            reply_token
        )

        return

    # =====================================================
    # genre
    # =====================================================

    if step == "genre":

        if user_text in GENRE_OPTIONS:

            state["genre"] = user_text
            state["step"] = "people"

            send_people_selection(
                reply_token
            )

            return

    # =====================================================
    # people
    # =====================================================

    if step == "people":

        if user_text in PEOPLE_OPTIONS:

            state["people"] = user_text
            state["step"] = "budget"

            send_budget_selection(
                reply_token
            )

            return

    # =====================================================
    # budget
    # =====================================================

    if step == "budget":

        if user_text in BUDGET_OPTIONS:

            state["budget"] = user_text
            state["step"] = "time"

            send_time_selection(
                reply_token
            )

            return

    # =====================================================
    # time
    # =====================================================

    if step == "time":

        if user_text in TIME_OPTIONS:

            state["time"] = user_text
            state["step"] = "confirm"

            print(
                "LINE選択条件完成"
            )

            final_preview = (
                f"{state['location']}で"
                f"{state['genre']}を探す。"
                f"予算は{state['budget']}。"
                f"{state['people']}で利用。"
                f"利用時間は{state['time']}。"
            )

            print()
            print(final_preview)
            print()

            send_confirmation(
                reply_token,
                state
            )

            return

    # =====================================================
    # 想定外
    # =====================================================

    reply_to_line(
        reply_token,
        "選択内容を確認できませんでした。\n"
        "最初から検索をやり直します。",
        ["最初から"]
    )


# =========================================================
# Health Check
# =========================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({
        "status": "ok"
    })


# =========================================================
# PowerShell用テスト
# =========================================================

@app.route(
    "/test",
    methods=["POST"]
)
def test():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        user_text = data.get(
            "message",
            ""
        )

        if not user_text:

            return jsonify({
                "error": "message is required"
            }), 400

        print(
            "========================================"
        )

        print(
            "PowerShell TEST：",
            user_text
        )

        answer = ask_gourmet_ai(
            "powershell-test",
            user_text
        )

        return jsonify({
            "message": user_text,
            "answer": answer
        })

    except Exception as e:

        print(
            "/testエラー：",
            e
        )

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# LINE Webhook
# =========================================================

@app.route(
    "/callback",
    methods=["POST"]
)
def callback():

    signature = request.headers.get(
        "X-Line-Signature",
        ""
    )

    body = request.get_data(
        as_text=True
    )

    try:

        events = line_parser.parse(
            body,
            signature
        )

    except InvalidSignatureError:

        print(
            "LINE署名エラー"
        )

        return "Invalid signature", 400

    except Exception as e:

        print(
            "Webhook解析エラー：",
            e
        )

        return "Bad Request", 400

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

        user_id = event.source.user_id

        user_text = event.message.text

        reply_token = event.reply_token

        print()
        print(
            "========================================"
        )

        print(
            "LINE受信：",
            user_text
        )

        print()

        print(
            "LINEユーザーID：",
            user_id
        )

        print()

        # -------------------------------------------------
        # 初回
        # -------------------------------------------------

        if user_id not in gourmet_search_states:

            start_gourmet_search(
                user_id
            )

            # 「開始」「店探し」など
            # 何が来てもまず選択画面
            send_location_selection(
                reply_token
            )

            continue

        # -------------------------------------------------
        # 選択フロー
        # -------------------------------------------------

        handle_gourmet_selection(
            user_id,
            user_text,
            reply_token
        )

    return "OK", 200


# =========================================================
# 起動
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )