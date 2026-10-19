"""
Comprehensive verification test for NGO organization data isolation in Serviqo AI
Tests:
1. Multi-tenant database query isolation
2. Two separate authenticated NGOs (NGO A = ISKCON id:1, NGO B = Sri Ramakrishna Ashram id:6)
3. Request creation and isolated dashboard metric increments
4. Security & anti-spoofing boundary: client cannot change URL/body to access another NGO's data
5. New NGO registration receives unique organization ID and zero-leakage view
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from main import app
import database as db

client = TestClient(app)

def run_ngo_isolation_test():
    print("=" * 70)
    print("SERVIQO AI - NGO MULTI-TENANT ORGANIZATION DATA ISOLATION TEST")
    print("=" * 70)

    # -------------------------------------------------------------
    # STEP 1: Authenticate NGO A and NGO B
    # -------------------------------------------------------------
    print("\n[STEP 1] Authenticating NGO A and NGO B...")
    res_a = client.post("/api/auth/login", json={"email": "ngo@serviqo.ai", "password": "ngo123"})
    assert res_a.status_code == 200, f"NGO A login failed: {res_a.text}"
    user_a = res_a.json()["user"]
    print(f"  NGO A Authenticated: {user_a['name']} | Org: {user_a['organization']} | NGO ID: {user_a['ngo_id']}")
    assert user_a["ngo_id"] == 1
    assert "ISKCON" in user_a["organization"]

    res_b = client.post("/api/auth/login", json={"email": "ashram@serviqo.ai", "password": "ngo123"})
    assert res_b.status_code == 200, f"NGO B login failed: {res_b.text}"
    user_b = res_b.json()["user"]
    print(f"  NGO B Authenticated: {user_b['name']} | Org: {user_b['organization']} | NGO ID: {user_b['ngo_id']}")
    assert user_b["ngo_id"] == 6
    assert "Ramakrishna" in user_b["organization"]

    headers_a = {"X-User-Email": user_a["email"]}
    headers_b = {"X-User-Email": user_b["email"]}

    # -------------------------------------------------------------
    # STEP 2: Verify Initial Dashboard Counts are Isolated
    # -------------------------------------------------------------
    print("\n[STEP 2] Verifying initial isolated dashboard KPIs...")
    dash_a = client.get("/api/dashboard/ngo", headers=headers_a).json()
    dash_b = client.get("/api/dashboard/ngo", headers=headers_b).json()

    print(f"  NGO A ({dash_a['ngo_name']}):")
    print(f"    Total Requests     : {dash_a['kpis']['total_requests']}")
    print(f"    Pending Requests   : {dash_a['kpis']['pending_requests']}")
    print(f"    Completed Requests : {dash_a['kpis']['completed_requests']}")
    print(f"    Food Received      : {dash_a['kpis']['food_received_kg']} kg")

    print(f"  NGO B ({dash_b['ngo_name']}):")
    print(f"    Total Requests     : {dash_b['kpis']['total_requests']}")
    print(f"    Pending Requests   : {dash_b['kpis']['pending_requests']}")
    print(f"    Completed Requests : {dash_b['kpis']['completed_requests']}")
    print(f"    Food Received      : {dash_b['kpis']['food_received_kg']} kg")

    assert dash_a["organization_id"] == 1
    assert dash_b["organization_id"] == 6
    assert dash_a["ngo_name"] != dash_b["ngo_name"]
    # Verify counts are organization-specific, not globally aggregated
    assert dash_a["kpis"]["total_requests"] != dash_b["kpis"]["total_requests"] or dash_a["kpis"]["total_requests"] == 0

    init_total_a = dash_a["kpis"]["total_requests"]
    init_pending_a = dash_a["kpis"]["pending_requests"]
    init_total_b = dash_b["kpis"]["total_requests"]
    init_pending_b = dash_b["kpis"]["pending_requests"]

    # -------------------------------------------------------------
    # STEP 3: Verify Request Lists are Strictly Isolated
    # -------------------------------------------------------------
    print("\n[STEP 3] Verifying request lists are isolated...")
    reqs_a = client.get("/api/redistribution/requests", headers=headers_a).json()["requests"]
    reqs_b = client.get("/api/redistribution/requests", headers=headers_b).json()["requests"]

    print(f"  NGO A request count: {len(reqs_a)}")
    for r in reqs_a[:3]:
        print(f"    * ID: {r['id']} | Org ID: {r['organization_id']} | Item: {r['food_item']} | Status: {r['status']}")
        assert r["organization_id"] == 1, f"Data leak! Found non-NGO A record in NGO A list: {r}"

    print(f"  NGO B request count: {len(reqs_b)}")
    for r in reqs_b[:3]:
        print(f"    * ID: {r['id']} | Org ID: {r['organization_id']} | Item: {r['food_item']} | Status: {r['status']}")
        assert r["organization_id"] == 6, f"Data leak! Found non-NGO B record in NGO B list: {r}"

    a_ids = {r["id"] for r in reqs_a}
    b_ids = {r["id"] for r in reqs_b}
    overlap = a_ids.intersection(b_ids)
    assert len(overlap) == 0, f"Data leak! Overlapping request IDs between NGO A and NGO B: {overlap}"
    print("  ✓ Zero ID overlap between NGO A and NGO B requests.")

    # -------------------------------------------------------------
    # STEP 4: NGO A Creates a Food Request
    # -------------------------------------------------------------
    # Fetch available surplus posts with sufficient quantity
    posts = client.get("/api/redistribution/posts", headers=headers_a).json()["posts"]
    valid_posts = [p for p in posts if float(p.get("remaining_available_quantity", 0)) >= 5.0]
    if valid_posts:
        test_post = valid_posts[0]
    else:
        pub_res = client.post("/api/redistribution/posts", json={
            "food_item": "Test Kitchen Khichdi",
            "published_quantity": 25.0,
            "unit": "kg",
            "available_until": "Today 5:00 PM",
            "pickup_location": "Srinivas Canteen Gate 2",
            "notes": "Fresh test batch"
        })
        assert pub_res.status_code == 200, f"Failed to publish test surplus post: {pub_res.text}"
        test_post = pub_res.json()["post"]

    payload_a = {
        "post_id": test_post["id"],
        "organization_id": 1,
        "organization_name": "ISKCON Food Relief Foundation - Mangalore",
        "requested_quantity": 2.0,
        "preferred_pickup_time": "Today 3:00 PM",
        "message": "NGO A test relief order"
    }
    create_res_a = client.post("/api/redistribution/requests", json=payload_a, headers=headers_a)
    assert create_res_a.status_code == 200, f"Request creation failed: {create_res_a.text}"
    req_a_created = create_res_a.json()["request"]
    req_a_id = req_a_created["id"]
    print(f"  ✓ NGO A created request #{req_a_id} for {req_a_created['food_item']} ({req_a_created['requested_quantity']} {req_a_created['unit']})")

    # Verify NGO A's counts increased
    dash_a_after = client.get("/api/dashboard/ngo", headers=headers_a).json()
    assert dash_a_after["kpis"]["total_requests"] == init_total_a + 1
    assert dash_a_after["kpis"]["pending_requests"] == init_pending_a + 1
    print(f"  ✓ NGO A dashboard updated: Total = {dash_a_after['kpis']['total_requests']}, Pending = {dash_a_after['kpis']['pending_requests']}")

    # -------------------------------------------------------------
    # STEP 5: NGO B Logs in and Verifies NGO B Cannot See NGO A's New Request
    # -------------------------------------------------------------
    print("\n[STEP 5] NGO B inspects dashboard and requests...")
    dash_b_after = client.get("/api/dashboard/ngo", headers=headers_b).json()
    assert dash_b_after["kpis"]["total_requests"] == init_total_b, "NGO B total requests should NOT change when NGO A creates a request!"
    assert dash_b_after["kpis"]["pending_requests"] == init_pending_b, "NGO B pending requests should NOT change when NGO A creates a request!"
    print(f"  ✓ NGO B dashboard unchanged: Total = {dash_b_after['kpis']['total_requests']}, Pending = {dash_b_after['kpis']['pending_requests']}")

    reqs_b_after = client.get("/api/redistribution/requests", headers=headers_b).json()["requests"]
    b_ids_after = {r["id"] for r in reqs_b_after}
    assert req_a_id not in b_ids_after, f"SECURITY VIOLATION! NGO B can see NGO A's new request #{req_a_id}!"
    print(f"  ✓ NGO B request feed strictly isolated: does NOT contain request #{req_a_id}")

    # -------------------------------------------------------------
    # STEP 6: NGO B Creates its Own Food Request
    # -------------------------------------------------------------
    print("\n[STEP 6] NGO B creates its own food request...")
    payload_b = {
        "post_id": test_post["id"],
        "organization_id": 6,
        "organization_name": "Sri Ramakrishna Ashram & Orphanage",
        "requested_quantity": 1.5,
        "preferred_pickup_time": "Tomorrow 10:00 AM",
        "message": "NGO B test relief order"
    }
    create_res_b = client.post("/api/redistribution/requests", json=payload_b, headers=headers_b)
    assert create_res_b.status_code == 200, f"Request creation failed: {create_res_b.text}"
    req_b_created = create_res_b.json()["request"]
    req_b_id = req_b_created["id"]
    print(f"  ✓ NGO B created request #{req_b_id} for {req_b_created['food_item']} ({req_b_created['requested_quantity']} {req_b_created['unit']})")

    # Verify NGO B's counts increased
    dash_b_after_b = client.get("/api/dashboard/ngo", headers=headers_b).json()
    assert dash_b_after_b["kpis"]["total_requests"] == init_total_b + 1
    assert dash_b_after_b["kpis"]["pending_requests"] == init_pending_b + 1
    print(f"  ✓ NGO B dashboard updated: Total = {dash_b_after_b['kpis']['total_requests']}, Pending = {dash_b_after_b['kpis']['pending_requests']}")

    # -------------------------------------------------------------
    # STEP 7: NGO A Returns and Verifies NGO A Cannot See NGO B's Request
    # -------------------------------------------------------------
    print("\n[STEP 7] NGO A re-inspects dashboard and requests...")
    dash_a_final = client.get("/api/dashboard/ngo", headers=headers_a).json()
    assert dash_a_final["kpis"]["total_requests"] == init_total_a + 1
    assert dash_a_final["kpis"]["pending_requests"] == init_pending_a + 1

    reqs_a_final = client.get("/api/redistribution/requests", headers=headers_a).json()["requests"]
    a_ids_final = {r["id"] for r in reqs_a_final}
    assert req_b_id not in a_ids_final, f"SECURITY VIOLATION! NGO A can see NGO B's request #{req_b_id}!"
    print(f"  ✓ NGO A request feed strictly isolated: does NOT contain request #{req_b_id}")

    # -------------------------------------------------------------
    # STEP 8: Security Attack & Anti-Spoofing Tests
    # -------------------------------------------------------------
    print("\n[STEP 8] Security attack tests (Attempting to bypass data isolation via parameters)...")
    
    # Attack 1: NGO B passes ?ngo_id=1 in dashboard query
    attack_dash = client.get("/api/dashboard/ngo?ngo_id=1", headers=headers_b).json()
    assert attack_dash["organization_id"] == 6, "Security Failure! Backend must not allow query param to override authenticated NGO identity!"
    assert "Ramakrishna" in attack_dash["ngo_name"], "Security Failure! Returned NGO A's name to NGO B!"
    assert attack_dash["kpis"]["total_requests"] == init_total_b + 1
    print("  ✓ Attack 1 Blocked: GET /api/dashboard/ngo?ngo_id=1 returned ONLY NGO B's data.")

    # Attack 2: NGO B passes ?organization_id=1 in requests query
    attack_reqs = client.get("/api/redistribution/requests?organization_id=1", headers=headers_b).json()["requests"]
    for r in attack_reqs:
        assert r["organization_id"] == 6, f"Security Failure! Found NGO 1 record when NGO B queried ?organization_id=1: {r}"
    print("  ✓ Attack 2 Blocked: GET /api/redistribution/requests?organization_id=1 returned ONLY NGO B's records.")

    # Attack 3: NGO B attempts to create request with organization_id = 1 in request body
    attack_post_payload = {
        "post_id": test_post["id"],
        "organization_id": 1,
        "organization_name": "ISKCON Food Relief Foundation - Mangalore",
        "requested_quantity": 1.0,
        "preferred_pickup_time": "Today 5:00 PM",
        "message": "Forged request attempt"
    }
    attack_post_res = client.post("/api/redistribution/requests", json=attack_post_payload, headers=headers_b)
    attack_created = attack_post_res.json()["request"]
    assert attack_created["organization_id"] == 6, f"Security Failure! Backend accepted forged organization_id: {attack_created}"
    assert "Ramakrishna" in attack_created["organization_name"]
    print("  ✓ Attack 3 Blocked: POST /api/redistribution/requests with forged organization_id=1 was locked to authenticated NGO 6.")

    # Attack 4: NGO B attempts to view NGO A's donation record directly
    # Find a donation belonging to NGO 1
    dons_a = client.get("/api/donations", headers=headers_a).json()["donations"]
    assert len(dons_a) > 0
    ngo_a_don_id = dons_a[0]["id"]
    attack_don_res = client.get(f"/api/donations/{ngo_a_don_id}", headers=headers_b)
    assert attack_don_res.status_code == 403, f"Security Failure! Expected 403 Forbidden for cross-NGO donation view, got: {attack_don_res.status_code}"
    print(f"  ✓ Attack 4 Blocked: GET /api/donations/{ngo_a_don_id} returned 403 Forbidden for unauthorized NGO.")

    # -------------------------------------------------------------
    # STEP 9: New NGO Registration Isolation
    # -------------------------------------------------------------
    print("\n[STEP 9] Registering a new NGO organization...")
    import random
    rand_suffix = random.randint(1000, 9999)
    new_email = f"coordinator_{rand_suffix}@sevasangha.org"
    new_org = f"Seva Sangha Trust #{rand_suffix}"

    reg_payload = {
        "name": "Dr. Raghuveer Shetty",
        "email": new_email,
        "password": "password123",
        "role": "NGO",
        "organization": new_org,
        "phone": "+91 98450 77889",
        "address": "Kadri Hills, Mangalore",
        "capacity_persons": 180,
        "need_level": "high"
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 200, f"Registration failed: {reg_res.text}"
    new_user = reg_res.json()["user"]
    new_ngo_id = new_user["ngo_id"]
    print(f"  ✓ Registered new NGO: {new_user['organization']} | Assigned NGO ID: {new_ngo_id}")
    assert new_ngo_id not in (1, 6), f"New NGO was improperly assigned existing ID {new_ngo_id}!"

    headers_new = {"X-User-Email": new_email}
    new_dash = client.get("/api/dashboard/ngo", headers=headers_new).json()
    print(f"  New NGO Dashboard: Org = {new_dash['ngo_name']} | Total Requests = {new_dash['kpis']['total_requests']}")
    assert new_dash["organization_id"] == new_ngo_id
    assert new_dash["kpis"]["total_requests"] == 0, "New NGO should start with 0 requests!"
    assert new_dash["kpis"]["pending_requests"] == 0
    assert new_dash["kpis"]["food_received_kg"] == 0.0

    new_reqs = client.get("/api/redistribution/requests", headers=headers_new).json()["requests"]
    assert len(new_reqs) == 0, "New NGO must not see any other NGO's requests!"
    print("  ✓ New NGO has clean zero-leakage view and cannot see other organizations' data.")

    print("\n" + "=" * 70)
    print("ALL NGO MULTI-TENANT ISOLATION TESTS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_ngo_isolation_test()
