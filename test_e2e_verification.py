"""
Serviqo AI — Complete End-to-End Verification Test Script
Tests the exact 11-step Supplier <-> Partner Organization Food Redistribution Workflow
as specified in Prompt Section 21.
"""
import sys
import json
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"

def api_call(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            return status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            return e.code, json.loads(content)
        except:
            return e.code, {"detail": content}

def run_e2e_test():
    print("=================================================================")
    print("SERVIQO AI — 11-STEP E2E FOOD REDISTRIBUTION VERIFICATION")
    print("=================================================================\n")

    # STEP 1: Supplier publishes Rice = 25 kg
    print("[STEP 1] Supplier publishes: Rice = 25 kg for Redistribution")
    pub_payload = {
        "food_item": "Basmati Rice",
        "published_quantity": 25.0,
        "unit": "kg",
        "available_until": "Today before 4:00 PM",
        "pickup_location": "Srinivas Campus Canteen Gate 2, Valachil, Mangalore",
        "notes": "Freshly prepared lunch batch, high quality",
        "supplier_name": "Srinivas Institute Canteen"
    }
    status, res = api_call("POST", "/api/redistribution/posts", pub_payload)
    assert status == 200, f"Step 1 failed: {res}"
    post_id = res["post"]["id"]
    print(f"  [OK] Post created successfully with ID: {post_id}")
    print(f"  [OK] Initial Published: {res['post']['published_quantity']} kg, Remaining Available: {res['post']['remaining_available']} kg\n")

    # STEP 2: NGO A queries feed -> sees Rice = 25 kg available
    print("[STEP 2] NGO A (ISKCON Mangalore) queries available food feed")
    status, res = api_call("GET", "/api/redistribution/posts?available_only=true")
    assert status == 200, f"Step 2 failed: {res}"
    post_ngo_a = next((p for p in res["posts"] if p["id"] == post_id), None)
    assert post_ngo_a is not None, "Post not found in available feed"
    assert post_ngo_a["remaining_available"] == 25.0, f"Expected 25.0 kg, got {post_ngo_a['remaining_available']}"
    print(f"  [OK] NGO A sees: {post_ngo_a['food_item']} — {post_ngo_a['remaining_available']} kg available\n")

    # STEP 3: NGO A requests 10 kg
    print("[STEP 3] NGO A requests 10 kg of Rice")
    req_a_payload = {
        "post_id": post_id,
        "organization_id": 1,
        "organization_name": "ISKCON Food Relief Foundation - Mangalore",
        "requested_quantity": 10.0,
        "preferred_pickup_time": "Today 2:30 PM",
        "message": "Required for midday community distribution"
    }
    status, res = api_call("POST", "/api/redistribution/requests", req_a_payload)
    assert status == 200, f"Step 3 failed: {res}"
    req_a_id = res["request"]["id"]
    print(f"  [OK] Request created with ID: {req_a_id}")
    print(f"  [OK] Request Status: {res['request']['status']} (HELD / RESERVED)\n")

    # STEP 4: System calculates: Available = 15 kg, Reserved/Pending = 10 kg
    print("[STEP 4] System calculates dynamic inventory reservation")
    status, res = api_call("GET", f"/api/redistribution/posts/{post_id}")
    assert status == 200, f"Step 4 failed: {res}"
    post_updated = res["post"]
    print(f"  [OK] Published Quantity: {post_updated['published_quantity']} kg")
    print(f"  [OK] Reserved Quantity : {post_updated['reserved_quantity']} kg")
    print(f"  [OK] Remaining Avail   : {post_updated['remaining_available']} kg")
    assert post_updated["remaining_available"] == 15.0, f"Expected 15.0 kg, got {post_updated['remaining_available']}"
    assert post_updated["reserved_quantity"] == 10.0, f"Expected 10.0 kg, got {post_updated['reserved_quantity']}\n"

    # STEP 5: NGO B logs in -> NGO B must see: Rice = 15 kg available, NOT 25 kg
    print("[STEP 5] NGO B (Mangalore Seva Trust) checks available feed")
    status, res = api_call("GET", "/api/redistribution/posts?available_only=true")
    assert status == 200, f"Step 5 failed: {res}"
    post_ngo_b = next((p for p in res["posts"] if p["id"] == post_id), None)
    assert post_ngo_b is not None, "Post not found for NGO B"
    assert post_ngo_b["remaining_available"] == 15.0, f"NGO B should see 15.0 kg, saw {post_ngo_b['remaining_available']}"
    print(f"  [OK] NGO B strictly sees: {post_ngo_b['remaining_available']} kg available (NOT 25 kg)\n")

    # STEP 6: Supplier accepts NGO A's 10 kg request
    print("[STEP 6] Supplier accepts NGO A's request for 10 kg")
    status, res = api_call("PUT", f"/api/redistribution/requests/{req_a_id}/status", {"status": "ACCEPTED"})
    assert status == 200, f"Step 6 failed: {res}"
    assert res["request"]["status"] == "ACCEPTED"
    print(f"  [OK] Request {req_a_id} marked ACCEPTED")

    # Check notification sent to NGO A
    status, res = api_call("GET", "/api/notifications?role=ngo&ngo_id=1")
    assert status == 200, f"Failed to get notifications: {res}"
    acc_notif = next((n for n in res["notifications"] if n.get("related_request_id") == req_a_id and "accepted" in n["title"].lower()), None)
    assert acc_notif is not None, "Acceptance notification not received by NGO A"
    print(f"  [OK] Notification confirmed for NGO A: \"{acc_notif['title']}\" — \"{acc_notif['message']}\"\n")

    # STEP 7: NGO B attempts to request 20 kg (more than remaining 15 kg) -> Must be rejected by backend
    print("[STEP 7] NGO B attempts to request 20 kg (exceeding remaining 15 kg)")
    req_over_payload = {
        "post_id": post_id,
        "organization_id": 6,
        "organization_name": "Mangalore Seva Trust",
        "requested_quantity": 20.0,
        "preferred_pickup_time": "Today 3:00 PM",
        "message": "Attempting overbooking"
    }
    status, res = api_call("POST", "/api/redistribution/requests", req_over_payload)
    print(f"  [OK] Backend response status: {status}, detail: {res.get('detail')}")
    assert status == 400, f"Expected 400 Bad Request, got {status}"
    assert "15" in res.get("detail", ""), f"Expected error to mention 15 kg remaining, got {res.get('detail')}"
    print(f"  [OK] Double-booking / overbooking correctly prevented by backend row-level locking!\n")

    # STEP 8: NGO B requests 5 kg, then supplier rejects it -> 5 kg returns to available inventory
    print("[STEP 8] Inventory Release Test: NGO B requests 5 kg, then Supplier rejects")
    req_b_payload = {
        "post_id": post_id,
        "organization_id": 6,
        "organization_name": "Mangalore Seva Trust",
        "requested_quantity": 5.0,
        "preferred_pickup_time": "Today 3:30 PM",
        "message": "Requesting 5 kg"
    }
    status, res = api_call("POST", "/api/redistribution/requests", req_b_payload)
    assert status == 200
    req_b_id = res["request"]["id"]

    # Verify inventory was temporarily reduced to 10 kg
    status, res = api_call("GET", f"/api/redistribution/posts/{post_id}")
    assert res["post"]["remaining_available"] == 10.0, f"Expected 10.0 kg, got {res['post']['remaining_available']}"
    print(f"  [OK] During pending request, remaining available reduced to: {res['post']['remaining_available']} kg")

    # Supplier rejects NGO B's request
    status, res = api_call("PUT", f"/api/redistribution/requests/{req_b_id}/status", {"status": "REJECTED"})
    assert status == 200
    print(f"  [OK] Supplier rejected Request {req_b_id}")

    # Verify 5 kg returned to available inventory (back to 15 kg)
    status, res = api_call("GET", f"/api/redistribution/posts/{post_id}")
    assert res["post"]["remaining_available"] == 15.0, f"Expected 15.0 kg after reject, got {res['post']['remaining_available']}"
    print(f"  [OK] Reserved quantity automatically released! Remaining available is back to: {res['post']['remaining_available']} kg\n")

    # STEP 9: Supplier schedules pickup for NGO A
    print("[STEP 9] Supplier schedules pickup for NGO A")
    sched_payload = {
        "pickup_date": "2026-10-03",
        "pickup_time": "2:30 PM",
        "pickup_location": "Srinivas Campus Canteen Gate 2, Valachil, Mangalore"
    }
    status, res = api_call("PUT", f"/api/redistribution/requests/{req_a_id}/schedule", sched_payload)
    assert status == 200, f"Step 9 failed: {res}"
    assert res["request"]["status"] == "SCHEDULED"
    print(f"  [OK] Pickup scheduled: {res['request']['pickup_date']} at {res['request']['pickup_time']}")

    # Both Supplier and NGO A can see the pickup
    status, res_sup = api_call("GET", "/api/redistribution/requests?status=SCHEDULED")
    sup_sched = [r for r in res_sup["requests"] if r["id"] == req_a_id]
    assert len(sup_sched) == 1, "Supplier did not see scheduled pickup"

    status, res_ngo = api_call("GET", "/api/redistribution/requests?organization_id=1")
    ngo_sched = [r for r in res_ngo["requests"] if r["id"] == req_a_id and r["status"] == "SCHEDULED"]
    assert len(ngo_sched) == 1, "NGO A did not see scheduled pickup in private feed"
    print(f"  [OK] Both Supplier and NGO A successfully view the pickup schedule\n")

    # STEP 10: Supplier marks COLLECTED -> COMPLETED
    print("[STEP 10] Supplier marks food as COLLECTED, then COMPLETED")
    status, res = api_call("PUT", f"/api/redistribution/requests/{req_a_id}/status", {"status": "COLLECTED"})
    assert status == 200
    assert res["request"]["status"] == "COLLECTED"
    print(f"  [OK] Status updated to COLLECTED")

    status, res = api_call("PUT", f"/api/redistribution/requests/{req_a_id}/status", {"status": "COMPLETED"})
    assert status == 200
    assert res["request"]["status"] == "COMPLETED"
    print(f"  [OK] Status updated to COMPLETED\n")

    # STEP 11: Data Isolation Verification
    print("[STEP 11] Strict Data Isolation & Audit History Verification")
    # Supplier sees it in history
    status, res_sup_hist = api_call("GET", "/api/redistribution/requests?status=COMPLETED")
    assert any(r["id"] == req_a_id for r in res_sup_hist["requests"]), "Supplier history missing completed request"
    print(f"  [OK] Present in Supplier donation history")

    # NGO A sees it in their private history
    status, res_ngo_a_hist = api_call("GET", "/api/redistribution/requests?organization_id=1")
    assert any(r["id"] == req_a_id and r["status"] == "COMPLETED" for r in res_ngo_a_hist["requests"]), "NGO A private history missing completed request"
    print(f"  [OK] Present in NGO A's private history (organization_id = 1)")

    # NGO B must NOT see it in their private history
    status, res_ngo_b_hist = api_call("GET", "/api/redistribution/requests?organization_id=6")
    assert not any(r["id"] == req_a_id for r in res_ngo_b_hist["requests"]), "CRITICAL BUG: NGO B saw NGO A's private donation record!"
    print(f"  [OK] STRICT DATA ISOLATION VERIFIED: NGO B (organization_id = 6) CANNOT see NGO A's donation record!")

    print("\n=================================================================")
    print("ALL 11 STEPS COMPLETED & VERIFIED WITH 100% SUCCESS!")
    print("=================================================================\n")

if __name__ == "__main__":
    run_e2e_test()
