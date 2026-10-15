from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app import engine, storage


def test_snapshot_and_plan_are_preserved_and_idempotent(isolated_db):
    evaluation = engine.evaluate({})
    storage.save_snapshot(evaluation)
    saved = storage.get_snapshot(evaluation["snapshot_id"])
    saved["company"]["name"] = "caller mutation"
    assert storage.get_snapshot(evaluation["snapshot_id"])["company"]["name"] == "星河模型"
    plan = storage.create_plan(evaluation["snapshot_id"], "a", "same-request")
    assert plan == storage.create_plan(evaluation["snapshot_id"], "a", "same-request")
    assert plan["status"] == "draft"
    assert plan["evaluation"] == evaluation
    confirmed = storage.confirm_plan(plan["id"], "甲")
    assert confirmed["status"] == "simulation_confirmed"
    assert storage.confirm_plan(plan["id"], "乙") == confirmed
    assert storage.list_plans() == [confirmed]
    assert storage.get_snapshot(evaluation["snapshot_id"])["suppliers"] == evaluation["suppliers"]


def test_concurrent_idempotency_produces_one_record(isolated_db):
    evaluation = engine.evaluate({})
    storage.save_snapshot(evaluation)
    def submit(_):
        return storage.create_plan(evaluation["snapshot_id"], "a", "concurrent")
    with ThreadPoolExecutor(max_workers=6) as executor:
        plans = list(executor.map(submit, range(12)))
    assert len({plan["id"] for plan in plans}) == 1
    assert len(storage.list_plans()) == 1


def test_idempotency_collision_and_ineligible_supplier_are_rejected(isolated_db):
    evaluation = engine.evaluate({})
    storage.save_snapshot(evaluation)
    storage.create_plan(evaluation["snapshot_id"], "a", "used-key")
    with pytest.raises(HTTPException) as collision:
        storage.create_plan(evaluation["snapshot_id"], "e", "used-key")
    assert collision.value.status_code == 409
    for supplier in ["b", "c", "d"]:
        with pytest.raises(HTTPException) as rejected:
            storage.create_plan(evaluation["snapshot_id"], supplier, "bad-" + supplier)
        assert rejected.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        storage.create_plan(evaluation["snapshot_id"], "other", "unknown")
    assert unknown.value.status_code == 422


def test_unmatched_and_missing_records_cannot_be_confirmed(isolated_db):
    with pytest.raises(HTTPException) as missing:
        storage.create_plan("missing", "a", "missing")
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as missing_plan:
        storage.confirm_plan("missing", "甲")
    assert missing_plan.value.status_code == 404
    evaluation = engine.evaluate({"budget": 80})
    storage.save_snapshot(evaluation)
    with pytest.raises(HTTPException) as unresolved:
        storage.create_plan(evaluation["snapshot_id"], "a", "unresolved")
    assert unresolved.value.status_code == 409
