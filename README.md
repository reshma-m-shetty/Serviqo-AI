# Serviqo AI — Zero-Waste Food Supply & Demand Intelligence Platform

Serviqo AI is an intelligent sustainability and food supply ecosystem engineered to eliminate institutional food waste. The platform bridges institutional kitchens (canteens, catering halls, campus dining) with charitable relief networks (NGOs, shelters, food recovery volunteers) by pairing **dual-model LightGBM machine learning demand forecasting** with a **real-time surplus food redistribution and reservation engine**.

---

## 🌟 Key Capabilities

### 1. 🧠 Dual-Model ML Demand Intelligence
* **Expected Portion Demand ($\text{L2}$ Regression):** Forecasts the exact baseline portions expected to be consumed based on dynamic operational parameters.
* **85th-Percentile Safe Prep Buffer (Quantile Regression $\alpha = 0.85$):** Forecasts conservative kitchen prep targets protecting against unexpected diner surges while avoiding wasteful overproduction.
* **19 Meteorological & Operational Features:** Automatically processes meal type, hostel vs. day-scholar attendance, campus footfall, temperature, rainfall, and calendar holidays.
* **Automated Feedback Loop & History:** Evaluates database-derived 7-day lags (`Demand_Lag_7_Days`, `Rolling_7D_Mean`) and logs ground-truth actual consumption (`record_actual_demand`) for continuous retraining.

### 2. 🍲 Food Redistribution & Dynamic Reservation Engine
* **Concurrent Food Reservation:** Prevents race conditions and double-booking using MySQL 8.0 ACID transactions with row-level locks (`SELECT ... FOR UPDATE`).
* **Live Quantity Tracking:** Real-time visibility into `published_quantity`, `reserved_pending`, `reserved_allocated`, and `remaining_available_quantity`.
* **Atomic Inventory Synchronization:** Automatically deducts physical inventory when donations are fulfilled and distributed.

### 3. 🏢 Multi-Tenant NGO Relief Portal
* **Strict Tenant Data Isolation:** Scoped queries guarantee relief partners only view their own requests, allocation metrics, and pickup histories.
* **Audience-Filtered Announcements:** Segregates internal kitchen notices (e.g. chef directives) from external volunteer recovery broadcasts.
* **Geospatial Distance Matching:** Uses the Haversine formula to sort nearby shelters and surplus suppliers by physical road proximity (km).

### 4. 📦 Smart Kitchen Inventory & Dynamic Markdown
* **Dynamic Expiry Pricing:** Automatically marks down prices for near-expiry items to incentivize redistribution before spoilage.
* **Health & Threshold Monitoring:** Categorizes stock into `AVAILABLE`, `SURPLUS`, `LOW STOCK`, and `EXPIRING SOON`.

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend API** | [FastAPI](https://fastapi.tiangolo.com/), Python 3.10+, Uvicorn, Pydantic v2 |
| **Database** | [MySQL 8.0](https://www.mysql.com/) with pure thread-safe connection pooling (`MySQLPool`) & SSL/TLS cloud support |
| **Machine Learning** | [LightGBM](https://lightgbm.readthedocs.io/), Scikit-Learn, Pandas, NumPy, Joblib |
| **Frontend** | Vanilla ES6+ JavaScript, Semantic HTML5, CSS Variables, Phosphor Icons |
| **Authentication** | Cryptographic password hashing (`bcrypt`), role-based access control (RBAC) |

---

## 📁 Repository Structure

```
c:\Serviqo Ai\
├── main.py                  # FastAPI REST API endpoints, routing & middleware
├── database.py              # Pure MySQL 8.0 connection pool, relational schemas & CRUD
├── ml_engine.py             # Dual LightGBM inference engine & automated lag extractor
├── canteen_model.joblib     # Production LightGBM dual-model artifact (6.6 MB)
├── index.html               # Frontend Single-Page Application (Canteen & NGO workspaces)
├── app.js                   # Application state, authentication & reactive UI logic
├── styles.css               # Design system, glassmorphism & responsive dark/light themes
├── requirements.txt         # Python project dependencies
├── .env.example             # Template for local & cloud environment variables
├── tests/                   # Automated test suites
│   ├── test_phase1_pipeline.py       # ML architecture, lag features & health tests
│   ├── test_phase2_verification.py   # Reservation engine, state machine & transaction tests
│   ├── test_ngo_data_isolation.py    # Multi-tenant NGO isolation tests
│   └── test_e2e_verification.py      # End-to-end full lifecycle tests
└── README.md                # Project documentation
```

---

## 🚀 Getting Started

### 1. Prerequisites
* **Python 3.10+**
* **MySQL 8.0 Server** (Local or cloud-hosted instance such as Aiven, TiDB Cloud, or AWS RDS)

### 2. Environment Configuration
Create a `.env` file in the project root:
```ini
# Server Settings
HOST=0.0.0.0
PORT=8000
ENVIRONMENT=development

# MySQL Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=serviqo_ai

# SSL/TLS Mode (REQUIRED for cloud providers like TiDB/Aiven, or PREFERRED/DISABLED for local)
DB_SSL_MODE=PREFERRED
DB_SSL_CA=

# Connection Pooling
DB_POOL_SIZE=10
DB_CONNECT_TIMEOUT=15
```

### 3. Installation
```bash
# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Running the Application
```bash
# Start FastAPI server with live reload
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Once started, open **`http://localhost:8000`** in your browser.
Interactive API documentation is accessible at **`http://localhost:8000/docs`**.

---

## 🧪 Testing & Verification

Run the test suite to verify ML inference, database integrity, and tenant isolation:
```bash
# Run core pipeline & ML model verification
python tests/test_phase1_pipeline.py

# Run food redistribution & reservation engine verification
python tests/test_phase2_verification.py
```

---

## 🔒 Security & Data Integrity
* **Zero-Leakage Tenancy:** Scoped queries ensure NGOs can never view or modify another organization's donation dispatches.
* **Parametrized SQL Queries:** 100% protection against SQL injection vulnerabilities across all database operations.
* **Strict Transport Security:** Native SSL/TLS support for secure connections to cloud-hosted databases.
=======
# Serviqo-AI
A food demand prediction model and connects the surplus food to the NGO and needed people without wasting of food

