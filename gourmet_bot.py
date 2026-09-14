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
    "カフェ",
    "中華",
    "和食",
    "韓国料理",
    "ファミレス",
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
    "～2,000円",
    "～3,000円",
    "～5,000円",
    "5,000円～",
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
            "people": "",
            "budget": "",
            "time": "",
        }

    return search_states[user_id]


def reset_search_state(user_id):
    search_states.pop(
        user_id,
        None,
    )


def build_confirmation_text(state):
    return (
        f"{state['location']}で"
        f"{state['genre']}を探す。"
        f"予算は{state['budget']}。"
        f"{state['people']}で利用。"
        f"利用時間は{state['time']}。"
    )


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

    # 「開始」は検索フロー開始
    if user_text == "開始":
        return True

    # 駅名を直接入力した場合も検索フロー開始
    for option in LOCATION_OPTIONS:
        if option in user_text:
            return True

    return any(
        keyword in user_text
        for keyword in keywords
    )


def build_hotpepper_keyword(user_text):
    parts = []

    location = ""

    for option in LOCATION_OPTIONS:
        if option in user_text:
            location = option
            break

    genre = ""

    for option in GENRE_OPTIONS:
        if option in user_text:
            genre = option
            break

    if location:
        parts.append(location)

    if genre and genre != "その他":
        parts.append(genre)

    if not parts:
        return user_text

    return " ".join(parts)


def search_hotpepper(user_text):
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
            "budget": (
                shop.get("budget", {})
                .get("name", "")
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

    results = verify_hotpepper_shops_with_tavily(
        results
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


def check_hotpepper_shop_with_tavily(shop):
    name = shop.get(
        "name",
        "",
    )

    address = shop.get(
        "address",
        "",
    )

    if not name:
        return {
            "status": "unknown",
            "reason": "",
        }

    query = (
        f'"{name}" '
        f"{address} "
        "営業時間 営業中 閉店 移転 最新情報"
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

    text_parts = []

    for result in results:
        title = result.get(
            "title",
            "",
        )

        content = result.get(
            "content",
            "",
        )

        text_parts.append(
            f"{title} {content}"
        )

    combined = " ".join(
        text_parts
    )

    closed_keywords = [
        "閉店",
        "閉業",
        "営業終了",
        "店舗終了",
        "閉店しました",
        "閉店のお知らせ",
        "移転",
    ]

    if any(
        keyword in combined
        for keyword in closed_keywords
    ):
        return {
            "status": "closed",
            "reason": combined[:500],
        }

    open_keywords = [
        "営業中",
        "営業しています",
        "営業しております",
        "営業時間",
        "オープン",
        "営業",
    ]

    if any(
        keyword in combined
        for keyword in open_keywords
    ):
        return {
            "status": "open",
            "reason": combined[:500],
        }

    return {
        "status": "unknown",
        "reason": combined[:500],
    }


def verify_hotpepper_shops_with_tavily(
    shops,
):
    verified = []

    for shop in shops:
        verification = (
            check_hotpepper_shop_with_tavily(
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

        if status == "closed":
            print(
                f"Tavily判定で除外: "
                f"{shop.get('name', '')}"
            )
            continue

        shop["tavily_status"] = status
        shop["tavily_reason"] = reason

        verified.append(shop)

        time.sleep(0.2)

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
    location = ""

    for option in LOCATION_OPTIONS:
        if option in user_text:
            location = option
            break

    genre = ""

    for option in GENRE_OPTIONS:
        if option in user_text:
            genre = option
            break

    if genre:
        return genre

    if location:
        return ""

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
    """
    Yahoo!ローカル検索結果の重複を除去する。
    """

    unique = []

    seen_name_address = set()
    seen_name_coordinates = set()
    seen_name_only = set()
    seen_coordinates = set()

    for candidate in candidates:

        name = normalize_for_duplicate(
            candidate.get(
                "name",
                "",
            )
        )

        address = normalize_for_duplicate(
            candidate.get(
                "address",
                "",
            )
        )

        coordinates = normalize_for_duplicate(
            candidate.get(
                "coordinates",
                "",
            )
        )

        if name and address:

            key = (
                name,
                address,
            )

            if key in seen_name_address:
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
                continue

            seen_name_address.add(key)

        elif name and coordinates:

            key = (
                name,
                coordinates,
            )

            if key in seen_name_coordinates:
                print(
                    "Yahoo!重複除外:",
                    candidate.get(
                        "name",
                        "",
                    ),
                )
                continue

            seen_name_coordinates.add(key)

        elif name:

            if name in seen_name_only:
                print(
                    "Yahoo!重複除外:",
                    candidate.get(
                        "name",
                        "",
                    ),
                )
                continue

            seen_name_only.add(name)

        elif coordinates:

            if coordinates in seen_coordinates:
                print(
                    "Yahoo!重複除外:",
                    candidate.get(
                        "name",
                        "",
                    ),
                )
                continue

            seen_coordinates.add(
                coordinates
            )

        else:
            continue

        unique.append(candidate)

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

    Yahoo!のCoordinatesは
    「経度,緯度」の順番。
    """

    if not YAHOO_CLIENT_ID:
        print(
            "YAHOO_CLIENT_IDが設定されていません。"
        )
        return None

    params = {
        "appid": YAHOO_CLIENT_ID,
        "query": location,
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
        return None

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

        candidate = (
            name or property_name,
            coordinates,
        )

        if (
            name == location
            or property_name == location
        ):
            exact_candidate = candidate
            break

        if (
            location in name
            or location in property_name
        ):
            if contains_candidate is None:
                contains_candidate = candidate

    candidate = (
        exact_candidate
        or contains_candidate
    )

    if not candidate:
        print(
            f"Yahoo!で駅座標を取得できませんでした: "
            f"{location}"
        )
        return None

    _, coordinate_text = candidate

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
        return None

    print(
        f"Yahoo!駅座標取得成功: "
        f"{location} "
        f"lat={latitude}, "
        f"lon={longitude}"
    )

    return latitude, longitude


def search_yahoo_local(
    user_text,
):
    """
    ユーザーが選択した駅を
    Yahoo! APIで検索し、
    その駅の座標を中心として
    半径1.5km以内を検索する。
    """

    location = ""

    for option in LOCATION_OPTIONS:
        if option in user_text:
            location = option
            break

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
# Yahoo!検索結果整形
# =========================================================

def format_yahoo_results(
    results,
):
    if not results:
        return "Yahoo!ローカルサーチ結果なし"

    lines = []

    for index, shop in enumerate(
        results,
        start=1,
    ):

        lines.append(
            f"{index}. "
            f"{shop.get('name', '')}"
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
                f"   駅: "
                f"{shop.get('station', '')}"
            )

        if shop.get("tel"):
            lines.append(
                f"   電話: "
                f"{shop.get('tel', '')}"
            )

        if shop.get("distance"):
            lines.append(
                f"   距離: "
                f"{shop.get('distance', '')}"
            )

        if shop.get("url"):
            lines.append(
                f"   URL: "
                f"{shop.get('url', '')}"
            )

        lines.append("")

    return "\n".join(lines)


# =========================================================
# Hot Pepper結果整形
# =========================================================

def format_hotpepper_results(
    results,
):
    if not results:
        return "Hot Pepper検索結果なし"

    lines = []

    for index, shop in enumerate(
        results,
        start=1,
    ):

        lines.append(
            f"{index}. "
            f"{shop.get('name', '')}"
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

        if shop.get("budget"):
            lines.append(
                f"   予算: "
                f"{shop.get('budget', '')}"
            )

        if shop.get("open"):
            lines.append(
                f"   営業時間: "
                f"{shop.get('open', '')}"
            )

        if shop.get("tavily_status"):
            lines.append(
                f"   Tavily確認: "
                f"{shop.get('tavily_status', '')}"
            )

        if shop.get("tavily_reason"):
            lines.append(
                f"   最新情報: "
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
# グルメAIプロンプト
# =========================================================

def build_gourmet_prompt(
    user_id,
    user_text,
):
    hotpepper_results = []

    yahoo_results = []

    if should_search_hotpepper(
        user_text
    ):

        hotpepper_results = search_hotpepper(
            user_text
        )

        yahoo_results = search_yahoo_local(
            user_text
        )

    hotpepper_context = (
        format_hotpepper_results(
            hotpepper_results
        )
    )

    yahoo_context = (
        format_yahoo_results(
            yahoo_results
        )
    )

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

【Hot Pepper検索結果】
{hotpepper_context}

【Yahoo!ローカルサーチ検索結果】
{yahoo_context}

【Tavily最新情報】
{tavily_context}

【重要ルール】

1. ユーザーが指定した条件を最優先してください。

2. 場所、ジャンル、人数、予算、利用時間などが
   すでに指定されている場合は、
   同じことをもう一度質問しないでください。

3. Hot Pepperの検索結果を優先的に利用してください。

4. Yahoo!ローカルサーチの結果も活用してください。

5. Yahoo!ローカルサーチは、
   ユーザーが選択した駅をYahoo! APIで取得し、
   その駅の座標を中心として
   半径1.5km以内を検索しています。

6. Hot PepperとYahoo!で同じ店舗が出ている場合は、
   重複して大量に表示しないでください。

7. Hot PepperとYahoo!の情報を組み合わせて、
   店名、ジャンル、場所、予算、営業時間などを
   分かりやすく整理してください。

8. ユーザーが予算を指定している場合は、
   予算に合う店を優先してください。

9. ユーザーが人数を指定している場合は、
   その人数で利用しやすい店を優先してください。

10. ユーザーが昼・夜など利用時間を指定している場合は、
    その時間帯に利用しやすい店を優先してください。

11. Tavilyで閉店と判断された店舗は、
    絶対に候補として表示しないでください。

12. Tavilyで確認できない場合は、
    勝手に営業中・閉店などと断定しないでください。

13. 検索結果に存在しない情報を勝手に作らないでください。

14. 条件に合う店が少ない場合は、
    無理に条件に合うと断定せず、
    「条件に近い候補」として正直に説明してください。

15. 店舗候補は見やすく整理してください。

16. 最後に、ユーザーが指定した条件を
    簡潔に確認しても構いません。

17. 検索結果にURLがある場合は、
    可能な範囲で店舗URLも提示してください。

18. 回答はLINEで読みやすいように、
    長くなりすぎないようにしてください。

19. 店舗情報を紹介するときは、
    「店名」「おすすめ理由」「予算・特徴」
    が分かりやすい構成にしてください。

20. 検索結果が複数ある場合は、
    特に条件に合いそうな店舗を優先してください。
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

    # =====================================================
    # ① Groqを最優先
    # =====================================================

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

    # =====================================================
    # ② Groq失敗 → Gemini
    # =====================================================

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

    # =====================================================
    # ③ Groq・Gemini両方失敗 → OpenRouter
    # =====================================================

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

    reply_text(
        reply_token,
        "どの駅の周辺で探しますか？",
        build_quick_reply(
            LOCATION_OPTIONS
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

        if user_text not in LOCATION_OPTIONS:

            reply_text(
                reply_token,
                "駅を選択してください。",
                build_quick_reply(
                    LOCATION_OPTIONS
                ),
            )

            return

        state["location"] = user_text
        state["step"] = "genre"

        reply_text(
            reply_token,
            "ジャンルは何にしますか？",
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
        state["step"] = "budget"

        reply_text(
            reply_token,
            "予算はどれくらいですか？",
            build_quick_reply(
                BUDGET_OPTIONS
            ),
        )

        return

    # =====================================================
    # 予算
    # =====================================================

    if step == "budget":

        if user_text not in BUDGET_OPTIONS:

            reply_text(
                reply_token,
                "予算を選択してください。",
                build_quick_reply(
                    BUDGET_OPTIONS
                ),
            )

            return

        state["budget"] = user_text
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

        # =================================================
        # AI検索
        # =================================================

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

            # 店検索系のメッセージなら
            # 検索フロー開始
            if should_search_hotpepper(
                user_text
            ):

                search_states[user_id] = {
                    "step": "location",
                    "location": "",
                    "genre": "",
                    "people": "",
                    "budget": "",
                    "time": "",
                }

                # すでに駅が入力されている場合
                # そのまま次へ進める
                selected_location = ""

                for option in LOCATION_OPTIONS:

                    if option in user_text:
                        selected_location = option
                        break

                if selected_location:

                    state = search_states[
                        user_id
                    ]

                    state["location"] = (
                        selected_location
                    )

                    state["step"] = "genre"

                    reply_text(
                        event.reply_token,
                        "ジャンルは何にしますか？",
                        build_quick_reply(
                            GENRE_OPTIONS
                        ),
                    )

                else:

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

    print("=" * 50)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )