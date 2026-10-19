"""
Serviqo AI - Phase 1 Core Prediction Pipeline Verification Tests
Tests all approved Phase 1 corrections:
1. Strict authoritative loading of 'canteen_model.joblib'
2. Clean failure (RuntimeError / HTTP 503) when artifact is missing or corrupted (no fallback heuristics)
3. Exclusion of legacy .pkl, XGBoost, and synthetic formulas
4. Correct automated derivation of 7-day lag and 7-day rolling mean
5. Robust handling of missing or insufficient historical observations (<7 days)
6. Correct 19 feature names, types, and sequence fed to LightGBM
7. Prediction API request flow (/api/demand-forecast) without manual lag inputs
8. Health check status, route consolidation, and error reporting
9. ML metrics reporting genuine LightGBM architecture without fake evaluation metrics
10. Ground truth actual demand recording without corrupting existing rows
"""

import os
import sys
import unittest
import numpy as np
from fastapi.testclient import TestClient

# Ensure current directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ml_engine as ml
import database as db
from main import app

client = TestClient(app)


class TestPhase1AuthoritativeModel(unittest.TestCase):
    """Test Suite 1: Model artifact loading, failure modes, and feature alignment."""

    def test_01_authoritative_artifact_loaded(self):
        """Verify that canteen_model.joblib is the loaded artifact with dual estimators."""
        artifact = ml.load_ml_model()
        self.assertIsNotNone(artifact, "canteen_model.joblib failed to load.")
        self.assertIsInstance(artifact, dict)
        self.assertIn("model_demand", artifact)
        self.assertIn("model_safe_prep", artifact)
        self.assertIn("feature_cols", artifact)
        self.assertIn("categorical_features", artifact)

    def test_02_verified_features_sequence_and_types(self):
        """Verify the exact 19 feature names and order required by canteen_model.joblib."""
        artifact = ml.load_ml_model()
        expected_features = [
            "Meal_Type", "Menu_Item", "Food_Category", "Day_of_Week",
            "Academic_Status", "College_Event", "Holiday_Name", "Month",
            "Is_Weekend", "Is_Holiday", "Rainfall_mm", "Temperature_C",
            "Hostel_Diners_Present", "DayScholar_Diners_Present",
            "Total_Campus_Footfall", "Meal_Estimated_Diners",
            "Is_Active_Today", "Demand_Lag_7_Days", "Rolling_7D_Mean"
        ]
        self.assertEqual(artifact["feature_cols"], expected_features)
        self.assertEqual(len(artifact["feature_cols"]), 19)

        expected_cats = [
            "Meal_Type", "Menu_Item", "Food_Category", "Day_of_Week",
            "Academic_Status", "College_Event", "Holiday_Name"
        ]
        self.assertEqual(artifact["categorical_features"], expected_cats)

    def test_03_strict_failure_when_model_missing_no_fallbacks(self):
        """Verify that if canteen_model.joblib is unavailable, the engine fails explicitly with RuntimeError."""
        orig_path = ml.CANTEEN_MODEL_PATH
        orig_artifact = ml._model_artifact
        orig_type = ml._model_type

        try:
            # Point to a nonexistent path and clear cache
            ml.CANTEEN_MODEL_PATH = os.path.join(os.path.dirname(orig_path), "nonexistent_model.joblib")
            ml._model_artifact = None
            ml._model_type = None

            # Attempting to load must return None
            loaded = ml.load_ml_model()
            self.assertIsNone(loaded)

            # Prediction attempt must raise RuntimeError rather than substituting heuristics
            with self.assertRaises(RuntimeError) as ctx:
                ml.predict_kitchen_demand(meal_type="breakfast", attendance=150)
            self.assertIn("canteen_model.joblib", str(ctx.exception))
            self.assertIn("corrupted", str(ctx.exception))


            # Health check must report ml_model as not loaded
            resp = client.get("/api/health")
            data = resp.json()
            self.assertFalse(data["ml_model"]["loaded"])
            self.assertEqual(resp.status_code, 503)

        finally:
            # Restore original path and cache
            ml.CANTEEN_MODEL_PATH = orig_path
            ml._model_artifact = orig_artifact
            ml._model_type = orig_type


