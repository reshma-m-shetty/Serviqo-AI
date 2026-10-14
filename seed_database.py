"""
Serviqo AI - MySQL Database Seeder & Batch Importer
Seeds relational tables and batch-imports large datasets if available.
"""

import os
import json
from datetime import datetime, timedelta
import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv
import database

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root123")
DB_NAME = os.getenv("DB_NAME", "serviqo_ai")


def seed_all():
    print("=" * 60)
    print("SERVIQO AI - MYSQL DATABASE INITIALIZATION & SEEDING")
    print("=" * 60)

    # 1. Initialize schema
    print("\n[Step 1/3] Initializing schema and tables in MySQL...")
    database.init_db()

    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=DictCursor,
        autocommit=False,
        charset="utf8mb4"
    )
    cursor = conn.cursor()

    # 2. Check and Seed Users if empty
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    user_cnt = cursor.fetchone()["cnt"]
    if user_cnt == 0:
        print("\n[Step 2/3] Seeding initial users...")
        staff_pwd = database.hash_password("staff123")
        ngo_pwd = database.hash_password("ngo123")
        admin_pwd = database.hash_password("admin123")
        users = [
            ("Rohan Sharma", "kitchen@serviqo.ai", staff_pwd, "Kitchen Staff"),
            ("Anita Desai", "ngo@serviqo.ai", ngo_pwd, "NGO"),
            ("Admin Manager", "admin@serviqo.ai", admin_pwd, "Kitchen Staff")
        ]
        cursor.executemany("INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)", users)
        conn.commit()
        print(f"  ✓ Users seeded: Loaded: {len(users)}, Inserted: {len(users)}, Failed: 0")
    else:
        print(f"\n[Step 2/3] Users table already contains {user_cnt} records.")

    # 3. Check for external CSV datasets (e.g. historical training / demo data)
    csv_file = "food_demand_FINAL_3_year_balanced_relationships.csv"
    if os.path.exists(csv_file):
        print(f"\n[Step 3/3] Found dataset file: {csv_file}. Preparing batch import...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_demand (
                id INT AUTO_INCREMENT PRIMARY KEY,
                date_recorded DATE,
                meal_type VARCHAR(50),
                menu_item VARCHAR(100),
                food_category VARCHAR(100),
                day_of_week VARCHAR(20),
                weather_condition VARCHAR(50),
                expected_attendance INT,
                actual_demand DECIMAL(10,2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
        """)
        conn.commit()

        import pandas as pd
        df = pd.read_csv(csv_file)
        total_rows = len(df)
        print(f"  Loaded: {total_rows:,} rows from {csv_file}")

        batch_size = 5000
        inserted_count = 0
        failed_count = 0

        for start_idx in range(0, total_rows, batch_size):
            chunk = df.iloc[start_idx:start_idx + batch_size]
            batch_data = []
            for _, row in chunk.iterrows():
                try:
                    d_val = row.get("Date", "2024-01-01")
                    if isinstance(d_val, str):
                        d_val = d_val.split(" ")[0]
                    batch_data.append((
                        d_val,
                        str(row.get("Meal_Type", "Breakfast")),
                        str(row.get("Menu_Item", "Idli")),
                        str(row.get("Food_Category", "Breakfast")),
                        str(row.get("Day_of_Week", "Monday")),
                        str(row.get("Weather_Condition", "Sunny")),
                        int(row.get("Expected_Attendance", 800)),
                        float(row.get("Actual_Demand", 750.0))
                    ))
                except Exception:
                    failed_count += 1

            if batch_data:
                cursor.executemany("""
                    INSERT INTO historical_demand 
                    (date_recorded, meal_type, menu_item, food_category, day_of_week, weather_condition, expected_attendance, actual_demand)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, batch_data)
                conn.commit()
                inserted_count += len(batch_data)
                print(f"    ... Inserted {inserted_count:,} / {total_rows:,} rows")

        print(f"  Batch import complete! Loaded: {total_rows:,}, Inserted: {inserted_count:,}, Failed: {failed_count}")
    else:
        print(f"\n[Step 3/3] No external CSV dataset file ({csv_file}) found in root directory. Standard demo database is fully seeded.")

    # Print summary counts
    print("\n" + "=" * 60)
    print("MYSQL DATABASE SEEDING SUMMARY")
    print("=" * 60)
    for tbl in ["users", "inventory", "ngos", "suppliers", "donations", "demand_forecasts", "announcements"]:
        cursor.execute(f"SELECT COUNT(*) as count FROM `{tbl}`")
        cnt = cursor.fetchone()["count"]
        print(f"  • Table `{tbl}`: {cnt} rows")
    
    conn.close()
    print("\nDatabase is 100% demo-ready on MySQL.")


if __name__ == "__main__":
    seed_all()
