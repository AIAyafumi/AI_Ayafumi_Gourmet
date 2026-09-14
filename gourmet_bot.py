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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
HOTPEPPER_API_KEY = os.getenv("HOTPEPPER_API_KEY")

# ============================================================
# API URL
# ============================================================

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

        conversation_histories[
            user_id
        ] = []

    return conversation_histories[
        user_id
    ]


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

        conversation_histories[
            user_id
        ] = history[
            -MAX_HISTORY_MESSAGES:
        ]


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

        return (
            "まだ過去の会話はありません。"
        )

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
                "ユーザー：" + content
            )

        elif role == "assistant":

            lines.append(
                "AI：" + content
            )

    return "\n".join(lines)


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
                e,
                flush=True
            )

            if attempt < retries:

                print(
                    "HTTPリトライ：",
                    attempt + 1,
                    flush=True
                )

                time.sleep(1)

    raise last_error


# ============================================================
# Hot Pepper検索が必要か判定
# ============================================================

def should_search_hotpepper(
    user_text
):

    keywords = [

        # 店舗・検索系
        "店",
        "店舗",
        "レストラン",
        "飲食店",
        "グルメ",
        "探して",
        "探す",
        "おすすめ",
        "近く",
        "近所",
        "人気",

        # ジャンル
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
        "定食",
        "韓国料理",
        "餃子",

        # エリア
        "堀之内",
        "南大沢",
        "八王子",
        "多摩",
        "聖蹟桜ヶ丘",
        "京王堀之内",
        "多摩センター"
    ]

    return any(
        keyword in user_text
        for keyword in keywords
    )


# ============================================================
# Hot Pepper検索キーワード作成
# ============================================================

def build_hotpepper_keyword(
    user_text
):

    keyword = user_text.strip()

    remove_words = [

        "探して",
        "探す",
        "探してほしい",
        "探して欲しい",
        "おすすめ",
        "オススメ",
        "教えて",
        "教えてほしい",
        "教えて欲しい",
        "お店",
        "店舗",
        "レストラン",
        "飲食店",
        "グルメ",
        "を探して",
        "を探す",
        "を教えて",
        "がいい",
        "が良い",
        "ありますか",
        "ある？",
        "あります？",
        "ください",
        "下さい"
    ]

    for word in remove_words:

        keyword = keyword.replace(
            word,
            " "
        )

    replace_words = [

        "で",
        "の",
        "を",
        "に",
        "が"
    ]

    for word in replace_words:

        keyword = keyword.replace(
            word,
            " "
        )

    keyword = keyword.replace(
        "ラーメン屋",
        "ラーメン"
    )

    keyword = keyword.replace(
        "焼肉屋",
        "焼肉"
    )

    keyword = keyword.replace(
        "寿司屋",
        "寿司"
    )

    keyword = keyword.replace(
        "そば屋",
        "そば"
    )

    keyword = keyword.replace(
        "うどん屋",
        "うどん"
    )

    keyword = keyword.replace(
        "カレー屋",
        "カレー"
    )

    keyword = " ".join(
        keyword.split()
    )

    if not keyword:

        keyword = user_text

    print(
        "Hot Pepper検索キーワード：",
        keyword,
        flush=True
    )

    return keyword


# ============================================================
# Tavily Web検索
# ============================================================

def search_tavily(
    query
):

    print(
        "Tavily検索開始：",
        query,
        flush=True
    )

    if not TAVILY_API_KEY:

        print(
            "TAVILY_API_KEY が設定されていません。",
            flush=True
        )

        return []

    data = {

        "api_key": TAVILY_API_KEY,

        "query": query,

        "search_depth": "basic",

        "topic": "general",

        "max_results": 5,

        "include_answer": False,

        "include_raw_content": False
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
            e,
            flush=True
        )

        return []

    print(
        "Tavily HTTPステータス：",
        response.status_code,
        flush=True
    )

    if response.status_code >= 400:

        print(
            "Tavily HTTPエラー：",
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
        )

        return []

    try:

        result = response.json()

    except ValueError:

        print(
            "TavilyレスポンスがJSONではありません。",
            flush=True
        )

        return []

    results = result.get(
        "results",
        []
    )

    print(
        "Tavily検索件数：",
        len(results),
        flush=True
    )

    return results


# ============================================================
# Hot Pepper店舗ごとのTavily閉店確認
# ============================================================

def check_hotpepper_shop_with_tavily(
    shop
):

    name = shop.get(
        "name",
        ""
    )

    address = shop.get(
        "address",
        ""
    )

    if not name:

        return {
            "status": "unknown",
            "reason": "店舗名が取得できませんでした。"
        }

    query = (
        f'"{name}" "{address}" '
        "営業 閉店 閉業 営業終了 移転 最新情報"
    )

    print(
        "店舗別Tavily確認：",
        name,
        flush=True
    )

    results = search_tavily(
        query
    )

    if not results:

        return {
            "status": "unknown",
            "reason": "Tavilyから確認情報を取得できませんでした。"
        }

    # --------------------------------------------------------
    # 検索結果をまとめる
    # --------------------------------------------------------

    matched_texts = []

    for result in results:

        title = str(
            result.get(
                "title",
                ""
            )
        )

        content = str(
            result.get(
                "content",
                ""
            )
        )

        text = (
            title
            + "\n"
            + content
        )

        # 店舗名が含まれる検索結果を優先
        if name in text:

            matched_texts.append(
                text
            )

    if not matched_texts:

        return {
            "status": "unknown",
            "reason": "店舗名が一致するWeb情報を確認できませんでした。"
        }

    # --------------------------------------------------------
    # 店舗名一致結果だけを判定
    # --------------------------------------------------------

    combined_text = "\n".join(
        matched_texts
    )

    # 強い閉店表現
    strong_closed_phrases = [

        "閉店しました",
        "閉店いたしました",
        "閉店のお知らせ",
        "閉店となりました",
        "営業終了しました",
        "営業終了いたしました",
        "営業終了のお知らせ",
        "閉業しました",
        "閉業いたしました",
        "閉業のお知らせ",
        "店舗閉鎖",
        "店を閉めました"
    ]

    # 一般的な閉店表現
    normal_closed_phrases = [

        "閉店",
        "閉業",
        "営業終了"
    ]

    # 閉店ではないことを示す表現
    negative_closed_phrases = [

        "閉店していません",
        "閉店してない",
        "閉店ではありません",
        "閉店情報はありません",
        "閉店の情報はありません",
        "営業終了していません",
        "営業終了してない"
    ]

    # 営業中を示す表現
    open_phrases = [

        "現在営業中",
        "現在も営業",
        "営業しています",
        "営業しております",
        "営業中",
        "営業再開",
        "営業を続けています"
    ]

    closed_score = 0
    open_score = 0

    # --------------------------------------------------------
    # 閉店表現
    # --------------------------------------------------------

    for phrase in strong_closed_phrases:

        if phrase in combined_text:

            closed_score += 3

    for phrase in normal_closed_phrases:

        if phrase in combined_text:

            # 否定表現の近くにある可能性がある場合は
            # 一般閉店スコアを加算しない
            is_negated = any(
                negative in combined_text
                for negative in negative_closed_phrases
            )

            if not is_negated:

                closed_score += 1

    # --------------------------------------------------------
    # 営業中表現
    # --------------------------------------------------------

    for phrase in open_phrases:

        if phrase in combined_text:

            open_score += 2

    # --------------------------------------------------------
    # 判定
    # --------------------------------------------------------

    if (
        closed_score >= 3
        and closed_score > open_score
    ):

        reason = (
            "Web検索結果に閉店・営業終了を示す情報がありました。"
        )

        print(
            "❌ 閉店確認・店舗除外：",
            name,
            flush=True
        )

        return {
            "status": "closed",
            "reason": reason
        }

    if (
        open_score >= 2
        and open_score >= closed_score
    ):

        reason = (
            "Web検索結果に現在営業中を示す情報がありました。"
        )

        print(
            "✅ 営業中情報確認：",
            name,
            flush=True
        )

        return {
            "status": "open",
            "reason": reason
        }

    print(
        "⚠️ 店舗営業状況を断定できず：",
        name,
        flush=True
    )

    return {
        "status": "unknown",
        "reason": (
            "Web検索結果だけでは営業状況を断定できませんでした。"
        )
    }


# ============================================================
# Hot Pepper店舗をTavilyで確認
# ============================================================

def verify_hotpepper_shops_with_tavily(
    shops
):

    if not shops:

        return []

    if not TAVILY_API_KEY:

        print(
            "TAVILY_API_KEYがないため店舗別確認をスキップします。",
            flush=True
        )

        return shops

    print(
        "",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    print(
        "Hot Pepper店舗ごとのTavily閉店チェック開始",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    verified_shops = []

    for index, shop in enumerate(
        shops,
        start=1
    ):

        print(
            "",
            flush=True
        )

        print(
            f"===== Tavily店舗確認 {index}/{len(shops)} =====",
            flush=True
        )

        print(
            "店舗名：",
            shop.get(
                "name",
                ""
            ),
            flush=True
        )

        verification = (
            check_hotpepper_shop_with_tavily(
                shop
            )
        )

        shop["tavily_status"] = (
            verification.get(
                "status",
                "unknown"
            )
        )

        shop["tavily_reason"] = (
            verification.get(
                "reason",
                ""
            )
        )

        status = shop[
            "tavily_status"
        ]

        if status == "closed":

            print(
                "❌ 閉店のため候補から除外：",
                shop.get(
                    "name",
                    ""
                ),
                flush=True
            )

            continue

        if status == "open":

            print(
                "✅ 営業中候補として保持：",
                shop.get(
                    "name",
                    ""
                ),
                flush=True
            )

        else:

            print(
                "⚠️ 営業状況不明のため候補として保持：",
                shop.get(
                    "name",
                    ""
                ),
                flush=True
            )

        verified_shops.append(
            shop
        )

    # --------------------------------------------------------
    # 番号を振り直す
    # --------------------------------------------------------

    for index, shop in enumerate(
        verified_shops,
        start=1
    ):

        shop["number"] = index

    print(
        "",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    print(
        "Hot Pepper + Tavily確認完了",
        flush=True
    )

    print(
        "確認前：",
        len(shops),
        "件",
        flush=True
    )

    print(
        "確認後：",
        len(verified_shops),
        "件",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    return verified_shops


# ============================================================
# Hot Pepper検索
# ============================================================

def search_hotpepper(
    user_text
):

    print(
        "Hot Pepper検索開始：",
        user_text,
        flush=True
    )

    if not HOTPEPPER_API_KEY:

        print(
            "HOTPEPPER_API_KEY が設定されていません。",
            flush=True
        )

        return []

    # --------------------------------------------------------
    # 自然文をHot Pepper用キーワードへ変換
    # --------------------------------------------------------

    search_keyword = (
        build_hotpepper_keyword(
            user_text
        )
    )

    params = {

        "key": HOTPEPPER_API_KEY,

        "keyword": search_keyword,

        "format": "json",

        "count": 10
    }

    print(
        "Hot Pepper API keyword：",
        search_keyword,
        flush=True
    )

    try:

        response = requests.get(
            HOTPEPPER_URL,
            params=params,
            timeout=30
        )

    except requests.RequestException as e:

        print(
            "Hot Pepper通信エラー：",
            e,
            flush=True
        )

        return []

    print(
        "Hot Pepper HTTPステータス：",
        response.status_code,
        flush=True
    )

    if response.status_code >= 400:

        print(
            "Hot Pepper HTTPエラー：",
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
        )

        return []

    try:

        data = response.json()

    except ValueError:

        print(
            "Hot PepperレスポンスがJSONではありません。",
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
        )

        return []

    results = data.get(
        "results",
        {}
    )

    print(
        "Hot Pepper検索件数：",
        results.get(
            "results_available",
            0
        ),
        flush=True
    )

    print(
        "Hot Pepper取得件数：",
        results.get(
            "results_returned",
            0
        ),
        flush=True
    )

    shops = results.get(
        "shop",
        []
    )

    if not shops:

        print(
            "Hot Pepper店舗候補なし",
            flush=True
        )

        return []

    formatted_shops = []

    for index, shop in enumerate(
        shops,
        start=1
    ):

        name = shop.get(
            "name",
            ""
        )

        address = shop.get(
            "address",
            ""
        )

        station = shop.get(
            "station_name",
            ""
        )

        budget_data = shop.get(
            "budget",
            {}
        )

        if isinstance(
            budget_data,
            dict
        ):

            budget = budget_data.get(
                "average",
                ""
            )

        else:

            budget = ""

        genre_data = shop.get(
            "genre",
            {}
        )

        if isinstance(
            genre_data,
            dict
        ):

            genre = genre_data.get(
                "name",
                ""
            )

        else:

            genre = ""

        lunch = shop.get(
            "lunch",
            ""
        )

        urls_data = shop.get(
            "urls",
            {}
        )

        if isinstance(
            urls_data,
            dict
        ):

            url_pc = urls_data.get(
                "pc",
                ""
            )

        else:

            url_pc = ""

        formatted_shops.append(
            {
                "number": index,
                "name": name,
                "genre": genre,
                "address": address,
                "station": station,
                "budget": budget,
                "lunch": lunch,
                "url": url_pc
            }
        )

    # --------------------------------------------------------
    # ここで店舗ごとのTavily確認
    # --------------------------------------------------------

    verified_shops = (
        verify_hotpepper_shops_with_tavily(
            formatted_shops
        )
    )

    print(
        "Hot Pepper + Tavily確認後の店舗候補：",
        len(verified_shops),
        "件",
        flush=True
    )

    print(
        "Hot Pepper店舗候補をAIへ渡します：",
        len(verified_shops),
        "件",
        flush=True
    )

    return verified_shops


# ============================================================
# Hot Pepper検索結果をAI用テキストへ変換
# ============================================================

def format_hotpepper_results(
    shops
):

    if not shops:

        return (
            "Hot Pepperから有力な店舗候補を"
            "取得できませんでした。"
        )

    lines = []

    for shop in shops:

        tavily_status = shop.get(
            "tavily_status",
            "unknown"
        )

        tavily_reason = shop.get(
            "tavily_reason",
            ""
        )

        lines.append(
            f"{shop['number']}. "
            f"{shop['name']}\n"
            f"ジャンル：{shop['genre']}\n"
            f"住所：{shop['address']}\n"
            f"駅：{shop['station']}\n"
            f"予算：{shop['budget']}\n"
            f"ランチ：{shop['lunch']}\n"
            f"Tavily営業確認：{tavily_status}\n"
            f"Tavily確認理由：{tavily_reason}\n"
            f"Hot Pepper：{shop['url']}"
        )

    return "\n\n".join(
        lines
    )


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

    # --------------------------------------------------------
    # Hot Pepper検索
    # --------------------------------------------------------

    hotpepper_shops = []

    if should_search_hotpepper(
        user_text
    ):

        hotpepper_shops = (
            search_hotpepper(
                user_text
            )
        )

    hotpepper_context = (
        format_hotpepper_results(
            hotpepper_shops
        )
    )

    # --------------------------------------------------------
    # Tavily検索
    # --------------------------------------------------------

    tavily_context = (
        get_tavily_context(
            user_text
        )
    )

    # --------------------------------------------------------
    # 基本プロンプト
    # --------------------------------------------------------

    prompt = (

        system_prompt

        + "\n\n"

        + "【過去の会話】\n"

        + conversation_history

        + "\n\n"

        + "【今回のユーザー依頼】\n"

        + user_text
    )

    # --------------------------------------------------------
    # Hot Pepper検索結果
    # --------------------------------------------------------

    if hotpepper_shops:

        prompt += (

            "\n\n"

            + "【Hot Pepper検索結果】\n"

            + hotpepper_context

            + "\n\n"

            + "【Hot Pepper検索結果の利用ルール】\n"

            + "現在、店舗検索機能は実装済みです。"

            + "上記のHot Pepper検索結果は、"

            + "実際にHot Pepper APIから取得した"

            + "店舗候補です。"

            + "さらに各店舗についてTavilyによる"

            + "営業状況確認を実施しています。"

            + "Tavilyで閉店と判断された店舗は、"

            + "AIに渡す店舗候補から除外済みです。"

            + "したがって、上記の店舗一覧には"

            + "閉店と判断された店舗は含まれていません。"

            + "ただし、Tavily営業確認がunknownの店舗は、"

            + "営業中と断定してはいけません。"

            + "ユーザーが店舗を探している場合は、"

            + "この店舗候補を使って回答してください。"

            + "ユーザーがすでに地域と料理ジャンルを"

            + "指定している場合、"

            + "その情報をもう一度質問しないでください。"

            + "ユーザーの条件が十分に揃っている場合は、"

            + "追加質問だけで終わらず、"

            + "取得した店舗候補から候補を提示してください。"

            + "店舗名、ジャンル、場所、予算などの情報は、"

            + "Hot Pepper検索結果に存在する情報を"

            + "優先して使用してください。"

            + "Hot Pepper検索結果に存在しない情報を"

            + "推測して作らないでください。"

            + "店舗が複数ある場合は、"

            + "ユーザーの条件に合いそうな店舗を"

            + "最大3店舗程度に絞ってください。"

            + "Hot Pepper URLがある場合は、"

            + "店舗確認用として提示して構いません。"
        )

    else:

        prompt += (

            "\n\n"

            + "【Hot Pepper検索について】\n"

            + "今回の依頼ではHot Pepperから"

            + "店舗候補を取得できませんでした。"

            + "店舗候補を実在するものとして"

            + "推測して作らないでください。"
        )

    # --------------------------------------------------------
    # Tavily検索結果
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 最終回答指示
    # --------------------------------------------------------

    prompt += (

        "\n\n"

        + "【今回の重要な回答ルール】\n"

        + "今回の店舗検索機能では、"

        + "Hot Pepper APIによる実店舗検索が"

        + "すでに実行されています。"

        + "さらに各Hot Pepper店舗について、"

        + "Tavilyによる営業状況確認も実行されています。"

        + "ユーザーが地域とジャンルなどを"

        + "すでに指定している場合は、"

        + "同じ条件をもう一度質問しないでください。"

        + "十分な条件が揃っている場合は、"

        + "検索結果から店舗候補を提示してください。"

        + "ただし、ユーザーが明確に"

        + "追加条件を指定している場合は、"

        + "その条件を優先してください。"

        + "過去の会話でユーザーが答えた情報も"

        + "再質問しないでください。"

        + "\n\n"

        + "【回答】\n"

        + "過去の会話を踏まえて、"

        + "今回のユーザーの発言に直接答えてください。"
    )

    print(
        "APIプロンプト文字数：",
        len(prompt),
        flush=True
    )

    return prompt


# ============================================================
# Gemini
# ============================================================

def ask_gemini(
    prompt
):

    print(
        "Gemini処理開始...",
        flush=True
    )

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "GEMINI_API_KEY が設定されていません。"
        )

    headers = {
        "Content-Type":
            "application/json"
    }

    params = {
        "key":
            GEMINI_API_KEY
    }

    data = {

        "contents": [

            {
                "parts": [

                    {
                        "text":
                            prompt
                    }

                ]
            }

        ],

        "generationConfig": {

            "temperature":
                0.7,

            "maxOutputTokens":
                2500
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
            response.status_code,
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
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
            "Geminiレスポンス：",
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
        )

        raise RuntimeError(
            "Geminiの回答本文を取得できませんでした。"
        )

    if not answer.strip():

        raise RuntimeError(
            "Geminiの回答本文が空です。"
        )

    print(
        "Gemini成功",
        flush=True
    )

    return answer


# ============================================================
# Groq
# ============================================================

def ask_groq(
    prompt
):

    print(
        "Groq処理開始...",
        flush=True
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
                "role":
                    "user",

                "content":
                    prompt
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
        response.status_code,
        flush=True
    )

    print(
        "Groq RateLimit残りリクエスト：",
        response.headers.get(
            "x-ratelimit-remaining-requests"
        ),
        flush=True
    )

    print(
        "Groq RateLimit残りトークン：",
        response.headers.get(
            "x-ratelimit-remaining-tokens"
        ),
        flush=True
    )

    print(
        "Groq RateLimitリセット：",
        response.headers.get(
            "x-ratelimit-reset-tokens"
        ),
        flush=True
    )

    if response.status_code >= 400:

        print(
            "Groq HTTPエラー：",
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
        )

        response.raise_for_status()

    print(
        "Groqレスポンス：",
        flush=True
    )

    print(
        response.text[:5000],
        flush=True
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
            "Groq choices が存在しません。",
            flush=True
        )

        print(
            "Groq JSON：",
            result,
            flush=True
        )

        raise RuntimeError(
            "Groqのchoicesが空です。"
        )

    message = choices[0].get(
        "message"
    )

    if not message:

        print(
            "Groq message が存在しません。",
            flush=True
        )

        print(
            "Groq choice：",
            choices[0],
            flush=True
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
        ),
        flush=True
    )

    print(
        "Groq content文字数：",
        len(answer)
        if isinstance(
            answer,
            str
        )
        else "文字列ではありません",
        flush=True
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
            message,
            flush=True
        )

        raise RuntimeError(
            "Groqの回答本文が空です。"
        )

    print(
        "Groq成功",
        flush=True
    )

    return answer


# ============================================================
# OpenRouter
# ============================================================

def ask_openrouter(
    prompt
):

    print(
        "OpenRouter処理開始...",
        flush=True
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
                "role":
                    "user",

                "content":
                    prompt
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
            response.status_code,
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
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
            "OpenRouterレスポンス：",
            flush=True
        )

        print(
            response.text[:3000],
            flush=True
        )

        raise RuntimeError(
            "OpenRouterの回答本文を取得できませんでした。"
        )

    if not answer.strip():

        raise RuntimeError(
            "OpenRouterの回答本文が空です。"
        )

    print(
        "OpenRouter成功",
        flush=True
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
        user_text,
        flush=True
    )

    print(
        "会話ユーザーID：",
        user_id,
        flush=True
    )

    history = get_conversation_history(
        user_id
    )

    print(
        "現在の会話履歴件数：",
        len(history),
        flush=True
    )

    prompt = build_gourmet_prompt(
        user_id,
        user_text
    )

    answer = None

    # --------------------------------------------------------
    # Groq
    # --------------------------------------------------------

    try:

        answer = ask_groq(
            prompt
        )

    except Exception as e:

        print(
            "Groq失敗：",
            e,
            flush=True
        )

    # --------------------------------------------------------
    # Gemini
    # --------------------------------------------------------

    if not answer:

        try:

            answer = ask_gemini(
                prompt
            )

        except Exception as e:

            print(
                "Gemini失敗：",
                e,
                flush=True
            )

    # --------------------------------------------------------
    # OpenRouter
    # --------------------------------------------------------

    if not answer:

        try:

            answer = ask_openrouter(
                prompt
            )

        except Exception as e:

            print(
                "OpenRouter失敗：",
                e,
                flush=True
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

    # --------------------------------------------------------
    # 会話履歴保存
    # --------------------------------------------------------

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
        ),
        flush=True
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

        messaging_api = (
            MessagingApi(
                api_client
            )
        )

        messaging_api.reply_message(

            ReplyMessageRequest(

                reply_token=
                    reply_token,

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
        "HEALTH CHECK",
        flush=True
    )

    return {
        "status":
            "ok"
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
        "TEST ROUTE START",
        flush=True
    )

    raw_body = request.get_data(
        as_text=True
    )

    print(
        "TEST Content-Type：",
        request.content_type,
        flush=True
    )

    print(
        "TEST Raw Body：",
        raw_body,
        flush=True
    )

    print(
        "TEST Request Headers：",
        dict(request.headers),
        flush=True
    )

    data = request.get_json(
        silent=True
    )

    print(
        "TEST Parsed JSON：",
        data,
        flush=True
    )

    if data is None and raw_body:

        try:

            data = json.loads(
                raw_body
            )

            print(
                "TEST Manual JSON Parse：",
                data,
                flush=True
            )

        except json.JSONDecodeError as e:

            print(
                "TEST Manual JSON Parse Error：",
                e,
                flush=True
            )

            return {

                "error":
                    "JSON解析に失敗しました。",

                "content_type":
                    request.content_type,

                "raw_body":
                    raw_body,

                "parse_error":
                    str(e)

            }, 400

    if not data:

        return {

            "error":
                "JSONを取得できませんでした。",

            "content_type":
                request.content_type,

            "raw_body":
                raw_body

        }, 400

    if "message" not in data:

        return {

            "error":
                "message が指定されていません。",

            "received_data":
                data

        }, 400

    user_text = data[
        "message"
    ]

    if not isinstance(
        user_text,
        str
    ):

        return {

            "error":
                "message は文字列で指定してください。"

        }, 400

    user_text = user_text.strip()

    if not user_text:

        return {

            "error":
                "message が空です。"

        }, 400

    print(
        "テスト受信：",
        user_text,
        flush=True
    )

    test_user_id = (
        "powershell-test"
    )

    try:

        answer = ask_gourmet_ai(

            test_user_id,

            user_text
        )

        print(
            "テスト回答：",
            answer,
            flush=True
        )

        return {

            "message":
                user_text,

            "answer":
                answer

        }

    except Exception as e:

        print(
            "テスト処理エラー：",
            e,
            flush=True
        )

        return {

            "error":
                str(e)

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

        user_id = (
            event.source.user_id
        )

        print(
            "LINE受信：",
            user_text,
            flush=True
        )

        print(
            "LINEユーザーID：",
            user_id,
            flush=True
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
                e,
                flush=True
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
        "AIアヤフミ（レストラン）起動開始",
        flush=True
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