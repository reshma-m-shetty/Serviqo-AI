# Serviqo AI — Cloud Database Migration & Production Deployment Guide

This guide details the complete procedure for migrating Serviqo AI's database to a cloud-hosted MySQL 8.0 service, deploying the FastAPI backend, connecting the frontend, and maintaining reliability and disaster recovery.

---

## 1. Cloud-Hosted MySQL Provider Selection

Serviqo AI requires pure MySQL 8.0 compatibility, InnoDB ACID transaction guarantees, row-level locking (`SELECT ... FOR UPDATE`), and persistent TLS/SSL connections.

### Evaluated Providers

| Provider | MySQL Compatibility | SSL/TLS Support | Persistence & Backups | Free Tier / Cost | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Aiven for MySQL** | Pure MySQL 8.0 | Mandatory TLS (`ca.pem` provided) | Dedicated persistent storage, automatic daily backups, point-in-time recovery | Free trial ($300 credit), then ~$19/month | **Recommended for Production** |
| **TiDB Cloud (Serverless)** | MySQL 8.0 Wire-Compatible | Mandatory TLS | Distributed persistent storage, automated cluster backups | **Free Tier: 5 GB storage, 50M Request Units/month** | **Recommended for Prototyping & Zero-Cost Hosting** |
| **AWS RDS for MySQL** | Pure MySQL 8.0 | Configurable SSL (`rds-ca-rsa2048-g1`) | Multi-AZ snapshots, automated rolling backups | 12 months free tier (db.t3.micro), then ~$15/mo | Enterprise / AWS Native |
| **DigitalOcean Managed MySQL** | Pure MySQL 8.0 | Mandatory TLS | Dedicated SSD storage, daily automated backups | From $15/month | Simple Managed Alternative |

> **Limitations & Constraints to Keep in Mind**:
> - Free hosting plans (e.g., TiDB Serverless, Render Free tier) may pause after inactivity or limit concurrent connection pools.
> - Ensure `DB_POOL_SIZE` is set appropriately (`5` to `10`) to avoid exceeding provider connection limits.
> - SSL/TLS is strictly required by cloud providers. Ensure `DB_SSL_MODE=REQUIRED` is set.

---

## 2. Environment Variables & Secret Configuration

Never commit credentials to version control. Set these in your hosting dashboard's Environment Variables (or `.env` on a secure VPS).

Use [`.env.example`](file:///c:/Serviqo%20Ai/.env.example) as your reference template:

```ini
# Environment
ENVIRONMENT=production
HOST=0.0.0.0
PORT=8000

# Cloud MySQL Database Configuration
DB_HOST=your-cloud-mysql-instance.example.com
DB_PORT=3306
DB_USER=serviqo_user
DB_PASSWORD=your_strong_cloud_db_password
DB_NAME=serviqo_ai

# SSL/TLS Security
DB_SSL_MODE=REQUIRED
# Path to CA certificate if required by provider (leave empty for default verification)
DB_SSL_CA=

# Connection Pooling & Health Tuning
DB_POOL_SIZE=10
DB_CONNECT_TIMEOUT=15

# Security & CORS
SECRET_KEY=your_random_32_character_hex_secret_key_here
ALLOWED_ORIGINS=https://your-frontend-domain.com,http://localhost:3000
```

---

## 3. Database Migration Procedure

### Step 3.1: Pre-Migration Backup (Completed & Verified)
A recoverable backup of the existing MySQL 8.0 database was generated and preserved before making changes:
- `backup_serviqo_ai.sql` (99 KB, contains all 10 tables and real operational records).

To create a new backup at any time:
```bash
mysqldump -h localhost -P 3306 -u root -p serviqo_ai > backup_serviqo_ai.sql
```

### Step 3.2: Provision the Cloud MySQL Database
1. In your cloud provider's console (e.g., Aiven or TiDB Cloud), create a MySQL service.
2. Create the target database: `serviqo_ai` (with charset `utf8mb4`).
3. Create a dedicated database user (e.g., `serviqo_user`) with `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `INDEX`, `ALTER` permissions on `serviqo_ai.*`. Do **not** use the administrative root user in production.

### Step 3.3: Execute the Automated Migration Pipeline
Run the provided migration utility [`migrate_to_cloud.py`](file:///c:/Serviqo%20Ai/migrate_to_cloud.py):

```bash
# Set your target cloud credentials
export CLOUD_DB_HOST="your-cloud-mysql.example.com"
export CLOUD_DB_PORT="3306"
export CLOUD_DB_USER="serviqo_user"
export CLOUD_DB_PASSWORD="your_strong_password"
export CLOUD_DB_NAME="serviqo_ai"
export DB_SSL_MODE="REQUIRED"

python migrate_to_cloud.py
```

The script will:
1. Connect securely via TLS to your cloud database.
2. Initialize the relational tables and indexes using non-administrative DDL.
3. Transfer all user accounts, active inventory, NGOs, suppliers, donations, and ML demand forecasts safely.
4. Verify 100% row-count equality across all 10 tables.
5. Leave your original local database completely untouched.

---

## 4. Backend Server Deployment

### Startup Command
The production entry point is `main:app` running via Uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Deployment Options

#### Option A: Render (Web Service)
1. Link your GitHub repository to Render.
2. Select **Python 3** environment.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add your Cloud MySQL credentials under **Environment Variables**.
6. Set Health Check Path to `/health`.

#### Option B: Railway
1. Create a new project and connect the repository.
2. Railway detects the [`Procfile`](file:///c:/Serviqo%20Ai/Procfile) and starts `uvicorn main:app --host 0.0.0.0 --port $PORT`.
3. Configure the cloud MySQL environment variables under **Variables**.

#### Option C: Docker Container
Build and run anywhere (AWS ECS, GCP Cloud Run, DigitalOcean App Platform):
```bash
docker build -t serviqo-ai:latest .
docker run -p 8000:8000 --env-file .env serviqo-ai:latest
```

---

## 5. Frontend Configuration

Serviqo AI's frontend [`app.js`](file:///c:/Serviqo%20Ai/app.js) automatically resolves the backend API URL:

1. **Same-Origin Hosting (Default)**: If the frontend is served by FastAPI or deployed on the same domain behind a reverse proxy (e.g., Nginx), it uses `window.location.origin` with zero configuration.
2. **Decoupled Frontend Hosting (Vercel / Netlify)**: If you host the static frontend on Vercel or Netlify while running the backend on Render/Railway, define the backend URL in `index.html` before `app.js` is loaded:
   ```html
   <script>
     window.__SERVIQO_API_URL__ = "https://your-serviqo-backend.onrender.com";
   </script>
   ```
3. **CORS Configuration**: On the backend, ensure `ALLOWED_ORIGINS` includes your frontend domain:
   ```ini
   ALLOWED_ORIGINS=https://serviqo-ai.vercel.app
   ```

---

## 6. Health Checks & Outage Recovery

### Health Check Endpoint
- Path: `GET /health` or `GET /api/health`
- Response:
  ```json
  {
    "status": "healthy",
    "database": {
      "connected": true,
      "status": "connected",
      "tables_count": 10,
      "message": "All 10 required tables present and healthy."
    },
    "service": "Serviqo AI Backend",
    "version": "3.0"
  }
  ```
- Does not expose passwords, hostnames, or sensitive credentials.
- Returns HTTP `503 Service Unavailable` if database connectivity is lost.

### Outage Recovery & Rollback Procedure
If a cloud database outage occurs:
1. **Connection Failures**: The connection pool automatically attempts reconnection (`conn.ping(reconnect=True)`) on broken or dropped sockets.
2. **Restoring from Cloud Backup**: Use your provider's Point-in-Time Recovery or restore the latest automated daily backup via the provider console.
3. **Restoring from Local Backup**:
   ```bash
   mysql -h your-cloud-host -P 3306 -u serviqo_user -p serviqo_ai < backup_serviqo_ai.sql
   ```
4. **Switching Database Host**:
   Update `DB_HOST` in the hosting environment variables and redeploy. The application will initialize connections to the new host without requiring code changes.
