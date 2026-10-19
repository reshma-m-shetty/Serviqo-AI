"""
Serviqo AI - Pure MySQL FastAPI Backend
Connected end-to-end to MySQL 8.0 (serviqo_ai) and canteen_model.joblib.
Zero SQLite dependencies.
"""

import os
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
try:
    from pydantic import PydanticDeprecatedSince20
    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
except ImportError:
    pass

from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Query, HTTPException, Body, status, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr

import database as db
import ml_engine as ml

app = FastAPI(
    title="Serviqo AI - Smart Food Supply Chain API",
    description="Clean, reliable MySQL 8.0 backend powering Kitchen Demand AI, Inventory Management, Surplus Recovery, and NGO Donation dispatch.",
    version="3.0"
)

raw_origins = os.getenv("ALLOWED_ORIGINS", "*").strip()
if raw_origins and raw_origins != "*":
    origins = [orig.strip() for orig in raw_origins.split(",") if orig.strip()]
else:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/api/health")
def health_check():
    """
    Unified health-check endpoint that checks application availability,
    database connectivity, and ML model status without exposing secrets.
    Returns HTTP 200 if fully healthy, or HTTP 503 if any critical service is unavailable or degraded.
    """
    db_health = db.check_mysql_health()
    model_status = ml.get_model_status()
    from fastapi.responses import JSONResponse

    is_db_ok = bool(db_health.get("connected") or db_health.get("healthy"))
    is_model_ok = bool(model_status.get("model_status") == "active_canteen_model" and model_status.get("model_file_exists"))
    is_healthy = is_db_ok and is_model_ok

    status_str = "healthy" if is_healthy else ("degraded" if is_db_ok else "unhealthy")
    status_code = 200 if is_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": status_str,
            "service": "Serviqo AI Backend",
            "version": "3.0",
            "application": {
                "status": "up"
            },
            "database": {
                "connected": is_db_ok,
                "status": db_health.get("status", "healthy" if is_db_ok else "disconnected"),
                "tables_count": len(db_health.get("tables", [])),
                "message": db_health.get("message")
            },
            "ml_model": {
                "loaded": is_model_ok,
                "model_name": model_status.get("model_name"),
                "model_status": model_status.get("model_status"),
                "framework": model_status.get("framework")
            }
        }
    )



def get_authenticated_user_context(request: Request) -> Optional[Dict[str, Any]]:
    """
    Backend single source of truth for session identity.
    Resolves the authenticated user from X-User-Email header or query parameters.
    """
    user_email = request.headers.get("x-user-email") or request.query_params.get("auth_email")
    if not user_email:
        return None
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, role, ngo_id, organization FROM users WHERE email = %s", (user_email.strip().lower(),))
        user = cursor.fetchone()
        return user


def enforce_ngo_organization_id(request: Request, client_org_id: Optional[int] = None) -> int:
    """
    Enforces strict organization-level data isolation for NGO requests.
    If the caller is authenticated as an NGO, the backend ALWAYS enforces their true database ngo_id.
    Any attempt to spoof or query another organization_id is rejected/ignored in favor of the authenticated organization.
    """
    user = get_authenticated_user_context(request)
    if user:
        role = (user.get("role") or "").strip().lower()
        if "ngo" in role or "relief" in role:
            auth_org_id = user.get("ngo_id")
            if auth_org_id:
                return int(auth_org_id)

    if client_org_id:
        return int(client_org_id)

    raise HTTPException(
        status_code=400,
        detail="Organization could not be identified. Please ensure you are logged into a registered NGO account."
    )


# ==========================================
# STARTUP HEALTH CHECK & SCHEMA VERIFICATION
# ==========================================
@app.on_event("startup")
def startup_event():
    print("[FastAPI Startup] Initializing MySQL database and verifying connectivity...")
    try:
        db.init_db()
        health = db.check_mysql_health()
        if health.get("connected"):
            print(f"[FastAPI Startup] MySQL 8.0 connected successfully. Tables: {health.get('tables')}")
        else:
            print(f"[FastAPI Startup] Warning: {health.get('message')}")
    except Exception as e:
        print(f"[FastAPI Startup] MySQL initialization error: {e}")


