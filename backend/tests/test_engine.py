from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app import data, engine


def test_main_case_is_exact_and_pure(isolated_db):
    payload = {"company_id": "xinghe", "scenario_id": "surge", "minute": 30}
    original = deepcopy(payload)
    result = engine.evaluate(payload)
    assert payload == original
    assert not isolated_db.exists()
    assert result == engine.evaluate(payload)
    assert result["metrics"] == {"capacity": 8, "current_demand": 7, "predicted_peak": 12, "peak_gap": 4, "shortage_card_hours": 8, "first_shortage_at": "14:00", "shortage_duration_minutes": 120, "utilization": 87.5, "headroom": 1, "lead_minutes": 30}
    assert {key: result["recommendation"][key] for key in ["supplier_id", "cost", "baseline_cost", "extra_cost", "remaining_cards"]} == {"supplier_id": "a", "cost": 96, "baseline_cost": 64, "extra_cost": 32, "remaining_cards": 0}
    suppliers = {row["id"]: row for row in result["suppliers"]}
    assert suppliers["a"]["rank"] == 1
    assert suppliers["e"]["rank"] == 2
    assert not suppliers["b"]["eligible"] and "90分钟" in "".join(suppliers["b"]["reasons"])
    assert suppliers["c"]["partial"] and not suppliers["c"]["eligible"]
    assert suppliers["d"]["cost"] is None and not suppliers["d"]["eligible"]


@pytest.mark.parametrize("company", ["xinghe", "haichuan", "yunling"])
@pytest.mark.parametrize("scenario", ["surge", "normal", "outage", "insufficient", "stale"])
def test_all_catalog_pairs(company, scenario):
    result = engine.evaluate({"company_id": company, "scenario_id": scenario})
    assert result["company"]["id"] == company
    assert len(result["chart"]) == 49
    assert result["chart"][0]["minute"] == -30
    assert result["chart"][-1]["minute"] == 210
    assert result["meta"]["simulation"] is True


def test_quality_priority_and_budget_are_hard_constraints():
    quality = engine.evaluate({"sort_by": "quality"})
    assert quality["recommendation"]["supplier_id"] == "e"
    assert quality["recommendation"]["cost"] == 116
    limited = engine.evaluate({"sort_by": "quality", "budget": 100})
    assert limited["recommendation"]["supplier_id"] == "a"
    unresolved = engine.evaluate({"budget": 80})
    assert unresolved["recommendation"]["status"] == "unresolved"
    assert unresolved["recommendation"]["remaining_cards"] == 4
    assert unresolved["recommendation"]["cost"] is None
    assert not any(row["selected"] for row in unresolved["suppliers"])


def test_deadline_includes_deployment_and_boundary_is_inclusive():
    assert engine.evaluate({"minute": 35})["recommendation"]["supplier_id"] == "a"
    result = engine.evaluate({"minute": 40})
    assert result["recommendation"]["supplier_id"] == "e"
    assert engine.evaluate({"minute": 45})["recommendation"]["status"] == "unresolved"


def test_partial_resource_is_never_presented_as_full_coverage():
    result = engine.evaluate({"scenario_id": "insufficient"})
    assert result["metrics"]["peak_gap"] == 10
    assert result["recommendation"]["status"] == "unresolved"
    assert result["recommendation"]["covered_cards"] == 0
    assert result["recommendation"]["remaining_cards"] == 10
    assert not any(row["eligible"] for row in result["suppliers"])


def test_stale_data_suppresses_forecasts_candidates_and_costs():
    result = engine.evaluate({"scenario_id": "stale"})
    assert result["risk"]["level"] == "unknown"
    assert result["risk"]["data_quality"] == "stale"
    assert result["metrics"]["predicted_peak"] is None
    assert result["metrics"]["shortage_card_hours"] is None
    assert result["recommendation"]["status"] == "data_unavailable"
    assert result["recommendation"]["cost"] is None
    assert result["suppliers"] == []
    assert all(point["forecast"] is None for point in result["chart"])
    assert all(point["demand"] is None for point in result["chart"] if point["minute"] > -15)


def test_remaining_window_excludes_elapsed_demand_and_end_is_exclusive():
    at_15 = engine.evaluate({"minute": 120})
    assert at_15["metrics"]["shortage_card_hours"] == 4
    assert at_15["metrics"]["shortage_duration_minutes"] == 60
    assert at_15["metrics"]["utilization"] == 100
    at_16 = engine.evaluate({"minute": 180})
    assert at_16["metrics"]["peak_gap"] == 0
    assert at_16["metrics"]["shortage_card_hours"] == 0
    assert at_16["recommendation"]["status"] == "not_needed"
    assert engine.evaluate({"minute": 240})["metrics"]["peak_gap"] == 0


def test_forecast_never_reads_future_observations(monkeypatch):
    original = engine.observed_demand
    calls = []
    def audited(company, scenario_id, minute):
        calls.append(minute)
        assert minute <= 30
        return original(company, scenario_id, minute)
    monkeypatch.setattr(engine, "observed_demand", audited)
    engine.evaluate({"minute": 30})
    assert calls and max(calls) == 30


def test_supply_window_and_quote_expiry_are_checked(monkeypatch):
    suppliers = deepcopy(data.SUPPLIERS)
    suppliers[0]["_available_until_minute"] = 120
    suppliers[4]["_quote_valid_until_minute"] = 20
    monkeypatch.setattr(data, "SUPPLIERS", suppliers)
    result = engine.evaluate({})
    rows = {row["id"]: row for row in result["suppliers"]}
    assert "无法覆盖完整缺口时段" in "".join(rows["a"]["reasons"])
    assert not rows["e"]["quote_valid"]
    assert result["recommendation"]["status"] == "unresolved"


def test_money_is_decimal_and_rounded_once(monkeypatch):
    suppliers = deepcopy(data.SUPPLIERS)
    suppliers[0]["price_per_card_hour"] = "12.13"
    monkeypatch.setattr(data, "SUPPLIERS", suppliers)
    result = engine.evaluate({"budget": Decimal("97.04")})
    assert result["recommendation"]["cost"] == 97.04
    assert result["recommendation"]["extra_cost"] == 33.04
    assert engine.evaluate({"budget": Decimal("97.03")})["recommendation"]["status"] == "unresolved"


@pytest.mark.parametrize("payload", [{"company_id": "unknown"}, {"scenario_id": "other"}, {"minute": -5}, {"minute": 245}, {"minute": 31}, {"minute": 30.0}, {"budget": 0}, {"budget": -1}, {"budget": "NaN"}, {"min_quality": 101}, {"sort_by": "random"}, {"extra": True}])
def test_engine_validates_inputs(payload):
    with pytest.raises(ValidationError):
        engine.evaluate(payload)
