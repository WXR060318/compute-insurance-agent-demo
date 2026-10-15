"""Exercise the running HTTP server with a dedicated DEMO_DB_PATH.

Run after starting a QA instance: .venv/bin/python scripts/smoke_api.py
The script creates simulation records in that server's database.
"""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

BASE = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8765")
checks = []


def request(method, path, payload=None, expected=200):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = Request(BASE + path, data=body, headers={"Content-Type": "application/json"}, method=method)
    try:
        response = urlopen(req, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        assert response.status == expected, (path, response.status, raw.decode(errors="replace")[:500])
        return json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw


def check(label, condition):
    assert condition, label
    checks.append(label)


def evaluate(**updates):
    payload = dict(company_id="xinghe", scenario_id="surge", minute=30, budget=None, min_quality=98, sort_by="cost")
    payload.update(updates)
    return request("POST", "/api/evaluate", payload)


health = request("GET", "/api/health")
check("真实服务健康检查", health["status"] == "ok" and health["simulation"] is True)
catalog = request("GET", "/api/catalog")
check("企业与场景目录", len(catalog["companies"]) == 3 and len(catalog["scenarios"]) == 5)
main = evaluate()
check("主案例缺口与卡时", main["metrics"]["peak_gap"] == 4 and main["metrics"]["shortage_card_hours"] == 8)
check("主案例成本与差价", main["recommendation"]["cost"] == 96 and main["recommendation"]["extra_cost"] == 32)
check("最低成本推荐A", main["recommendation"]["supplier_id"] == "a")
check("同快照计算可复现", evaluate()["snapshot_id"] == main["snapshot_id"])
budget = evaluate(budget=80)
check("预算不足保留缺口", budget["recommendation"]["status"] == "unresolved" and budget["recommendation"]["remaining_cards"] == 4)
quality = evaluate(sort_by="quality")
check("质量优先改变推荐", quality["recommendation"]["supplier_id"] == "e" and quality["recommendation"]["cost"] == 116)
normal = evaluate(scenario_id="normal")
check("平稳场景不采购", normal["risk"]["level"] == "low" and normal["recommendation"]["status"] == "not_needed")
insufficient = evaluate(scenario_id="insufficient")
check("供应不足保留缺口", insufficient["recommendation"]["status"] == "unresolved" and insufficient["recommendation"]["remaining_cards"] > 0)
stale = evaluate(scenario_id="stale")
check("过期数据停止预测和推荐", stale["risk"]["level"] == "unknown" and stale["metrics"]["peak_gap"] is None and stale["suppliers"] == [])
recovered = evaluate(minute=180)
check("16点高峰结束后恢复", recovered["recommendation"]["status"] == "not_needed" and recovered["metrics"]["peak_gap"] == 0)
request("POST", "/api/evaluate", {"company_id": "missing"}, expected=422)
request("POST", "/api/evaluate", {"minute": 241}, expected=422)
request("POST", "/api/evaluate", {"budget": -1}, expected=422)
checks.append("无效企业、时间和预算返回422")

key = "smoke-" + str(uuid4())
payload = dict(snapshot_id=main["snapshot_id"], supplier_id="a", idempotency_key=key)
plan = request("POST", "/api/plans", payload)
again = request("POST", "/api/plans", payload)
check("重复生成预案幂等", plan["id"] == again["id"])
request("POST", "/api/plans", {**payload, "supplier_id": "e"}, expected=409)
checks.append("同幂等键不同内容返回409")
confirmed = request("POST", f"/api/plans/{plan['id']}/confirm", {"reviewer": "HTTP验收操作员"})
again = request("POST", f"/api/plans/{plan['id']}/confirm", {"reviewer": "HTTP验收操作员"})
check("人工模拟确认可重复且不重复写入", confirmed["status"] == "simulation_confirmed" and confirmed["confirmed_at"] == again["confirmed_at"])
plans = request("GET", "/api/plans")["plans"]
check("历史记录经HTTP可读取", any(item["id"] == plan["id"] for item in plans))
for fmt in ("json", "html", "csv"):
    exported = request("GET", f"/api/plans/{plan['id']}/export?format={fmt}")
    check(f"{fmt.upper()}处置单下载", len(exported) > 10 if isinstance(exported, bytes) else bool(exported))
request("POST", "/api/plans", {"snapshot_id": stale["snapshot_id"], "supplier_id": "a", "idempotency_key": str(uuid4())}, expected=422)
checks.append("失效快照不能创建资源预案")

reply = request("POST", "/api/chat", {"snapshot_id": main["snapshot_id"], "message": "为什么不选更便宜的B？"})
check("离线助手如实标记并提供工具记录", reply["mode"] == "offline" and bool(reply["trace"]) and bool(reply["answer"]))
reply = request("POST", "/api/chat", {"snapshot_id": main["snapshot_id"], "message": "预算只有80元"})
check("助手预算约束实际改变计算", reply["evaluation"]["input"]["budget"] == 80 and reply["evaluation"]["recommendation"]["status"] == "unresolved")
print(json.dumps({"passed": len(checks), "checks": checks, "base_url": BASE}, ensure_ascii=False, indent=2))
