import csv
import io

import pytest

from app import storage


def test_catalog_health_and_evaluation(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["app"] == "compute-insurance-demo"
    assert health["simulation"] is True
    catalog = client.get("/api/catalog").json()
    assert len(catalog["companies"]) == 3 and len(catalog["scenarios"]) == 5
    response = client.post("/api/evaluate", json={})
    assert response.status_code == 200
    evaluation = response.json()
    assert evaluation["recommendation"]["cost"] == 96
    assert storage.get_snapshot(evaluation["snapshot_id"]) == evaluation


@pytest.mark.parametrize("payload", [{"company_id": "bad"}, {"scenario_id": "bad"}, {"minute": 1}, {"minute": 245}, {"minute": True}, {"budget": 0}, {"budget": 1_000_001}, {"min_quality": -1}, {"min_quality": 101}, {"sort_by": "bad"}, {"unknown": 1}])
def test_invalid_inputs_return_422(client, payload):
    assert client.post("/api/evaluate", json=payload).status_code == 422


def test_plan_confirmation_and_all_exports(client):
    evaluation = client.post("/api/evaluate", json={}).json()
    payload = {"snapshot_id": evaluation["snapshot_id"], "supplier_id": "a", "idempotency_key": "api-main"}
    plan = client.post("/api/plans", json=payload).json()
    assert client.post("/api/plans", json=payload).json() == plan
    # This deliberately includes HTML and a CSV formula marker.
    reviewer = '=HYPERLINK("https://example.invalid","<script>alert(1)</script>")'
    confirmed = client.post(f"/api/plans/{plan['id']}/confirm", json={"reviewer": reviewer})
    assert confirmed.status_code == 200
    confirmed = confirmed.json()
    assert confirmed["status"] == "simulation_confirmed"
    assert client.post(f"/api/plans/{plan['id']}/confirm", json={"reviewer": "二次"}).json() == confirmed
    exported_json = client.get(f"/api/plans/{plan['id']}/export?format=json")
    assert exported_json.json() == confirmed
    assert "attachment" in exported_json.headers["content-disposition"]
    exported_html = client.get(f"/api/plans/{plan['id']}/export?format=html")
    assert "<script>" not in exported_html.text
    assert "&lt;script&gt;" in exported_html.text
    exported_csv = client.get(f"/api/plans/{plan['id']}/export?format=csv")
    rows = list(csv.reader(io.StringIO(exported_csv.content.decode("utf-8-sig"))))
    assert len(rows) == 2 and rows[1][0] == plan["id"]
    assert rows[1][9].startswith("'=HYPERLINK")
    assert client.get(f"/api/plans/{plan['id']}/export?format=pdf").status_code == 422
    assert client.get("/api/plans/missing/export").status_code == 404


def test_cors_allows_loopback_only(client):
    headers = {"Origin": "http://127.0.0.1:5175", "Access-Control-Request-Method": "POST"}
    assert client.options("/api/evaluate", headers=headers).status_code == 200
    headers["Origin"] = "https://evil.example"
    assert client.options("/api/evaluate", headers=headers).status_code == 400


def test_alternative_eligible_supplier_export_uses_plan_cost(client):
    evaluation = client.post("/api/evaluate", json={}).json()
    plan = client.post("/api/plans", json={"snapshot_id": evaluation["snapshot_id"], "supplier_id": "e", "idempotency_key": "choose-alternative"}).json()
    assert plan["cost"] == 116
    exported = client.get(f"/api/plans/{plan['id']}/export?format=html").text
    assert "选择恒稳云，预计采购成本116元" in exported
    assert "原始自动推荐" in exported


def test_unknown_api_does_not_fall_through_to_frontend(client):
    assert client.get("/api/not-a-route").status_code == 404


def test_compiled_frontend_hosting_keeps_api_priority(client, monkeypatch, tmp_path):
    from app import main
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>测试前端</title>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log('demo')", encoding="utf-8")
    monkeypatch.setattr(main, "DIST_PATH", dist)
    assert "测试前端" in client.get("/").text
    assert "测试前端" in client.get("/overview").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/api/health").json()["status"] == "ok"


def test_chat_and_plan_validation(client):
    assert client.post("/api/chat", json={"snapshot_id": "x", "message": " "}).status_code == 422
    assert client.post("/api/chat", json={"snapshot_id": "x", "message": "a" * 1201}).status_code == 422
    assert client.post("/api/plans", json={"snapshot_id": "x", "supplier_id": "a", "idempotency_key": " "}).status_code == 422
    assert client.post("/api/plans/missing/confirm", json={"reviewer": " "}).status_code == 422