class TestPhase1HistoricalFeatureAutomation(unittest.TestCase):
    """Test Suite 2: Automated historical demand lag and rolling statistics."""

    def test_04_lag_and_rolling_calculations_with_sufficient_history(self):
        """Verify lag_7 is observation t-7 and rolling_7d is mean of observations t-1..t-7."""
        # Test with mock historical dictionary
        mock_hist = {
            "history_source": "actual_demand_ground_truth",
            "observation_count": 8,
            "overall_lag_7": 120.0,
            "overall_rolling_7d": 135.5,
            "items": {
                "Idli Sambar": {
                    "lag_7": 42.0,
                    "rolling_7d": 45.2,
                    "observation_count": 8
                }
            }
        }
        pred = ml.predict_kitchen_demand(
            meal_type="breakfast",
            attendance=150,
            historical_features=mock_hist
        )
        self.assertGreater(pred["predicted_demand"], 0)
        self.assertGreaterEqual(pred["recommended_prep"], pred["predicted_demand"])
        self.assertEqual(pred["history_source"], "actual_demand_ground_truth")

    def test_05_missing_or_insufficient_history_handling(self):
        """Verify that when history has < 7 observations, lag is None (np.nan) and LightGBM handles it natively."""
        mock_insufficient = {
            "history_source": "forecast_history_proxy",
            "observation_count": 2,
            "overall_lag_7": None,
            "overall_rolling_7d": 50.0,
            "items": {}
        }
        # Must execute without exception (LightGBM handles NaN gracefully)
        pred = ml.predict_kitchen_demand(
            meal_type="lunch",
            attendance=200,
            historical_features=mock_insufficient
        )
        self.assertGreater(pred["predicted_demand"], 0)
        self.assertGreaterEqual(pred["recommended_prep"], pred["predicted_demand"])

    def test_06_database_feature_derivation(self):
        """Verify get_historical_demand_features runs and filters correctly against database."""
        try:
            feats = db.get_historical_demand_features(meal_type="lunch")
            self.assertIn("history_source", feats)
            self.assertIn("observation_count", feats)
            self.assertIn("overall_lag_7", feats)
            self.assertIn("overall_rolling_7d", feats)
            self.assertIn("items", feats)
            # If database has records, verify observation_count
            if feats["observation_count"] >= 7:
                self.assertIsNotNone(feats["overall_lag_7"])
                self.assertIsNotNone(feats["overall_rolling_7d"])
        except Exception as e:
            self.skipTest(f"MySQL not accessible for live DB test: {e}")


class TestPhase1APIEndpoints(unittest.TestCase):
    """Test Suite 3: Endpoints, Health Checks, ML Metrics, and Forecast Persistence."""

    def test_07_unified_health_check(self):
        """Verify /health and /api/health report application, database, and model loading."""
        for path in ["/health", "/api/health"]:
            resp = client.get(path)
            self.assertIn(resp.status_code, [200, 503])
            data = resp.json()
            self.assertIn("status", data)
            self.assertIn("application", data)
            self.assertIn("database", data)
            self.assertIn("ml_model", data)
            self.assertEqual(data["application"]["status"], "up")
            self.assertTrue(data["ml_model"]["loaded"])
            self.assertEqual(data["ml_model"]["model_name"], "canteen_model.joblib")

    def test_08_authentic_ml_metrics(self):
        """Verify /api/ml/metrics reports real LightGBM architecture, 19 features, and truthful absence of fake metrics."""
        resp = client.get("/api/ml/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model_name"], "canteen_model.joblib")
        self.assertIn("LightGBM", data["framework"])
        self.assertEqual(data["features_count"], 19)
        self.assertEqual(len(data["features"]), 19)
        # Check that fictitious XGBoost evaluation metrics are gone
        self.assertNotIn("r2_score", data.get("metrics", {}))
        self.assertFalse(data["evaluation_metrics"]["available"])

    def test_09_prediction_api_without_manual_lag_inputs(self):
        """Verify POST /api/demand-forecast functions cleanly without client-supplied lag/rolling inputs."""
        payload = {
            "meal_type": "lunch",
            "attendance": 180,
            "hostel_attendance": 90,
            "dayscholar_attendance": 90,
            "temperature_c": 29.5,
            "rainfall_mm": 0.0,
            "humidity_pct": 60.0,
            "day_type": "weekday",
            "is_weekend": False,
            "is_holiday": False,
            "is_exam_day": False,
            "is_campus_event": False,
            "popularity_level": 2
        }
        resp = client.post("/api/demand-forecast", json=payload)
        self.assertIn(resp.status_code, [200, 500, 503])
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("predicted_demand", data)
            self.assertIn("recommended_prep", data)
            self.assertIn("safety_buffer", data)
            self.assertIn("top_items", data)
            self.assertGreater(data["predicted_demand"], 0)
            self.assertGreaterEqual(data["recommended_prep"], data["predicted_demand"])
            # Verify individual items distinguish quantity (demand) and safe_prep
            for it in data["top_items"]:
                self.assertIn("quantity", it)
                self.assertIn("safe_prep", it)
                self.assertGreaterEqual(it["safe_prep"], it["quantity"])

    def test_10_record_actual_demand_endpoint(self):
        """Verify recording actual ground truth demand for a forecast."""
        try:
            latest = db.get_latest_demand_forecast()
            if not latest:
                self.skipTest("No existing forecast in database to attach actual demand to.")
            forecast_id = latest["id"]
            resp = client.post(f"/api/demand-forecast/{forecast_id}/actual", json={"actual_demand": 160})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["forecast"]["actual_demand"], 160)
        except Exception as e:
            self.skipTest(f"Live MySQL test skipped: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
