import requests, uuid, json

base = "http://localhost:8000"
sid = str(uuid.uuid4())

print("=== 1. Health ===")
r = requests.get(f"{base}/health")
print(r.status_code, r.json())

print("\n=== 2. History (empty session) ===")
r = requests.get(f"{base}/api/chat/history/{sid}")
print(r.status_code, r.json())

print("\n=== 3. Chat - hello ===")
r = requests.post(f"{base}/api/chat", json={"message": "hello", "session_id": sid}, timeout=30)
d = r.json()
print("status:", r.status_code)
print("answer:", d.get("answer", "")[:80])
print("followups:", d.get("followups", []))
print("message_id:", d.get("message_id"))
print("tokenUsage:", d.get("tokenUsage"))

print("\n=== 4. Chat - college query ===")
r2 = requests.post(f"{base}/api/chat", json={"message": "what departments are in MSAJCE", "session_id": sid, "bypass_cache": True}, timeout=60)
d2 = r2.json()
print("status:", r2.status_code)
print("answer:", d2.get("answer", "")[:120])
print("followups:", d2.get("followups", []))
print("message_id:", d2.get("message_id"))

print("\n=== 5. History after chats ===")
r3 = requests.get(f"{base}/api/chat/history/{sid}")
msgs = r3.json()
print("History count:", len(msgs))
for m in msgs:
    role = m.get("role")
    content = m.get("content", "")[:50]
    msg_id = m.get("id")
    print(f"  [{role}] {content}  id={msg_id}")
