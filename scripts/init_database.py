import os

import psycopg2
from dotenv import load_dotenv


# =========================================================
# 環境変数
# =========================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL が設定されていません。"
    )


# =========================================================
# DB初期化
# =========================================================

def init_database():
    print("========================================")
    print("AIアヤフミ（グルメ）DB初期化")
    print("========================================")

    conn = psycopg2.connect(
        DATABASE_URL,
        connect_timeout=5,
    )

    try:
        with conn:
            with conn.cursor() as cur:

                # =========================================
                # 店舗基本情報
                # =========================================

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stores (
                        id BIGSERIAL PRIMARY KEY,

                        normalized_name TEXT NOT NULL,
                        name TEXT NOT NULL,

                        address TEXT,

                        latitude DOUBLE PRECISION,
                        longitude DOUBLE PRECISION,

                        phone TEXT,
                        genre TEXT,
                        url TEXT,
                        source TEXT,

                        created_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        updated_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    );
                    """
                )

                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_stores_normalized_name_address
                    ON stores (
                        normalized_name,
                        COALESCE(address, '')
                    );
                    """
                )

                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_stores_lat_lon
                    ON stores (
                        latitude,
                        longitude
                    );
                    """
                )

                # =========================================
                # 曜日別営業時間
                # =========================================

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS business_hours (
                        id BIGSERIAL PRIMARY KEY,

                        store_id BIGINT NOT NULL
                            REFERENCES stores(id)
                            ON DELETE CASCADE,

                        day_of_week SMALLINT NOT NULL
                            CHECK (
                                day_of_week BETWEEN 0 AND 6
                            ),

                        open_time TIME,
                        close_time TIME,

                        closes_next_day BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        is_closed BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        source TEXT,

                        checked_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        updated_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        UNIQUE (
                            store_id,
                            day_of_week
                        )
                    );
                    """
                )

                # =========================================
                # 営業確認キャッシュ
                # =========================================

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS store_status_cache (
                        store_id BIGINT PRIMARY KEY
                            REFERENCES stores(id)
                            ON DELETE CASCADE,

                        status TEXT NOT NULL
                            CHECK (
                                status IN (
                                    'open',
                                    'closed',
                                    'unknown'
                                )
                            ),

                        reason TEXT,
                        source TEXT,

                        checked_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        expires_at TIMESTAMPTZ
                            NOT NULL,

                        updated_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    );
                    """
                )

        print("Neon PostgreSQL テーブル作成成功")
        print("")
        print("作成対象:")
        print("  stores")
        print("  business_hours")
        print("  store_status_cache")

    finally:
        conn.close()


if __name__ == "__main__":
    init_database()
