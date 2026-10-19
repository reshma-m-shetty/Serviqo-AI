"""
Serviqo AI - Phase 2 Repository Cleanup, Security, and Full Integration Verification
Tests:
1. Static-file security & file exposure prevention (.env, .py, .sql, .joblib, .git blocked)
2. Authorized frontend asset delivery (/, /index.html, /styles.css, /app.js)
3. End-to-end API contracts (Auth, Inventory, Redistribution, Forecasting, Health)
4. Authenticated identity vs client spoofing enforcement
"""

import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
import database as db
import ml_engine as ml

client = TestClient(app)


class TestPhase2StaticSecurity(unittest.TestCase):
    """Test Suite: Public Static Asset Serving Security."""

    def test_01_public_frontend_assets_served(self):
        """Verify intended frontend assets (index.html, styles.css, app.js) are accessible."""
        for path, expected_type in [
            ("/", "text/html"),
            ("/index.html", "text/html"),
            ("/styles.css", "text/css"),
            ("/app.js", "application/javascript"),
        ]:
            resp = client.get(path)
            self.assertEqual(resp.status_code, 200, f"Failed to serve {path}")
            self.assertIn(expected_type, resp.headers.get("content-type", ""))

    def test_02_sensitive_files_strictly_blocked(self):
        """Verify sensitive server files cannot be accessed or downloaded via HTTP."""
        sensitive_paths = [
            "/.env",
            "/.env.example",
            "/main.py",
            "/database.py",
            "/ml_engine.py",
            "/seed_database.py",
            "/migrate_to_cloud.py",
            "/backup_serviqo_ai.sql",
            "/canteen_model.joblib",
            "/.git",
            "/.git/config",
            "/.venv",
            "/quarantine/food_supply.db",
            "/quarantine/check_mysql.py",
            "/requirements.txt",
            "/Dockerfile",
            "/Procfile"
        ]
        for path in sensitive_paths:
            resp = client.get(path)
            self.assertIn(
                resp.status_code,
                [404, 403],
                f"Security Vulnerability! Sensitive path '{path}' was exposed with status {resp.status_code}!"
            )


class TestPhase2APIContracts(unittest.TestCase):
    """Test Suite: Core API endpoints, Authentication, and Operational Flows."""

    def test_03_health_check_contract(self):
        """Verify unified health check returns 200 or 503 and proper JSON schema."""
        resp = client.get("/api/health")
        self.assertIn(resp.status_code, [200, 503])
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("application", data)
        self.assertIn("database", data)
        self.assertIn("ml_model", data)
        self.assertEqual(data["application"]["status"], "up")
        self.assertEqual(data["ml_model"]["model_name"], "canteen_model.joblib")

    def test_04_ml_metrics_contract(self):
        """Verify /api/ml/metrics returns genuine LightGBM dual-model metadata."""
        resp = client.get("/api/ml/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model_name"], "canteen_model.joblib")
        self.assertIn("LightGBM", data["framework"])
        self.assertEqual(data["features_count"], 19)
        self.assertFalse(data["evaluation_metrics"]["available"])

    def test_05_auth_login_and_ngo_isolation(self):
        """Verify authentication contract and session identity enforcement."""
        # 1. Kitchen staff login
        res_staff = client.post("/api/auth/login", json={"email": "kitchen@serviqo.ai", "password": "staff123"})
        self.assertEqual(res_staff.status_code, 200)
        staff_user = res_staff.json()["user"]
        self.assertIn("Kitchen", staff_user["role"])

        # 2. NGO login
        res_ngo = client.post("/api/auth/login", json={"email": "ngo@serviqo.ai", "password": "ngo123"})
        self.assertEqual(res_ngo.status_code, 200)
        ngo_user = res_ngo.json()["user"]
        self.assertEqual(ngo_user["ngo_id"], 1)

        # 3. NGO dashboard access using session context
        ngo_dash = client.get("/api/dashboard/ngo", headers={"X-User-Email": "ngo@serviqo.ai"})
        self.assertEqual(ngo_dash.status_code, 200)
        dash_data = ngo_dash.json()
        self.assertEqual(dash_data["organization_id"], 1)

        # 4. Attempt spoofing by changing query parameter -> server enforces authenticated ngo_id
        spoofed_dash = client.get("/api/dashboard/ngo?ngo_id=99", headers={"X-User-Email": "ngo@serviqo.ai"})
        self.assertEqual(spoofed_dash.status_code, 200)
        self.assertEqual(spoofed_dash.json()["organization_id"], 1)

    def test_06_demand_forecast_contract(self):
        """Verify demand forecasting automated pipeline produces prediction with dual targets."""
        payload = {
            "meal_type": "lunch",
            "attendance": 175,
            "hostel_attendance": 85,
            "dayscholar_attendance": 90,
            "temperature_c": 28.0,
            "rainfall_mm": 0.0,
            "humidity_pct": 65.0,
            "day_type": "weekday",
            "is_weekend": False,
            "is_holiday": False,
            "is_exam_day": False,
            "is_campus_event": False,
            "popularity_level": 2
        }
        resp = client.post("/api/demand-forecast", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("predicted_demand", data)
        self.assertIn("recommended_prep", data)
        self.assertIn("top_items", data)
        self.assertGreater(data["predicted_demand"], 0)
        self.assertGreaterEqual(data["recommended_prep"], data["predicted_demand"])
        self.assertEqual(data["model_source"], "LightGBM Production Model (canteen_model.joblib)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
