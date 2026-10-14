"""
Serviqo AI - ML Demand Forecasting Engine
Directly integrates canteen_model.joblib (LightGBM dual-model: expected demand + 85th-percentile quantile safe preparation).
Provides item-level portion forecasting and overall kitchen demand requirements.
"""

import os
import pickle
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

try:
    import joblib
except ImportError:
    joblib = None

# Model file paths with priority for canteen_model.joblib
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CANTEEN_MODEL_PATH = os.path.join(BASE_DIR, "canteen_model.joblib")
FOOD_DEMAND_MODEL_PATH = os.path.join(BASE_DIR, "food_demand_model.pkl")
FALLBACK_MODEL_PATH = os.path.join(BASE_DIR, "model.pkl")

# Cached ML model instance and metadata
_model_artifact = None
_model_loaded_time = None
_model_type = None  # 'canteen_dual_joblib' or 'legacy_pickle'


def load_ml_model():
    """
    Loads and caches the trained ML model.
    Prioritizes canteen_model.joblib (dual-model: model_demand + model_safe_prep).
    Falls back to food_demand_model.pkl or model.pkl if available.
    """
    global _model_artifact, _model_loaded_time, _model_type

    # 1. Try loading canteen_model.joblib
    if os.path.exists(CANTEEN_MODEL_PATH) and joblib is not None:
        try:
            loaded = joblib.load(CANTEEN_MODEL_PATH)
            if isinstance(loaded, dict) and "model_demand" in loaded and "model_safe_prep" in loaded:
                _model_artifact = loaded
                _model_type = "canteen_dual_joblib"
                _model_loaded_time = os.path.getmtime(CANTEEN_MODEL_PATH)
                print(f"[ML Engine] Successfully loaded dual-target ML model from {CANTEEN_MODEL_PATH}")
                return _model_artifact
        except Exception as e:
            print(f"[ML Engine] Warning: Failed to load {CANTEEN_MODEL_PATH}: {e}")

    # 2. Try loading legacy pickle model if joblib failed or file absent
    target_path = FOOD_DEMAND_MODEL_PATH if os.path.exists(FOOD_DEMAND_MODEL_PATH) else FALLBACK_MODEL_PATH
    if os.path.exists(target_path):
        try:
            with open(target_path, "rb") as f:
                loaded = pickle.load(f)
            if isinstance(loaded, dict) and "model" in loaded:
                _model_artifact = loaded
            else:
                _model_artifact = {"model": loaded, "features": None, "cat_cols": []}
            _model_type = "legacy_pickle"
            _model_loaded_time = os.path.getmtime(target_path)
            print(f"[ML Engine] Successfully loaded fallback ML model from {target_path}")
            return _model_artifact
        except Exception as e:
            print(f"[ML Engine] Warning: Failed to unpickle {target_path}: {e}")

    _model_artifact = None
    _model_type = None
    return _model_artifact


def get_model_status() -> Dict[str, Any]:
    """Check whether canteen_model.joblib is currently loaded or in fallback mode."""
    artifact = load_ml_model()
    is_joblib = _model_type == "canteen_dual_joblib"
    is_available = artifact is not None

    if is_joblib:
        model_name = "canteen_model.joblib"
        model_path = CANTEEN_MODEL_PATH
        status_key = "active_canteen_model"
        desc = "Active LightGBM Dual-Model (Expected Demand + 85th-Percentile Safe Prep) loaded from canteen_model.joblib."
    elif is_available:
        model_name = "food_demand_model.pkl"
        model_path = FOOD_DEMAND_MODEL_PATH if os.path.exists(FOOD_DEMAND_MODEL_PATH) else FALLBACK_MODEL_PATH
        status_key = "active_legacy_model"
        desc = "Active single-target LightGBM model loaded."
    else:
        model_name = None
        model_path = CANTEEN_MODEL_PATH
        status_key = "heuristic_fallback_ready"
        desc = "Model not found; using heuristic fallback engine."

    return {
        "model_file_exists": is_available,
        "model_name": model_name,
        "model_path": model_path,
        "model_type": _model_type,
        "model_status": status_key,
        "description": desc,
        "features_count": len(artifact.get("feature_cols", [])) if (artifact and is_joblib) else 0
    }