# ==========================================
# PYDANTIC REQUEST & RESPONSE SCHEMAS
# ==========================================
class UserRegister(BaseModel):
    name: str = Field(..., example="Rohan Sharma")
    email: str = Field(..., example="staff@serviqo.ai")
    password: str = Field(..., min_length=4, example="staff123")
    role: Optional[str] = Field("Kitchen Staff", example="Kitchen Staff")
    organization: Optional[str] = Field(None, example="Srinivas Institute Canteen")
    ngo_id: Optional[int] = Field(None, example=1)
    phone: Optional[str] = Field(None, example="+91 98450 12345")
    address: Optional[str] = Field(None, example="Kodialbail, Mangalore, Karnataka 575003")
    capacity_persons: Optional[int] = Field(None, example=250)
    need_level: Optional[str] = Field("high", example="high")
    latitude: Optional[float] = Field(None, example=12.8712)
    longitude: Optional[float] = Field(None, example=74.8431)


class UserLogin(BaseModel):
    email: str = Field(..., example="kitchen@serviqo.ai")
    password: str = Field(..., example="staff123")


class UserProfileUpdate(BaseModel):
    user_id: int = Field(..., example=1)
    name: str = Field(..., min_length=2, example="Rohan Sharma")


class InventoryCreate(BaseModel):
    name: Optional[str] = None
    item_name: Optional[str] = None
    quantity: float = Field(..., gt=0, example=50.0)
    unit: str = Field("portions", example="portions")
    category: Optional[str] = "Cooked Meals"
    expiry_days: int = Field(..., ge=0, example=1)
    base_price_inr: Optional[float] = 50.0
    supplier_name: Optional[str] = "Srinivas Institute Canteen"


class InventoryUpdate(BaseModel):
    quantity: Optional[float] = None
    expiry_days: Optional[int] = None
    status: Optional[str] = None


class DonationCreate(BaseModel):
    inventory_id: Optional[int] = None
    food_item: Optional[str] = None
    item_name: Optional[str] = None
    quantity: float = Field(..., gt=0, example=40.0)
    unit: str = Field("portions", example="portions")
    ngo_id: int = Field(..., example=1)
    ngo_name: str = Field(..., example="The Akshaya Patra Foundation")
    supplier_name: Optional[str] = "Srinivas Institute Canteen"
    pickup_address: Optional[str] = "Srinivas Campus Canteen Gate 2, Mangalore"
    pickup_deadline: Optional[str] = "Within 3 hours"
    message: Optional[str] = None


class SurplusPostCreate(BaseModel):
    inventory_id: Optional[int] = None
    food_item: str = Field(..., example="Steamed Rice")
    published_quantity: float = Field(..., gt=0, example=25.0)
    unit: str = Field("kg", example="kg")
    available_until: Optional[str] = Field("Today before 4:00 PM", example="3:00 PM")
    pickup_location: Optional[str] = Field("Srinivas Campus Canteen Gate 2, Mangalore", example="Srinivas Canteen")
    notes: Optional[str] = Field("Freshly prepared", example="Freshly prepared afternoon batch")
    supplier_name: Optional[str] = Field("Srinivas Institute Canteen", example="Srinivas Institute Canteen")


class DonationRequestCreate(BaseModel):
    post_id: int = Field(..., example=1)
    organization_id: int = Field(..., example=1)
    organization_name: Optional[str] = Field("Partner NGO", example="ISKCON Food Relief Foundation - Mangalore")
    requested_quantity: float = Field(..., gt=0, example=10.0)
    message: Optional[str] = Field("", example="Can pick up today afternoon")
    preferred_pickup_time: Optional[str] = Field("Today 2:00 PM", example="2:00 PM")


class DonationRequestStatusUpdate(BaseModel):
    status: str = Field(..., example="ACCEPTED")
    pickup_date: Optional[str] = None
    pickup_time: Optional[str] = None
    pickup_location: Optional[str] = None
    fulfilled_quantity: Optional[float] = Field(None, example=20.0, description="Actual collected quantity if partial or specified")


class PickupScheduleRequest(BaseModel):
    pickup_date: str = Field(..., example="2026-10-03")
    pickup_time: str = Field(..., example="2:00 PM")
    pickup_location: Optional[str] = Field("Srinivas Campus Canteen Gate 2, Mangalore", example="Srinivas Canteen Gate 2")


