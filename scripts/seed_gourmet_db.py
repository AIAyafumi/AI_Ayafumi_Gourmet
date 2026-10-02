import argparse
import sys

from collections import Counter
from pathlib import Path

import requests


ROOT_DIR = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT_DIR),
    )


from dotenv import load_dotenv


load_dotenv(
    ROOT_DIR / ".env"
)


import gourmet_bot as g


TARGET_TABLES = (
    "stores",
    "business_hours",
    "smoking_info",
    "venue_features",
    "store_status_cache",
)

HOTPEPPER_PAGE_SIZE = 10


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "AIアヤフミ（グルメ）の"
            "初期店舗DB Seeder"
        )
    )

    parser.add_argument(
        "--area",
        help=(
            "ログ表示用のエリア名。"
            "--location指定時は省略可能"
        ),
    )

    parser.add_argument(
        "--location",
        help=(
            "駅名・エリア名からYahoo!で"
            "検索中心座標を自動取得する。"
            "例: 八王子"
        ),
    )

    parser.add_argument(
        "--lat",
        "--latitude",
        dest="latitude",
        type=float,
        help="検索中心の緯度",
    )

    parser.add_argument(
        "--lon",
        "--longitude",
        dest="longitude",
        type=float,
        help="検索中心の経度",
    )

    parser.add_argument(
        "--range",
        dest="range_value",
        type=int,
        choices=[
            1,
            2,
            3,
            4,
            5,
        ],
        default=3,
        help=(
            "Hot Pepper range値。"
            "デフォルト3（約1000m）"
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help=(
            "検索語ごとの最大取得ページ数。"
            "デフォルト20"
        ),
    )

    parser.add_argument(
        "--list-limit",
        type=int,
        default=30,
        help=(
            "候補一覧に表示する最大件数。"
            "デフォルト30。0で一覧非表示"
        ),
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help=(
            "1回のapplyで保存する最大店舗数。"
            "0なら全件。"
            "Bridge実行時は40程度を推奨"
        ),
    )

    parser.add_argument(
        "--chunk-index",
        type=int,
        default=1,
        help=(
            "保存するチャンク番号。"
            "1始まり。"
            "--chunk-size 0 の場合は無視"
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Neonへ実際に保存する。"
            "省略時はdry-run"
        ),
    )

    args = parser.parse_args()

    has_location = bool(
        str(
            args.location
            or ""
        ).strip()
    )

    has_latitude = (
        args.latitude
        is not None
    )

    has_longitude = (
        args.longitude
        is not None
    )

    if has_location and (
        has_latitude
        or has_longitude
    ):
        parser.error(
            "--location と "
            "--lat/--lon は"
            "同時指定できません"
        )

    if (
        not has_location
        and not has_latitude
        and not has_longitude
    ):
        parser.error(
            "--location または "
            "--lat と --lon を"
            "指定してください"
        )

    if (
        has_latitude
        != has_longitude
    ):
        parser.error(
            "--lat と --lon は"
            "必ず両方指定してください"
        )

    if args.max_pages < 1:
        parser.error(
            "--max-pages must be >= 1"
        )

    if args.list_limit < 0:
        parser.error(
            "--list-limit must be >= 0"
        )

    if args.chunk_size < 0:
        parser.error(
            "--chunk-size must be >= 0"
        )

    if args.chunk_index < 1:
        parser.error(
            "--chunk-index must be >= 1"
        )

    return args


def convert_hotpepper_shop(
    shop,
):
    return {
        "name": shop.get(
            "name",
            "",
        ),
        "genre": (
            shop.get(
                "genre",
                {},
            )
            .get(
                "name",
                "",
            )
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
            shop.get(
                "urls",
                {},
            )
            .get(
                "pc",
                "",
            )
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
        "non_smoking": shop.get(
            "non_smoking",
            "",
        ),
        "free_drink": shop.get(
            "free_drink",
            "",
        ),
        "private_room": shop.get(
            "private_room",
            "",
        ),
        "karaoke": shop.get(
            "karaoke",
            "",
        ),
        "midnight": shop.get(
            "midnight",
            "",
        ),
        "budget_code": (
            shop.get(
                "budget",
                {},
            )
            .get(
                "code",
                "",
            )
        ),
        "budget_name": (
            shop.get(
                "budget",
                {},
            )
            .get(
                "name",
                "",
            )
        ),
        "budget_average": (
            shop.get(
                "budget",
                {},
            )
            .get(
                "average",
                "",
            )
        ),
        "source": "Hot Pepper",
    }


def resolve_seed_center(
    args,
):
    location = str(
        args.location
        or ""
    ).strip()

    if location:

        coordinates = (
            g.get_yahoo_location_coordinates(
                location
            )
        )

        if not coordinates:
            raise RuntimeError(
                "Yahoo!で検索中心座標を"
                f"取得できませんでした: {location}"
            )

        latitude, longitude = (
            coordinates
        )

        area = str(
            args.area
            or location
        ).strip()

        return (
            area,
            float(latitude),
            float(longitude),
            "Yahoo! location",
        )

    latitude = float(
        args.latitude
    )

    longitude = float(
        args.longitude
    )

    area = str(
        args.area
        or (
            f"{latitude},"
            f"{longitude}"
        )
    ).strip()

    return (
        area,
        latitude,
        longitude,
        "direct coordinates",
    )


def get_table_counts(
    conn,
):
    counts = {}

    with conn.cursor() as cur:

        for table in TARGET_TABLES:

            cur.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            )

            counts[
                table
            ] = cur.fetchone()[0]

    return counts


def search_hotpepper_seed_pages(
    latitude,
    longitude,
    search_term,
    range_value,
    max_pages,
):
    if not g.HOTPEPPER_API_KEY:
        raise RuntimeError(
            "HOTPEPPER_API_KEY is not configured"
        )

    raw_results = []
    accepted_results = []

    results_available = 0
    pages_fetched = 0
    reached_final_page = False

    for page_index in range(
        max_pages
    ):

        start = (
            page_index
            * HOTPEPPER_PAGE_SIZE
            + 1
        )

        params = {
            "key": g.HOTPEPPER_API_KEY,
            "lat": latitude,
            "lng": longitude,
            "range": range_value,
            "keyword": search_term,
            "format": "json",
            "count": HOTPEPPER_PAGE_SIZE,
            "start": start,
            "order": 4,
        }

        response = requests.get(
            g.HOTPEPPER_URL,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        results = (
            response.json()
            .get(
                "results",
                {},
            )
        )

        results_available = int(
            results.get(
                "results_available",
                0,
            )
            or 0
        )

        results_returned = int(
            results.get(
                "results_returned",
                0,
            )
            or 0
        )

        results_start = int(
            results.get(
                "results_start",
                0,
            )
            or 0
        )

        shops = results.get(
            "shop",
            [],
        )

        if isinstance(
            shops,
            dict,
        ):
            shops = [
                shops
            ]

        if not shops:
            reached_final_page = True
            break

        pages_fetched += 1

        converted = [
            convert_hotpepper_shop(
                shop
            )
            for shop in shops
        ]

        raw_results.extend(
            converted
        )

        accepted_results.extend(
            shop
            for shop in converted
            if g.is_second_party_genre_match(
                shop,
                search_term,
            )
        )

        if (
            results_start
            + results_returned
            - 1
            >= results_available
        ):
            reached_final_page = True
            break

    unique_results = (
        g.deduplicate_gourmet_shops(
            accepted_results
        )
    )

    print(
        f"{search_term}: "
        f"available={results_available}, "
        f"pages={pages_fetched}, "
        f"fetched={len(raw_results)}, "
        f"accepted={len(accepted_results)}, "
        f"unique={len(unique_results)}"
    )

    if (
        not reached_final_page
        and results_available
        > len(raw_results)
    ):
        print(
            "WARNING: "
            f"{search_term} は "
            f"max-pages={max_pages} に到達。"
            "全件取得できていない可能性があります。"
        )

    return unique_results


def search_seed_candidates(
    latitude,
    longitude,
    range_value,
    max_pages,
):
    combined = []
    accepted_by_term = {}

    print("")
    print(
        "========================================"
    )
    print(
        "PAGINATED HOT PEPPER SEARCH"
    )
    print(
        "========================================"
    )

    for search_term in (
        g.SECOND_PARTY_SEARCH_TERMS
    ):

        unique_results = (
            search_hotpepper_seed_pages(
                latitude,
                longitude,
                search_term,
                range_value,
                max_pages,
            )
        )

        accepted_by_term[
            search_term
        ] = len(
            unique_results
        )

        combined.extend(
            unique_results
        )

    unique_combined = (
        g.deduplicate_gourmet_shops(
            combined
        )
    )

    return (
        combined,
        unique_combined,
        accepted_by_term,
    )


def print_candidate_summary(
    shops,
    list_limit,
):
    category_counts = Counter()

    for shop in shops:

        category = (
            g.classify_second_party_candidate_category(
                shop
            )
        )

        category_counts[
            category
        ] += 1

    print("")
    print(
        "========================================"
    )
    print(
        "INITIAL DB CANDIDATE SUMMARY"
    )
    print(
        "========================================"
    )

    print(
        "unique total =",
        len(shops),
    )

    print(
        "カテゴリ内訳:"
    )

    for category in [
        "居酒屋",
        "バー",
        "カラオケ",
        "その他",
    ]:
        print(
            f"  {category}: "
            f"{category_counts.get(category, 0)}"
        )

    if list_limit <= 0:
        return category_counts

    print("")
    print(
        f"候補一覧（先頭"
        f"{min(list_limit, len(shops))}件）:"
    )

    for index, shop in enumerate(
        shops[:list_limit],
        start=1,
    ):

        category = (
            g.classify_second_party_candidate_category(
                shop
            )
        )

        print(
            f"{index}. "
            f"[{category}] "
            f"{shop.get('name', '')}"
        )

        print(
            "   genre:",
            shop.get(
                "genre",
                "",
            ),
        )

        print(
            "   address:",
            shop.get(
                "address",
                "",
            ),
        )

        print(
            "   smoking:",
            shop.get(
                "non_smoking",
                "",
            ),
        )

    remaining = (
        len(shops)
        - min(
            list_limit,
            len(shops),
        )
    )

    if remaining > 0:
        print(
            f"... 残り {remaining}件は表示省略"
        )

    return category_counts


def select_seed_chunk(
    shops,
    chunk_size,
    chunk_index,
):
    shops = list(
        shops or []
    )

    total = len(
        shops
    )

    if chunk_size <= 0:

        return (
            shops,
            1,
            1 if total else 0,
            0,
            total,
        )

    total_chunks = (
        (
            total
            + chunk_size
            - 1
        )
        // chunk_size
    )

    start = (
        (
            chunk_index
            - 1
        )
        * chunk_size
    )

    end = min(
        start
        + chunk_size,
        total,
    )

    if (
        total > 0
        and chunk_index > total_chunks
    ):
        raise ValueError(
            f"chunk-index {chunk_index} "
            f"exceeds total chunks "
            f"{total_chunks}"
        )

    return (
        shops[
            start:end
        ],
        chunk_index,
        total_chunks,
        start,
        end,
    )


def apply_seed(
    shops,
):
    conn = (
        g._get_gourmet_neon_connection()
    )

    if conn is None:
        raise RuntimeError(
            "Neon connection unavailable"
        )

    summary = {
        "stores_inserted": 0,
        "stores_existing": 0,
        "stores_failed": 0,
        "business_hours_saved": 0,
        "smoking_saved": 0,
        "venue_features_saved": 0,
    }

    try:

        before = (
            get_table_counts(
                conn
            )
        )

        print("")
        print(
            "========================================"
        )
        print(
            "DB COUNTS BEFORE"
        )
        print(
            "========================================"
        )

        for table, count in (
            before.items()
        ):
            print(
                table,
                "=",
                count,
            )

        print("")
        print(
            "========================================"
        )
        print(
            "SEED APPLY"
        )
        print(
            "========================================"
        )

        for index, shop in enumerate(
            shops,
            start=1,
        ):

            name = shop.get(
                "name",
                "",
            )

            print(
                f"[{index}/{len(shops)}] "
                f"{name}"
            )

            with conn:

                existing_id = (
                    g._find_gourmet_neon_store_id(
                        conn,
                        shop,
                        create_if_missing=False,
                    )
                )

                store_id = (
                    g._find_gourmet_neon_store_id(
                        conn,
                        shop,
                        create_if_missing=True,
                    )
                )

            if store_id is None:

                summary[
                    "stores_failed"
                ] += 1

                print(
                    "  store: FAILED"
                )

                continue

            if existing_id is None:

                summary[
                    "stores_inserted"
                ] += 1

                print(
                    "  store: INSERTED /",
                    store_id,
                )

            else:

                summary[
                    "stores_existing"
                ] += 1

                print(
                    "  store: EXISTING /",
                    store_id,
                )

            if (
                g.save_hotpepper_business_hours(
                    shop,
                    conn=conn,
                )
            ):
                summary[
                    "business_hours_saved"
                ] += 1

            if (
                g.save_hotpepper_smoking_info(
                    shop,
                    conn=conn,
                )
            ):
                summary[
                    "smoking_saved"
                ] += 1

            if (
                g.save_hotpepper_venue_features(
                    shop,
                    conn=conn,
                )
            ):
                summary[
                    "venue_features_saved"
                ] += 1

        after = (
            get_table_counts(
                conn
            )
        )

        print("")
        print(
            "========================================"
        )
        print(
            "DB COUNTS AFTER"
        )
        print(
            "========================================"
        )

        for table, count in (
            after.items()
        ):
            print(
                table,
                "=",
                count,
                "(",
                f"{count - before[table]:+d}",
                ")",
            )

        return (
            summary,
            before,
            after,
        )

    finally:
        conn.close()


def main():
    args = parse_args()

    (
        area,
        latitude,
        longitude,
        coordinate_source,
    ) = resolve_seed_center(
        args
    )

    print(
        "========================================"
    )
    print(
        "AIアヤフミ（グルメ）"
    )
    print(
        "初期店舗DB Seeder"
    )
    print(
        "========================================"
    )

    print(
        "Area:",
        area,
    )

    print(
        "Location input:",
        (
            args.location
            or "(direct coordinates)"
        ),
    )

    print(
        "Coordinate source:",
        coordinate_source,
    )

    print(
        "Center:",
        latitude,
        longitude,
    )

    print(
        "Hot Pepper range:",
        args.range_value,
    )

    print(
        "Max pages / term:",
        args.max_pages,
    )

    print(
        "Mode:",
        (
            "APPLY"
            if args.apply
            else "DRY RUN"
        ),
    )

    print(
        "Chunk size:",
        (
            args.chunk_size
            if args.chunk_size > 0
            else "ALL"
        ),
    )

    print(
        "Chunk index:",
        args.chunk_index,
    )

    (
        combined_results,
        unique_results,
        accepted_by_term,
    ) = search_seed_candidates(
        latitude,
        longitude,
        args.range_value,
        args.max_pages,
    )

    print("")
    print(
        "========================================"
    )
    print(
        "SEARCH SUMMARY"
    )
    print(
        "========================================"
    )

    for search_term in (
        g.SECOND_PARTY_SEARCH_TERMS
    ):
        print(
            search_term,
            "=",
            accepted_by_term.get(
                search_term,
                0,
            ),
        )

    print(
        "before cross-term dedup =",
        len(combined_results),
    )

    print(
        "after cross-term dedup =",
        len(unique_results),
    )

    print_candidate_summary(
        unique_results,
        args.list_limit,
    )

    (
        apply_results,
        selected_chunk,
        total_chunks,
        chunk_start,
        chunk_end,
    ) = select_seed_chunk(
        unique_results,
        args.chunk_size,
        args.chunk_index,
    )

    print("")
    print(
        "========================================"
    )
    print(
        "CHUNK PLAN"
    )
    print(
        "========================================"
    )

    print(
        "total candidates =",
        len(unique_results),
    )

    print(
        "selected chunk =",
        selected_chunk,
    )

    print(
        "total chunks =",
        total_chunks,
    )

    print(
        "selected range =",
        (
            f"{chunk_start + 1}-"
            f"{chunk_end}"
            if apply_results
            else "EMPTY"
        ),
    )

    print(
        "selected stores =",
        len(apply_results),
    )

    if not args.apply:

        print("")
        print(
            "========================================"
        )
        print(
            "DRY RUN COMPLETE"
        )
        print(
            "========================================"
        )

        print(
            "Neonへの書き込みは"
            "行っていません。"
        )

        return

    (
        summary,
        _before,
        _after,
    ) = apply_seed(
        apply_results
    )

    print("")
    print(
        "========================================"
    )
    print(
        "APPLY SUMMARY"
    )
    print(
        "========================================"
    )

    for key, value in (
        summary.items()
    ):
        print(
            key,
            "=",
            value,
        )

    print("")
    print(
        "SEED APPLY COMPLETE"
    )


if __name__ == "__main__":
    main()