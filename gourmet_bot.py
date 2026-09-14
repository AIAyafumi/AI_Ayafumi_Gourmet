import os
import time
import json
import re
import unicodedata
import requests

from flask import Flask, request, jsonify
from dotenv import load_dotenv

from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
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
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID")


# =========================================================
# URL
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

YAHOO_LOCAL_SEARCH_URL = (
    "https://map.yahooapis.jp/search/local/V1/localSearch"
)


# =========================================================
# Yahoo!設定
# =========================================================

YAHOO_SEARCH_DISTANCE_METERS = 1500


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)


# =========================================================
# LINE設定
# =========================================================

line_configuration = Configuration(
    access_token=GOURMET_LINE_CHANNEL_ACCESS_TOKEN
)

line_api_client = ApiClient(line_configuration)
line_messaging_api = MessagingApi(line_api_client)

line_parser = WebhookParser(GOURMET_LINE_CHANNEL_SECRET)


# =========================================================
# 会話履歴
# =========================================================

conversation_histories = {}

MAX_HISTORY = 10


# =========================================================
# レストラン検索ステート
# =========================================================

search_states = {}


# =========================================================
# 選択肢
# =========================================================

GENRE_OPTIONS = [
    "ラーメン",
    "焼肉",
    "寿司",
    "居酒屋",
    "イタリアン",
    "カフェ",
    "中華",
    "和食",
    "韓国料理",
    "ファミレス",
    "その他",
]


# ラーメンを選択した場合のみ表示する
RAMEN_STYLE_OPTIONS = [
    "家系",
    "二郎系",
    "町中華系",
    "魚介系",
    "味噌",
    "その他",
    "指定なし",
]


PEOPLE_OPTIONS = [
    "1人",
    "2人",
    "3人",
    "4人",
    "5人以上",
]

TIME_OPTIONS = [
    "昼",
    "夜",
    "いつでも",
]


# =========================================================
# 共通ユーティリティ
# =========================================================

def safe_json(response):
    try:
        return response.json()
    except Exception:
        return {}


def normalize_text(text):
    if not text:
        return ""

    return (
        str(text)
        .strip()
        .replace("　", " ")
        .replace("\n", " ")
    )


def normalize_for_duplicate(text):
    """
    重複判定専用の文字列正規化。

    以下を吸収する。
    - 全角/半角
    - 大文字/小文字
    - 空白
    - ハイフン類
    - 句読点
    """

    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(text),
    )

    text = text.lower()

    text = re.sub(
        r"\s+",
        "",
        text,
    )

    text = re.sub(
        r"[-‐-‒–—−ーｰ]",
        "-",
        text,
    )

    text = re.sub(
        r"[、，,。．.]",
        "",
        text,
    )

    return text


def normalize_shop_name_for_duplicate(text):
    """
    店舗名専用の重複判定正規化。
    """

    text = normalize_for_duplicate(text)

    if not text:
        return ""

    text = re.sub(
        r"[「」『』【】（）()［］\[\]〈〉<>・･/／\\]",
        "",
        text,
    )

    return text


def normalize_address_for_duplicate(text):
    """
    住所専用の重複判定正規化。
    """

    text = normalize_for_duplicate(text)

    if not text:
        return ""

    text = text.replace(
        "丁目",
        "-",
    )

    text = text.replace(
        "番地",
        "-",
    )

    text = text.replace(
        "番",
        "-",
    )

    text = text.replace(
        "号",
        "",
    )

    text = re.sub(
        r"-+",
        "-",
        text,
    )

    return text.strip("-")


def parse_coordinates(coordinates):
    """
    Yahoo!の
        longitude,latitude
    形式をfloatへ変換する。

    戻り値:
        (latitude, longitude)
    """

    if not coordinates:
        return None

    try:
        parts = str(
            coordinates
        ).split(",")

        if len(parts) < 2:
            return None

        longitude = float(
            parts[0]
        )

        latitude = float(
            parts[1]
        )

        return latitude, longitude

    except Exception:
        return None


def get_shop_coordinates(shop):
    """
    店舗データから緯度経度を取得する。
    """

    coordinates = shop.get(
        "coordinates",
        "",
    )

    parsed = parse_coordinates(
        coordinates
    )

    if parsed:
        return parsed

    lat = shop.get(
        "lat",
        "",
    )

    lng = shop.get(
        "lng",
        "",
    )

    try:

        if lat and lng:
            return (
                float(lat),
                float(lng),
            )

    except Exception:
        pass

    return None


def coordinates_are_close(
    shop1,
    shop2,
    threshold_meters=50,
):
    """
    2店舗の座標が一定距離以内なら
    同一店舗候補と判定する。
    """

    coordinates1 = get_shop_coordinates(
        shop1
    )

    coordinates2 = get_shop_coordinates(
        shop2
    )

    if not coordinates1 or not coordinates2:
        return False

    lat1, lon1 = coordinates1
    lat2, lon2 = coordinates2

    lat_distance = (
        abs(lat1 - lat2)
        * 111000
    )

    average_latitude = (
        lat1 + lat2
    ) / 2

    lon_distance = (
        abs(lon1 - lon2)
        * 111000
        * max(
            0.1,
            abs(
                __import__("math").cos(
                    __import__("math").radians(
                        average_latitude
                    )
                )
            ),
        )
    )

    distance = (
        lat_distance ** 2
        + lon_distance ** 2
    ) ** 0.5

    return distance <= threshold_meters


def shop_names_are_similar(
    name1,
    name2,
):
    """
    店舗名の表記揺れを考慮して
    同一店舗候補か判定する。
    """

    normalized1 = (
        normalize_shop_name_for_duplicate(
            name1
        )
    )

    normalized2 = (
        normalize_shop_name_for_duplicate(
            name2
        )
    )

    if not normalized1 or not normalized2:
        return False

    if normalized1 == normalized2:
        return True

    if (
        len(normalized1) < 6
        or len(normalized2) < 6
    ):
        return False

    if (
        normalized1 in normalized2
        or normalized2 in normalized1
    ):
        return True

    return False


