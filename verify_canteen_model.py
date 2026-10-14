"""
Verification script for canteen_model.joblib integration in Serviqo AI
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_canteen_model_integration():
    print("=" * 60)
    print("SERVIQO AI - CANTEEN MODEL JOBLIB INTEGRATION VERIFICATION")
    print("=" * 60)

    # 1. Health and ML Status check
    res = client.get("/api/ml-status")
    assert res.status_code == 200, f"ML status endpoint failed: {res.text}"
    status_data = res.json()
    print("\n[STEP 1] /api/ml-status:")
    print("  Model File Exists :", status_data.get("model_file_exists"))
    print("  Model Name        :", status_data.get("model_name"))
    print("  Model Status      :", status_data.get("model_status"))
    print("  Features Count    :", status_data.get("features_count"))
    print("  Description       :", status_data.get("description"))

    assert status_data.get("model_file_exists") is True
    assert status_data.get("model_name") == "canteen_model.joblib"
    assert status_data.get("model_status") == "active_canteen_model"

    # 2. Demand Forecast for each meal type
    meals = ["breakfast", "lunch", "snacks", "dinner"]
    for meal in meals:
        payload = {
            "meal_type": meal,
            "attendance": 175,
            "temperature_c": 28.0,
            "rainfall_mm": 2.0,
            "humidity_pct": 65.0,
            "day_type": "weekday",
            "is_exam_day": False,
            "is_college_event": False,
            "previous_demand": 165,
            "avg_7day_demand": 170,
            "popularity_level": 2
        }
        res = client.post("/api/demand-forecast", json=payload)
        assert res.status_code == 200, f"Forecast failed for {meal}: {res.text}"
        data = res.json()
        print(f"\n[STEP 2] /api/demand-forecast for {meal.upper()}:")
        print(f"  Model Engine     : {data.get('model_engine')}")
        print(f"  Predicted Demand : {data.get('predicted_demand')} servings")
        print(f"  Recommended Prep : {data.get('recommended_prep')} servings")
        print(f"  Safety Buffer    : {data.get('safety_buffer')} ({data.get('safety_buffer_percent')}%)")
        print(f"  Status           : {data.get('demand_status')}")
        print(f"  Items Breakdown  : {len(data.get('top_items', []))} items")
        for item in data.get("top_items", [])[:4]:
            print(f"    * {item['name']}: {item['quantity']} {item['unit']} (Safe Prep: {item.get('safe_prep')}, Waste Risk: {item['waste_risk']})")
        
        assert "canteen_model.joblib" in data.get("model_source", "")
        assert data.get("predicted_demand") > 0
        assert data.get("recommended_prep") >= data.get("predicted_demand")
        assert len(data.get("top_items", [])) > 0

    # 3. Verify latest prediction persisted to MySQL
    res = client.get("/api/demand-forecast/latest")
    assert res.status_code == 200
    latest = res.json()
    print("\n[STEP 3] /api/demand-forecast/latest:")
    print(f"  Latest Meal Type : {latest.get('meal_type')}")
    print(f"  Predicted Demand : {latest.get('predicted_demand')}")
    print(f"  Recommended Prep : {latest.get('recommended_prep')}")
    assert latest.get("predicted_demand") > 0

    # 4. Verify Dashboard KPIs reflect operational metrics
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    kpis = res.json().get("kpis", {})
    print("\n[STEP 4] /api/dashboard KPIs:")
    print(f"  Today's Predicted Demand : {kpis.get('today_predicted_demand')}")
    print(f"  Recommended Kitchen Prep : {kpis.get('recommended_kitchen_prep')}")
    print(f"  Kitchen Prep Efficiency  : {kpis.get('kitchen_prep_efficiency')}%")
    print(f"  Demand Status            : {kpis.get('demand_status')}")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED: canteen_model.joblib IS FULLY CONNECTED!")
    print("=" * 60)

if __name__ == "__main__":
    test_canteen_model_integration()