class DemandForecastRequest(BaseModel):
    meal_type: str = Field("breakfast", example="breakfast")
    attendance: int = Field(150, ge=10, example=150)
    hostel_attendance: Optional[int] = None
    dayscholar_attendance: Optional[int] = None
    temperature_c: Optional[float] = 27.0
    rainfall_mm: Optional[float] = 0.0
    humidity_pct: Optional[float] = 65.0
    day_type: Optional[str] = "weekday"
    is_weekend: Optional[bool] = None
    is_holiday: Optional[bool] = None
    is_exam_day: Optional[bool] = False
    is_college_event: Optional[bool] = False
    is_campus_event: Optional[bool] = False
    popularity_level: Optional[int] = Field(2, ge=1, le=3)
    menu_item: Optional[str] = None
    academic_status: Optional[str] = None
    college_event: Optional[str] = None
    holiday_name: Optional[str] = None
    # Historical demand features are automated from MySQL observations;
    # manual inputs are retained only as optional deprecated fields for backwards compatibility
    previous_demand: Optional[int] = None
    avg_7day_demand: Optional[int] = None
    rolling_avg_7day: Optional[int] = None


class ActualDemandRecordRequest(BaseModel):
    actual_demand: int = Field(..., ge=0, example=155, description="Actual meal servings consumed (ground truth)")



class AnnouncementCreate(BaseModel):
    title: str = Field(..., example="Notice")
    message: str = Field(..., example="Important kitchen message")
    recipient: Optional[str] = "All Staff"
    priority: Optional[str] = "Normal"
    sender: Optional[str] = "Canteen Manager"


class NgoVerifyRequest(BaseModel):
    status: str = Field(..., example="VERIFIED")


# ==========================================
# AUTHENTICATION ENDPOINTS
# ==========================================
@app.post("/auth/register")
@app.post("/api/auth/register")
def register(req: UserRegister):
    try:
        user = db.register_user(
            name=req.name,
            email=req.email,
            password=req.password,
            role=req.role or "Kitchen Staff",
            organization=req.organization,
            ngo_id=req.ngo_id,
            phone=req.phone,
            address=req.address,
            capacity_persons=req.capacity_persons,
            need_level=req.need_level,
            latitude=req.latitude,
            longitude=req.longitude
        )
        return {"success": True, "message": "Registration successful", "user": user}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Database registration failed. Please try again.")


@app.post("/auth/login")
@app.post("/api/auth/login")
def login(req: UserLogin):
    user = db.authenticate_user(email=req.email, password=req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {
        "success": True,
        "message": f"Welcome back, {user['name']}!",
        "user": user
    }


@app.get("/api/auth/me")
def get_current_user(email: str = Query(..., description="Email of logged-in user")):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, role, organization, ngo_id FROM users WHERE email = %s", (email.strip().lower(),))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "user": user}


@app.put("/api/auth/profile")
def update_profile(req: UserProfileUpdate):
    """Updates user's name in MySQL and returns refreshed profile."""
    try:
        updated = db.update_user_profile(user_id=req.user_id, name=req.name)
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "message": "Profile updated successfully", "user": updated}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Database profile update failed.")


# ==========================================
# ML MODEL STATUS
# ==========================================
@app.get("/api/ml-status")

def ml_status():
    return ml.get_model_status()