def shops_are_same_store(
    shop1,
    shop2,
):
    """
    2つの店舗データが同一店舗か判定する。
    """

    name1 = normalize_shop_name_for_duplicate(
        shop1.get(
            "name",
            "",
        )
    )

    name2 = normalize_shop_name_for_duplicate(
        shop2.get(
            "name",
            "",
        )
    )

    address1 = normalize_address_for_duplicate(
        shop1.get(
            "address",
            "",
        )
    )

    address2 = normalize_address_for_duplicate(
        shop2.get(
            "address",
            "",
        )
    )

    # =====================================================
    # ① 店名 + 住所 完全一致
    # =====================================================

    if (
        name1
        and name2
        and address1
        and address2
        and name1 == name2
        and address1 == address2
    ):
        return True

    # =====================================================
    # ② 店名 + 座標 完全一致
    # =====================================================

    coordinates1 = get_shop_coordinates(
        shop1
    )

    coordinates2 = get_shop_coordinates(
        shop2
    )

    if (
        name1
        and name2
        and coordinates1
        and coordinates2
        and name1 == name2
    ):

        lat1, lon1 = coordinates1
        lat2, lon2 = coordinates2

        if (
            abs(lat1 - lat2) < 0.000001
            and abs(lon1 - lon2) < 0.000001
        ):
            return True

    # =====================================================
    # ③ 店名表記揺れ + 住所一致
    # =====================================================

    if (
        name1
        and name2
        and address1
        and address2
        and shop_names_are_similar(
            name1,
            name2,
        )
        and address1 == address2
    ):
        return True

    # =====================================================
    # ④ 店名表記揺れ + 座標近接
    # =====================================================

    if (
        name1
        and name2
        and shop_names_are_similar(
            name1,
            name2,
        )
        and coordinates_are_close(
            shop1,
            shop2,
            threshold_meters=50,
        )
    ):
        return True

    # =====================================================
    # ⑤ 店名完全一致 + 座標近接
    # =====================================================

    if (
        name1
        and name2
        and name1 == name2
        and coordinates_are_close(
            shop1,
            shop2,
            threshold_meters=50,
        )
    ):
        return True

    return False


def add_conversation_history(
    user_id,
    role,
    content,
):
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_histories[user_id].append({
        "role": role,
        "content": content,
    })

    if len(conversation_histories[user_id]) > MAX_HISTORY:
        conversation_histories[user_id] = (
            conversation_histories[user_id][-MAX_HISTORY:]
        )


def get_conversation_history(user_id):
    return conversation_histories.get(
        user_id,
        [],
    )


# =========================================================
# LINE返信
# =========================================================

def reply_text(
    reply_token,
    text,
    quick_reply=None,
):
    message = TextMessage(
        text=text,
        quick_reply=quick_reply,
    )

    request_body = ReplyMessageRequest(
        reply_token=reply_token,
        messages=[message],
    )

    line_messaging_api.reply_message(
        request_body
    )


def push_text(
    user_id,
    text,
):
    """
    ReplyToken使用後に追加回答を送るためのPush Message。
    """

    message = TextMessage(
        text=text
    )

    request_body = PushMessageRequest(
        to=user_id,
        messages=[message],
    )

    line_messaging_api.push_message(
        request_body
    )


def build_quick_reply(options):
    items = []

    for option in options:
        items.append(
            QuickReplyItem(
                action=MessageAction(
                    label=option,
                    text=option,
                )
            )
        )

    return QuickReply(
        items=items
    )


# =========================================================
# 検索ステート
# =========================================================

def get_search_state(user_id):
    if user_id not in search_states:
        search_states[user_id] = {
            "step": "location",
            "location": "",
            "genre": "",
            "ramen_style": "",
            "people": "",
            "time": "",
        }

    return search_states[user_id]


def reset_search_state(user_id):
    search_states.pop(
        user_id,
        None,
    )


def build_confirmation_text(state):
    genre_text = state["genre"]

    if (
        state.get("genre") == "ラーメン"
        and state.get("ramen_style")
        and state.get("ramen_style") != "指定なし"
    ):
        genre_text += (
            f"（{state['ramen_style']}）"
        )

    return (
        f"{state['location']}で"
        f"{genre_text}を探す。"
        f"{state['people']}で利用。"
        f"利用時間は{state['time']}。"
    )


# =========================================================
# 駅名関連
# =========================================================

def normalize_station_name(location):
    """
    ユーザーが入力した駅名を整える。
    """

    location = normalize_text(location)

    if not location:
        return ""

    if location.endswith("駅"):
        return location

    return f"{location}駅"


def extract_location_from_text(user_text):
    """
    検索文から駅名部分を取得する。
    """

    user_text = normalize_text(user_text)

    if not user_text:
        return ""

    if "で" in user_text:
        location = user_text.split("で", 1)[0].strip()

        if location:
            return location

    return user_text


# =========================================================
# Hot Pepper
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
        "開始",
    ]

    if user_text == "開始":
        return True

    return any(
        keyword in user_text
        for keyword in keywords
    )


def build_hotpepper_keyword(user_text):
    parts = []

    location = extract_location_from_text(
        user_text
    )

    if location:
        location = normalize_text(location)

        if location:
            parts.append(location)

    genre = ""

    for option in GENRE_OPTIONS:
        if option in user_text:
            genre = option
            break

    if genre and genre != "その他":
        parts.append(genre)

    # ラーメン系統を検索キーワードにも追加
    ramen_styles = [
        "家系",
        "二郎系",
        "町中華系",
        "魚介系",
        "味噌",
    ]

    if genre == "ラーメン":
        for style in ramen_styles:
            if style in user_text:
                parts.append(style)
                break

    if not parts:
        return user_text

    return " ".join(parts)


