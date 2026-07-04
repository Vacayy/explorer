"""Seed the companies table from DART corp_code list."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))

import OpenDartReader
from config import DART_API_KEY
from database import get_connection, init_db


def seed():
    init_db()
    dart = OpenDartReader(DART_API_KEY)

    print("Fetching corp_code list from DART...")
    corps = dart.corp_codes

    # Filter to listed companies only (stock_code is not empty)
    listed = corps[corps["stock_code"].str.strip() != ""].copy()
    print(f"Found {len(listed)} listed companies")

    conn = get_connection()
    inserted = 0
    for _, row in listed.iterrows():
        conn.execute(
            """
            INSERT OR REPLACE INTO companies (corp_code, corp_name, stock_code)
            VALUES (?, ?, ?)
            """,
            (row["corp_code"], row["corp_name"], row["stock_code"].strip()),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"Seeded {inserted} companies.")


if __name__ == "__main__":
    seed()
