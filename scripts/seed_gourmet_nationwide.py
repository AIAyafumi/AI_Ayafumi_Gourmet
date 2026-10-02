import argparse
import hashlib
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
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


import gourmet_bot as g


SEEDER_PATH = (
    ROOT_DIR
    / "scripts"
    / "seed_gourmet_db.py"
)

_spec = (
    importlib.util.spec_from_file_location(
        "seed_gourmet_db",
        SEEDER_PATH,
    )
)

seed = (
    importlib.util.module_from_spec(
        _spec
    )
)

_spec.loader.exec_module(
    seed
)


SMALL_AREA_URL = (
    "https://webservice.recruit.co.jp/"
    "hotpepper/small_area/v1/"
)

MASTER_PAGE_SIZE = 100
SHOP_PAGE_SIZE = 10

CHECKPOINT_VERSION = 1

DEFAULT_CHECKPOINT = (
    ROOT_DIR
    / "data"
    / "gourmet_seed_checkpoint.json"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "AIアヤフミ（グルメ）"
            "全国初期DB Seeder"
        )
    )

    scope = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    scope.add_argument(
        "--prefecture",
        help=(
            "対象都道府県。"
            "例: 東京"
        ),
    )

    scope.add_argument(
        "--prefecture-code",
        help=(
            "Hot Pepper large_areaコードで"
            "都道府県を指定する。"
            "例: 東京=Z011"
        ),
    )

    scope.add_argument(
        "--nationwide",
        action="store_true",
        help="47都道府県すべてを対象にする",
    )

    scope.add_argument(
        "--small-area",
        help=(
            "Hot Pepper small_areaコードを"
            "1件だけ対象にする。"
            "例: X005"
        ),
    )

    parser.add_argument(
        "--max-areas",
        type=int,
        default=0,
        help=(
            "1回の実行で処理する"
            "small_area数の上限。"
            "0なら制限なし"
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help=(
            "検索語ごとの最大ページ数。"
            "不足時はエラーで停止する"
        ),
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=40,
        help=(
            "Neon保存時の1チャンク店舗数。"
            "デフォルト40"
        ),
    )

    parser.add_argument(
        "--max-chunks",
        type=int,
        default=0,
        help=(
            "1回の実行でapplyする"
            "最大チャンク数。"
            "0なら制限なし。"
            "Bridgeの安全停止・resume確認用"
        ),
    )

    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.20,
        help=(
            "Hot Pepper APIリクエスト間隔（秒）。"
            "デフォルト0.20"
        ),
    )

    parser.add_argument(
        "--checkpoint",
        default=str(
            DEFAULT_CHECKPOINT
        ),
        help=(
            "再開用checkpoint JSON"
        ),
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "checkpointから再開し、"
            "完了済みエリアをスキップする"
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "実際にNeonへ保存する。"
            "省略時はdry-run"
        ),
    )

    args = parser.parse_args()

    if args.max_areas < 0:
        parser.error(
            "--max-areas must be >= 0"
        )

    if args.max_pages < 1:
        parser.error(
            "--max-pages must be >= 1"
        )

    if args.chunk_size < 1:
        parser.error(
            "--chunk-size must be >= 1"
        )

    if args.max_chunks < 0:
        parser.error(
            "--max-chunks must be >= 0"
        )

    if args.request_delay < 0:
        parser.error(
            "--request-delay must be >= 0"
        )

    return args


def utc_now():
    return (
        datetime.now(
            timezone.utc
        )
        .isoformat(
            timespec="seconds"
        )
    )


def api_get(
    url,
    params,
    request_delay,
    retries=3,
):
    last_error = None

    for attempt in range(
        retries
    ):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=20,
            )

            if (
                response.status_code == 429
                or response.status_code >= 500
            ):
                raise requests.HTTPError(
                    (
                        "retryable HTTP status "
                        f"{response.status_code}"
                    ),
                    response=response,
                )

            response.raise_for_status()

            data = response.json()

            if request_delay > 0:
                time.sleep(
                    request_delay
                )

            return data

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            last_error = exc

            if attempt + 1 >= retries:
                break

            wait_seconds = (
                max(
                    request_delay,
                    0.5,
                )
                * (
                    2 ** attempt
                )
            )

            print(
                "API retry:",
                attempt + 1,
                "/",
                retries - 1,
                "wait=",
                wait_seconds,
                "error=",
                repr(exc),
            )

            time.sleep(
                wait_seconds
            )

    raise RuntimeError(
        "Hot Pepper API request failed"
    ) from last_error


def fetch_small_area_master(
    request_delay,
):
    first = api_get(
        SMALL_AREA_URL,
        {
            "key": g.HOTPEPPER_API_KEY,
            "format": "json",
            "count": MASTER_PAGE_SIZE,
            "start": 1,
        },
        request_delay,
    )

    first_results = first.get(
        "results",
        {},
    )

    available = int(
        first_results.get(
            "results_available",
            0,
        )
        or 0
    )

    if available <= 0:
        raise RuntimeError(
            "small_area master is empty"
        )

    all_areas = []
    start = 1

    while start <= available:
        if start == 1:
            data = first
        else:
            data = api_get(
                SMALL_AREA_URL,
                {
                    "key": g.HOTPEPPER_API_KEY,
                    "format": "json",
                    "count": MASTER_PAGE_SIZE,
                    "start": start,
                },
                request_delay,
            )

        results = data.get(
            "results",
            {},
        )

        items = results.get(
            "small_area",
            [],
        )

        if isinstance(
            items,
            dict,
        ):
            items = [items]

        if not items:
            break

        all_areas.extend(
            items
        )

        start += len(
            items
        )

    if len(all_areas) != available:
        raise RuntimeError(
            "small_area master pagination "
            "incomplete: "
            f"{len(all_areas)}/{available}"
        )

    codes = [
        item.get(
            "code"
        )
        for item in all_areas
    ]

    if (
        len(set(codes))
        != len(all_areas)
    ):
        raise RuntimeError(
            "duplicate small_area codes "
            "detected"
        )

    return all_areas


def select_target_areas(
    all_areas,
    args,
):
    if args.nationwide:
        selected = list(
            all_areas
        )

    elif args.prefecture:
        prefecture = (
            str(
                args.prefecture
            )
            .strip()
        )

        selected = [
            item
            for item in all_areas
            if (
                (
                    item.get(
                        "large_area",
                        {},
                    )
                    or {}
                ).get(
                    "name"
                )
                == prefecture
            )
        ]

        if not selected:
            raise RuntimeError(
                "Prefecture not found: "
                f"{prefecture}"
            )

    elif args.prefecture_code:
        prefecture_code = (
            str(
                args.prefecture_code
            )
            .strip()
            .upper()
        )

        selected = [
            item
            for item in all_areas
            if (
                str(
                    (
                        item.get(
                            "large_area",
                            {},
                        )
                        or {}
                    ).get(
                        "code",
                        "",
                    )
                ).upper()
                == prefecture_code
            )
        ]

        if not selected:
            raise RuntimeError(
                "Prefecture code not found: "
                f"{prefecture_code}"
            )

    else:
        code = (
            str(
                args.small_area
            )
            .strip()
            .upper()
        )

        selected = [
            item
            for item in all_areas
            if (
                str(
                    item.get(
                        "code",
                        "",
                    )
                ).upper()
                == code
            )
        ]

        if len(selected) != 1:
            raise RuntimeError(
                "small_area not found: "
                f"{code}"
            )

    return selected


def convert_raw_shops(
    shops,
    search_term,
):
    converted = [
        seed.convert_hotpepper_shop(
            shop
        )
        for shop in shops
    ]

    return [
        shop
        for shop in converted
        if g.is_second_party_genre_match(
            shop,
            search_term,
        )
    ]


def search_small_area_term(
    area_code,
    search_term,
    max_pages,
    request_delay,
):
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
            * SHOP_PAGE_SIZE
            + 1
        )

        data = api_get(
            g.HOTPEPPER_URL,
            {
                "key": g.HOTPEPPER_API_KEY,
                "small_area": area_code,
                "keyword": search_term,
                "format": "json",
                "count": SHOP_PAGE_SIZE,
                "start": start,
            },
            request_delay,
        )

        results = data.get(
            "results",
            {},
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
            shops = [shops]

        if not shops:
            reached_final_page = True
            break

        pages_fetched += 1

        raw_results.extend(
            shops
        )

        accepted_results.extend(
            convert_raw_shops(
                shops,
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

    if (
        not reached_final_page
        and results_available
        > len(raw_results)
    ):
        raise RuntimeError(
            (
                f"{area_code} / "
                f"{search_term}: "
                f"max-pages={max_pages} "
                "では全件取得できません"
            )
        )

    unique_results = (
        g.deduplicate_gourmet_shops(
            accepted_results
        )
    )

    print(
        f"  {search_term}: "
        f"available={results_available}, "
        f"pages={pages_fetched}, "
        f"fetched={len(raw_results)}, "
        f"accepted={len(accepted_results)}, "
        f"unique={len(unique_results)}"
    )

    return unique_results


def stable_shop_key(
    shop,
):
    return (
        str(
            shop.get(
                "name",
                "",
            )
        ),
        str(
            shop.get(
                "address",
                "",
            )
        ),
        str(
            shop.get(
                "url",
                "",
            )
        ),
    )


def search_small_area_candidates(
    area,
    max_pages,
    request_delay,
):
    area_code = area.get(
        "code",
        "",
    )

    area_name = area.get(
        "name",
        "",
    )

    print("")
    print(
        "========================================"
    )
    print(
        "SMALL AREA:",
        area_code,
        area_name,
    )
    print(
        "========================================"
    )

    combined = []
    accepted_by_term = {}

    for search_term in (
        g.SECOND_PARTY_SEARCH_TERMS
    ):
        shops = (
            search_small_area_term(
                area_code,
                search_term,
                max_pages,
                request_delay,
            )
        )

        accepted_by_term[
            search_term
        ] = len(
            shops
        )

        combined.extend(
            shops
        )

    unique = (
        g.deduplicate_gourmet_shops(
            combined
        )
    )

    unique = sorted(
        unique,
        key=stable_shop_key,
    )

    return (
        unique,
        accepted_by_term,
    )


def candidate_fingerprint(
    shops,
):
    lines = []

    for shop in shops:
        key = stable_shop_key(
            shop
        )

        lines.append(
            "\t".join(
                key
            )
        )

    payload = (
        "\n".join(
            lines
        )
        .encode(
            "utf-8"
        )
    )

    return (
        hashlib.sha256(
            payload
        )
        .hexdigest()
    )


def category_counts(
    shops,
):
    counts = {
        "居酒屋": 0,
        "バー": 0,
        "カラオケ": 0,
        "その他": 0,
    }

    for shop in shops:
        category = (
            g.classify_second_party_candidate_category(
                shop
            )
        )

        if category not in counts:
            category = "その他"

        counts[
            category
        ] += 1

    return counts


def new_checkpoint():
    return {
        "version": CHECKPOINT_VERSION,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "completed_areas": {},
        "progress": {},
    }


def load_checkpoint(
    path,
):
    if not path.exists():
        return new_checkpoint()

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        data.get(
            "version"
        )
        != CHECKPOINT_VERSION
    ):
        raise RuntimeError(
            "Unsupported checkpoint version"
        )

    data.setdefault(
        "completed_areas",
        {},
    )

    data.setdefault(
        "progress",
        {},
    )

    return data


def save_checkpoint(
    path,
    data,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    data[
        "updated_at"
    ] = utc_now()

    temp_path = (
        path.with_suffix(
            path.suffix
            + ".tmp"
        )
    )

    temp_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temp_path.replace(
        path
    )


def checkpoint_start_chunk(
    checkpoint,
    area_code,
    fingerprint,
    resume,
):
    if not resume:
        return 1

    progress = (
        checkpoint.get(
            "progress",
            {}
        )
        .get(
            area_code
        )
    )

    if not progress:
        return 1

    old_fingerprint = (
        progress.get(
            "candidate_fingerprint"
        )
    )

    if (
        old_fingerprint
        != fingerprint
    ):
        print(
            "  Candidate set changed."
        )
        print(
            "  Restarting area from chunk 1 "
            "(idempotent re-apply)."
        )

        return 1

    return max(
        1,
        int(
            progress.get(
                "next_chunk",
                1,
            )
        ),
    )


def update_progress(
    checkpoint,
    area,
    fingerprint,
    candidate_total,
    next_chunk,
):
    code = area.get(
        "code",
        "",
    )

    checkpoint[
        "progress"
    ][code] = {
        "name": area.get(
            "name",
            "",
        ),
        "prefecture": (
            (
                area.get(
                    "large_area",
                    {},
                )
                or {}
            ).get(
                "name",
                "",
            )
        ),
        "candidate_total": candidate_total,
        "candidate_fingerprint": fingerprint,
        "next_chunk": next_chunk,
        "updated_at": utc_now(),
    }


def mark_area_complete(
    checkpoint,
    area,
    fingerprint,
    candidate_total,
):
    code = area.get(
        "code",
        "",
    )

    checkpoint[
        "completed_areas"
    ][code] = {
        "name": area.get(
            "name",
            "",
        ),
        "prefecture": (
            (
                area.get(
                    "large_area",
                    {},
                )
                or {}
            ).get(
                "name",
                "",
            )
        ),
        "candidate_total": candidate_total,
        "candidate_fingerprint": fingerprint,
        "completed_at": utc_now(),
    }

    checkpoint[
        "progress"
    ].pop(
        code,
        None,
    )


def apply_area(
    area,
    shops,
    args,
    checkpoint,
    checkpoint_path,
    run_state,
):
    area_code = area.get(
        "code",
        "",
    )

    fingerprint = (
        candidate_fingerprint(
            shops
        )
    )

    candidate_total = len(
        shops
    )

    if candidate_total == 0:
        mark_area_complete(
            checkpoint,
            area,
            fingerprint,
            candidate_total,
        )

        save_checkpoint(
            checkpoint_path,
            checkpoint,
        )

        print(
            "  No candidates. "
            "Area marked complete."
        )

        return True

    total_chunks = (
        (
            candidate_total
            + args.chunk_size
            - 1
        )
        // args.chunk_size
    )

    start_chunk = (
        checkpoint_start_chunk(
            checkpoint,
            area_code,
            fingerprint,
            args.resume,
        )
    )

    if start_chunk > total_chunks:
        start_chunk = 1

    print(
        "  candidate_total =",
        candidate_total,
    )

    print(
        "  total_chunks =",
        total_chunks,
    )

    print(
        "  start_chunk =",
        start_chunk,
    )

    for chunk_index in range(
        start_chunk,
        total_chunks + 1,
    ):
        if (
            args.max_chunks > 0
            and run_state[
                "chunks_applied"
            ] >= args.max_chunks
        ):
            print(
                "  RUN CHUNK LIMIT REACHED"
            )

            print(
                "  Area remains incomplete."
            )

            return False

        (
            chunk,
            _selected,
            _total,
            start,
            end,
        ) = seed.select_seed_chunk(
            shops,
            args.chunk_size,
            chunk_index,
        )

        print("")
        print(
            "  ------------------------------------"
        )
        print(
            "  APPLY CHUNK",
            chunk_index,
            "/",
            total_chunks,
            f"({start + 1}-{end})",
        )
        print(
            "  ------------------------------------"
        )

        (
            summary,
            _before,
            _after,
        ) = seed.apply_seed(
            chunk
        )

        if (
            summary.get(
                "stores_failed",
                0,
            )
            != 0
        ):
            raise RuntimeError(
                (
                    f"{area_code} chunk "
                    f"{chunk_index} has "
                    "failed stores"
                )
            )

        run_state[
            "chunks_applied"
        ] += 1

        update_progress(
            checkpoint,
            area,
            fingerprint,
            candidate_total,
            chunk_index + 1,
        )

        save_checkpoint(
            checkpoint_path,
            checkpoint,
        )

        print(
            "  checkpoint saved: "
            f"next_chunk={chunk_index + 1}"
        )

        print(
            "  run chunks applied =",
            run_state[
                "chunks_applied"
            ],
        )

        if (
            chunk_index < total_chunks
            and args.max_chunks > 0
            and run_state[
                "chunks_applied"
            ] >= args.max_chunks
        ):
            print(
                "  RUN CHUNK LIMIT REACHED"
            )

            print(
                "  Area remains incomplete."
            )

            return False

    mark_area_complete(
        checkpoint,
        area,
        fingerprint,
        candidate_total,
    )

    save_checkpoint(
        checkpoint_path,
        checkpoint,
    )

    print(
        "  AREA COMPLETE:",
        area_code,
        area.get(
            "name",
            "",
        ),
    )

    return True


def main():
    args = parse_args()

    if not g.HOTPEPPER_API_KEY:
        raise RuntimeError(
            "HOTPEPPER_API_KEY "
            "is not configured"
        )

    checkpoint_path = (
        Path(
            args.checkpoint
        )
    )

    if not checkpoint_path.is_absolute():
        checkpoint_path = (
            ROOT_DIR
            / checkpoint_path
        )

    if (
        args.apply
        and checkpoint_path.exists()
        and not args.resume
    ):
        raise RuntimeError(
            (
                "Checkpoint already exists. "
                "Use --resume or specify "
                "another --checkpoint path."
            )
        )

    print(
        "========================================"
    )
    print(
        "AI AYAFUMI GOURMET "
        "NATIONWIDE SEEDER"
    )
    print(
        "========================================"
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
        "Checkpoint:",
        checkpoint_path,
    )

    all_areas = (
        fetch_small_area_master(
            args.request_delay
        )
    )

    print(
        "Master small areas =",
        len(all_areas),
    )

    target_areas = (
        select_target_areas(
            all_areas,
            args,
        )
    )

    print(
        "Selected small areas =",
        len(target_areas),
    )

    checkpoint = (
        load_checkpoint(
            checkpoint_path
        )
        if (
            args.apply
            or args.resume
        )
        else new_checkpoint()
    )

    completed = checkpoint.get(
        "completed_areas",
        {},
    )

    processed_areas = 0
    skipped_areas = 0

    run_state = {
        "chunks_applied": 0,
    }

    stopped_by_chunk_limit = False

    for area in target_areas:
        area_code = area.get(
            "code",
            "",
        )

        area_name = area.get(
            "name",
            "",
        )

        prefecture = (
            (
                area.get(
                    "large_area",
                    {},
                )
                or {}
            ).get(
                "name",
                "",
            )
        )

        if (
            args.resume
            and area_code in completed
        ):
            print(
                "SKIP COMPLETE:",
                area_code,
                area_name,
            )

            skipped_areas += 1
            continue

        if (
            args.max_areas > 0
            and processed_areas
            >= args.max_areas
        ):
            break

        print("")
        print(
            "########################################"
        )
        print(
            "AREA:",
            area_code,
            area_name,
            "/",
            prefecture,
        )
        print(
            "########################################"
        )

        (
            candidates,
            accepted_by_term,
        ) = search_small_area_candidates(
            area,
            args.max_pages,
            args.request_delay,
        )

        counts = (
            category_counts(
                candidates
            )
        )

        fingerprint = (
            candidate_fingerprint(
                candidates
            )
        )

        print("")
        print(
            "accepted_by_term =",
            accepted_by_term,
        )

        print(
            "candidate_total =",
            len(candidates),
        )

        print(
            "categories =",
            counts,
        )

        print(
            "fingerprint =",
            fingerprint,
        )

        total_chunks = (
            (
                len(candidates)
                + args.chunk_size
                - 1
            )
            // args.chunk_size
            if candidates
            else 0
        )

        print(
            "chunk_size =",
            args.chunk_size,
        )

        print(
            "total_chunks =",
            total_chunks,
        )

        if args.apply:
            area_complete = (
                apply_area(
                    area,
                    candidates,
                    args,
                    checkpoint,
                    checkpoint_path,
                    run_state,
                )
            )

            if area_complete is False:
                stopped_by_chunk_limit = True

        processed_areas += 1

        if stopped_by_chunk_limit:
            break

    print("")
    print(
        "========================================"
    )
    print(
        "RUN SUMMARY"
    )
    print(
        "========================================"
    )

    print(
        "processed_areas =",
        processed_areas,
    )

    print(
        "skipped_completed_areas =",
        skipped_areas,
    )

    print(
        "chunks_applied =",
        run_state[
            "chunks_applied"
        ],
    )

    print(
        "stopped_by_chunk_limit =",
        stopped_by_chunk_limit,
    )

    print(
        "mode =",
        (
            "APPLY"
            if args.apply
            else "DRY RUN"
        ),
    )

    if not args.apply:
        print(
            "Checkpoint was not modified."
        )

    print(
        "NATIONWIDE SEEDER RUN COMPLETE"
    )


if __name__ == "__main__":
    main()