def search_hotpepper(user_text):
    """
    Hot Pepperから店舗候補を取得する。
    """

    if not HOTPEPPER_API_KEY:
        print(
            "HOTPEPPER_API_KEYが設定されていません。"
        )
        return []

    keyword = build_hotpepper_keyword(
        user_text
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
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:
        print(
            "Hot Pepper APIエラー:",
            e,
        )
        return []

    results = []

    shops = (
        data.get("results", {})
        .get("shop", [])
    )

    if isinstance(shops, dict):
        shops = [shops]

    for shop in shops:
        results.append({
            "name": shop.get(
                "name",
                "",
            ),
            "genre": (
                shop.get("genre", {})
                .get("name", "")
            ),
            "address": shop.get(
                "address",
                "",
            ),
            "station": shop.get(
                "station_name",
                "",
            ),
            "open": shop.get(
                "open",
                "",
            ),
            "close": shop.get(
                "close",
                "",
            ),
            "url": (
                shop.get("urls", {})
                .get("pc", "")
            ),
            "tel": shop.get(
                "tel",
                "",
            ),
            "lat": shop.get(
                "lat",
                "",
            ),
            "lng": shop.get(
                "lng",
                "",
            ),
            "source": "Hot Pepper",
        })

    print(
        f"Hot Pepper取得店舗数: "
        f"{len(results)}件"
    )

    for index, shop in enumerate(
        results,
        start=1,
    ):
        print(
            f"  Hot Pepper {index}: "
            f"{shop.get('name', '')}"
        )

    return results


# =========================================================
# Tavily
# =========================================================

def search_tavily(
    query,
    max_results=5,
):
    if not TAVILY_API_KEY:
        print(
            "TAVILY_API_KEYが設定されていません。"
        )
        return []

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        response = requests.post(
            TAVILY_URL,
            json=payload,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:
        print(
            "Tavily APIエラー:",
            e,
        )
        return []

    return data.get(
        "results",
        [],
    )


def _build_tavily_shop_text(results):
    text_parts = []

    for result in results:
        title = normalize_text(
            result.get(
                "title",
                "",
            )
        )

        content = normalize_text(
            result.get(
                "content",
                "",
            )
        )

        if title:
            text_parts.append(
                title
            )

        if content:
            text_parts.append(
                content
            )

    return " ".join(
        text_parts
    )


def _contains_any(
    text,
    keywords,
):
    return any(
        keyword in text
        for keyword in keywords
    )


def check_shop_with_tavily(shop):
    """
    Tavilyを使って店舗の営業状況を確認する。
    """

    name = normalize_text(
        shop.get(
            "name",
            "",
        )
    )

    address = normalize_text(
        shop.get(
            "address",
            "",
        )
    )

    if not name:
        return {
            "status": "unknown",
            "reason": "",
        }

    query = (
        f'"{name}" '
        f"{address} "
        "営業状況 営業時間 営業中 閉店 閉業 移転 "
        "最新情報"
    )

    results = search_tavily(
        query,
        max_results=5,
    )

    if not results:
        return {
            "status": "unknown",
            "reason": "",
        }

    combined = _build_tavily_shop_text(
        results
    )

    if not combined:
        return {
            "status": "unknown",
            "reason": "",
        }

    future_closure_keywords = [
        "閉店予定",
        "閉店する予定",
        "閉店を予定",
        "閉店予告",
        "営業終了予定",
        "営業終了を予定",
        "閉店予定です",
        "閉店することになりました",
    ]

    strong_closed_keywords = [
        "閉店しました",
        "閉店いたしました",
        "閉店のお知らせ",
        "閉店のお知らせです",
        "営業終了しました",
        "営業を終了しました",
        "営業終了のお知らせ",
        "営業を終了いたしました",
        "閉業しました",
        "閉業いたしました",
        "廃業しました",
        "廃業いたしました",
        "店舗を閉鎖しました",
        "店舗閉鎖",
        "閉鎖しました",
        "閉鎖いたしました",
        "営業していません",
        "現在営業していません",
        "現在は営業していません",
        "現在営業しておりません",
        "店舗はありません",
        "店舗は閉店",
    ]

    general_closed_keywords = [
        "閉店",
        "閉業",
        "廃業",
        "営業終了",
        "店舗終了",
        "閉鎖",
    ]

    has_future_closure = _contains_any(
        combined,
        future_closure_keywords,
    )

    has_strong_closed = _contains_any(
        combined,
        strong_closed_keywords,
    )

    has_general_closed = _contains_any(
        combined,
        general_closed_keywords,
    )

    strong_open_keywords = [
        "現在営業中",
        "現在も営業",
        "現在営業しています",
        "現在も営業しています",
        "現在営業しております",
        "営業中です",
        "営業しています",
        "営業しております",
        "営業中",
        "営業再開",
        "営業再開しました",
        "営業を再開しました",
        "営業再開のお知らせ",
        "現在営業中です",
        "現在も営業中です",
    ]

    weak_open_keywords = [
        "営業時間",
        "定休日",
        "ランチ営業",
        "ディナー営業",
    ]

    has_strong_open = _contains_any(
        combined,
        strong_open_keywords,
    )

    has_weak_open = _contains_any(
        combined,
        weak_open_keywords,
    )

    relocation_keywords = [
        "移転しました",
        "移転いたしました",
        "移転のお知らせ",
        "移転しましたので",
        "移転先",
        "店舗を移転",
    ]

    has_relocation = _contains_any(
        combined,
        relocation_keywords,
    )

    if has_strong_closed:

        if not has_strong_open:
            return {
                "status": "closed",
                "reason": combined[:500],
            }

    if (
        has_general_closed
        and not has_future_closure
        and not has_strong_open
    ):

        if has_relocation:
            return {
                "status": "unknown",
                "reason": combined[:500],
            }

        return {
            "status": "closed",
            "reason": combined[:500],
        }

    if has_strong_open:
        return {
            "status": "open",
            "reason": combined[:500],
        }

    if (
        has_relocation
        or has_future_closure
    ):
        return {
            "status": "unknown",
            "reason": combined[:500],
        }

    if has_weak_open:
        return {
            "status": "unknown",
            "reason": combined[:500],
        }

    return {
        "status": "unknown",
        "reason": combined[:500],
    }


def verify_shops_with_tavily(
    shops,
):
    verified = []

    print(
        "========================================"
    )
    print(
        "統合店舗のTavily営業状況確認開始"
    )
    print(
        f"Tavily確認対象: {len(shops)}件"
    )
    print(
        "========================================"
    )

    for shop in shops:

        shop_name = shop.get(
            "name",
            "",
        )

        verification = (
            check_shop_with_tavily(
                shop
            )
        )

        status = verification.get(
            "status",
            "unknown",
        )

        reason = verification.get(
            "reason",
            "",
        )

        print(
            f"Tavily確認: "
            f"{shop_name} → {status}"
        )

        if reason:

            reason_log = (
                reason
                .replace("\n", " ")
                .strip()
            )

            if len(reason_log) > 200:
                reason_log = (
                    reason_log[:200]
                    + "..."
                )

            print(
                f"  判定理由: "
                f"{reason_log}"
            )

        else:
            print(
                "  判定理由: 情報なし"
            )

        if status == "closed":

            print(
                f"Tavily判定で除外: "
                f"{shop_name}"
            )

            print(
                "----------------------------------------"
            )

            continue

        shop["tavily_status"] = status
        shop["tavily_reason"] = reason

        verified.append(shop)

        print(
            f"候補として保持: "
            f"{shop_name}"
        )

        print(
            "----------------------------------------"
        )

        time.sleep(0.2)

    print(
        "統合店舗のTavily営業状況確認終了"
    )

    print(
        f"保持店舗数: "
        f"{len(verified)}件"
    )

    print(
        "========================================"
    )

    return verified


def should_search_tavily(user_text):
    keywords = [
        "営業",
        "開いてる",
        "開いている",
        "閉まってる",
        "閉店",
        "営業中",
        "最新",
        "今",
        "今日",
    ]

    return any(
        keyword in user_text
        for keyword in keywords
    )


def get_tavily_context(user_text):
    if not should_search_tavily(
        user_text
    ):
        return ""

    results = search_tavily(
        user_text,
        max_results=5,
    )

    if not results:
        return ""

    context_parts = []

    for result in results:

        title = result.get(
            "title",
            "",
        )

        content = result.get(
            "content",
            "",
        )

        url = result.get(
            "url",
            "",
        )

        context_parts.append(
            f"タイトル: {title}\n"
            f"内容: {content}\n"
            f"URL: {url}"
        )

    return "\n\n".join(
        context_parts
    )


# =========================================================
# Yahoo!ローカルサーチ
# =========================================================

def build_yahoo_local_keyword(user_text):
    genre = ""

    for option in GENRE_OPTIONS:
        if option in user_text:
            genre = option
            break

    if genre:
        if genre == "その他":
            return "飲食店"

        keyword = genre

        # ラーメン系統を検索キーワードにも追加
        if genre == "ラーメン":

            ramen_styles = [
                "家系",
                "二郎系",
                "町中華系",
                "魚介系",
                "味噌",
            ]

            for style in ramen_styles:
                if style in user_text:
                    keyword = (
                        f"{genre} {style}"
                    )
                    break

        return keyword

    search_terms = [
        "お店",
        "店",
        "飲食店",
        "レストラン",
        "探して",
        "検索",
        "おすすめ",
    ]

    keyword = user_text

    for term in search_terms:
        keyword = keyword.replace(
            term,
            "",
        )

    return keyword.strip()


def parse_yahoo_features(data):
    features = data.get(
        "Feature",
        [],
    )

    if isinstance(features, dict):
        features = [features]

    candidates = []

    for feature in features:

        name = feature.get(
            "Name",
            "",
        )

        property_data = feature.get(
            "Property",
            {},
        ) or {}

        if isinstance(property_data, list):
            property_data = (
                property_data[0]
                if property_data
                else {}
            )

        address = property_data.get(
            "Address",
            "",
        )

        tel = property_data.get(
            "Tel1",
            "",
        )

        detail = property_data.get(
            "Detail",
            {},
        ) or {}

        pc_url = detail.get(
            "PcUrl1",
            "",
        )

        genre_data = property_data.get(
            "Genre",
            [],
        )

        if isinstance(
            genre_data,
            dict,
        ):
            genre_data = [genre_data]

        genre_names = []

        for genre in genre_data:

            if isinstance(
                genre,
                dict,
            ):
                genre_name = genre.get(
                    "Name",
                    "",
                )
            else:
                genre_name = str(
                    genre
                )

            if genre_name:
                genre_names.append(
                    genre_name
                )

        station_data = property_data.get(
            "Station",
            [],
        )

        if isinstance(
            station_data,
            dict,
        ):
            station_data = [
                station_data
            ]

        station_names = []

        for station in station_data:

            if isinstance(
                station,
                dict,
            ):
                station_name = station.get(
                    "Name",
                    "",
                )
            else:
                station_name = str(
                    station
                )

            if station_name:
                station_names.append(
                    station_name
                )

        geometry = feature.get(
            "Geometry",
            {},
        ) or {}

        coordinates = geometry.get(
            "Coordinates",
            "",
        )

        distance_value = feature.get(
            "Distance",
            "",
        )

        candidates.append({
            "name": name,
            "genre": ", ".join(
                genre_names
            ),
            "address": address,
            "station": ", ".join(
                station_names
            ),
            "tel": tel,
            "url": pc_url,
            "coordinates": coordinates,
            "distance": distance_value,
            "source": "Yahoo!ローカルサーチ",
        })

    return candidates


# =========================================================
# Yahoo!重複除去
# =========================================================

def deduplicate_yahoo_results(
    candidates,
):
    unique = []

    for candidate in candidates:

        duplicate_index = None

        for index, existing in enumerate(
            unique
        ):

            if shops_are_same_store(
                candidate,
                existing,
            ):
                duplicate_index = index
                break

        if duplicate_index is not None:

            existing = unique[
                duplicate_index
            ]

            print(
                "Yahoo!重複除外:",
                candidate.get(
                    "name",
                    "",
                ),
                candidate.get(
                    "address",
                    "",
                ),
            )

            print(
                "  → 既存:",
                existing.get(
                    "name",
                    "",
                ),
                existing.get(
                    "address",
                    "",
                ),
            )

            continue

        unique.append(
            candidate
        )

    print(
        f"Yahoo!重複除去: "
        f"{len(candidates)}件 → "
        f"{len(unique)}件"
    )

    return unique


def search_yahoo_local_by_coordinates(
    latitude,
    longitude,
    query="",
    distance=YAHOO_SEARCH_DISTANCE_METERS,
):
    if not YAHOO_CLIENT_ID:
        print(
            "YAHOO_CLIENT_IDが設定されていません。"
        )
        return []

    params = {
        "appid": YAHOO_CLIENT_ID,
        "lat": latitude,
        "lon": longitude,
        "dist": distance,
        "results": 10,
        "sort": "geo",
        "detail": "standard",
        "output": "json",
    }

    if query:
        params["query"] = query

    try:
        response = requests.get(
            YAHOO_LOCAL_SEARCH_URL,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:

        print(
            "Yahoo!座標検索エラー:",
            e,
        )

        return []

    candidates = parse_yahoo_features(
        data
    )

    candidates = deduplicate_yahoo_results(
        candidates
    )

    return candidates


def search_yahoo_local_keyword(
    keyword,
):
    if not YAHOO_CLIENT_ID:
        print(
            "YAHOO_CLIENT_IDが設定されていません。"
        )
        return []

    if not keyword:
        keyword = "飲食店"

    params = {
        "appid": YAHOO_CLIENT_ID,
        "query": keyword,
        "results": 10,
        "sort": "geo",
        "detail": "standard",
        "output": "json",
    }

    try:
        response = requests.get(
            YAHOO_LOCAL_SEARCH_URL,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:

        print(
            "Yahoo!キーワード検索エラー:",
            e,
        )

        return []

    candidates = parse_yahoo_features(
        data
    )

    return deduplicate_yahoo_results(
        candidates
    )


def get_yahoo_location_coordinates(
    location,
):
    """
    Yahoo!ローカルサーチで駅名を検索し、
    駅のGeometry.Coordinatesから
    緯度・経度を取得する。
    """

    if not YAHOO_CLIENT_ID:
        print(
            "YAHOO_CLIENT_IDが設定されていません。"
        )
        return None

    location = normalize_text(location)

    if not location:
        return None

    station_name = normalize_station_name(
        location
    )

    query_candidates = []

    query_candidates.append(location)

    if station_name not in query_candidates:
        query_candidates.append(
            station_name
        )

    for query in query_candidates:

        params = {
            "appid": YAHOO_CLIENT_ID,
            "query": query,
            "results": 10,
            "sort": "geo",
            "detail": "standard",
            "output": "json",
        }

        try:
            response = requests.get(
                YAHOO_LOCAL_SEARCH_URL,
                params=params,
                timeout=20,
            )

            response.raise_for_status()

            data = response.json()

        except Exception as e:

            print(
                "Yahoo!駅座標取得エラー:",
                e,
            )

            continue

        features = data.get(
            "Feature",
            [],
        )

        if isinstance(
            features,
            dict,
        ):
            features = [features]

        exact_candidate = None
        contains_candidate = None
        station_candidate = None

        for feature in features:

            name = feature.get(
                "Name",
                "",
            )

            property_data = feature.get(
                "Property",
                {},
            ) or {}

            if isinstance(
                property_data,
                list,
            ):
                property_data = (
                    property_data[0]
                    if property_data
                    else {}
                )

            property_name = property_data.get(
                "Name",
                "",
            )

            geometry = feature.get(
                "Geometry",
                {},
            ) or {}

            coordinates = geometry.get(
                "Coordinates",
                "",
            )

            if not coordinates:
                continue

            candidate_name = (
                name
                or property_name
            )

            if not candidate_name:
                continue

            is_station = (
                "駅" in candidate_name
            )

            candidate = (
                candidate_name,
                coordinates,
            )

            if (
                candidate_name == station_name
                or candidate_name == location
            ):

                if is_station:
                    exact_candidate = candidate
                    break

                if exact_candidate is None:
                    exact_candidate = candidate

            if (
                station_name in candidate_name
                or location in candidate_name
            ):

                if is_station:

                    if station_candidate is None:
                        station_candidate = candidate

                elif contains_candidate is None:

                    contains_candidate = candidate

        candidate = (
            exact_candidate
            or station_candidate
            or contains_candidate
        )

        if not candidate:
            continue

        candidate_name, coordinate_text = candidate

        if "駅" not in candidate_name:
            continue

        try:

            longitude_str, latitude_str = (
                coordinate_text.split(",")[:2]
            )

            latitude = float(
                latitude_str
            )

            longitude = float(
                longitude_str
            )

        except Exception as e:

            print(
                "Yahoo!座標解析エラー:",
                e,
            )

            continue

        print(
            f"Yahoo!駅座標取得成功: "
            f"{candidate_name} "
            f"lat={latitude}, "
            f"lon={longitude}"
        )

        return latitude, longitude

    print(
        f"Yahoo!で駅座標を取得できませんでした: "
        f"{location}"
    )

    return None


def search_yahoo_local(
    user_text,
):
    """
    指定駅の座標を取得し、
    半径1.5km以内を検索する。
    """

    location = extract_location_from_text(
        user_text
    )

    keyword = build_yahoo_local_keyword(
        user_text
    )

    if location:

        coordinates = (
            get_yahoo_location_coordinates(
                location
            )
        )

        if coordinates:

            latitude, longitude = coordinates

            if keyword == "その他":
                keyword = "飲食店"

            return search_yahoo_local_by_coordinates(
                latitude,
                longitude,
                query=keyword,
                distance=YAHOO_SEARCH_DISTANCE_METERS,
            )

        fallback_keyword = " ".join(
            part
            for part in [
                location,
                keyword,
            ]
            if part
        )

        return search_yahoo_local_keyword(
            fallback_keyword
        )

    return search_yahoo_local_keyword(
        keyword
    )


# =========================================================
# Hot Pepper + Yahoo! 統合
# =========================================================

def merge_shop_results(
    hotpepper_results,
    yahoo_results,
):
    """
    Hot PepperとYahoo!の検索結果を統合する。
    """

    print(
        "========================================"
    )

    print(
        "Hot Pepper + Yahoo! 店舗統合開始"
    )

    print(
        f"Hot Pepper: "
        f"{len(hotpepper_results)}件"
    )

    print(
        f"Yahoo!: "
        f"{len(yahoo_results)}件"
    )

    print(
        "========================================"
    )

    merged = []

    # =====================================================
    # Hot Pepperを先に追加
    # =====================================================

    for shop in hotpepper_results:

        new_shop = dict(shop)

        new_shop["source"] = "Hot Pepper"

        merged.append(
            new_shop
        )

    # =====================================================
    # Yahoo!を追加
    # =====================================================

    for yahoo_shop in yahoo_results:

        existing_index = None

        for index, existing in enumerate(
            merged
        ):

            if shops_are_same_store(
                yahoo_shop,
                existing,
            ):
                existing_index = index
                break

        if existing_index is None:

            new_shop = dict(
                yahoo_shop
            )

            new_shop["source"] = (
                "Yahoo!ローカルサーチ"
            )

            merged.append(
                new_shop
            )

            print(
                "統合追加:",
                new_shop.get(
                    "name",
                    "",
                ),
                "← Yahoo!"
            )

            continue

        existing = merged[
            existing_index
        ]

        if not existing.get("genre"):
            existing["genre"] = (
                yahoo_shop.get(
                    "genre",
                    "",
                )
            )

        if not existing.get("address"):
            existing["address"] = (
                yahoo_shop.get(
                    "address",
                    "",
                )
            )

        if not existing.get("station"):
            existing["station"] = (
                yahoo_shop.get(
                    "station",
                    "",
                )
            )

        if not existing.get("tel"):
            existing["tel"] = (
                yahoo_shop.get(
                    "tel",
                    "",
                )
            )

        if not existing.get("url"):
            existing["url"] = (
                yahoo_shop.get(
                    "url",
                    "",
                )
            )

        if not existing.get("coordinates"):
            existing["coordinates"] = (
                yahoo_shop.get(
                    "coordinates",
                    "",
                )
            )

        if not existing.get("distance"):
            existing["distance"] = (
                yahoo_shop.get(
                    "distance",
                    "",
                )
            )

        existing["source"] = (
            "Hot Pepper + Yahoo!"
        )

        print(
            "店舗統合:",
            existing.get(
                "name",
                "",
            ),
            "← Hot Pepper + Yahoo!"
        )

    print(
        "----------------------------------------"
    )

    print(
        f"統合前: "
        f"{len(hotpepper_results) + len(yahoo_results)}件"
    )

    print(
        f"統合後: "
        f"{len(merged)}件"
    )

    print(
        "========================================"
    )

    return merged


# =========================================================
# 統合店舗整形
# =========================================================

def format_merged_results(
    results,
):
    if not results:
        return "店舗検索結果なし"

    lines = []

    for index, shop in enumerate(
        results,
        start=1,
    ):

        lines.append(
            f"{index}. "
            f"{shop.get('name', '')}"
        )

        if shop.get("source"):
            lines.append(
                f"   情報元: "
                f"{shop.get('source', '')}"
            )

        if shop.get("genre"):
            lines.append(
                f"   ジャンル: "
                f"{shop.get('genre', '')}"
            )

        if shop.get("address"):
            lines.append(
                f"   住所: "
                f"{shop.get('address', '')}"
            )

        if shop.get("station"):
            lines.append(
                f"   最寄駅: "
                f"{shop.get('station', '')}"
            )

        if shop.get("open"):
            lines.append(
                f"   営業時間: "
                f"{shop.get('open', '')}"
            )

        if shop.get("distance"):
            lines.append(
                f"   距離: "
                f"{shop.get('distance', '')}"
            )

        if shop.get("tavily_status"):
            lines.append(
                f"   Tavily営業状況: "
                f"{shop.get('tavily_status', '')}"
            )

        if shop.get("tavily_reason"):
            lines.append(
                f"   Tavily確認情報: "
                f"{shop.get('tavily_reason', '')[:300]}"
            )

        if shop.get("url"):
            lines.append(
                f"   URL: "
                f"{shop.get('url', '')}"
            )

        lines.append("")

    return "\n".join(lines)


# =========================================================
# 旧フォーマット互換
# =========================================================

def format_yahoo_results(
    results,
):
    return format_merged_results(
        results
    )


def format_hotpepper_results(
    results,
):
    return format_merged_results(
        results
    )


# =========================================================
# グルメAIプロンプト
# =========================================================

def build_gourmet_prompt(
    user_id,
    user_text,
):
    hotpepper_results = []
    yahoo_results = []
    merged_results = []

    if should_search_hotpepper(
        user_text
    ):

        # =================================================
        # ① Hot Pepper
        # =================================================

        hotpepper_results = search_hotpepper(
            user_text
        )

        # =================================================
        # ② Yahoo!
        # =================================================

        yahoo_results = search_yahoo_local(
            user_text
        )

        print(
            f"Yahoo!取得店舗数: "
            f"{len(yahoo_results)}件"
        )

        # =================================================
        # ③ Hot Pepper + Yahoo! 統合
        # =================================================

        merged_results = merge_shop_results(
            hotpepper_results,
            yahoo_results,
        )

        # =================================================
        # ④ 統合後にTavily確認
        # =================================================

        print(
            f"統合店舗 → Tavily確認前: "
            f"{len(merged_results)}件"
        )

        merged_results = verify_shops_with_tavily(
            merged_results
        )

        print(
            f"統合店舗 → Tavily確認後: "
            f"{len(merged_results)}件"
        )

    merged_context = format_merged_results(
        merged_results
    )

    if should_search_hotpepper(
        user_text
    ):
        tavily_context = ""
    else:
        tavily_context = get_tavily_context(
            user_text
        )

    history = get_conversation_history(
        user_id
    )

    history_text = ""

    if history:

        history_lines = []

        for item in history:

            role = item.get(
                "role",
                "",
            )

            content = item.get(
                "content",
                "",
            )

            history_lines.append(
                f"{role}: {content}"
            )

        history_text = "\n".join(
            history_lines
        )

    prompt = f"""
あなたは「AIアヤフミ（グルメ）」です。
ユーザーの希望に合った飲食店を探して提案してください。

【ユーザーの今回の依頼】
{user_text}

【過去の会話】
{history_text}

【Hot Pepper + Yahoo! 統合後の店舗検索結果】
{merged_context}

【Tavily最新情報】
{tavily_context}

【重要ルール】

1. ユーザーが指定した条件を最優先してください。

2. 場所、ジャンル、人数、利用時間などが
   すでに指定されている場合は、
   同じことをもう一度質問しないでください。

3. ラーメンの系統が指定されている場合は、
   その系統を候補選定の重要条件として扱ってください。

4. 例えば「家系」と指定された場合、
   検索結果に家系である根拠がある店舗を優先してください。

5. 「二郎系」と指定された場合、
   検索結果に二郎系である根拠がある店舗を優先してください。

6. ラーメン系統について検索結果に十分な情報がない場合は、
   勝手に系統を断定しないでください。

7. Hot PepperとYahoo!の情報を統合した
   「Hot Pepper + Yahoo! 統合後の店舗検索結果」
   を基本的な店舗候補として利用してください。

8. 同じ店舗がHot PepperとYahoo!の両方に存在する場合は、
   1店舗として扱ってください。

9. 「情報元」が
   「Hot Pepper + Yahoo!」となっている店舗は、
   複数の検索元で確認できた店舗として扱ってください。

10. Tavilyで「closed」と判断された店舗は、
    統合後の候補から除外されています。
    絶対に候補として表示しないでください。

11. Tavilyで「unknown」の店舗については、
    営業中・閉店のどちらかを勝手に断定しないでください。

12. Tavilyで「open」と判断された店舗についても、
    検索結果に存在しない情報を追加しないでください。

13. 検索結果に存在しない情報を勝手に作らないでください。

14. ユーザーが人数を指定している場合は、
    その人数で利用しやすい店を優先してください。

15. ユーザーが昼・夜など利用時間を指定している場合は、
    その時間帯に利用しやすい店を優先してください。

16. Yahoo!検索結果の「距離」が存在する場合は、
    駅からの近さを候補選定の参考にしてください。

17. Hot PepperとYahoo!の情報が両方存在する場合は、
    情報を組み合わせて分かりやすく説明してください。

18. 条件に合う店が少ない場合は、
    無理に条件に合うと断定せず、
    「条件に近い候補」として正直に説明してください。

19. 店舗候補は見やすく整理してください。

20. 特に条件に合いそうな店舗を優先してください。

21. 店舗情報を紹介するときは、
    「店名」「おすすめ理由」「特徴」
    が分かりやすい構成にしてください。

22. 検索結果にURLがある場合は、
    可能な範囲で店舗URLも提示してください。

23. 回答はLINEで読みやすいように、
    長くなりすぎないようにしてください。

24. 店舗数を水増しするために、
    検索結果にない店舗を追加しないでください。

25. 予算を条件として勝手に設定しないでください。
    店舗の価格情報が検索結果に存在する場合でも、
    価格だけを理由に候補から除外しないでください。
"""

    return prompt


# =========================================================
# Gemini
# =========================================================

def ask_gemini(prompt):
    if not GEMINI_API_KEY:
        print(
            "GEMINI_API_KEYが設定されていません。"
        )
        return None

    headers = {
        "Content-Type": "application/json",
    }

    params = {
        "key": GEMINI_API_KEY,
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
            timeout=60,
        )

        if response.status_code != 200:

            print(
                "Gemini HTTP:",
                response.status_code,
            )

            print(
                response.text[:1000]
            )

            return None

        data = response.json()

        candidates = data.get(
            "candidates",
            [],
        )

        if not candidates:
            return None

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        texts = []

        for part in parts:

            text = part.get(
                "text",
                "",
            )

            if text:
                texts.append(text)

        result = "\n".join(
            texts
        ).strip()

        if not result:
            return None

        return result

    except Exception as e:

        print(
            "Gemini APIエラー:",
            e,
        )

        return None


# =========================================================
# Groq
# =========================================================

def ask_groq(prompt):
    if not GROQ_API_KEY:
        print(
            "GROQ_API_KEYが設定されていません。"
        )
        return None

    headers = {
        "Authorization": (
            f"Bearer {GROQ_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:

        response = requests.post(
            GROQ_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code != 200:

            print(
                "Groq HTTP:",
                response.status_code,
            )

            print(
                response.text[:1000]
            )

            return None

        data = response.json()

        choices = data.get(
            "choices",
            [],
        )

        if not choices:
            return None

        message = choices[0].get(
            "message",
            {},
        )

        result = message.get(
            "content",
            "",
        )

        if not result:
            return None

        return result.strip()

    except Exception as e:

        print(
            "Groq APIエラー:",
            e,
        )

        return None


# =========================================================
# OpenRouter
# =========================================================

def ask_openrouter(prompt):
    if not OPENROUTER_API_KEY:
        print(
            "OPENROUTER_API_KEYが設定されていません。"
        )
        return None

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://ai-ayafumi-gourmet.onrender.com"
        ),
        "X-Title": "AIアヤフミ（グルメ）",
    }

    payload = {
        "model": "openai/gpt-oss-20b:free",
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:

        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code != 200:

            print(
                "OpenRouter HTTP:",
                response.status_code,
            )

            print(
                response.text[:1000]
            )

            return None

        data = response.json()

        choices = data.get(
            "choices",
            [],
        )

        if not choices:
            return None

        message = choices[0].get(
            "message",
            {},
        )

        result = message.get(
            "content",
            "",
        )

        if not result:
            return None

        return result.strip()

    except Exception as e:

        print(
            "OpenRouter APIエラー:",
            e,
        )

        return None


# =========================================================
# AI回答整形
# =========================================================

def clean_answer(answer):
    if not answer:
        return ""

    answer = answer.strip()

    answer = answer.replace(
        "### ",
        "",
    )

    return answer


# =========================================================
# グルメAI本体
# =========================================================

def ask_gourmet_ai(
    user_id,
    user_text,
):
    prompt = build_gourmet_prompt(
        user_id,
        user_text,
    )

    answer = ask_groq(
        prompt
    )

    if answer:

        print(
            "AI回答: Groq"
        )

        return clean_answer(
            answer
        )

    answer = ask_gemini(
        prompt
    )

    if answer:

        print(
            "AI回答: Gemini"
        )

        return clean_answer(
            answer
        )

    answer = ask_openrouter(
        prompt
    )

    if answer:

        print(
            "AI回答: OpenRouter"
        )

        return clean_answer(
            answer
        )

    return (
        "すみません。"
        "現在、グルメ検索AIに接続できませんでした。"
        "少し時間を置いてもう一度試してください。"
    )


# =========================================================
# 検索フロー
# =========================================================

def start_search_flow(
    reply_token,
    user_id,
):
    state = get_search_state(
        user_id
    )

    state["step"] = "location"
    state["location"] = ""
    state["genre"] = ""
    state["ramen_style"] = ""
    state["people"] = ""
    state["time"] = ""

    reply_text(
        reply_token,
        (
            "お店を探したい駅名を入力してください。\n"
            "例：町田駅、新宿駅、京王堀之内駅"
        ),
    )


def handle_search_selection(
    reply_token,
    user_id,
    user_text,
):
    state = get_search_state(
        user_id
    )

    step = state.get(
        "step",
        "location",
    )

    # =====================================================
    # 場所
    # =====================================================

    if step == "location":

        location = normalize_text(
            user_text
        )

        if not location:

            reply_text(
                reply_token,
                (
                    "駅名を入力してください。\n"
                    "例：町田駅、新宿駅、京王堀之内駅"
                ),
            )

            return

        print(
            f"駅名入力確認: {location}"
        )

        coordinates = (
            get_yahoo_location_coordinates(
                location
            )
        )

        if not coordinates:

            reply_text(
                reply_token,
                (
                    f"「{location}」の駅を確認できませんでした。\n\n"
                    "駅名をもう一度入力してください。\n"
                    "例：町田駅、新宿駅、京王堀之内駅"
                ),
            )

            return

        normalized_location = (
            normalize_station_name(
                location
            )
        )

        state["location"] = (
            normalized_location
        )

        state["step"] = "genre"

        reply_text(
            reply_token,
            (
                f"{normalized_location}ですね。\n"
                "ジャンルは何にしますか？"
            ),
            build_quick_reply(
                GENRE_OPTIONS
            ),
        )

        return

    # =====================================================
    # ジャンル
    # =====================================================

    if step == "genre":

        if user_text not in GENRE_OPTIONS:

            reply_text(
                reply_token,
                "ジャンルを選択してください。",
                build_quick_reply(
                    GENRE_OPTIONS
                ),
            )

            return

        state["genre"] = user_text

        # ラーメンの場合だけ系統選択へ
        if user_text == "ラーメン":

            state["step"] = "ramen_style"

            reply_text(
                reply_token,
                "ラーメンの系統はどうしますか？",
                build_quick_reply(
                    RAMEN_STYLE_OPTIONS
                ),
            )

            return

        state["ramen_style"] = ""
        state["step"] = "people"

        reply_text(
            reply_token,
            "何人で利用しますか？",
            build_quick_reply(
                PEOPLE_OPTIONS
            ),
        )

        return

    # =====================================================
    # ラーメン系統
    # =====================================================

    if step == "ramen_style":

        if user_text not in RAMEN_STYLE_OPTIONS:

            reply_text(
                reply_token,
                "ラーメンの系統を選択してください。",
                build_quick_reply(
                    RAMEN_STYLE_OPTIONS
                ),
            )

            return

        state["ramen_style"] = user_text
        state["step"] = "people"

        reply_text(
            reply_token,
            "何人で利用しますか？",
            build_quick_reply(
                PEOPLE_OPTIONS
            ),
        )

        return

    # =====================================================
    # 人数
    # =====================================================

    if step == "people":

        if user_text not in PEOPLE_OPTIONS:

            reply_text(
                reply_token,
                "人数を選択してください。",
                build_quick_reply(
                    PEOPLE_OPTIONS
                ),
            )

            return

        state["people"] = user_text
        state["step"] = "time"

        reply_text(
            reply_token,
            "利用時間はいつですか？",
            build_quick_reply(
                TIME_OPTIONS
            ),
        )

        return

    # =====================================================
    # 時間
    # =====================================================

    if step == "time":

        if user_text not in TIME_OPTIONS:

            reply_text(
                reply_token,
                "利用時間を選択してください。",
                build_quick_reply(
                    TIME_OPTIONS
                ),
            )

            return

        state["time"] = user_text
        state["step"] = "confirmation"

        confirmation = (
            build_confirmation_text(
                state
            )
        )

        reply_text(
            reply_token,
            (
                f"{confirmation}\n\n"
                "この条件で探しますか？"
            ),
            build_quick_reply(
                [
                    "この条件で探す",
                    "条件をやり直す",
                ]
            ),
        )

        return

    # =====================================================
    # 確認
    # =====================================================

    if step == "confirmation":

        if user_text == "条件をやり直す":

            reset_search_state(
                user_id
            )

            start_search_flow(
                reply_token,
                user_id,
            )

            return

        if user_text != "この条件で探す":

            reply_text(
                reply_token,
                (
                    "「この条件で探す」または"
                    "「条件をやり直す」を選択してください。"
                ),
                build_quick_reply(
                    [
                        "この条件で探す",
                        "条件をやり直す",
                    ]
                ),
            )

            return

        search_text = (
            build_confirmation_text(
                state
            )
        )

        add_conversation_history(
            user_id,
            "user",
            search_text,
        )

        reply_text(
            reply_token,
            "探しています。少々お待ちください…",
        )

        answer = ask_gourmet_ai(
            user_id,
            search_text,
        )

        add_conversation_history(
            user_id,
            "assistant",
            answer,
        )

        reset_search_state(
            user_id
        )

        try:

            push_text(
                user_id,
                answer,
            )

            print(
                "LINE最終回答送信成功"
            )

        except Exception as e:

            print(
                "LINE Push Messageエラー:",
                e,
            )

        return


# =========================================================
# Health Check
# =========================================================

@app.route(
    "/health",
    methods=["GET"],
)
def health():

    return jsonify({
        "status": "ok",
        "service": "AIアヤフミ（グルメ）",
    })


# =========================================================
# Yahoo!テスト
# =========================================================

@app.route(
    "/test_yahoo",
    methods=["POST"],
)
def test_yahoo():

    body = request.get_json(
        silent=True
    ) or {}

    user_text = body.get(
        "message",
        "",
    )

    if not user_text:

        return jsonify({
            "error": "messageがありません",
        }), 400

    results = search_yahoo_local(
        user_text
    )

    return jsonify({
        "message": user_text,
        "count": len(results),
        "results": results,
    })


# =========================================================
# Yahoo!駅周辺テスト
# =========================================================

@app.route(
    "/test_yahoo_nearby",
    methods=["POST"],
)
def test_yahoo_nearby():

    body = request.get_json(
        silent=True
    ) or {}

    keyword = body.get(
        "keyword",
        "ラーメン",
    )

    location = "京王堀之内駅"

    coordinates = (
        get_yahoo_location_coordinates(
            location
        )
    )

    if not coordinates:

        return jsonify({
            "error": "駅座標を取得できませんでした",
            "location": location,
        }), 500

    latitude, longitude = coordinates

    results = (
        search_yahoo_local_by_coordinates(
            latitude,
            longitude,
            query=keyword,
            distance=YAHOO_SEARCH_DISTANCE_METERS,
        )
    )

    return jsonify({
        "location": location,
        "center": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "distance": YAHOO_SEARCH_DISTANCE_METERS,
        "count": len(results),
        "results": results,
    })


# =========================================================
# AI単体テスト
# =========================================================

@app.route(
    "/test",
    methods=["POST"],
)
def test_ai():

    body = request.get_json(
        silent=True
    ) or {}

    user_text = body.get(
        "message",
        "",
    )

    if not user_text:

        return jsonify({
            "error": "messageがありません",
        }), 400

    user_id = "test-user"

    add_conversation_history(
        user_id,
        "user",
        user_text,
    )

    answer = ask_gourmet_ai(
        user_id,
        user_text,
    )

    add_conversation_history(
        user_id,
        "assistant",
        answer,
    )

    return jsonify({
        "message": user_text,
        "answer": answer,
    })


# =========================================================
# LINE Webhook
# =========================================================

@app.route(
    "/callback",
    methods=["POST"],
)
def callback():

    signature = request.headers.get(
        "X-Line-Signature",
        "",
    )

    body = request.get_data(
        as_text=True
    )

    try:

        events = line_parser.parse(
            body,
            signature,
        )

    except InvalidSignatureError:

        print(
            "LINE署名検証エラー"
        )

        return "Invalid signature", 400

    except Exception as e:

        print(
            "LINE Webhook解析エラー:",
            e,
        )

        return "Bad Request", 400

    for event in events:

        if not isinstance(
            event,
            MessageEvent,
        ):
            continue

        if not isinstance(
            event.message,
            TextMessageContent,
        ):
            continue

        user_id = event.source.user_id

        if not user_id:
            continue

        user_text = (
            event.message.text
            or ""
        ).strip()

        print(
            f"LINE受信: "
            f"user={user_id}, "
            f"text={user_text}"
        )

        # =================================================
        # 初回
        # =================================================

        if user_id not in search_states:

            if should_search_hotpepper(
                user_text
            ):

                search_states[user_id] = {
                    "step": "location",
                    "location": "",
                    "genre": "",
                    "ramen_style": "",
                    "people": "",
                    "time": "",
                }

                if user_text == "開始":

                    start_search_flow(
                        event.reply_token,
                        user_id,
                    )

                    continue

                start_search_flow(
                    event.reply_token,
                    user_id,
                )

                continue

            # -----------------------------------------
            # 通常会話
            # -----------------------------------------

            add_conversation_history(
                user_id,
                "user",
                user_text,
            )

            answer = ask_gourmet_ai(
                user_id,
                user_text,
            )

            add_conversation_history(
                user_id,
                "assistant",
                answer,
            )

            reply_text(
                event.reply_token,
                answer,
            )

            continue

        # =================================================
        # 検索フロー中
        # =================================================

        handle_search_selection(
            event.reply_token,
            user_id,
            user_text,
        )

    return "OK", 200


# =========================================================
# メイン
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000",
        )
    )

    print("=" * 50)

    print(
        "AIアヤフミ（グルメ）"
    )

    print("=" * 50)

    print(
        f"PORT: {port}"
    )

    print(
        "Yahoo!検索半径: "
        f"{YAHOO_SEARCH_DISTANCE_METERS}m"
    )

    print(
        "Yahoo!駅座標: "
        "Yahoo APIから自動取得"
    )

    print(
        "検索条件: "
        "駅・ジャンル・ラーメン系統・人数・利用時間"
    )

    print(
        "予算条件: 無効"
    )

    print("=" * 50)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )