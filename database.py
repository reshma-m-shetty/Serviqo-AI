"""
Serviqo AI - Pure MySQL Database Layer
All SQLite dependencies have been completely replaced with MySQL 8.0.
Thread-safe connection pool, secure password hashing (bcrypt), and relational schema.
"""

import os
import json
import math
import queue
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv
import bcrypt

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root123")
DB_NAME = os.getenv("DB_NAME", "serviqo_ai")
DB_SSL_MODE = os.getenv("DB_SSL_MODE", "REQUIRED").strip().upper()
DB_SSL_CA = os.getenv("DB_SSL_CA", "").strip()
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "15"))


def _get_ssl_config() -> Optional[Dict[str, Any]]:
    """Builds secure SSL config for cloud MySQL providers (Aiven, TiDB, RDS, etc.)."""
    mode = os.getenv("DB_SSL_MODE", DB_SSL_MODE).strip().upper()
    ca = os.getenv("DB_SSL_CA", DB_SSL_CA).strip()

    if mode in ("REQUIRED", "PREFERRED", "VERIFY_CA", "VERIFY_IDENTITY") or ca:
        ssl_kwargs: Dict[str, Any] = {}
        if ca and os.path.exists(ca):
            ssl_kwargs["ca"] = ca
            if mode == "VERIFY_IDENTITY":
                ssl_kwargs["check_hostname"] = True
            else:
                ssl_kwargs["check_hostname"] = False
        elif mode in ("REQUIRED", "PREFERRED"):
            ssl_kwargs["check_hostname"] = False
        elif mode in ("VERIFY_CA", "VERIFY_IDENTITY"):
            try:
                import certifi
                ssl_kwargs["ca"] = certifi.where()
                ssl_kwargs["check_hostname"] = (mode == "VERIFY_IDENTITY")
            except Exception:
                ssl_kwargs["check_hostname"] = False
        return ssl_kwargs
    return None


# ==========================================
# THREAD-SAFE MYSQL CONNECTION POOL
# ==========================================
class MySQLPool:
    def __init__(self, max_connections: int = 10):
        self.max_connections = int(os.getenv("DB_POOL_SIZE", str(max_connections)))
        self._pool = queue.Queue(maxsize=self.max_connections)
        self._lock = threading.Lock()
        self._created_connections = 0

    def _create_connection(self):
        kwargs = {
            "host": os.getenv("DB_HOST", DB_HOST),
            "port": int(os.getenv("DB_PORT", str(DB_PORT))),
            "user": os.getenv("DB_USER", DB_USER),
            "password": os.getenv("DB_PASSWORD", DB_PASSWORD),
            "database": os.getenv("DB_NAME", DB_NAME),
            "cursorclass": DictCursor,
            "autocommit": False,
            "charset": "utf8mb4",
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", str(DB_CONNECT_TIMEOUT))),
        }
        ssl_cfg = _get_ssl_config()
        if ssl_cfg:
            kwargs["ssl"] = ssl_cfg
        return pymysql.connect(**kwargs)

    def get_connection(self):
        conn = None
        timeout_val = int(os.getenv("DB_CONNECT_TIMEOUT", str(DB_CONNECT_TIMEOUT)))
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created_connections < self.max_connections:
                    self._created_connections += 1
                    try:
                        return self._create_connection()
                    except Exception:
                        self._created_connections -= 1
                        raise
            # Wait for an available connection from the pool
            conn = self._pool.get(timeout=timeout_val)

        # Validate borrowed connection health; recreate if closed/stale
        try:
            conn.ping(reconnect=True)
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created_connections -= 1
            fresh = self._create_connection()
            with self._lock:
                self._created_connections += 1
            return fresh

    def release_connection(self, conn):
        if conn is not None:
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    self._created_connections = max(0, self._created_connections - 1)

    def close_all(self):
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._created_connections = 0


_pool: Optional[MySQLPool] = None


def get_pool() -> MySQLPool:
    global _pool
    if _pool is None:
        _pool = MySQLPool(max_connections=DB_POOL_SIZE)
    return _pool


def reset_pool():
    """Closes all pooled MySQL connections and clears pool singleton."""
    global _pool
    if _pool is not None:
        _pool.close_all()
        _pool = None


class get_db:
    """Context manager for borrowing and safely returning a pooled MySQL connection."""
    def __enter__(self):
        self.conn = get_pool().get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            try:
                self.conn.rollback()
            except Exception:
                pass
        else:
            try:
                self.conn.commit()
            except Exception:
                pass
        get_pool().release_connection(self.conn)


# ==========================================
# PASSWORD HASHING (BCRYPT)
# ==========================================
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# ==========================================
# GEOLOCATION DISTANCE CALCULATION
# ==========================================
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)


# ==========================================
# DATABASE INITIALIZATION & SCHEMA CREATION
# ==========================================
def init_db():
    """
    Ensure MySQL database and all required tables exist.
    Compatible with cloud-hosted MySQL without requiring administrative privileges on every startup.
    Does NOT automatically seed demo records in production.
    """
    ssl_cfg = _get_ssl_config()
    target_db = os.getenv("DB_NAME", DB_NAME)
    db_kwargs = {
        "host": os.getenv("DB_HOST", DB_HOST),
        "port": int(os.getenv("DB_PORT", str(DB_PORT))),
        "user": os.getenv("DB_USER", DB_USER),
        "password": os.getenv("DB_PASSWORD", DB_PASSWORD),
        "charset": "utf8mb4",
        "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", str(DB_CONNECT_TIMEOUT)))
    }
    if ssl_cfg:
        db_kwargs["ssl"] = ssl_cfg

    # Attempt 1: Connect directly to target_db (standard cloud/production MySQL workflow)
    conn = None
    try:
        conn = pymysql.connect(database=target_db, **db_kwargs)
    except pymysql.err.OperationalError as oe:
        # Error 1049: Unknown database. Attempt creation if admin privileges exist.
        if oe.args[0] == 1049:
            try:
                admin_conn = pymysql.connect(**db_kwargs)
                admin_cursor = admin_conn.cursor()
                admin_cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{target_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                admin_conn.commit()
                admin_conn.close()
                conn = pymysql.connect(database=target_db, **db_kwargs)
            except Exception as admin_err:
                raise RuntimeError(
                    f"[MySQL Database] Database '{target_db}' does not exist and could not be auto-created: {admin_err}. "
                    f"Please create database '{target_db}' in your cloud MySQL console (Aiven/TiDB/RDS/Railway)."
                ) from admin_err
        else:
            raise

    cursor = conn.cursor()

    # Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'Kitchen Staff',
            organization VARCHAR(150) DEFAULT 'Srinivas Institute Canteen',
            ngo_id INT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    cursor.execute("SHOW COLUMNS FROM users LIKE 'organization'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE users ADD COLUMN organization VARCHAR(150) DEFAULT 'Srinivas Institute Canteen'")
    cursor.execute("SHOW COLUMNS FROM users LIKE 'ngo_id'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE users ADD COLUMN ngo_id INT NULL")

    # Inventory Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            category VARCHAR(100) DEFAULT 'General',
            quantity DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            unit VARCHAR(50) DEFAULT 'kg',
            expiry_days INT DEFAULT 5,
            expiry_date DATE NULL,
            servings_estimate INT DEFAULT 50,
            status VARCHAR(50) DEFAULT 'AVAILABLE',
            supplier_name VARCHAR(150) DEFAULT 'Srinivas Institute Canteen',
            suggested_action VARCHAR(255) DEFAULT 'Standard Kitchen Stock',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    # NGOs / Shelters Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ngos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            ngo_type VARCHAR(100) DEFAULT 'Charity & Shelter',
            need_level VARCHAR(20) DEFAULT 'high',
            distance_km DECIMAL(6,2) DEFAULT 0.00,
            latitude DECIMAL(10,6) NOT NULL,
            longitude DECIMAL(10,6) NOT NULL,
            address VARCHAR(255),
            manager VARCHAR(100),
            phone VARCHAR(50),
            email VARCHAR(150),
            capacity_persons INT DEFAULT 150,
            requested_items TEXT,
            verification_status VARCHAR(50) DEFAULT 'VERIFIED',
            account_status VARCHAR(50) DEFAULT 'ACTIVE',
            verified_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    cursor.execute("SHOW COLUMNS FROM ngos LIKE 'verification_status'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE ngos ADD COLUMN verification_status VARCHAR(50) DEFAULT 'VERIFIED'")
    cursor.execute("SHOW COLUMNS FROM ngos LIKE 'account_status'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE ngos ADD COLUMN account_status VARCHAR(50) DEFAULT 'ACTIVE'")
    cursor.execute("SHOW COLUMNS FROM ngos LIKE 'verified_at'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE ngos ADD COLUMN verified_at TIMESTAMP NULL")

    # Suppliers / Kitchens Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            category VARCHAR(100) DEFAULT 'canteen',
            surplus_level VARCHAR(50) DEFAULT 'high',
            distance_km DECIMAL(6,2) DEFAULT 0.00,
            latitude DECIMAL(10,6) NOT NULL,
            longitude DECIMAL(10,6) NOT NULL,
            address VARCHAR(255),
            manager VARCHAR(100),
            phone VARCHAR(50),
            email VARCHAR(150),
            available_items TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    # Donations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            request_id INT NULL,
            post_id INT NULL,
            inventory_id INT NULL,
            food_item VARCHAR(150) NOT NULL,
            quantity DECIMAL(10,2) NOT NULL,
            unit VARCHAR(50) DEFAULT 'kg',
            ngo_id INT NOT NULL,
            ngo_name VARCHAR(150) NOT NULL,
            supplier_name VARCHAR(150) DEFAULT 'Srinivas Institute Canteen',
            pickup_address VARCHAR(255),
            pickup_deadline VARCHAR(100) DEFAULT 'Within 3 hours',
            message TEXT,
            status VARCHAR(50) DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP NULL
        ) ENGINE=InnoDB;
    """)

    cursor.execute("SHOW COLUMNS FROM donations LIKE 'request_id'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE donations ADD COLUMN request_id INT NULL")
    cursor.execute("SHOW COLUMNS FROM donations LIKE 'post_id'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE donations ADD COLUMN post_id INT NULL")
    cursor.execute("SHOW COLUMNS FROM donations LIKE 'completed_at'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE donations ADD COLUMN completed_at TIMESTAMP NULL")

    # Demand Forecasts Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS demand_forecasts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            meal_type VARCHAR(50) NOT NULL,
            attendance INT NOT NULL,
            predicted_demand INT NOT NULL,
            recommended_prep INT NOT NULL,
            buffer INT DEFAULT 0,
            top_items_json TEXT,
            weather VARCHAR(50) DEFAULT 'Clear / Sunny',
            demand_status VARCHAR(50) DEFAULT 'Optimal',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    cursor.execute("SHOW COLUMNS FROM demand_forecasts LIKE 'actual_demand'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE demand_forecasts ADD COLUMN actual_demand INT NULL")

    # Announcements Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            message TEXT NOT NULL,
            recipient VARCHAR(100) DEFAULT 'All Staff',
            priority VARCHAR(50) DEFAULT 'Normal',
            sender VARCHAR(100) DEFAULT 'Kitchen Manager',
            status VARCHAR(50) DEFAULT 'Sent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    # Food Redistribution Posts Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS donation_posts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            inventory_id INT NULL,
            supplier_name VARCHAR(150) DEFAULT 'Srinivas Institute Canteen',
            food_item VARCHAR(150) NOT NULL,
            published_quantity DECIMAL(10,2) NOT NULL,
            unit VARCHAR(50) DEFAULT 'kg',
            available_until VARCHAR(100) DEFAULT 'Today before 4:00 PM',
            pickup_location VARCHAR(255) DEFAULT 'Srinivas Campus Canteen Gate 2, Mangalore',
            notes TEXT,
            status VARCHAR(50) DEFAULT 'AVAILABLE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    # Food Redistribution Requests Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS donation_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            post_id INT NOT NULL,
            inventory_id INT NULL,
            organization_id INT NOT NULL,
            organization_name VARCHAR(150) NOT NULL,
            food_item VARCHAR(150) NOT NULL,
            requested_quantity DECIMAL(10,2) NOT NULL,
            fulfilled_quantity DECIMAL(10,2) NULL,
            unit VARCHAR(50) DEFAULT 'kg',
            status VARCHAR(50) DEFAULT 'PENDING',
            message TEXT,
            preferred_pickup_time VARCHAR(100),
            pickup_date VARCHAR(100),
            pickup_time VARCHAR(100),
            pickup_location VARCHAR(255) DEFAULT 'Srinivas Campus Canteen Gate 2, Mangalore',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accepted_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL
        ) ENGINE=InnoDB;
    """)

    cursor.execute("SHOW COLUMNS FROM donation_requests LIKE 'inventory_id'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE donation_requests ADD COLUMN inventory_id INT NULL")
    cursor.execute("SHOW COLUMNS FROM donation_requests LIKE 'fulfilled_quantity'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE donation_requests ADD COLUMN fulfilled_quantity DECIMAL(10,2) NULL")

    # Notifications Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            recipient_role VARCHAR(50) NOT NULL,
            recipient_user_id INT NULL,
            recipient_ngo_id INT NULL,
            notification_type VARCHAR(50) NOT NULL,
            title VARCHAR(200) NOT NULL,
            message TEXT NOT NULL,
            related_post_id INT NULL,
            related_request_id INT NULL,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)

    conn.commit()

    # Align existing records to Srinivas Institute Canteen (safe idempotent alignment)
    try:
        cursor.execute("UPDATE users SET organization = 'Srinivas Institute Canteen' WHERE role IN ('Kitchen Staff', 'Supplier', 'Staff') AND (organization IS NULL OR organization = '')")
        cursor.execute("UPDATE users SET organization = 'ISKCON Food Relief Foundation - Mangalore', ngo_id = 1 WHERE email = 'ngo@serviqo.ai'")
        cursor.execute("UPDATE inventory SET supplier_name = 'Srinivas Institute Canteen' WHERE supplier_name LIKE '%Central Campus%'")
        cursor.execute("UPDATE donations SET supplier_name = 'Srinivas Institute Canteen' WHERE supplier_name LIKE '%Central Campus%'")
        cursor.execute("UPDATE suppliers SET name = 'Srinivas Institute Canteen / Kitchen', address = 'Srinivas Campus, Valachil, Mangalore', manager = 'Chef Venkatesh Rao', email = 'canteen@srinivasgroup.edu' WHERE id = 1")
        conn.commit()
    except Exception as e:
        pass

    # NOTE: Demo records are NOT automatically seeded here. Tables start clean in production.
    conn.close()
    print(f"[MySQL Database] Serviqo AI database '{DB_NAME}' and relational schema initialized successfully.")