# Standard campus menu items mapped to categories trained in canteen_model.joblib
CANTEEN_MENU_BLUEPRINTS = {
    "breakfast": [
        {"name": "Idli Sambar", "category": "South_Indian", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Masala Dosa", "category": "South_Indian", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Plain Dosa", "category": "South_Indian", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Medu Vada", "category": "South_Indian", "unit": "pieces", "waste_risk": "medium", "is_main": True},
        {"name": "Poori Bhaji", "category": "Indian_Bread", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Khara Bath (Upma)", "category": "South_Indian", "unit": "plates", "waste_risk": "low", "is_main": True},
        {"name": "Ven Pongal", "category": "South_Indian", "unit": "plates", "waste_risk": "low", "is_main": True},
        {"name": "Filter Coffee", "category": "Beverage", "unit": "cups", "waste_risk": "low", "is_main": False},
        {"name": "Chai (Tea)", "category": "Beverage", "unit": "cups", "waste_risk": "low", "is_main": False}
    ],
    "lunch": [
        {"name": "Veg Meals (Rice+Sambar+Rasam)", "category": "South_Indian", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Steamed Rice with Sambar/Rasam", "category": "Rice_Combo", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Veg Biryani", "category": "Special_Rice", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Chapati Kurma", "category": "Indian_Bread", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Curd Rice", "category": "Rice_Combo", "unit": "plates", "waste_risk": "low", "is_main": True},
        {"name": "Dal Tadka", "category": "Dal", "unit": "liters", "waste_risk": "medium", "is_main": False},
        {"name": "Paneer Butter Masala", "category": "Curry", "unit": "liters", "waste_risk": "medium", "is_main": False},
        {"name": "Buttermilk", "category": "Beverage", "unit": "cups", "waste_risk": "low", "is_main": False}
    ],
    "snacks": [
        {"name": "Samosa", "category": "Fried_Snack", "unit": "pieces", "waste_risk": "high", "is_main": True},
        {"name": "Mirchi Bajji / Pakoda", "category": "Fried_Snack", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Veg Puff", "category": "Bakery", "unit": "pieces", "waste_risk": "medium", "is_main": True},
        {"name": "Veg Sandwich", "category": "Fast_Food", "unit": "pieces", "waste_risk": "medium", "is_main": True},
        {"name": "Veg Noodles", "category": "Fast_Food", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Chai (Tea)", "category": "Beverage", "unit": "cups", "waste_risk": "low", "is_main": False},
        {"name": "Filter Coffee", "category": "Beverage", "unit": "cups", "waste_risk": "low", "is_main": False}
    ],
    "dinner": [
        {"name": "Veg Meals (Rice+Sambar+Rasam)", "category": "South_Indian", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Chapati with Curry", "category": "Indian_Bread", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Chapati with Dal", "category": "Indian_Bread", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Roti with Paneer Curry", "category": "Indian_Bread", "unit": "plates", "waste_risk": "medium", "is_main": True},
        {"name": "Veg Fried Rice", "category": "Rice_Based", "unit": "plates", "waste_risk": "high", "is_main": True},
        {"name": "Paneer Butter Masala", "category": "Curry", "unit": "liters", "waste_risk": "medium", "is_main": False},
        {"name": "Dal Tadka", "category": "Dal", "unit": "liters", "waste_risk": "medium", "is_main": False},
        {"name": "Curd Rice", "category": "Rice_Combo", "unit": "plates", "waste_risk": "low", "is_main": False}
    ]
}

# Backwards-compatible alias
MENU_BLUEPRINTS = CANTEEN_MENU_BLUEPRINTS


def predict_kitchen_demand(
    meal_type: str = "breakfast",
    attendance: int = 150,
    hostel_attendance: Optional[int] = None,
    dayscholar_attendance: Optional[int] = None,
    temperature_c: Optional[float] = 27.0,
    rainfall_mm: Optional[float] = 0.0,
    humidity_pct: Optional[float] = 60.0,
    day_type: Optional[str] = "weekday",
    is_weekend: Optional[bool] = None,
    is_holiday: Optional[bool] = None,
    is_exam_day: Optional[bool] = False,
    is_college_event: Optional[bool] = False,
    previous_demand: Optional[int] = None,
    avg_7day_demand: Optional[int] = None,
    popularity_level: Optional[int] = 2,
    menu_item: Optional[str] = None,
    academic_status: Optional[str] = None,
    college_event: Optional[str] = None,
    holiday_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Predict overall meal counts and itemized requirements using the trained LightGBM ML model
    from canteen_model.joblib.
    """
    artifact = load_ml_model()

    meal_key = meal_type.lower() if meal_type else "breakfast"
    if meal_key not in CANTEEN_MENU_BLUEPRINTS:
        meal_key = "breakfast"

    # Default attendance calculations
    expected_att = max(10, attendance)
    hostel_att = hostel_attendance if hostel_attendance is not None else int(expected_att * 0.65)
    dayscholar_att = dayscholar_attendance if dayscholar_attendance is not None else int(expected_att * 0.35)
    prev_demand = previous_demand if previous_demand is not None else int(expected_att * 0.95)
    rolling_7d = avg_7day_demand if avg_7day_demand is not None else int(expected_att * 0.96)
    temp_c = float(temperature_c) if temperature_c is not None else 27.0
    rain_mm = float(rainfall_mm) if rainfall_mm is not None else 0.0
    hum_pct = float(humidity_pct) if humidity_pct is not None else 65.0

    weekend_bool = is_weekend if is_weekend is not None else (day_type == "weekend")
    holiday_bool = is_holiday if is_holiday is not None else (day_type == "holiday")

    now = datetime.datetime.now()
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = days_of_week[now.weekday()]
    if weekend_bool and day_name not in ("Saturday", "Sunday"):
        day_name = "Saturday"

    weather_condition = "Rainy" if rain_mm > 15 else ("Cloudy" if rain_mm > 5 else "Sunny")
    total_footfall = hostel_att + dayscholar_att + 100

    # Academic & event status mappings
    if academic_status:
        acad_stat = academic_status
    elif is_exam_day:
        acad_stat = "Final_Exams"
    else:
        acad_stat = "Regular_Semester"

    col_event = college_event if college_event else ("Tech_Fest" if is_college_event else None)
    hol_name = holiday_name if holiday_name else ("Diwali_Break" if holiday_bool else None)

    predicted_meals = None
    recommended_prep = None
    model_source = "heuristic_fallback"
    model_engine = "Heuristic Fallback Engine"
    top_items = []

    # -------------------------------------------------------------
    # 1. Primary Execution: Dual LightGBM Model (canteen_model.joblib)
    # -------------------------------------------------------------
    if _model_type == "canteen_dual_joblib" and artifact is not None:
        try:
            m_dem = artifact["model_demand"]
            m_safe = artifact["model_safe_prep"]
            feat_cols = artifact["feature_cols"]
            cat_cols = artifact["categorical_features"]
            cats_by_col = dict(zip(cat_cols, m_dem.booster_.pandas_categorical))

            # Select items to infer: either a specific requested item or the meal blueprint
            items_to_predict = CANTEEN_MENU_BLUEPRINTS[meal_key]
            if menu_item:
                matched = [it for it in items_to_predict if it["name"].lower() == menu_item.lower()]
                if matched:
                    items_to_predict = matched

            # Popularity multiplier
            pop_mult = 1.05 if popularity_level == 3 else (0.95 if popularity_level == 1 else 1.0)

            total_main_demand = 0.0
            total_main_safe = 0.0

            for item in items_to_predict:
                item_name = item["name"]
                cat_name = item["category"]
                unit = item["unit"]
                risk = item["waste_risk"]
                is_main = item.get("is_main", True)

                row_dict = {
                    "Meal_Type": [meal_key.title()],
                    "Menu_Item": [item_name],
                    "Food_Category": [cat_name],
                    "Day_of_Week": [day_name],
                    "Academic_Status": [acad_stat],
                    "College_Event": [col_event],
                    "Holiday_Name": [hol_name],
                    "Month": [now.month],
                    "Is_Weekend": [1 if weekend_bool else 0],
                    "Is_Holiday": [1 if holiday_bool else 0],
                    "Rainfall_mm": [rain_mm],
                    "Temperature_C": [temp_c],
                    "Hostel_Diners_Present": [hostel_att],
                    "DayScholar_Diners_Present": [dayscholar_att],
                    "Total_Campus_Footfall": [total_footfall],
                    "Meal_Estimated_Diners": [expected_att],
                    "Is_Active_Today": [0 if (holiday_bool and not is_college_event) else 1],
                    "Demand_Lag_7_Days": [float(rolling_7d)],
                    "Rolling_7D_Mean": [float(rolling_7d)]
                }

                df_item = pd.DataFrame(row_dict)
                for col in cat_cols:
                    if col in cats_by_col:
                        df_item[col] = pd.Categorical(df_item[col], categories=cats_by_col[col])

                raw_dem = float(m_dem.predict(df_item[feat_cols])[0]) * pop_mult
                raw_safe = float(m_safe.predict(df_item[feat_cols])[0]) * pop_mult

                item_demand_val = max(1, int(round(raw_dem)))
                item_safe_val = max(item_demand_val, int(round(raw_safe)))

                top_items.append({
                    "name": item_name,
                    "unit": unit,
                    "quantity": item_demand_val,
                    "safe_prep": item_safe_val,
                    "waste_risk": risk,
                    "category": cat_name,
                    "is_main": is_main
                })

                if is_main:
                    total_main_demand += item_demand_val
                    total_main_safe += item_safe_val

            # Calibrate overall meal demand and prep
            predicted_meals = max(int(round(total_main_demand)), int(round(expected_att * 0.85)))
            recommended_prep = max(int(round(total_main_safe)), int(round(predicted_meals * 1.06)))
            model_source = "LightGBM Production Model (canteen_model.joblib)"
            model_engine = "LightGBM Dual-Model Engine (canteen_model.joblib)"

        except Exception as e:
            print(f"[ML Engine] canteen_model.joblib inference error ({e}), trying fallback.")
            predicted_meals = None

    # -------------------------------------------------------------
    # 2. Secondary Execution: Single-Target Pickle Model
    # -------------------------------------------------------------
    if predicted_meals is None and artifact is not None and "model" in artifact and artifact.get("features"):
        try:
            model = artifact["model"]
            features = artifact["features"]
            cat_cols = artifact.get("cat_cols", [])

            feature_dict = {
                "Meal_Type": [meal_key.title()],
                "Menu_Item": [CANTEEN_MENU_BLUEPRINTS[meal_key][0]["name"]],
                "Food_Category": [meal_key.title()],
                "Day_of_Week": [day_name],
                "Event_Type": ["College Event" if is_college_event else "None"],
                "Weather_Condition": [weather_condition],
                "Month": [now.month],
                "Day_of_Month": [now.day],
                "Week_of_Year": [now.isocalendar()[1]],
                "Semester_Week": [8],
                "Is_Weekend": [1 if weekend_bool else 0],
                "Is_Holiday": [1 if holiday_bool else 0],
                "Is_Exam_Day": [1 if is_exam_day else 0],
                "Is_College_Event": [1 if is_college_event else 0],
                "Total_Students": [max(expected_att + 200, 1000)],
                "Expected_Attendance": [expected_att],
                "Attendance_Rate_Expected": [min(1.0, round(expected_att / max(expected_att + 200, 1000), 2))],
                "Total_Reservations": [hostel_att + int(dayscholar_att * 0.5)],
                "Hostel_Preorders": [hostel_att],
                "Expected_Event_Attendance": [expected_att if is_college_event else 0],
                "Temperature_C": [temp_c],
                "Rainfall_mm": [rain_mm],
                "Humidity_Percent": [hum_pct],
                "Weather_Severity": [3.0 if rain_mm > 25 else (2.0 if rain_mm > 8 else 1.0)],
                "Previous_Day_Demand": [prev_demand],
                "Demand_Lag_7_Days": [rolling_7d],
                "Demand_Lag_14_Days": [rolling_7d],
                "Rolling_7Day_Demand": [float(rolling_7d)]
            }

            df = pd.DataFrame(feature_dict)
            for c in cat_cols:
                if c in df.columns:
                    df[c] = df[c].astype("category")

            pred = model.predict(df[features])
            raw_prediction = float(pred[0])
            if popularity_level == 3:
                raw_prediction *= 1.05
            elif popularity_level == 1:
                raw_prediction *= 0.95

            predicted_meals = max(10, int(round(raw_prediction)))
            recommended_prep = int(round(predicted_meals * 1.06))
            model_source = "LightGBM Model (food_demand_model.pkl)"
            model_engine = "LightGBM Single Model"

            # Populate top items using ratios
            top_items = []
            for item in CANTEEN_MENU_BLUEPRINTS[meal_key]:
                ratio = 0.25 if item.get("is_main") else 0.40
                qty = max(1, int(round(predicted_meals * ratio)))
                top_items.append({
                    "name": item["name"],
                    "unit": item["unit"],
                    "quantity": qty,
                    "safe_prep": int(round(qty * 1.08)),
                    "waste_risk": item["waste_risk"],
                    "category": item["category"]
                })
        except Exception as e:
            print(f"[ML Engine] Pickle model prediction error ({e}), utilizing heuristic formula.")
            predicted_meals = None

    # -------------------------------------------------------------
    # 3. Tertiary Execution: Heuristic Fallback Engine
    # -------------------------------------------------------------
    if predicted_meals is None:
        base_demand = (expected_att * 0.72) + (prev_demand * 0.28)
        if popularity_level == 3:
            base_demand += 10
        elif popularity_level == 1:
            base_demand -= 10
        if rain_mm > 20:
            base_demand -= 8
        if weekend_bool:
            base_demand -= 15
        if holiday_bool:
            base_demand -= 25
        if is_exam_day:
            base_demand += 12
        if is_college_event:
            base_demand += 25

        predicted_meals = max(10, int(round(base_demand)))
        recommended_prep = int(round(predicted_meals * 1.06))
        model_source = "Heuristic Regression Fallback"
        model_engine = "Heuristic Fallback Engine"

        top_items = []
        for item in CANTEEN_MENU_BLUEPRINTS[meal_key]:
            ratio = 0.25 if item.get("is_main") else 0.40
            qty = max(1, int(round(predicted_meals * ratio)))
            top_items.append({
                "name": item["name"],
                "unit": item["unit"],
                "quantity": qty,
                "safe_prep": int(round(qty * 1.06)),
                "waste_risk": item["waste_risk"],
                "category": item["category"]
            })

    # Final buffer calculation
    safety_buffer = max(0, recommended_prep - predicted_meals)
    safety_buffer_pct = round((safety_buffer / max(1, predicted_meals)) * 100.0, 1)

    top_item_name = top_items[0]["name"] if top_items else "Primary Meal"
    top_item_qty = top_items[0]["quantity"] if top_items else predicted_meals
    recommendation_text = (
        f"For {meal_key.title()}, {top_item_name} has highest projected demand ({top_item_qty} units). "
        f"Base ML Demand: {predicted_meals} servings + {safety_buffer_pct}% safety prep buffer ({safety_buffer} servings) "
        f"= Recommended Kitchen Prep: {recommended_prep} units."
    )

    return {
        "meal_type": meal_key,
        "attendance": expected_att,
        "predicted_demand": int(predicted_meals),
        "safety_buffer": int(safety_buffer),
        "safety_buffer_percent": safety_buffer_pct,
        "recommended_prep": int(recommended_prep),
        "model_source": model_source,
        "model_engine": model_engine,
        "top_items": top_items,
        "recommendation": recommendation_text,
        "weather": weather_condition,
        "demand_status": "High Demand" if predicted_meals >= expected_att * 0.9 else "Optimal",
        "temperature_c": temp_c,
        "rainfall_mm": rain_mm,
        "humidity_pct": hum_pct
    }


# Initial model load attempt on start
load_ml_model()