# ==========================================
# DASHBOARD KPI METRICS
# ==========================================
@app.get("/dashboard")
@app.get("/api/dashboard")
def dashboard():
    """Returns live operational KPI counts calculated directly from MySQL."""
    try:
        kpis = db.get_dashboard_kpis()
        return {"success": True, "kpis": kpis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard KPIs: {e}")


@app.get("/api/dashboard/demand-trend")
def demand_trend(limit: int = 7):
    """Returns historical demand forecast trend directly from MySQL demand_forecasts."""
    return db.get_demand_trend(limit=limit)


@app.get("/api/dashboard/donation-trend")
def donation_trend(limit: int = 7):
    """Returns historical donation dispatch trend directly from MySQL donations."""
    return db.get_donation_trend(limit=limit)


@app.get("/api/dashboard/inventory-summary")
def inventory_summary():
    """Returns real inventory category and NGO breakdown from MySQL."""
    return db.get_inventory_summary()


@app.get("/api/analytics")
def analytics():
    """Returns live environmental and human impact analytics directly from MySQL."""
    return db.get_analytics_summary()


@app.get("/api/dashboard/canteen")
def canteen_dashboard():
    """Returns pure Srinivas Canteen operational KPIs directly from MySQL."""
    try:
        kpis = db.get_dashboard_kpis()
        return {
            "success": True,
            "role": "Kitchen Staff",
            "organization": "Srinivas Institute Canteen / Kitchen",
            "kpis": kpis
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch canteen dashboard KPIs: {e}")


@app.get("/api/dashboard/ngo")
def ngo_dashboard(
    request: Request,
    ngo_id: Optional[int] = Query(None, description="Optional NGO ID to filter relief metrics")
):
    """Returns dedicated NGO recovery, intake, and relief distribution metrics strictly isolated by organization from MySQL."""
    try:
        effective_ngo_id = enforce_ngo_organization_id(request, client_org_id=ngo_id)
        kpis = db.get_ngo_kpis(ngo_id=effective_ngo_id)
        ngo_rec = db.get_ngo_by_id(effective_ngo_id)
        ngo_name = (ngo_rec.get("name") if ngo_rec else None) or kpis.get("organization_name") or f"Relief Partner #{effective_ngo_id}"

        return {
            "success": True,
            "role": "NGO",
            "ngo_id": effective_ngo_id,
            "organization_id": effective_ngo_id,
            "ngo_name": ngo_name,
            "organization_name": ngo_name,
            "kpis": kpis
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch NGO dashboard KPIs: {e}")


@app.get("/api/analytics/ngo")
def ngo_analytics(
    request: Request,
    ngo_id: Optional[int] = Query(None, description="Optional NGO ID")
):
    """Returns dedicated NGO recovery trend and partner contributions strictly isolated by organization from MySQL."""
    try:
        effective_ngo_id = enforce_ngo_organization_id(request, client_org_id=ngo_id)
        data = db.get_ngo_analytics(ngo_id=effective_ngo_id)
        return {"success": True, "organization_id": effective_ngo_id, **data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch NGO analytics: {e}")


# ==========================================
# INVENTORY MANAGEMENT ENDPOINTS (MYSQL)
# ==========================================
@app.get("/api/inventory")
@app.get("/inventory")
def list_inventory():
    return db.get_all_inventory()


@app.post("/api/inventory")
@app.post("/inventory")
def create_inventory(item: InventoryCreate):
    try:
        item_dict = item.dict()
        if not item_dict.get("name") and item_dict.get("item_name"):
            item_dict["name"] = item_dict["item_name"]
        elif not item_dict.get("item_name") and item_dict.get("name"):
            item_dict["item_name"] = item_dict["name"]
        created = db.add_inventory_item(item_dict)
        res = {"message": "Inventory item added successfully", "item": created}
        if isinstance(created, dict):
            res.update({
                "id": created.get("id"),
                "name": created.get("name") or created.get("item_name"),
                "quantity": created.get("quantity"),
                "unit": created.get("unit"),
                "status": created.get("status")
            })
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add inventory item: {e}")


@app.put("/api/inventory/{item_id}")
@app.put("/inventory/{item_id}")
def update_inventory(item_id: int, update_data: InventoryUpdate):
    data_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    updated = db.update_inventory_item(item_id, data_dict)
    if not updated:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    return {"message": "Inventory item updated successfully", "item": updated}


@app.delete("/api/inventory/{item_id}")
@app.delete("/inventory/{item_id}")
def delete_inventory(item_id: int):
    deleted = db.delete_inventory_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    return {"message": "Inventory item deleted successfully", "id": item_id}


# ==========================================
# IDENTIFY SURPLUS FOOD ENDPOINT
# ==========================================
@app.get("/api/surplus")
@app.get("/surplus")
def get_surplus():
    """Identifies verified surplus food items from MySQL inventory."""
    surplus_items = db.get_surplus_food_items()
    return {
        "count": len(surplus_items),
        "surplus_items": surplus_items
    }


# ==========================================
# ML KITCHEN DEMAND FORECASTING (canteen_model.joblib)
# ==========================================
@app.post("/api/demand-forecast")
@app.post("/api/demand-forecast/predict")
@app.post("/predict")
def generate_kitchen_demand(req: DemandForecastRequest):
    """
    Infers food demand using the authoritative canteen_model.joblib LightGBM dual-model.
    Derives historical lag and rolling statistics automatically from MySQL database records.
    Stores the prediction result into MySQL 'demand_forecasts'.
    """
    is_event = req.is_college_event or req.is_campus_event or False

    # Automatically derive legitimate historical lag and rolling features from database
    historical_features = db.get_historical_demand_features(
        meal_type=req.meal_type,
        menu_item=req.menu_item
    )

    try:
        prediction_result = ml.predict_kitchen_demand(
            meal_type=req.meal_type,
            attendance=req.attendance,
            hostel_attendance=req.hostel_attendance,
            dayscholar_attendance=req.dayscholar_attendance,
            temperature_c=req.temperature_c or 27.0,
            rainfall_mm=req.rainfall_mm or 0.0,
            humidity_pct=req.humidity_pct or 65.0,
            day_type=req.day_type or "weekday",
            is_weekend=req.is_weekend,
            is_holiday=req.is_holiday,
            is_exam_day=req.is_exam_day or False,
            is_college_event=is_event,
            popularity_level=req.popularity_level or 2,
            menu_item=req.menu_item,
            academic_status=req.academic_status,
            college_event=req.college_event,
            holiday_name=req.holiday_name,
            historical_features=historical_features
        )
    except RuntimeError as re:
        raise HTTPException(status_code=503, detail=str(re))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ML prediction pipeline error: {str(e)}")

    # Persist prediction to MySQL database
    logged = db.log_demand_forecast(prediction_result)
    if isinstance(logged, dict):
        prediction_result["demand_status"] = logged.get("demand_status", prediction_result.get("demand_status", "Optimal"))
        prediction_result["id"] = logged.get("id")
    return prediction_result


@app.get("/api/demand-forecast/latest")
def get_latest_demand_forecast():
    latest = db.get_latest_demand_forecast()
    if not latest:
        return {
            "predicted_demand": 0,
            "recommended_prep": 0,
            "attendance": 0,
            "weather": "Clear / Sunny",
            "demand_status": "Awaiting Prediction"
        }
    return latest


@app.get("/api/predictions")
@app.get("/predictions")
def get_predictions_history():
    latest = db.get_latest_demand_forecast()
    return {"latest": latest}


@app.post("/api/demand-forecast/{forecast_id}/actual")
def record_actual_demand_endpoint(forecast_id: int, req: ActualDemandRecordRequest):
    """Records verified post-meal actual ground truth demand into MySQL demand_forecasts."""
    try:
        updated = db.record_actual_demand(forecast_id=forecast_id, actual_demand=req.actual_demand)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Demand forecast #{forecast_id} not found.")
        return {
            "success": True,
            "message": f"Actual demand ({req.actual_demand}) recorded for forecast #{forecast_id}.",
            "forecast": updated
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record actual demand: {e}")


@app.get("/api/ml/metrics")
def get_ml_metrics():
    """Provides authentic architectural metadata for the authoritative canteen_model.joblib model."""
    status = ml.get_model_status()
    is_loaded = (status.get("model_status") == "active_canteen_model")
    return {
        "model_name": status.get("model_name", "canteen_model.joblib"),
        "framework": status.get("framework", "LightGBM Dual-Model (LGBMRegressor)"),
        "target": "dual_target: expected_demand (regression) + safe_prep (quantile alpha=0.85)",
        "status": "HEALTHY" if is_loaded else "UNAVAILABLE",
        "features_count": status.get("features_count", 19),
        "features": status.get("feature_cols", []),
        "categorical_features": status.get("categorical_features", []),
        "target_estimators": status.get("target_estimators", []),
        "evaluation_metrics": {
            "available": False,
            "message": "Offline evaluation metrics are not bundled in canteen_model.joblib. Authentic validation metrics will be computed continuously against logged actual demand."
        }
    }



# ==========================================
# NGOS & SUPPLIERS DIRECTORY
# ==========================================
@app.get("/api/ngos")
@app.get("/ngos")
def get_ngos(
    latitude: Optional[float] = Query(None, description="Current user latitude for distance sorting"),
    longitude: Optional[float] = Query(None, description="Current user longitude for distance sorting")
):
    ngos = db.get_all_ngos(latitude=latitude, longitude=longitude)
    return {"ngos": ngos}


@app.get("/api/ngos/{ngo_id}")
def get_ngo_by_id_endpoint(ngo_id: int):
    ngo = db.get_ngo_by_id(ngo_id)
    if not ngo:
        raise HTTPException(status_code=404, detail="NGO not found")
    return {"ngo": ngo}


@app.put("/api/ngos/{ngo_id}/verify")
@app.post("/api/ngos/{ngo_id}/verify")
def verify_ngo_endpoint(ngo_id: int, req: NgoVerifyRequest):
    try:
        updated = db.verify_ngo(ngo_id=ngo_id, status=req.status)
        if not updated:
            raise HTTPException(status_code=404, detail="NGO partner not found")
        return {"success": True, "message": f"NGO status successfully updated to {req.status.upper()}", "ngo": updated}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update NGO verification status: {e}")


@app.get("/api/suppliers")
@app.get("/suppliers")
def get_suppliers(
    latitude: Optional[float] = Query(None, description="Current user latitude"),
    longitude: Optional[float] = Query(None, description="Current user longitude")
):
    suppliers = db.get_all_suppliers(latitude=latitude, longitude=longitude)
    return {"suppliers": suppliers}


# ==========================================
# DONATIONS DISPATCH & STATUS
# ==========================================
@app.post("/api/donations")
@app.post("/donations")
def dispatch_donation(donation: DonationCreate):
    try:
        data = donation.dict()
        if not data.get("food_item"):
            data["food_item"] = data.get("item_name") or "Surplus Food"
        created = db.create_donation(data)
        res = {"message": "Donation request registered successfully in MySQL", "donation": created}
        if isinstance(created, dict):
            res.update({
                "id": created.get("id"),
                "status": created.get("status"),
                "item_name": created.get("item_name") or created.get("food_item")
            })
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dispatch donation: {e}")


@app.get("/api/donations")
@app.get("/donations")
def list_donations(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status: PENDING, ACCEPTED, REJECTED, COMPLETED, ALL"),
    ngo_id: Optional[int] = Query(None, description="Filter by NGO ID")
):
    user = get_authenticated_user_context(request)
    effective_ngo_id = ngo_id

    if user:
        role = (user.get("role") or "").strip().lower()
        if "ngo" in role or "relief" in role:
            # Strictly isolate to authenticated NGO's organization
            effective_ngo_id = user.get("ngo_id")

    donations = db.get_all_donations(status=status, ngo_id=effective_ngo_id)
    return {"donations": donations}


@app.get("/api/donations/{donation_id}")
@app.get("/donations/{donation_id}")
def get_donation(donation_id: int, request: Request):
    donation = db.get_donation_by_id(donation_id)
    if not donation:
        raise HTTPException(status_code=404, detail="Donation record not found.")

    user = get_authenticated_user_context(request)
    if user:
        role = (user.get("role") or "").strip().lower()
        if "ngo" in role or "relief" in role:
            auth_ngo_id = user.get("ngo_id")
            if auth_ngo_id and donation.get("ngo_id") != auth_ngo_id:
                raise HTTPException(
                    status_code=403, 
                    detail="Access denied: You do not have permission to view another organization's donation record."
                )

    return {"donation": donation}


@app.put("/api/donations/{donation_id}/status")
@app.put("/donations/{donation_id}/status")
def update_donation_state(
    donation_id: int,
    status: str = Query(..., pattern="^(PENDING|ACCEPTED|REJECTED|COMPLETED|APPROVED|DISTRIBUTED|pending|accepted|rejected|completed|approved|distributed)$")
):
    updated = db.update_donation_status(donation_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Donation record not found.")
    return {"message": f"Donation status updated to {updated['status']}", "donation": updated}


# ==========================================
# FOOD REDISTRIBUTION & INVENTORY RESERVATION ENGINE
# ==========================================
@app.post("/api/redistribution/posts")
def publish_surplus_food(post: SurplusPostCreate):
    """
    Supplier publishes surplus food for redistribution to ALL partner organizations.
    Enforces dynamic availability and notifies all partner NGOs.
    """
    try:
        created = db.publish_surplus_post(post.dict())
        return {
            "message": "Surplus food published for redistribution to all partner organizations.",
            "post": created
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish surplus food: {str(e)}")


@app.get("/api/redistribution/posts")
def get_redistribution_posts(available_only: bool = Query(False, description="Filter only posts with remaining available quantity")):
    """
    Feed of surplus food posts.
    Available to ALL authenticated partner organizations and suppliers.
    Quantities are dynamically calculated from MySQL.
    """
    if available_only:
        posts = db.get_available_donation_posts()
    else:
        posts = db.get_all_donation_posts()
    return {"posts": posts, "count": len(posts)}


@app.get("/api/redistribution/posts/{post_id}")
def get_redistribution_post(post_id: int):
    post = db.get_donation_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Surplus food post not found.")
    return {"post": post}


@app.post("/api/redistribution/requests")
@app.post("/api/donation-requests")
def submit_donation_request(req: DonationRequestCreate, request: Request):
    """
    Partner organization requests food.
    Backend validates authenticated NGO identity and strictly locks the organization_id
    and real organization_name to prevent frontend spoofing or cross-organization pollution.
    """
    try:
        user = get_authenticated_user_context(request)
        if user:
            role = (user.get("role") or "").strip().lower()
            if "ngo" in role or "relief" in role:
                auth_org_id = user.get("ngo_id")
                if auth_org_id:
                    req.organization_id = int(auth_org_id)

        # Retrieve real official organization name from MySQL ngos table or authenticated user session
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM ngos WHERE id = %s", (req.organization_id,))
            ngo_row = cursor.fetchone()
            if ngo_row and ngo_row.get("name"):
                req.organization_name = ngo_row["name"]
            elif user and user.get("organization"):
                req.organization_name = user.get("organization")

        created = db.create_donation_request(req.dict())
        return {
            "message": f"Request for {req.requested_quantity} {created['unit']} of {created['food_item']} submitted and inventory reserved.",
            "request": created
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process food request: {str(e)}")


@app.get("/api/redistribution/requests")
def list_redistribution_requests(
    request: Request,
    organization_id: Optional[int] = Query(None, description="Filter by authenticated organization ID for data isolation"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, ACCEPTED, SCHEDULED, COLLECTED, COMPLETED, REJECTED)")
):
    """
    List food redistribution requests.
    If caller is an authenticated NGO, strictly enforces their organization_id.
    If caller is supplier/canteen staff, returns incoming or filtered requests.
    """
    user = get_authenticated_user_context(request)
    effective_org_id = organization_id

    if user:
        role = (user.get("role") or "").strip().lower()
        if "ngo" in role or "relief" in role:
            # Backend source of truth: strictly enforce authenticated NGO's organization_id
            effective_org_id = user.get("ngo_id")

    if effective_org_id:
        requests = db.get_organization_requests(int(effective_org_id))
        if status and status.upper() != "ALL":
            s = status.upper().strip()
            requests = [r for r in requests if (r.get("status") or "").upper() == s]
    else:
        requests = db.get_supplier_requests(status_filter=status)

    return {"requests": requests, "count": len(requests)}


@app.put("/api/redistribution/requests/{request_id}/status")
def update_redistribution_request_status(request_id: int, payload: DonationRequestStatusUpdate):
    """
    Supplier accepts, rejects, or marks request collected/completed.
    If REJECTED: held reservation quantity is automatically restored to available inventory.
    """
    try:
        updated = db.update_donation_request_status(
            request_id=request_id,
            status=payload.status,
            pickup_date=payload.pickup_date,
            pickup_time=payload.pickup_time,
            pickup_location=payload.pickup_location,
            fulfilled_quantity=payload.fulfilled_quantity
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Redistribution request not found.")
        return {
            "message": f"Request status updated to {updated['status']}.",
            "request": updated
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update request: {str(e)}")


@app.put("/api/redistribution/requests/{request_id}/schedule")
def schedule_redistribution_pickup(request_id: int, payload: PickupScheduleRequest):
    """
    Supplier schedules pickup for an accepted donation request.
    Notifies the requesting partner organization with pickup details.
    """
    try:
        updated = db.update_donation_request_status(
            request_id=request_id,
            status="SCHEDULED",
            pickup_date=payload.pickup_date,
            pickup_time=payload.pickup_time,
            pickup_location=payload.pickup_location
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Redistribution request not found.")
        return {
            "message": f"Pickup scheduled for {payload.pickup_date} at {payload.pickup_time}.",
            "request": updated
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to schedule pickup: {str(e)}")


# ==========================================
# NOTIFICATIONS API (SEPARATE FROM STAFF ANNOUNCEMENTS)
# ==========================================
@app.get("/api/notifications")
def get_user_notifications(
    request: Request,
    role: Optional[str] = Query(None, description="Role of current user (supplier, staff, ngo)"),
    user_id: Optional[int] = Query(None, description="User ID"),
    ngo_id: Optional[int] = Query(None, description="NGO ID if role is ngo")
):
    """
    Retrieve real-time notifications for the authenticated user/organization.
    """
    user = get_authenticated_user_context(request)
    effective_role = role
    effective_user_id = user_id
    effective_ngo_id = ngo_id

    if user:
        effective_role = user.get("role")
        effective_user_id = user.get("id")
        r_clean = (effective_role or "").strip().lower()
        if "ngo" in r_clean or "relief" in r_clean:
            effective_ngo_id = user.get("ngo_id")

    res = db.get_notifications_for_user(role=effective_role, user_id=effective_user_id, ngo_id=effective_ngo_id)
    items = res.get("notifications", [])
    unread = res.get("unread_count", 0)
    return {
        "notifications": items,
        "unread_count": unread,
        "total_count": len(items)
    }


@app.put("/api/notifications/{notification_id}/read")
def mark_notification_as_read(notification_id: int):
    success = db.mark_notification_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"message": "Notification marked as read."}


@app.put("/api/notifications/read-all")
def mark_all_notifications_as_read(
    request: Request,
    role: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    ngo_id: Optional[int] = Query(None)
):
    user = get_authenticated_user_context(request)
    effective_role = role
    effective_user_id = user_id
    effective_ngo_id = ngo_id

    if user:
        effective_role = user.get("role")
        effective_user_id = user.get("id")
        r_clean = (effective_role or "").strip().lower()
        if "ngo" in r_clean or "relief" in r_clean:
            effective_ngo_id = user.get("ngo_id")

    count = db.mark_all_notifications_read(role=effective_role, user_id=effective_user_id, ngo_id=effective_ngo_id)
    return {"message": f"{count} notifications marked as read."}


# ==========================================
# LIVE ROUTING & MAP DATA
# ==========================================
@app.get("/map-data")
def map_data(
    latitude: float = Query(12.8718, description="Latitude (default Mangalore)"),
    longitude: float = Query(74.9204, description="Longitude (default Mangalore)"),
    radius_km: float = Query(35.0, description="Search radius in km")
):
    ngos = db.get_all_ngos(latitude=latitude, longitude=longitude)
    suppliers = db.get_all_suppliers(latitude=latitude, longitude=longitude)

    # Filter within radius
    nearby_ngos = [n for n in ngos if n["distance_km"] <= radius_km]
    nearby_suppliers = [s for s in suppliers if s["distance_km"] <= radius_km]

    # Format smart pairings
    smart_matches = []
    if nearby_suppliers and nearby_ngos:
        for s in nearby_suppliers[:3]:
            best_ngo = min(nearby_ngos, key=lambda n: n["distance_km"])
            smart_matches.append({
                "from": s["name"],
                "from_coords": {"lat": float(s["latitude"]), "lon": float(s["longitude"])},
                "to": best_ngo["name"],
                "to_coords": {"lat": float(best_ngo["latitude"]), "lon": float(best_ngo["longitude"])},
                "to_need_level": best_ngo["need_level"],
                "route_distance_km": round(db.haversine_distance(float(s["latitude"]), float(s["longitude"]), float(best_ngo["latitude"]), float(best_ngo["longitude"])), 1),
                "items_available": s.get("available_items", [])
            })

    return {
        "user_location": {"latitude": latitude, "longitude": longitude, "label": "Your Active Location"},
        "nearby_ngos": nearby_ngos[:6],
        "surplus_locations": nearby_suppliers[:6],
        "smart_matches": smart_matches,
        "summary": {
            "total_ngos_in_radius": len(nearby_ngos),
            "total_surplus_in_radius": len(nearby_suppliers),
            "search_radius_km": radius_km
        }
    }


# ==========================================
# ANNOUNCEMENTS ENDPOINTS
# ==========================================
@app.get("/api/announcements")
def list_announcements(audience: Optional[str] = None):
    return {"announcements": db.get_all_announcements(audience=audience)}


@app.post("/api/announcements")
def create_announcement(ann: AnnouncementCreate):
    created = db.add_announcement(ann.dict())
    return {"message": "Announcement created successfully.", "announcement": created}


# ==========================================
# SECURE RESTRICTED STATIC ASSET SERVING
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ALLOWED_STATIC_FILES = {
    "": ("index.html", "text/html"),
    "index.html": ("index.html", "text/html"),
    "styles.css": ("styles.css", "text/css"),
    "app.js": ("app.js", "application/javascript"),
}


@app.get("/")
@app.get("/index.html")
def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"), media_type="text/html")


@app.get("/styles.css")
def serve_styles():
    return FileResponse(os.path.join(BASE_DIR, "styles.css"), media_type="text/css")


@app.get("/app.js")
def serve_script():
    return FileResponse(os.path.join(BASE_DIR, "app.js"), media_type="application/javascript")


@app.get("/{file_path:path}")
def serve_restricted_static(file_path: str):
    """
    Restricted static file endpoint.
    Explicitly prevents public exposure of sensitive files:
    .env, python sources (*.py), SQL backups (*.sql), model artifacts (*.joblib, *.pkl),
    .git, .venv, quarantine, or arbitrary filesystem directories.
    """
    clean_path = file_path.strip().lstrip("/\\")
    if clean_path in ALLOWED_STATIC_FILES:
        filename, media_type = ALLOWED_STATIC_FILES[clean_path]
        full_path = os.path.join(BASE_DIR, filename)
        if os.path.exists(full_path):
            return FileResponse(full_path, media_type=media_type)
    raise HTTPException(status_code=404, detail="Resource not found or access restricted.")



if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    is_dev = os.getenv("ENVIRONMENT", "development").lower() == "development"
    print(f"\n[Serviqo AI] Starting FastAPI Server on http://{host}:{port} ...")
    uvicorn.run("main:app", host=host, port=port, reload=is_dev)