def setup_admin_user(email: str, password: str, name: str = "Admin Manager", organization: str = "Srinivas Institute Canteen") -> Dict[str, Any]:
    """
    Configures an authorized administrative user without demo data pollution.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, role FROM users WHERE email = %s", (email.strip().lower(),))
        existing = cursor.fetchone()
        pwd_hash = hash_password(password)
        if existing:
            cursor.execute("UPDATE users SET name = %s, password_hash = %s, organization = %s WHERE id = %s", (name, pwd_hash, organization, existing["id"]))
            conn.commit()
            return {"status": "updated", "id": existing["id"], "email": email}
        else:
            cursor.execute("""
                INSERT INTO users (name, email, password_hash, role, organization)
                VALUES (%s, %s, %s, 'Kitchen Staff', %s)
            """, (name, email.strip().lower(), pwd_hash, organization))
            conn.commit()
            return {"status": "created", "id": cursor.lastrowid, "email": email}


def seed_demo_data(force: bool = False) -> bool:
    """
    Explicitly seeds realistic development/demo data into MySQL.
    NEVER runs automatically on production startup or deployment.
    Must be called deliberately.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM ngos")
        count = cursor.fetchone()["cnt"]
        if count > 0 and not force:
            print("[MySQL Seeder] Database already contains records. Skipping demo seed to preserve existing records.")
            return False

        today = datetime.now().date()

        # Seed Default Users
        staff_pwd = hash_password("staff123")
        ngo_pwd = hash_password("ngo123")
        cursor.execute("""
            INSERT IGNORE INTO users (name, email, password_hash, role, organization, ngo_id) VALUES
            ('Rohan Sharma', 'kitchen@serviqo.ai', %s, 'Kitchen Staff', 'Srinivas Institute Canteen', NULL),
            ('Anita Desai', 'ngo@serviqo.ai', %s, 'NGO', 'ISKCON Food Relief Foundation - Mangalore', 1)
        """, (staff_pwd, ngo_pwd))

        # Seed Verified NGOs
        sample_ngos = [
            ("ISKCON Food Relief Foundation - Mangalore", "Food Relief & Ashram Support", "high", 12.8698, 74.8430, "ISKCON Temple, Arya Samaj Road, Balmatta, Mangalore", "Anita Desai", "+91 824 242 1234", "iskcon.mangalore@serviqo.ai", 450, json.dumps(["Cooked Rice", "Dal", "Sambar", "Vegetables", "Curd"])),
            ("Sri Ramakrishna Ashram & Orphanage", "Ashram & Orphanage", "high", 12.9200, 74.8500, "Mangaladevi Road, Bolar, Mangalore", "Swami Prakash", "+91 98450 12345", "contact@ramakrishnaashram.org", 150, json.dumps(["Dal", "Rice", "Idli", "Sambar", "Vegetable Curry"])),
            ("Karunya Community Feeding Kitchen", "Community Kitchen", "high", 12.9180, 74.8580, "Near Hampankatta Circle, Mangalore", "Mahesh Prabhu", "+91 99001 88776", "karunyafeeding@gmail.com", 180, json.dumps(["All Cooked Meals", "Rice", "Dal", "Idli", "Sambar"])),
            ("Robin Hood Army - Mangalore Chapter", "Volunteer Food Rescue & Hunger Relief", "high", 12.8700, 74.8800, "City Center Area, K.S. Rao Road, Mangalore", "Priya Sharma", "+91 98200 45678", "rescue.mangalore@robinhoodarmy.com", 300, json.dumps(["Prepared Meals", "Rice", "Chapatis", "Curries", "Fruits"])),
            ("Sneha Sadan Care Home - Mangalore", "Care Home & Shelter", "high", 12.9450, 74.9300, "Gurpur, Kaikamba, Mangalore", "Fr. Mathew", "+91 94480 33221", "contact@snehasadan.org", 140, json.dumps(["Cooked Rice", "Dal", "Vegetables", "Milk"]))
        ]
        cursor.executemany("""
            INSERT INTO ngos (name, ngo_type, need_level, latitude, longitude, address, manager, phone, email, capacity_persons, requested_items)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, sample_ngos)

        # Seed Suppliers
        sample_suppliers = [
            ("Srinivas Institute Canteen / Kitchen", "canteen", "high", 12.8718, 74.9204, "Srinivas Campus, Valachil, Mangalore", "Chef Venkatesh Rao", "+91 824 227 4730", "canteen@srinivasgroup.edu", json.dumps(["Steamed Rice (40kg)", "Sambar (25L)", "Chapati (120 pcs)"])),
            ("Ocean Pearl Banquet & Kitchen", "function_hall", "high", 12.8732, 74.8421, "K.S. Rao Road, Hampankatta, Mangalore", "Vikram Soans", "+91 824 249 7000", "events@oceanpearl.in", json.dumps(["Veg Biryani (50kg)", "Paneer Curry (30L)", "Gulab Jamun (200 pcs)"])),
            ("Mangalore University Central Canteen", "caterer", "medium", 12.8159, 74.9248, "Konaje Campus, Mangalore", "Chef Murugan", "+91 824 228 7276", "canteen@mangaloreuniv.ac.in", json.dumps(["Cooked Meals (60 portions)", "Sambar (20L)", "Curd Rice (25kg)"]))
        ]
        cursor.executemany("""
            INSERT INTO suppliers (name, category, surplus_level, latitude, longitude, address, manager, phone, email, available_items)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, sample_suppliers)

        # Seed Inventory Items
        sample_inventory = [
            ("Cooked Rice", "Cooked Meals", 120.0, "portions", 1, today + timedelta(days=1), 120, "EXPIRING SOON", "Srinivas Institute Canteen", "Surplus Donation Eligible"),
            ("Dal Tadka", "Cooked Meals", 75.0, "portions", 1, today + timedelta(days=1), 75, "EXPIRING SOON", "Srinivas Institute Canteen", "Surplus Donation Eligible"),
            ("Steamed Idli", "Breakfast Items", 100.0, "plates", 1, today + timedelta(days=1), 100, "SURPLUS", "Srinivas Institute Canteen", "Immediate Recovery Advised"),
            ("Mixed Vegetable Curry", "Cooked Meals", 45.0, "portions", 1, today + timedelta(days=1), 45, "AVAILABLE", "Srinivas Institute Canteen", "Standard Distribution"),
            ("Fresh Milk", "Dairy", 30.0, "liters", 2, today + timedelta(days=2), 60, "AVAILABLE", "Srinivas Institute Canteen", "Kitchen Stock"),
            ("Wheat Roti / Chapatis", "Cooked Meals", 150.0, "pieces", 1, today + timedelta(days=1), 75, "SURPLUS", "Srinivas Institute Canteen", "Surplus Donation Eligible"),
            ("Raw Rice (Bags)", "Dry Rations", 250.0, "kg", 60, today + timedelta(days=60), 1000, "AVAILABLE", "Srinivas Institute Canteen", "Bulk Storage"),
            ("Cooking Oil", "Dry Rations", 8.0, "liters", 45, today + timedelta(days=45), 200, "LOW STOCK", "Srinivas Institute Canteen", "Reorder Required")
        ]
        cursor.executemany("""
            INSERT INTO inventory (name, category, quantity, unit, expiry_days, expiry_date, servings_estimate, status, supplier_name, suggested_action)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, sample_inventory)

        # Seed Sample Donations
        sample_donations = [
            (1, "Cooked Rice", 40.0, "portions", 1, "The Akshaya Patra Foundation", "Srinivas Institute Canteen", "Srinivas Campus Canteen Gate 2, Mangalore", "Within 3 hours", "Surplus afternoon lunch cooked rice available for immediate distribution.", "PENDING"),
            (2, "Steamed Idli", 50.0, "plates", 6, "Sri Ramakrishna Ashram & Orphanage", "Srinivas Institute Canteen", "Srinivas Campus Canteen Gate 2, Mangalore", "Within 2 hours", "Fresh breakfast idli ready for volunteer pickup.", "ACCEPTED")
        ]
        cursor.executemany("""
            INSERT INTO donations (inventory_id, food_item, quantity, unit, ngo_id, ngo_name, supplier_name, pickup_address, pickup_deadline, message, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, sample_donations)

        # Seed Sample Announcements
        sample_announcements = [
            ("Welcome to Serviqo AI", "MySQL 8.0 database integration is fully active. All Srinivas canteen inventory, demand forecasts, and donation dispatches are now relationally managed.", "All Staff", "High", "Canteen Manager", "Sent"),
            ("Afternoon Recovery Schedule", "Akshaya Patra volunteer vehicle will arrive between 3:30 PM - 4:00 PM for surplus recovery.", "Kitchen Staff", "Normal", "Kitchen Operations", "Sent")
        ]
        cursor.executemany("""
            INSERT INTO announcements (title, message, recipient, priority, sender, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, sample_announcements)

        conn.commit()
        print("[MySQL Seeder] Explicit demo dataset successfully loaded.")
        return True


# ==========================================
# HEALTH CHECK
# ==========================================
def check_mysql_health() -> Dict[str, Any]:
    """Verify MySQL connectivity and table presence safely without revealing secrets."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT VERSION()")
            ver_row = cursor.fetchone()
            version = ver_row["VERSION()"] if isinstance(ver_row, dict) else ver_row[0]
            cursor.execute("SHOW TABLES")
            raw_tables = cursor.fetchall()
            tables = [list(r.values())[0] if isinstance(r, dict) else r[0] for r in raw_tables]
            required = [
                "users", "inventory", "ngos", "suppliers", "donations", 
                "demand_forecasts", "announcements", "donation_posts", 
                "donation_requests", "notifications"
            ]
            missing = [t for t in required if t not in tables]
            return {
                "connected": True,
                "version": version,
                "database": os.getenv("DB_NAME", DB_NAME),
                "tables": tables,
                "tables_count": len(tables),
                "healthy": len(missing) == 0,
                "missing_tables": missing
            }
    except Exception as e:
        err_msg = str(e)
        active_pwd = os.getenv("DB_PASSWORD", DB_PASSWORD)
        if active_pwd and active_pwd in err_msg:
            err_msg = err_msg.replace(active_pwd, "******")
        return {
            "connected": False,
            "healthy": False,
            "error": err_msg,
            "message": "MySQL database connection failed. Please ensure MySQL Server is reachable and credentials in environment are correct."
        }


# ==========================================
# USER AUTHENTICATION CRUD
# ==========================================
def register_user(
    name: str,
    email: str,
    password: str,
    role: str = "Kitchen Staff",
    organization: Optional[str] = None,
    ngo_id: Optional[int] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    capacity_persons: Optional[int] = None,
    need_level: Optional[str] = "high",
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        clean_email = email.strip().lower()
        cursor.execute("SELECT id FROM users WHERE email = %s", (clean_email,))
        if cursor.fetchone():
            raise ValueError("Email already registered")

        hashed = hash_password(password)
        clean_role = role.strip()
        org = organization.strip() if organization else ("Srinivas Institute Canteen" if clean_role in ("Kitchen Staff", "Staff") else "Registered Relief Partner")

        final_ngo_id = ngo_id

        if clean_role == "NGO":
            if final_ngo_id:
                # Link to existing pre-registered NGO organization (Activate Account)
                cursor.execute("SELECT id, name FROM ngos WHERE id = %s", (final_ngo_id,))
                existing_ngo = cursor.fetchone()
                if existing_ngo:
                    org = existing_ngo["name"]
                    cursor.execute("UPDATE ngos SET account_status = 'ACTIVE' WHERE id = %s", (final_ngo_id,))
            else:
                # Check if organization with same name already exists in ngos table
                cursor.execute("SELECT id, name FROM ngos WHERE LOWER(name) = %s OR LOWER(email) = %s", (org.lower(), clean_email))
                matched_ngo = cursor.fetchone()
                if matched_ngo:
                    final_ngo_id = matched_ngo["id"]
                    org = matched_ngo["name"]
                    cursor.execute("UPDATE ngos SET account_status = 'ACTIVE' WHERE id = %s", (final_ngo_id,))
                else:
                    # Dynamically create new NGO organization record with PENDING verification status
                    n_lat = float(latitude) if latitude is not None else 12.8700
                    n_lon = float(longitude) if longitude is not None else 74.8800
                    n_cap = int(capacity_persons) if capacity_persons is not None else 150
                    n_phone = phone.strip() if phone else "+91 98450 12345"
                    n_addr = address.strip() if address else "Mangalore Relief Network"
                    n_need = need_level.strip().lower() if need_level else "high"
                    
                    cursor.execute("""
                        INSERT INTO ngos 
                        (name, ngo_type, need_level, latitude, longitude, address, manager, phone, email, capacity_persons, requested_items, verification_status, account_status)
                        VALUES (%s, 'Charity & Shelter', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', 'ACTIVE')
                    """, (org, n_need, n_lat, n_lon, n_addr, name.strip(), n_phone, clean_email, n_cap, json.dumps(["Prepared Meals", "Cooked Rice", "Dal", "Curry"])))
                    final_ngo_id = cursor.lastrowid

                    # Broadcast notification to Canteen staff about new registration awaiting approval
                    cursor.execute("""
                        INSERT INTO notifications (recipient_role, notification_type, title, message)
                        VALUES ('Supplier', 'NGO_PENDING_APPROVAL', 'New Relief Partner Awaiting Verification', %s)
                    """, (f"Organization '{org}' has registered via {name.strip()} ({clean_email}) and is pending verification.",))

        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role, organization, ngo_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name.strip(), clean_email, hashed, clean_role, org, final_ngo_id))
        user_id = cursor.lastrowid

        return {
            "id": user_id,
            "name": name.strip(),
            "email": clean_email,
            "role": clean_role,
            "organization": org,
            "ngo_id": final_ngo_id
        }


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
        user = cursor.fetchone()
        if not user:
            return None
        if verify_password(password, user["password_hash"]):
            role = user.get("role") or "Kitchen Staff"
            clean_role = role.strip()
            org = user.get("organization")
            ngo_id = user.get("ngo_id")

            if clean_role == "NGO":
                if ngo_id:
                    cursor.execute("SELECT id, name FROM ngos WHERE id = %s", (ngo_id,))
                    ngo_rec = cursor.fetchone()
                    if ngo_rec:
                        org = ngo_rec["name"]
                else:
                    # Resolve organization from ngos table
                    cursor.execute("SELECT id, name FROM ngos WHERE LOWER(name) = %s OR LOWER(email) = %s", (org.lower() if org else "", user["email"].lower()))
                    ngo_rec = cursor.fetchone()
                    if ngo_rec:
                        ngo_id = ngo_rec["id"]
                        org = ngo_rec["name"]
                        cursor.execute("UPDATE users SET ngo_id = %s, organization = %s WHERE id = %s", (ngo_id, org, user["id"]))
                        conn.commit()

            return {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "role": clean_role,
                "organization": org or ("Srinivas Institute Canteen" if "kitchen" in clean_role.lower() or "staff" in clean_role.lower() else "Registered NGO Partner"),
                "ngo_id": ngo_id
            }
        return None


def update_user_profile(user_id: int, name: str) -> Optional[Dict[str, Any]]:
    """Update user full name in MySQL users table and return updated user record."""
    with get_db() as conn:
        cursor = conn.cursor()
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Full name cannot be empty")
        cursor.execute("UPDATE users SET name = %s WHERE id = %s", (clean_name, user_id))
        conn.commit()
        cursor.execute("SELECT id, name, email, role, organization, ngo_id FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


# ==========================================
# INVENTORY MANAGEMENT CRUD
# ==========================================
def get_all_inventory(include_depleted: bool = False) -> List[Dict[str, Any]]:
    """
    Returns current active kitchen stock.
    Depleted and fully donated items (quantity = 0 or status in DONATED/DEPLETED)
    are excluded from the active list to maintain an uncluttered active inventory view.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        if include_depleted:
            cursor.execute("SELECT * FROM inventory ORDER BY expiry_days ASC, id DESC")
        else:
            cursor.execute("""
                SELECT * FROM inventory 
                WHERE UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0 
                ORDER BY expiry_days ASC, id DESC
            """)
        rows = cursor.fetchall()
        for r in rows:
            if r.get("quantity") is not None:
                try:
                    r["quantity"] = float(r["quantity"])
                except Exception:
                    pass
            if r.get("expiry_date"):
                r["expiry_date"] = str(r["expiry_date"])
            if "name" not in r or not r["name"]:
                r["name"] = r.get("item_name", "")
            if "item_name" not in r or not r["item_name"]:
                r["item_name"] = r.get("name", "")
            r["final_price_inr"] = float(r["final_price_inr"]) if r.get("final_price_inr") is not None else 0.0
            r["base_price_inr"] = float(r["base_price_inr"]) if r.get("base_price_inr") is not None else 0.0
            if "discount_percent" not in r:
                r["discount_percent"] = 0
            if "suggested_action" not in r or not r["suggested_action"]:
                r["suggested_action"] = "Standard Kitchen Stock"
        return rows


def get_inventory_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Fetch single inventory item by ID directly from MySQL."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inventory WHERE id = %s", (item_id,))
        item = cursor.fetchone()
        if not item:
            return None
        if item.get("quantity") is not None:
            try:
                item["quantity"] = float(item["quantity"])
            except Exception:
                pass
        if item.get("expiry_date"):
            item["expiry_date"] = str(item["expiry_date"])
        return item


def add_inventory_item(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        qty = float(data.get("quantity", 0))
        if qty <= 0:
            raise ValueError("Inventory item quantity must be greater than zero.")
        expiry_days = int(data.get("expiry_days", 5))

        # Transparent business rules for status
        if expiry_days <= 1:
            status = "EXPIRING SOON"
        elif qty <= 10:
            status = "LOW STOCK"
        elif qty >= 100:
            status = "SURPLUS"
        else:
            status = "AVAILABLE"

        expiry_date = datetime.now().date() + timedelta(days=expiry_days)
        item_name = (data.get("name") or data.get("item_name") or "New Item").strip()
        supplier_name = data.get("supplier_name") or "Srinivas Institute Canteen"

        cursor.execute("""
            INSERT INTO inventory (name, category, quantity, unit, expiry_days, expiry_date, servings_estimate, status, supplier_name, suggested_action)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            item_name,
            data.get("category", "General"),
            qty,
            data.get("unit", "kg"),
            expiry_days,
            expiry_date,
            int(data.get("servings_estimate", int(qty))),
            data.get("status", status),
            supplier_name,
            data.get("suggested_action", "Regular Stock")
        ))
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM inventory WHERE id = %s", (new_id,))
        item = cursor.fetchone()
        if item and item.get("expiry_date"):
            item["expiry_date"] = item["expiry_date"].strftime("%Y-%m-%d")
        if item and item.get("quantity") is not None:
            item["quantity"] = float(item["quantity"])
        return item


def update_inventory_item(item_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inventory WHERE id = %s", (item_id,))
        existing = cursor.fetchone()
        if not existing:
            return None

        qty = float(data.get("quantity", existing["quantity"]))
        expiry_days = int(data.get("expiry_days", existing["expiry_days"]))
        status = data.get("status", existing["status"])

        if qty <= 0:
            status = "DEPLETED"

        expiry_date = datetime.now().date() + timedelta(days=expiry_days)

        cursor.execute("""
            UPDATE inventory
            SET quantity = %s, expiry_days = %s, expiry_date = %s, status = %s
            WHERE id = %s
        """, (qty, expiry_days, expiry_date, status, item_id))

        cursor.execute("SELECT * FROM inventory WHERE id = %s", (item_id,))
        item = cursor.fetchone()
        if item and item.get("expiry_date"):
            item["expiry_date"] = item["expiry_date"].strftime("%Y-%m-%d")
        if item and item.get("quantity") is not None:
            item["quantity"] = float(item["quantity"])
        return item


def delete_inventory_item(item_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM inventory WHERE id = %s", (item_id,))
        return cursor.rowcount > 0


# ==========================================
# IDENTIFY SURPLUS FOOD
# ==========================================
def get_surplus_food_items() -> List[Dict[str, Any]]:
    """
    Identifies surplus items from active MySQL inventory based on:
    1. Active inventory only (quantity > 0 and status NOT IN ('DONATED', 'DEPLETED'))
    2. Available unreserved quantity vs estimated required servings
    3. Near-expiry items (<= 2 days) or status SURPLUS/EXPIRING SOON
    Formula: Surplus Quantity = max(0, Available Quantity - Expected Consumption)
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM inventory 
            WHERE UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0 
            ORDER BY expiry_days ASC
        """)
        items = cursor.fetchall()

        surplus_list = []
        for item in items:
            qty = float(item["quantity"])
            days = int(item["expiry_days"])

            # Standard consumption expectation: baseline 60% of stock is consumed daily
            # Items expiring in <= 2 days or large batch quantities generate actionable surplus
            expected_consumption = round(qty * 0.60, 1) if days > 1 else round(qty * 0.30, 1)
            surplus_qty = round(max(0.0, qty - expected_consumption), 1)

            # Mark eligible if surplus > 0 or expiry <= 2 days
            if surplus_qty > 0 or days <= 2 or item["status"] in ("SURPLUS", "EXPIRING SOON"):
                final_surplus = surplus_qty if surplus_qty > 0 else qty
                surplus_list.append({
                    "inventory_id": item["id"],
                    "food_item": item["name"],
                    "category": item["category"],
                    "available_quantity": qty,
                    "expected_demand": expected_consumption,
                    "surplus_quantity": final_surplus,
                    "unit": item["unit"],
                    "expiry_days": days,
                    "expiry_date": item["expiry_date"].strftime("%Y-%m-%d") if item.get("expiry_date") else "Immediate",
                    "status": item["status"],
                    "supplier_name": item["supplier_name"]
                })
        return surplus_list


# ==========================================
# NGOS & SUPPLIERS CRUD
# ==========================================
def get_all_ngos(latitude: Optional[float] = None, longitude: Optional[float] = None) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ngos ORDER BY id ASC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("requested_items"), str):
                try:
                    d["requested_items"] = json.loads(d["requested_items"])
                except Exception:
                    d["requested_items"] = []

            # Populate field name aliases for resilient frontend rendering
            d["capacity_people"] = d.get("capacity_persons", 150)
            d["contact_person"] = d.get("manager", "Relief Coordinator")
            d["verification_status"] = d.get("verification_status") or "VERIFIED"
            d["account_status"] = d.get("account_status") or "ACTIVE"

            # Compute actual geographic distance if coordinates provided
            if latitude is not None and longitude is not None:
                d["distance_km"] = haversine_distance(latitude, longitude, float(d["latitude"]), float(d["longitude"]))
            else:
                d["distance_km"] = float(d.get("distance_km") or 0.0)

            result.append(d)

        # Sort closest first if coordinates were provided
        if latitude is not None and longitude is not None:
            result.sort(key=lambda x: (x["distance_km"], 0 if x.get("need_level") == "high" else 1))
        return result


def get_ngo_by_id(ngo_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ngos WHERE id = %s", (ngo_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("requested_items"), str):
            try:
                d["requested_items"] = json.loads(d["requested_items"])
            except Exception:
                d["requested_items"] = []
        d["capacity_people"] = d.get("capacity_persons", 150)
        d["contact_person"] = d.get("manager", "Relief Coordinator")
        d["verification_status"] = d.get("verification_status") or "VERIFIED"
        d["account_status"] = d.get("account_status") or "ACTIVE"
        return d


def verify_ngo(ngo_id: int, status: str) -> Optional[Dict[str, Any]]:
    """Update NGO verification status (VERIFIED, REJECTED, PENDING) with timestamp and notification."""
    clean_status = status.upper().strip()
    if clean_status not in ("VERIFIED", "REJECTED", "PENDING"):
        raise ValueError("Invalid verification status. Must be VERIFIED, REJECTED, or PENDING.")
    with get_db() as conn:
        cursor = conn.cursor()
        now = datetime.now() if clean_status == "VERIFIED" else None
        cursor.execute("UPDATE ngos SET verification_status = %s, verified_at = %s WHERE id = %s", (clean_status, now, ngo_id))
        conn.commit()

        # Notify NGO if registered
        cursor.execute("SELECT name, email FROM ngos WHERE id = %s", (ngo_id,))
        ngo_info = cursor.fetchone()
        if ngo_info:
            notif_msg = f"Your NGO partnership for '{ngo_info['name']}' has been {clean_status.lower()} by Srinivas Canteen administration."
            cursor.execute("""
                INSERT INTO notifications (recipient_role, recipient_ngo_id, notification_type, title, message)
                VALUES ('NGO', %s, %s, %s, %s)
            """, (ngo_id, f"NGO_{clean_status}", f"Partnership {clean_status.capitalize()}", notif_msg))
            conn.commit()

        cursor.execute("SELECT * FROM ngos WHERE id = %s", (ngo_id,))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["capacity_people"] = d.get("capacity_persons", 150)
            d["contact_person"] = d.get("manager", "Relief Coordinator")
            d["verification_status"] = d.get("verification_status") or clean_status
            d["account_status"] = d.get("account_status") or "ACTIVE"
            return d
        return None


def get_all_suppliers(latitude: Optional[float] = None, longitude: Optional[float] = None) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM suppliers ORDER BY id ASC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("available_items"), str):
                try:
                    d["available_items"] = json.loads(d["available_items"])
                except Exception:
                    d["available_items"] = []

            if latitude is not None and longitude is not None:
                d["distance_km"] = haversine_distance(latitude, longitude, float(d["latitude"]), float(d["longitude"]))
            else:
                d["distance_km"] = float(d.get("distance_km") or 0.0)

            result.append(d)
        return result


# ==========================================
# DONATION REQUESTS CRUD
# ==========================================
def create_donation(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        inventory_id = data.get("inventory_id")
        food_item = data.get("food_item") or data.get("item_name") or "Surplus Food"
        quantity = float(data.get("quantity", 1))
        unit = data.get("unit", "kg")
        ngo_id = int(data.get("ngo_id", 1))
        ngo_name = data.get("ngo_name", "Local Community Shelter")
        supplier_name = data.get("supplier_name", "Srinivas Institute Canteen")
        pickup_address = data.get("pickup_address", "Srinivas Campus Canteen Gate 2, Mangalore")
        pickup_deadline = data.get("pickup_deadline", "Within 3 hours")

        # Dynamically generate professional donation message if not supplied
        message = data.get("message")
        if not message:
            message = (
                f"Hello {ngo_name},\n\n"
                f"Serviqo AI has identified a verified surplus of {food_item} from {supplier_name}. "
                f"We would like to donate approximately {quantity} {unit} for immediate charitable distribution.\n\n"
                f"Pickup Location: {pickup_address}\n"
                f"Suggested Window: {pickup_deadline}\n\n"
                f"Please confirm if your organization can accept this donation.\n\n"
                f"Thank you,\n{supplier_name}"
            )

        cursor.execute("""
            INSERT INTO donations (inventory_id, food_item, quantity, unit, ngo_id, ngo_name, supplier_name, pickup_address, pickup_deadline, message, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
        """, (inventory_id, food_item, quantity, unit, ngo_id, ngo_name, supplier_name, pickup_address, pickup_deadline, message))
        new_id = cursor.lastrowid

        # Do NOT mark inventory as DONATED while status is PENDING.
        if inventory_id:
            cursor.execute("SELECT status FROM inventory WHERE id = %s", (inventory_id,))
            inv_st = cursor.fetchone()
            if inv_st and inv_st.get("status") in ("AVAILABLE", "EXPIRING SOON"):
                cursor.execute("UPDATE inventory SET status = 'SURPLUS' WHERE id = %s", (inventory_id,))

        cursor.execute("SELECT * FROM donations WHERE id = %s", (new_id,))
        created = cursor.fetchone()
        if created:
            if isinstance(created.get("quantity"), (float, int)):
                created["quantity"] = float(created["quantity"])
            if created.get("created_at"):
                created["created_at"] = created["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            created["item_name"] = created.get("food_item", "")
        return created


def get_all_donations(status: Optional[str] = None, ngo_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM donations WHERE 1=1"
        params = []
        if status and status.upper() != "ALL":
            clean_filter = status.upper().strip()
            if clean_filter in ("APPROVED", "ACCEPT"):
                clean_filter = "ACCEPTED"
            elif clean_filter in ("DISTRIBUTED", "COMPLETE"):
                clean_filter = "COMPLETED"
            query += " AND UPPER(status) = %s"
            params.append(clean_filter)
        if ngo_id:
            query += " AND ngo_id = %s"
            params.append(ngo_id)
        query += " ORDER BY id DESC"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        for r in rows:
            if isinstance(r.get("quantity"), (float, int)):
                r["quantity"] = float(r["quantity"])
            if r.get("created_at"):
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            if r.get("completed_at"):
                r["completed_at"] = r["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            r["item_name"] = r.get("food_item", "")
        return rows


def get_donation_by_id(donation_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donations WHERE id = %s", (donation_id,))
        row = cursor.fetchone()
        if row:
            if isinstance(row.get("quantity"), (float, int)):
                row["quantity"] = float(row["quantity"])
            if row.get("created_at"):
                row["created_at"] = row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            if row.get("completed_at"):
                row["completed_at"] = row["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            row["item_name"] = row.get("food_item", "")
        return row


def update_donation_status(donation_id: int, status: str) -> Optional[Dict[str, Any]]:
    clean_status = status.upper().strip()
    if clean_status in ("APPROVED", "ACCEPT"):
        clean_status = "ACCEPTED"
    elif clean_status in ("DISTRIBUTED", "COMPLETE"):
        clean_status = "COMPLETED"
    elif clean_status in ("REJECT", "DECLINED"):
        clean_status = "REJECTED"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donations WHERE id = %s FOR UPDATE", (donation_id,))
        existing = cursor.fetchone()
        if not existing:
            return None

        now = datetime.now()
        completed_at = existing.get("completed_at")
        if clean_status == "COMPLETED":
            completed_at = now
            # Deduct inventory stock if linked and not already deducted
            if existing.get("inventory_id") and existing.get("status") != "COMPLETED":
                cursor.execute("SELECT * FROM inventory WHERE id = %s FOR UPDATE", (existing["inventory_id"],))
                inv = cursor.fetchone()
                if inv:
                    cur_q = float(inv["quantity"])
                    sub_q = float(existing["quantity"])
                    rem_q = max(0.0, round(cur_q - sub_q, 2))
                    new_st = "DONATED" if rem_q <= 0 else ("LOW STOCK" if rem_q <= 10 else "AVAILABLE")
                    cursor.execute("UPDATE inventory SET quantity = %s, status = %s WHERE id = %s", (rem_q, new_st, existing["inventory_id"]))

        cursor.execute("UPDATE donations SET status = %s, completed_at = %s WHERE id = %s", (clean_status, completed_at, donation_id))
        cursor.execute("SELECT * FROM donations WHERE id = %s", (donation_id,))
        row = cursor.fetchone()
        if row:
            if isinstance(row.get("quantity"), (float, int)):
                row["quantity"] = float(row["quantity"])
            if row.get("created_at"):
                row["created_at"] = row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            if row.get("completed_at"):
                row["completed_at"] = row["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            row["item_name"] = row.get("food_item", "")
        return row


# ==========================================
# FOOD REDISTRIBUTION WORKFLOW & RESERVATION ENGINE
# ==========================================

def _enrich_post_quantities(cursor, post: Dict[str, Any]) -> Dict[str, Any]:
    post_id = post["id"]
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN UPPER(status) = 'PENDING' THEN requested_quantity ELSE 0 END), 0) AS reserved_pending,
            COALESCE(SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'SCHEDULED') THEN requested_quantity ELSE 0 END), 0) AS reserved_allocated,
            COALESCE(SUM(CASE WHEN UPPER(status) IN ('PENDING', 'ACCEPTED', 'SCHEDULED') THEN requested_quantity ELSE 0 END), 0) AS total_reserved,
            COALESCE(SUM(CASE WHEN UPPER(status) IN ('COLLECTED', 'COMPLETED') THEN COALESCE(fulfilled_quantity, requested_quantity) ELSE 0 END), 0) AS total_completed
        FROM donation_requests
        WHERE post_id = %s
    """, (post_id,))
    res_row = cursor.fetchone()
    total_reserved = float(res_row["total_reserved"])
    reserved_pending = float(res_row["reserved_pending"])
    reserved_allocated = float(res_row["reserved_allocated"])
    total_completed = float(res_row["total_completed"])

    published_qty = float(post["published_quantity"])
    remaining = round(max(0.0, published_qty - (total_reserved + total_completed)), 2)

    # If linked to inventory, verify physical stock
    if post.get("inventory_id"):
        cursor.execute("SELECT quantity, status FROM inventory WHERE id = %s", (post["inventory_id"],))
        inv_row = cursor.fetchone()
        if inv_row:
            inv_stock = float(inv_row["quantity"])
            if inv_row["status"] in ("DONATED", "DEPLETED") or inv_stock <= 0:
                remaining = 0.0
            else:
                remaining = min(remaining, inv_stock)

    post["published_quantity"] = published_qty
    post["reserved_quantity"] = round(total_reserved, 2)
    post["reserved_pending"] = round(reserved_pending, 2)
    post["reserved_allocated"] = round(reserved_allocated, 2)
    post["completed_quantity"] = round(total_completed, 2)
    post["remaining_available_quantity"] = remaining
    post["remaining_available"] = remaining
    post["available_quantity"] = remaining

    if remaining <= 0 and post["status"] == "AVAILABLE":
        post["status"] = "EXHAUSTED"
    elif remaining > 0 and post["status"] == "EXHAUSTED":
        post["status"] = "AVAILABLE"

    if post.get("created_at"):
        post["created_at"] = post["created_at"].strftime("%Y-%m-%d %H:%M:%S")

    return post


def publish_surplus_post(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Supplier publishes surplus food available for redistribution.
    Visible to ALL registered partner organizations.
    Validates against live inventory stock if linked to an inventory item.
    Does NOT mark inventory as DONATED and does not double-reduce stock.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        inventory_id = data.get("inventory_id")
        food_item = data.get("food_item") or data.get("item_name") or "Surplus Food"
        published_quantity = float(data.get("published_quantity") or data.get("quantity") or 1.0)
        unit = data.get("unit", "kg")
        available_until = data.get("available_until", "Today before 4:00 PM")
        pickup_location = data.get("pickup_location", "Srinivas Campus Canteen Gate 2, Mangalore")
        notes = data.get("notes", "Freshly prepared")
        supplier_name = data.get("supplier_name", "Srinivas Institute Canteen")

        if published_quantity <= 0:
            raise ValueError("Published surplus quantity must be greater than zero.")

        # If linked to inventory, validate active stock under row lock
        if inventory_id:
            cursor.execute("SELECT * FROM inventory WHERE id = %s FOR UPDATE", (inventory_id,))
            inv = cursor.fetchone()
            if not inv:
                raise ValueError(f"Linked inventory item #{inventory_id} does not exist.")
            if inv["status"] in ("DONATED", "DEPLETED") or float(inv["quantity"]) <= 0:
                raise ValueError(f"Cannot publish surplus from depleted/donated inventory item '{inv['name']}'.")

            current_stock = float(inv["quantity"])
            if published_quantity > current_stock:
                raise ValueError(
                    f"Published quantity ({published_quantity} {unit}) exceeds current active inventory stock ({current_stock} {inv['unit']})."
                )

            # Update inventory status to SURPLUS without reducing stock or marking DONATED
            if inv["status"] in ("AVAILABLE", "EXPIRING SOON", "LOW STOCK"):
                cursor.execute("UPDATE inventory SET status = 'SURPLUS' WHERE id = %s", (inventory_id,))

        cursor.execute("""
            INSERT INTO donation_posts (inventory_id, supplier_name, food_item, published_quantity, unit, available_until, pickup_location, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'AVAILABLE')
        """, (inventory_id, supplier_name, food_item, published_quantity, unit, available_until, pickup_location, notes))
        post_id = cursor.lastrowid

        # Broadcast food availability notification to ALL partner organizations
        notif_msg = f"New surplus food is available from {supplier_name}: {food_item} ({published_quantity} {unit}). Available until {available_until}."
        cursor.execute("""
            INSERT INTO notifications (recipient_role, notification_type, title, message, related_post_id)
            VALUES ('NGO', 'SURPLUS_AVAILABLE', 'New Surplus Food Available', %s, %s)
        """, (notif_msg, post_id))

        conn.commit()
        return get_donation_post_by_id(post_id)


def get_donation_post_by_id(post_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donation_posts WHERE id = %s", (post_id,))
        post = cursor.fetchone()
        if not post:
            return None
        return _enrich_post_quantities(cursor, post)


def get_all_donation_posts() -> List[Dict[str, Any]]:
    """Supplier view of all surplus posts."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donation_posts ORDER BY id DESC")
        posts = cursor.fetchall()
        return [_enrich_post_quantities(cursor, p) for p in posts]


def get_available_donation_posts() -> List[Dict[str, Any]]:
    """Partner organizations view of currently available surplus posts."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donation_posts WHERE status != 'CANCELLED' ORDER BY id DESC")
        posts = cursor.fetchall()
        enriched = [_enrich_post_quantities(cursor, p) for p in posts]
        # Return posts that still have remaining available quantity
        return [p for p in enriched if p["remaining_available_quantity"] > 0]


def create_donation_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Partner organization requests a specific quantity of food from an available post.
    Enforces row-level locking (SELECT ... FOR UPDATE) and validates remaining inventory.
    Calculates remaining available quantity dynamically.
    Returns HTTP 400 error message if requested_quantity exceeds available.
    """
    post_id = int(data.get("post_id"))
    organization_id = int(data.get("organization_id"))
    organization_name = data.get("organization_name", "Partner NGO")
    requested_qty = float(data.get("requested_quantity", 0))
    message = data.get("message", "")
    preferred_pickup_time = data.get("preferred_pickup_time", "As soon as possible")

    if requested_qty <= 0:
        raise ValueError("Requested quantity must be greater than zero.")

    with get_db() as conn:
        cursor = conn.cursor()

        # 0. Check NGO partner verification status
        cursor.execute("SELECT verification_status, name FROM ngos WHERE id = %s", (organization_id,))
        ngo_info = cursor.fetchone()
        if ngo_info and ngo_info.get("verification_status") == "PENDING":
            raise ValueError(f"Organization '{ngo_info.get('name')}' is currently pending verification by Canteen administration. Food recovery booking will be enabled upon approval.")
        elif ngo_info and ngo_info.get("verification_status") == "REJECTED":
            raise ValueError(f"Organization '{ngo_info.get('name')}' has not been approved for food recovery dispatches.")

        # 1. Lock the post record to prevent race conditions & double-booking
        cursor.execute("SELECT * FROM donation_posts WHERE id = %s FOR UPDATE", (post_id,))
        post = cursor.fetchone()
        if not post:
            raise ValueError("Food availability post not found.")

        # 2. Compute live remaining available quantity under lock
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('PENDING', 'ACCEPTED', 'SCHEDULED') THEN requested_quantity ELSE 0 END), 0) AS total_reserved,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('COLLECTED', 'COMPLETED') THEN COALESCE(fulfilled_quantity, requested_quantity) ELSE 0 END), 0) AS total_completed
            FROM donation_requests
            WHERE post_id = %s
        """, (post_id,))
        booking_row = cursor.fetchone()
        total_reserved = float(booking_row["total_reserved"])
        total_completed = float(booking_row["total_completed"])
        published_qty = float(post["published_quantity"])
        remaining_available = round(max(0.0, published_qty - (total_reserved + total_completed)), 2)

        # Also check physical inventory stock if linked
        inventory_id = post.get("inventory_id")
        if inventory_id:
            cursor.execute("SELECT quantity, status FROM inventory WHERE id = %s FOR UPDATE", (inventory_id,))
            inv_row = cursor.fetchone()
            if inv_row:
                curr_inv_stock = float(inv_row["quantity"])
                remaining_available = min(remaining_available, curr_inv_stock)

        # 3. Validate requested quantity against remaining available
        if requested_qty > remaining_available:
            raise ValueError(f"Only {remaining_available} {post['unit']} is currently available.")

        # 4. Insert request with status PENDING (holding the reserved quantity)
        cursor.execute("""
            INSERT INTO donation_requests 
            (post_id, inventory_id, organization_id, organization_name, food_item, requested_quantity, unit, status, message, preferred_pickup_time, pickup_location)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s)
        """, (post_id, inventory_id, organization_id, organization_name, post["food_item"], requested_qty, post["unit"], message, preferred_pickup_time, post["pickup_location"]))
        request_id = cursor.lastrowid

        # 5. Mirror to legacy donations table linked by request_id
        cursor.execute("""
            INSERT INTO donations (request_id, post_id, inventory_id, food_item, quantity, unit, ngo_id, ngo_name, supplier_name, pickup_address, pickup_deadline, message, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
        """, (request_id, post_id, inventory_id, post["food_item"], requested_qty, post["unit"], organization_id, organization_name, post["supplier_name"], post["pickup_location"], preferred_pickup_time, message))

        # 6. Notify Supplier
        notif_msg = f"{organization_name} has requested {requested_qty} {post['unit']} of {post['food_item']}."
        cursor.execute("""
            INSERT INTO notifications (recipient_role, notification_type, title, message, related_post_id, related_request_id)
            VALUES ('Supplier', 'REQUEST_CREATED', 'New Food Request', %s, %s, %s)
        """, (notif_msg, post_id, request_id))

        conn.commit()

        cursor.execute("SELECT * FROM donation_requests WHERE id = %s", (request_id,))
        req = cursor.fetchone()
        if req and req.get("requested_at"):
            req["requested_at"] = req["requested_at"].strftime("%Y-%m-%d %H:%M:%S")
        if req:
            req["requested_quantity"] = float(req["requested_quantity"])
        return req


def update_donation_request_status(
    request_id: int, 
    status: str, 
    pickup_date: Optional[str] = None, 
    pickup_time: Optional[str] = None, 
    pickup_location: Optional[str] = None,
    fulfilled_quantity: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Supplier updates request status with atomic inventory deduction and concurrency safety:
    - ACCEPTED: keeps reserved quantity, notifies NGO.
    - REJECTED: releases reserved quantity back to available pool, notifies NGO.
    - SCHEDULED: schedules pickup, notifies NGO.
    - COLLECTED / COMPLETED: food collected; deducts inventory stock exactly once.
      Depleted items (quantity <= 0) receive status 'DONATED' / 'DEPLETED' and disappear from active inventory.
      Idempotent: retries do not deduct stock twice.
    """
    clean_status = status.upper().strip()
    if clean_status in ("DISTRIBUTED", "COMPLETE"):
        clean_status = "COMPLETED"
    elif clean_status in ("APPROVE", "APPROVED", "ACCEPT"):
        clean_status = "ACCEPTED"
    elif clean_status in ("REJECT", "DECLINED"):
        clean_status = "REJECTED"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donation_requests WHERE id = %s FOR UPDATE", (request_id,))
        req = cursor.fetchone()
        if not req:
            return None

        current_status = req["status"].upper().strip()
        now = datetime.now()
        accepted_at = req.get("accepted_at")
        completed_at = req.get("completed_at")

        # Idempotency check for COMPLETED / COLLECTED
        if current_status in ("COMPLETED", "COLLECTED") and clean_status in ("COMPLETED", "COLLECTED"):
            cursor.execute("SELECT * FROM donation_requests WHERE id = %s", (request_id,))
            upd = cursor.fetchone()
            if upd:
                if upd.get("requested_at"):
                    upd["requested_at"] = upd["requested_at"].strftime("%Y-%m-%d %H:%M:%S")
                if upd.get("accepted_at"):
                    upd["accepted_at"] = upd["accepted_at"].strftime("%Y-%m-%d %H:%M:%S")
                if upd.get("completed_at"):
                    upd["completed_at"] = upd["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
                upd["requested_quantity"] = float(upd["requested_quantity"])
            return upd

        if current_status in ("COMPLETED", "COLLECTED") and clean_status in ("REJECTED", "CANCELLED", "PENDING"):
            raise ValueError("Cannot cancel or reject a donation that has already been collected and completed.")

        if clean_status == "ACCEPTED":
            accepted_at = now
            notif_title = "Donation Request Accepted"
            notif_msg = f"Your request for {req['requested_quantity']} {req['unit']} of {req['food_item']} from Srinivas Canteen has been accepted."
            cursor.execute("""
                INSERT INTO notifications (recipient_role, recipient_ngo_id, notification_type, title, message, related_request_id)
                VALUES ('NGO', %s, 'REQUEST_ACCEPTED', %s, %s, %s)
            """, (req["organization_id"], notif_title, notif_msg, request_id))

        elif clean_status in ("REJECTED", "CANCELLED"):
            notif_title = "Donation Request Rejected" if clean_status == "REJECTED" else "Donation Request Cancelled"
            notif_msg = f"Your request for {req['requested_quantity']} {req['unit']} of {req['food_item']} from Srinivas Canteen has been {clean_status.lower()}."
            cursor.execute("""
                INSERT INTO notifications (recipient_role, recipient_ngo_id, notification_type, title, message, related_request_id)
                VALUES ('NGO', %s, %s, %s, %s, %s)
            """, (req["organization_id"], f"REQUEST_{clean_status}", notif_title, notif_msg, request_id))

        elif clean_status == "SCHEDULED":
            pickup_date = pickup_date or datetime.now().strftime("%Y-%m-%d")
            pickup_time = pickup_time or "2:00 PM"
            pickup_location = pickup_location or req.get("pickup_location") or "Srinivas Campus Canteen Gate 2, Mangalore"
            notif_title = "Pickup Scheduled"
            notif_msg = f"Pickup scheduled for {pickup_time} on {pickup_date} at {pickup_location} for {req['requested_quantity']} {req['unit']} of {req['food_item']}."
            cursor.execute("""
                INSERT INTO notifications (recipient_role, recipient_ngo_id, notification_type, title, message, related_request_id)
                VALUES ('NGO', %s, 'PICKUP_SCHEDULED', %s, %s, %s)
            """, (req["organization_id"], notif_title, notif_msg, request_id))

        elif clean_status in ("COMPLETED", "COLLECTED"):
            completed_at = now
            accepted_at = accepted_at or now
            deduct_qty = float(fulfilled_quantity if fulfilled_quantity is not None and fulfilled_quantity > 0 else req["requested_quantity"])

            # -------------------------------------------------------------
            # DEDUCT INVENTORY STOCK EXACTLY ONCE
            # -------------------------------------------------------------
            inv_id = req.get("inventory_id")
            if not inv_id and req.get("post_id"):
                cursor.execute("SELECT inventory_id FROM donation_posts WHERE id = %s", (req["post_id"],))
                p_row = cursor.fetchone()
                if p_row:
                    inv_id = p_row.get("inventory_id")

            if inv_id:
                cursor.execute("SELECT * FROM inventory WHERE id = %s FOR UPDATE", (inv_id,))
                inv = cursor.fetchone()
                if inv:
                    curr_qty = float(inv["quantity"])
                    new_qty = max(0.0, round(curr_qty - deduct_qty, 2))

                    # Update status: if depleted (0 kg), mark DONATED so it is excluded from active inventory
                    if new_qty <= 0.0:
                        new_inv_status = "DONATED"
                    elif int(inv.get("expiry_days", 5)) <= 1:
                        new_inv_status = "EXPIRING SOON"
                    elif new_qty <= 10.0:
                        new_inv_status = "LOW STOCK"
                    elif new_qty >= 100.0:
                        new_inv_status = "SURPLUS"
                    else:
                        new_inv_status = "AVAILABLE"

                    cursor.execute("""
                        UPDATE inventory 
                        SET quantity = %s, status = %s 
                        WHERE id = %s
                    """, (new_qty, new_inv_status, inv_id))

            # Notifications
            cursor.execute("""
                INSERT INTO notifications (recipient_role, recipient_ngo_id, notification_type, title, message, related_request_id)
                VALUES ('NGO', %s, 'DONATION_COMPLETED', 'Donation Completed', %s, %s)
            """, (req["organization_id"], f"Donation of {deduct_qty} {req['unit']} of {req['food_item']} has been completed and verified.", request_id))

            cursor.execute("""
                INSERT INTO notifications (recipient_role, notification_type, title, message, related_request_id)
                VALUES ('Supplier', 'DONATION_COMPLETED', 'Donation Picked Up', %s, %s)
            """, (f"{req['organization_name']} collected {deduct_qty} {req['unit']} of {req['food_item']}.", request_id))

        # Update donation_requests table
        actual_fulfilled = float(fulfilled_quantity) if fulfilled_quantity is not None else float(req["requested_quantity"])
        cursor.execute("""
            UPDATE donation_requests
            SET status = %s,
                pickup_date = COALESCE(%s, pickup_date),
                pickup_time = COALESCE(%s, pickup_time),
                pickup_location = COALESCE(%s, pickup_location),
                accepted_at = %s,
                completed_at = %s,
                fulfilled_quantity = %s
            WHERE id = %s
        """, (clean_status, pickup_date, pickup_time, pickup_location, accepted_at, completed_at, actual_fulfilled, request_id))

        # Update legacy donations table mirror by request_id (or fallback match)
        cursor.execute("""
            UPDATE donations
            SET status = %s, completed_at = %s
            WHERE request_id = %s
        """, (clean_status, completed_at, request_id))

        if cursor.rowcount == 0:
            cursor.execute("""
                UPDATE donations
                SET status = %s, completed_at = %s
                WHERE food_item = %s AND ngo_id = %s AND status != 'COMPLETED'
                ORDER BY id DESC LIMIT 1
            """, (clean_status, completed_at, req["food_item"], req["organization_id"]))

        conn.commit()

        cursor.execute("SELECT * FROM donation_requests WHERE id = %s", (request_id,))
        updated = cursor.fetchone()
        if updated:
            if updated.get("requested_at"):
                updated["requested_at"] = updated["requested_at"].strftime("%Y-%m-%d %H:%M:%S")
            if updated.get("accepted_at"):
                updated["accepted_at"] = updated["accepted_at"].strftime("%Y-%m-%d %H:%M:%S")
            if updated.get("completed_at"):
                updated["completed_at"] = updated["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            updated["requested_quantity"] = float(updated["requested_quantity"])
        return updated


def get_organization_requests(organization_id: int) -> List[Dict[str, Any]]:
    """Private requests for an individual organization. Strictly isolated."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, p.available_until, p.notes as post_notes
            FROM donation_requests r
            LEFT JOIN donation_posts p ON r.post_id = p.id
            WHERE r.organization_id = %s
            ORDER BY r.id DESC
        """, (organization_id,))
        rows = cursor.fetchall()
        for r in rows:
            if r.get("requested_at"):
                r["requested_at"] = r["requested_at"].strftime("%Y-%m-%d %H:%M:%S")
            if r.get("accepted_at"):
                r["accepted_at"] = r["accepted_at"].strftime("%Y-%m-%d %H:%M:%S")
            if r.get("completed_at"):
                r["completed_at"] = r["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            r["requested_quantity"] = float(r["requested_quantity"])
        return rows


def get_supplier_requests(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Supplier view of incoming requests, scheduled pickups, and donation history."""
    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT r.*, p.available_until, p.published_quantity
            FROM donation_requests r
            LEFT JOIN donation_posts p ON r.post_id = p.id
            WHERE 1=1
        """
        params = []
        if status_filter and status_filter.upper() != "ALL":
            s = status_filter.upper().strip()
            if s == "INCOMING":
                query += " AND r.status = 'PENDING'"
            elif s == "SCHEDULED":
                query += " AND r.status IN ('ACCEPTED', 'SCHEDULED')"
            elif s == "HISTORY":
                query += " AND r.status IN ('COLLECTED', 'COMPLETED', 'REJECTED', 'CANCELLED')"
            else:
                query += " AND r.status = %s"
                params.append(s)

        query += " ORDER BY r.id DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        for r in rows:
            if r.get("requested_at"):
                r["requested_at"] = r["requested_at"].strftime("%Y-%m-%d %H:%M:%S")
            if r.get("accepted_at"):
                r["accepted_at"] = r["accepted_at"].strftime("%Y-%m-%d %H:%M:%S")
            if r.get("completed_at"):
                r["completed_at"] = r["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            r["requested_quantity"] = float(r["requested_quantity"])
            if r.get("published_quantity"):
                r["published_quantity"] = float(r["published_quantity"])
        return rows


def get_notifications_for_user(role: str, user_id: Optional[int] = None, ngo_id: Optional[int] = None) -> Dict[str, Any]:
    """Retrieve notifications filtered by role and organization."""
    with get_db() as conn:
        cursor = conn.cursor()
        clean_role = role.lower() if role else ""
        if "kitchen" in clean_role or "supplier" in clean_role or "admin" in clean_role:
            cursor.execute("""
                SELECT * FROM notifications 
                WHERE recipient_role IN ('Supplier', 'ALL_STAFF') OR recipient_user_id = %s
                ORDER BY id DESC LIMIT 50
            """, (user_id,))
        elif "staff" in clean_role:
            cursor.execute("""
                SELECT * FROM notifications 
                WHERE recipient_role IN ('Staff', 'ALL_STAFF') OR recipient_user_id = %s
                ORDER BY id DESC LIMIT 50
            """, (user_id,))
        else: # NGO
            cursor.execute("""
                SELECT * FROM notifications 
                WHERE (recipient_ngo_id = %s) OR (recipient_role = 'NGO' AND recipient_ngo_id IS NULL)
                ORDER BY id DESC LIMIT 50
            """, (ngo_id,))

        rows = cursor.fetchall()
        unread_count = sum(1 for n in rows if not n.get("is_read"))
        for n in rows:
            if n.get("created_at"):
                n["created_at"] = n["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        return {
            "unread_count": unread_count,
            "notifications": rows
        }


def mark_notification_read(notification_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read = TRUE WHERE id = %s", (notification_id,))
        conn.commit()
        return cursor.rowcount > 0


def mark_all_notifications_read(role: Optional[str] = None, user_id: Optional[int] = None, ngo_id: Optional[int] = None) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        clean_role = role.lower() if role else ""
        if "kitchen" in clean_role or "supplier" in clean_role or "admin" in clean_role:
            cursor.execute("UPDATE notifications SET is_read = TRUE WHERE recipient_role IN ('Supplier', 'ALL_STAFF') OR recipient_user_id = %s", (user_id,))
        elif "staff" in clean_role:
            cursor.execute("UPDATE notifications SET is_read = TRUE WHERE recipient_role IN ('Staff', 'ALL_STAFF') OR recipient_user_id = %s", (user_id,))
        else:
            cursor.execute("UPDATE notifications SET is_read = TRUE WHERE (recipient_ngo_id = %s) OR (recipient_role = 'NGO' AND recipient_ngo_id IS NULL)", (ngo_id,))
        conn.commit()
        return cursor.rowcount


# ==========================================
# DEMAND FORECAST LOGGING & RETRIEVAL
# ==========================================
def log_demand_forecast(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        top_items_json = json.dumps(data.get("top_items", []))
        cursor.execute("""
            INSERT INTO demand_forecasts (meal_type, attendance, predicted_demand, recommended_prep, buffer, top_items_json, weather, demand_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get("meal_type", "breakfast"),
            int(data.get("attendance", 100)),
            int(data.get("predicted_demand", 0)),
            int(data.get("recommended_prep", 0)),
            int(data.get("safety_buffer", data.get("buffer", 0))),
            top_items_json,
            data.get("weather", "Clear / Sunny"),
            data.get("demand_status", "Optimal")
        ))
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM demand_forecasts WHERE id = %s", (new_id,))
        res = cursor.fetchone()
        if res and isinstance(res.get("top_items_json"), str):
            try:
                res["top_items"] = json.loads(res["top_items_json"])
            except Exception:
                res["top_items"] = []
        return res


def get_latest_demand_forecast() -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM demand_forecasts ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row and isinstance(row.get("top_items_json"), str):
            try:
                row["top_items"] = json.loads(row["top_items_json"])
            except Exception:
                row["top_items"] = []
        return row


# ==========================================
# ANNOUNCEMENTS CRUD
# ==========================================
def get_all_announcements() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM announcements ORDER BY id DESC")
        rows = cursor.fetchall()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        return rows


def add_announcement(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO announcements (title, message, recipient, priority, sender, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data.get("title", "Announcement"),
            data.get("message", ""),
            data.get("recipient", "All Staff"),
            data.get("priority", "Normal"),
            data.get("sender", "Kitchen Manager"),
            data.get("status", "Sent")
        ))
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM announcements WHERE id = %s", (new_id,))
        return cursor.fetchone()


# ==========================================
# DASHBOARD KPI METRICS & ANALYTICS (MYSQL)
# ==========================================
def get_dashboard_kpis() -> Dict[str, Any]:
    """Calculate live operational KPIs directly from MySQL database."""
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Latest predicted demand from demand_forecasts
        cursor.execute("""
            SELECT meal_type, attendance, predicted_demand, recommended_prep, buffer, weather, demand_status, created_at 
            FROM demand_forecasts 
            ORDER BY id DESC LIMIT 1
        """)
        latest_pred = cursor.fetchone()
        today_demand = int(latest_pred["predicted_demand"]) if latest_pred else 0
        recommended_prep = int(latest_pred["recommended_prep"]) if latest_pred else 0
        attendance = int(latest_pred["attendance"]) if latest_pred else 0
        weather = latest_pred["weather"] if latest_pred else "Clear / Sunny"
        demand_status = latest_pred["demand_status"] if latest_pred else "Awaiting Data"
        prediction_time = latest_pred["created_at"].strftime("%Y-%m-%d %H:%M:%S") if (latest_pred and latest_pred.get("created_at")) else None

        # 2. Inventory metrics from inventory table (strictly active un-depleted stock)
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0 THEN 1 ELSE 0 END) as available_items,
                SUM(CASE WHEN (UPPER(status) = 'LOW STOCK' OR quantity <= 10) AND UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0 THEN 1 ELSE 0 END) as low_stock_items,
                SUM(CASE WHEN expiry_days <= 2 AND UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0 THEN 1 ELSE 0 END) as near_expiry_items,
                SUM(CASE WHEN UPPER(status) IN ('DONATED', 'DEPLETED') OR quantity <= 0 THEN 1 ELSE 0 END) as donated_items,
                COALESCE(SUM(CASE WHEN UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0 THEN quantity ELSE 0 END), 0) as available_qty,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('DONATED', 'DEPLETED') OR quantity <= 0 THEN quantity ELSE 0 END), 0) as donated_qty
            FROM inventory
        """)
        inv = cursor.fetchone()
        available_items = int(inv["available_items"] or 0)
        total_items = available_items  # Requirement 7: Total inventory is calculated from actual active inventory
        low_stock_items = int(inv["low_stock_items"] or 0)
        near_expiry_count = int(inv["near_expiry_items"] or 0)
        donated_items = int(inv["donated_items"] or 0)
        available_qty = float(inv["available_qty"] or 0.0)
        total_qty = available_qty
        donated_qty = float(inv["donated_qty"] or 0.0)

        # 3. Surplus food calculation from actual inventory data
        surplus_items = get_surplus_food_items()
        surplus_count = len(surplus_items)
        surplus_qty_sum = sum(s["surplus_quantity"] for s in surplus_items)

        # 4. Donations metrics from donations table
        cursor.execute("""
            SELECT 
                COUNT(*) as total_donations,
                SUM(CASE WHEN UPPER(status) = 'PENDING' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'APPROVED') THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED') THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN UPPER(status) = 'REJECTED' THEN 1 ELSE 0 END) as rejected,
                COALESCE(SUM(quantity), 0) as total_donation_qty,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED') THEN quantity ELSE 0 END), 0) as completed_donation_qty
            FROM donations
        """)
        don = cursor.fetchone()
        total_donations = int(don["total_donations"] or 0)
        pending_donations = int(don["pending"] or 0)
        accepted_donations = int(don["accepted"] or 0)
        completed_donations = int(don["completed"] or 0)
        rejected_donations = int(don["rejected"] or 0)
        total_donation_qty = float(don["total_donation_qty"] or 0.0)
        completed_donation_qty = float(don["completed_donation_qty"] or 0.0)
        active_donations = pending_donations + accepted_donations

        # 5. Partners counts
        cursor.execute("SELECT COUNT(*) as total_ngos FROM ngos")
        total_ngos = int(cursor.fetchone()["total_ngos"] or 0)
        cursor.execute("SELECT COUNT(*) as total_suppliers FROM suppliers")
        total_suppliers = int(cursor.fetchone()["total_suppliers"] or 0)

        # 6. Calculated operational rates (with zero division protection)
        donation_completion_rate = round((completed_donations / total_donations) * 100, 1) if total_donations > 0 else 0.0
        donation_acceptance_rate = round(((accepted_donations + completed_donations) / total_donations) * 100, 1) if total_donations > 0 else 0.0
        low_stock_pct = round((low_stock_items / total_items) * 100, 1) if total_items > 0 else 0.0
        inventory_availability_pct = round((available_items / total_items) * 100, 1) if total_items > 0 else 0.0

        kitchen_prep_eff = min(100.0, round((today_demand / recommended_prep) * 100, 1)) if recommended_prep > 0 else 0.0
        overprod_avoided = max(0, recommended_prep - today_demand) if latest_pred else 0
        spoilage_prevention_rate = min(100.0, round(((donated_qty + available_qty) / max(1.0, total_qty)) * 100, 1)) if total_qty > 0 else 0.0
        charity_food_val = round((completed_donation_qty + donated_qty) * 50.0, 2)
        inventory_at_risk = near_expiry_count + low_stock_items
        food_saved_kg = completed_donation_qty
        active_recovery_requests = active_donations

        return {
            # Demand
            "today_predicted_demand": today_demand,
            "recommended_preparation": recommended_prep,
            "recommended_prep": recommended_prep,
            "recommended_kitchen_prep": recommended_prep,
            "expected_attendance": attendance,
            "weather": weather,
            "demand_status": demand_status,
            "prediction_date": prediction_time,
            "has_prediction": latest_pred is not None,

            # Inventory
            "total_inventory_items": total_items,
            "available_inventory_items": available_items,
            "low_stock_items": low_stock_items,
            "near_expiry_items": near_expiry_count,
            "inventory_at_risk": inventory_at_risk,
            "donated_inventory_items": donated_items,
            "total_inventory_quantity": round(total_qty, 1),
            "available_inventory_quantity": round(available_qty, 1),
            "donated_inventory_quantity": round(donated_qty, 1),
            "inventory_availability_pct": inventory_availability_pct,
            "low_stock_pct": low_stock_pct,

            # Surplus
            "surplus_food_items": surplus_count,
            "total_surplus_quantity": round(surplus_qty_sum, 1),

            # Donations & Recovery
            "total_donations": total_donations,
            "pending_donations": pending_donations,
            "accepted_donations": accepted_donations,
            "completed_donations": completed_donations,
            "rejected_donations": rejected_donations,
            "active_donation_requests": active_donations,
            "active_recovery_requests": active_recovery_requests,
            "food_saved_kg": round(food_saved_kg, 1),
            "food_recovered_kg": round(food_saved_kg, 1),
            "total_donation_quantity": round(total_donation_qty, 1),
            "completed_donation_quantity": round(completed_donation_qty, 1),
            "donation_completion_rate": donation_completion_rate,
            "donation_acceptance_rate": donation_acceptance_rate,

            # Operational metrics
            "kitchen_prep_efficiency": kitchen_prep_eff,
            "overproduction_avoided": overprod_avoided,
            "spoilage_prevention_rate": spoilage_prevention_rate,
            "charitable_food_value_inr": charity_food_val,
            "active_partner_kitchens": total_suppliers,
            "active_partner_ngos": total_ngos,

            # Nested structures for modern frontend consumption
            "demand": {
                "predicted_demand": latest_pred.get("predicted_demand", 0) if latest_pred else 0,
                "recommended_prep": latest_pred.get("recommended_prep", 0) if latest_pred else 0,
                "attendance": latest_pred.get("attendance", 0) if latest_pred else 0,
                "weather": latest_pred.get("weather", "Clear") if latest_pred else "Clear",
                "demand_status": latest_pred.get("demand_status", "Optimal") if latest_pred else "Optimal",
                "time_slot": latest_pred.get("meal_type", "lunch") if latest_pred else "lunch",
            },
            "inventory": {
                "total_items": total_items,
                "available_items": available_items,
                "low_stock_items": low_stock_items,
                "near_expiry_items": near_expiry_count,
                "inventory_at_risk": inventory_at_risk,
                "donated_items": donated_items,
                "surplus_items": surplus_count,
                "total_quantity": round(total_qty, 1),
                "available_quantity": round(available_qty, 1),
                "donated_quantity": round(donated_qty, 1),
                "availability_pct": inventory_availability_pct,
                "low_stock_pct": low_stock_pct,
            },
            "surplus": {
                "count": surplus_count,
                "surplus_items": surplus_count,
                "quantity": round(surplus_qty_sum, 1)
            },
            "donations": {
                "total": total_donations,
                "pending": pending_donations,
                "accepted": accepted_donations,
                "completed": completed_donations,
                "rejected": rejected_donations,
                "active_dispatches": active_donations,
                "active_requests": active_recovery_requests,
                "active_recovery_requests": active_recovery_requests,
                "food_saved_kg": round(food_saved_kg, 1),
                "food_recovered_kg": round(food_saved_kg, 1),
                "total_quantity": round(total_donation_qty, 1),
                "completed_quantity": round(completed_donation_qty, 1),
                "completion_rate_pct": donation_completion_rate,
                "acceptance_rate_pct": donation_acceptance_rate,
            },
            "operations": {
                "prep_efficiency_pct": kitchen_prep_eff,
                "overproduction_avoided": overprod_avoided,
                "spoilage_prevention_rate_pct": spoilage_prevention_rate,
                "charitable_food_val_inr": charity_food_val,
                "partner_kitchens_count": total_suppliers,
                "partner_ngos_count": total_ngos
            }
        }


def get_ngo_kpis(ngo_id: int) -> Dict[str, Any]:
    """Calculate dedicated operational KPIs strictly for the authenticated NGO Relief Partner from MySQL."""
    if not ngo_id:
        raise ValueError("Organization ID is required to calculate isolated NGO KPIs.")

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Fetch organization metadata directly from existing ngos table (with fallback to user organization)
        cursor.execute("SELECT id, name, manager, phone, email, address, capacity_persons FROM ngos WHERE id = %s", (ngo_id,))
        ngo_row = cursor.fetchone()
        if ngo_row and ngo_row.get("name"):
            org_name = ngo_row["name"]
        else:
            cursor.execute("SELECT organization FROM users WHERE ngo_id = %s LIMIT 1", (ngo_id,))
            u_row = cursor.fetchone()
            org_name = (u_row["organization"] if u_row and u_row.get("organization") else None) or f"Relief Partner #{ngo_id}"

        # 2. Compute live operational metrics from donation_requests (primary redistribution requests table)
        cursor.execute("""
            SELECT 
                COUNT(*) as total_requests,
                SUM(CASE WHEN UPPER(status) = 'PENDING' THEN 1 ELSE 0 END) as incoming_pending,
                SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'SCHEDULED') THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'COLLECTED') THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN UPPER(status) IN ('REJECTED', 'CANCELLED') THEN 1 ELSE 0 END) as rejected,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'COLLECTED') THEN requested_quantity ELSE 0 END), 0) as food_received_kg,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'SCHEDULED') THEN requested_quantity ELSE 0 END), 0) as accepted_kg
            FROM donation_requests
            WHERE organization_id = %s
        """, (ngo_id,))
        req_row = cursor.fetchone()

        total_requests = int(req_row["total_requests"] or 0)
        incoming_pending = int(req_row["incoming_pending"] or 0)
        accepted = int(req_row["accepted"] or 0)
        completed = int(req_row["completed"] or 0)
        rejected = int(req_row["rejected"] or 0)
        food_received_kg = round(float(req_row["food_received_kg"] or 0.0), 1)
        accepted_kg = round(float(req_row["accepted_kg"] or 0.0), 1)

        # Fallback check on donations table if no donation_requests exist yet for this legacy NGO
        if total_requests == 0:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN UPPER(status) = 'PENDING' THEN 1 ELSE 0 END) as incoming_pending,
                    SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'APPROVED', 'SCHEDULED') THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED', 'COLLECTED') THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN UPPER(status) IN ('REJECTED', 'CANCELLED') THEN 1 ELSE 0 END) as rejected,
                    COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED', 'COLLECTED') THEN quantity ELSE 0 END), 0) as food_received_kg,
                    COALESCE(SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'APPROVED', 'SCHEDULED') THEN quantity ELSE 0 END), 0) as accepted_kg
                FROM donations
                WHERE ngo_id = %s
            """, (ngo_id,))
            legacy_don = cursor.fetchone()
            if legacy_don and int(legacy_don["total_requests"] or 0) > 0:
                total_requests = int(legacy_don["total_requests"] or 0)
                incoming_pending = int(legacy_don["incoming_pending"] or 0)
                accepted = int(legacy_don["accepted"] or 0)
                completed = int(legacy_don["completed"] or 0)
                rejected = int(legacy_don["rejected"] or 0)
                food_received_kg = round(float(legacy_don["food_received_kg"] or 0.0), 1)
                accepted_kg = round(float(legacy_don["accepted_kg"] or 0.0), 1)

        food_distributed_kg = food_received_kg
        active_requests = incoming_pending + accepted
        acceptance_rate = round(((accepted + completed) / total_requests) * 100, 1) if total_requests > 0 else 0.0
        meals_distributed = int(round(food_received_kg * 2.5))
        people_nourished = int(round(meals_distributed * 0.7))
        waste_avoided_kg = food_received_kg
        co2_avoided_kg = round(waste_avoided_kg * 2.5, 1)

        surplus_items = get_surplus_food_items()
        available_surplus_batches = len(surplus_items)
        available_surplus_qty = sum(s["surplus_quantity"] for s in surplus_items)

        cursor.execute("SELECT COUNT(*) as cnt FROM suppliers")
        connected_canteens = int(cursor.fetchone()["cnt"] or 0)

        return {
            "organization_id": ngo_id,
            "organization_name": org_name,
            "ngo_id": ngo_id,
            "ngo_name": org_name,
            "total_requests": total_requests,
            "pending_requests": incoming_pending,
            "incoming_pending": incoming_pending,
            "accepted_requests": accepted,
            "completed_requests": completed,
            "completed_donations": completed,
            "rejected_requests": rejected,
            "rejected_donations": rejected,
            "active_requests": active_requests,
            "active_recovery_requests": active_requests,
            "food_received_kg": food_received_kg,
            "food_distributed_kg": food_distributed_kg,
            "accepted_kg": accepted_kg,
            "meals_distributed": meals_distributed,
            "meals_provided": meals_distributed,
            "people_nourished": people_nourished,
            "waste_avoided_kg": waste_avoided_kg,
            "co2_avoided_kg": co2_avoided_kg,
            "acceptance_rate_pct": acceptance_rate,
            "available_surplus_batches": available_surplus_batches,
            "available_surplus_qty": round(available_surplus_qty, 1),
            "connected_canteens": connected_canteens,
            "donations": {
                "organization_id": ngo_id,
                "organization_name": org_name,
                "total_requests": total_requests,
                "incoming_requests": incoming_pending,
                "incoming_pending": incoming_pending,
                "pending_requests": incoming_pending,
                "accepted_requests": accepted,
                "completed_donations": completed,
                "completed_requests": completed,
                "rejected_donations": rejected,
                "rejected_requests": rejected,
                "active_recovery_requests": active_requests,
                "active_requests": active_requests,
                "food_received_kg": food_received_kg,
                "food_distributed_kg": food_distributed_kg,
                "accepted_kg": accepted_kg,
                "available_surplus_batches": available_surplus_batches,
                "available_surplus_qty": round(available_surplus_qty, 1),
                "connected_canteens": connected_canteens
            },
            "impact": {
                "meals_provided": meals_distributed,
                "people_nourished": people_nourished,
                "waste_diverted_kg": waste_avoided_kg,
                "co2_avoided_kg": co2_avoided_kg,
                "acceptance_rate_pct": acceptance_rate
            }
        }


def get_ngo_analytics(ngo_id: int) -> Dict[str, Any]:
    """Retrieve historical intake and distribution statistics for NGO views strictly isolated to the organization."""
    if not ngo_id:
        raise ValueError("Organization ID is required for isolated NGO analytics.")

    with get_db() as conn:
        cursor = conn.cursor()
        kpis = get_ngo_kpis(ngo_id=ngo_id)

        # Check donation_requests first for daily trend
        cursor.execute("""
            SELECT DATE(requested_at) as log_date,
                   COALESCE(SUM(requested_quantity), 0) as total_qty,
                   COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'COLLECTED') THEN requested_quantity ELSE 0 END), 0) as received_qty
            FROM donation_requests
            WHERE organization_id = %s
            GROUP BY DATE(requested_at)
            ORDER BY log_date ASC LIMIT 7
        """, (ngo_id,))
        rows = cursor.fetchall()

        if not rows:
            cursor.execute("""
                SELECT DATE(created_at) as log_date,
                       COALESCE(SUM(quantity), 0) as total_qty,
                       COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED') THEN quantity ELSE 0 END), 0) as received_qty
                FROM donations
                WHERE ngo_id = %s
                GROUP BY DATE(created_at)
                ORDER BY log_date ASC LIMIT 7
            """, (ngo_id,))
            rows = cursor.fetchall()

        labels = [r["log_date"].strftime("%b %d") if r.get("log_date") else "Day" for r in rows]
        received = [float(r["received_qty"]) for r in rows]
        total = [float(r["total_qty"]) for r in rows]

        # Partner canteen contributions strictly for this NGO
        cursor.execute("""
            SELECT COALESCE(p.supplier_name, 'Srinivas Institute Canteen') as supplier_name,
                   COUNT(*) as dispatch_count,
                   COALESCE(SUM(r.requested_quantity), 0) as total_qty
            FROM donation_requests r
            LEFT JOIN donation_posts p ON r.post_id = p.id
            WHERE r.organization_id = %s AND UPPER(r.status) IN ('COMPLETED', 'COLLECTED', 'ACCEPTED', 'SCHEDULED')
            GROUP BY COALESCE(p.supplier_name, 'Srinivas Institute Canteen')
            ORDER BY total_qty DESC
        """, (ngo_id,))
        partners = cursor.fetchall()

        if not partners:
            cursor.execute("""
                SELECT supplier_name, 
                       COUNT(*) as dispatch_count, 
                       COALESCE(SUM(quantity), 0) as total_qty
                FROM donations
                WHERE ngo_id = %s
                GROUP BY supplier_name
                ORDER BY total_qty DESC
            """, (ngo_id,))
            partners = cursor.fetchall()

        total_received = float(kpis["food_received_kg"])
        total_all = sum(float(p["total_qty"]) for p in partners) if partners else 0.0

        donor_contributions = [
            {
                "canteen_name": p["supplier_name"],
                "donations_count": int(p["dispatch_count"]),
                "total_kg": round(float(p["total_qty"]), 1),
                "percentage": round((float(p["total_qty"]) / total_all * 100), 1) if total_all > 0 else 0.0
            } for p in partners
        ]

        return {
            "kpis": kpis,
            "total_intake_kg": total_received,
            "acceptance_rate_pct": kpis["impact"]["acceptance_rate_pct"],
            "meals_provided": kpis["impact"]["meals_provided"],
            "active_partner_canteens": len(donor_contributions) if donor_contributions else (1 if total_received > 0 else 0),
            "trend": {
                "labels": labels if labels else ["No History"],
                "received_qty": received if received else [0],
                "requested_qty": total if total else [0]
            },
            "donor_contributions": donor_contributions,
            "partner_contributions": [
                {
                    "canteen": p["supplier_name"],
                    "count": int(p["dispatch_count"]),
                    "quantity": float(p["total_qty"])
                } for p in partners
            ]
        }


def get_demand_trend(limit: int = 7) -> Dict[str, Any]:
    """Retrieve historical demand prediction records from MySQL demand_forecasts table."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, meal_type, attendance, predicted_demand, recommended_prep, weather, demand_status, created_at
            FROM demand_forecasts
            ORDER BY id DESC LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        if not rows:
            return {
                "has_data": False,
                "labels": [],
                "predicted_demand": [],
                "demand": [],
                "recommended_prep": [],
                "records": []
            }

        # Chronological order
        rows = list(reversed(rows))
        labels = [
            f"{r['created_at'].strftime('%a %d') if r.get('created_at') else 'Run'} ({r['meal_type'].title()[:3]})"
            for r in rows
        ]
        predicted = [r["predicted_demand"] for r in rows]
        prep = [r["recommended_prep"] for r in rows]
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")

        return {
            "has_data": True,
            "labels": labels,
            "predicted_demand": predicted,
            "demand": predicted,
            "recommended_prep": prep,
            "records": rows
        }


def get_donation_trend(limit: int = 7) -> Dict[str, Any]:
    """Retrieve historical donation dispatches grouped by date from MySQL."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DATE(created_at) as don_date,
                   COUNT(*) as dispatch_count,
                   COALESCE(SUM(quantity), 0) as total_quantity,
                   COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED') THEN quantity ELSE 0 END), 0) as completed_quantity,
                   COALESCE(SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'APPROVED') THEN quantity ELSE 0 END), 0) as accepted_quantity
            FROM donations
            GROUP BY DATE(created_at)
            ORDER BY don_date ASC LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        if not rows:
            return {
                "has_data": False,
                "labels": [],
                "total_quantity": [],
                "received_quantity": [],
                "completed_quantity": [],
                "distributed_quantity": [],
                "records": []
            }

        labels = [r["don_date"].strftime("%b %d") if r.get("don_date") else "Day" for r in rows]
        total_q = [float(r["total_quantity"]) for r in rows]
        completed_q = [float(r["completed_quantity"]) for r in rows]

        return {
            "has_data": True,
            "labels": labels,
            "total_quantity": total_q,
            "received_quantity": total_q,
            "completed_quantity": completed_q,
            "distributed_quantity": completed_q,
            "records": rows
        }


def get_inventory_summary() -> Dict[str, Any]:
    """Calculate category distribution from MySQL inventory and community distribution from NGOs."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Category distribution (strictly active stock)
        cursor.execute("""
            SELECT category, COUNT(*) as item_count, COALESCE(SUM(quantity), 0) as total_quantity
            FROM inventory
            WHERE UPPER(status) NOT IN ('DONATED', 'DEPLETED', 'DISCARDED') AND quantity > 0
            GROUP BY category
            ORDER BY total_quantity DESC
        """)
        cat_rows = cursor.fetchall()

        total_cat_qty = sum(float(r["total_quantity"]) for r in cat_rows)
        categories = []
        for r in cat_rows:
            qty = float(r["total_quantity"])
            pct = round((qty / total_cat_qty) * 100, 1) if total_cat_qty > 0 else 0.0
            categories.append({
                "category": r["category"],
                "item_count": int(r["item_count"]),
                "quantity": qty,
                "percentage": pct
            })

        # NGO community allocation
        cursor.execute("""
            SELECT ngo_type, COUNT(*) as count
            FROM ngos
            GROUP BY ngo_type
            ORDER BY count DESC
        """)
        ngo_rows = cursor.fetchall()
        total_ngos = sum(r["count"] for r in ngo_rows)
        beneficiaries = []
        for r in ngo_rows:
            pct = round((r["count"] / total_ngos) * 100, 1) if total_ngos > 0 else 0.0
            beneficiaries.append({
                "type": r["ngo_type"],
                "count": r["count"],
                "percentage": pct
            })

        return {
            "categories": categories,
            "total_category_quantity": round(total_cat_qty, 1),
            "beneficiary_types": beneficiaries
        }


def get_analytics_summary() -> Dict[str, Any]:
    """Calculate environmental and human impact metrics dynamically from MySQL."""
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Total food saved: completed donations + donated inventory items
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED') THEN quantity ELSE 0 END), 0) as completed_donations_qty,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('ACCEPTED', 'APPROVED') THEN quantity ELSE 0 END), 0) as accepted_donations_qty,
                COUNT(*) as total_donations_count,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('COMPLETED', 'DISTRIBUTED') THEN 1 ELSE 0 END), 0) as completed_donations_count
            FROM donations
        """)
        don_row = cursor.fetchone()
        completed_donations_qty = float(don_row["completed_donations_qty"] or 0.0)
        accepted_donations_qty = float(don_row["accepted_donations_qty"] or 0.0)
        total_donations_count = int(don_row["total_donations_count"] or 0)
        completed_donations_count = int(don_row["completed_donations_count"] or 0)

        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(status) = 'DONATED' THEN quantity ELSE 0 END), 0) as donated_inv_qty,
                COALESCE(SUM(quantity), 0) as total_inv_qty
            FROM inventory
        """)
        inv_row = cursor.fetchone()
        donated_inv_qty = float(inv_row["donated_inv_qty"] or 0.0)
        total_inv_qty = float(inv_row["total_inv_qty"] or 0.0)

        # Operational food saved: completed donations quantity (or donated inventory)
        food_saved_kg = round(max(completed_donations_qty, donated_inv_qty), 1)
        co2_reduced_kg = round(food_saved_kg * 2.5, 1)
        meals_provided = int(round(food_saved_kg * 2.5))
        people_benefited = int(round(meals_provided * 0.7))
        families_helped = int(round(food_saved_kg / 20.0)) if food_saved_kg >= 20 else (1 if food_saved_kg > 0 else 0)

        # Waste reduction rate
        waste_reduction_rate = round((food_saved_kg / total_inv_qty) * 100, 1) if total_inv_qty > 0 else 0.0
        # Redistribution efficiency
        redistribution_efficiency = round((completed_donations_count / total_donations_count) * 100, 1) if total_donations_count > 0 else 0.0

        return {
            "total_food_saved_kg": food_saved_kg,
            "co2_reduced_kg": co2_reduced_kg,
            "meals_provided": meals_provided,
            "people_benefited": people_benefited,
            "families_helped": families_helped,
            "waste_reduction_rate": waste_reduction_rate,
            "redistribution_efficiency": redistribution_efficiency,
            "total_donations_count": total_donations_count,
            "completed_donations_count": completed_donations_count
        }
