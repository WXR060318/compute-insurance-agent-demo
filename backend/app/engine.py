"""Pure replay evaluation. Forecasting only reads observations at or before now."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from . import data
from .schemas import EvaluateRequest

STEP_MINUTES = 5
HORIZON_MINUTES = 180


def money(value: Decimal) -> int | float:
    """Round monetary presentation to cents after all Decimal arithmetic."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(rounded) if rounded == rounded.to_integral_value() else float(rounded)


def observed_demand(company: dict, scenario_id: str, minute: int) -> int:
    """Synthetic observations; callers must not request timestamps after now."""
    capacity = company["capacity"]
    baseline = capacity - 1 if minute >= 0 else capacity - 2
    if scenario_id in {"surge", "insufficient"} and 60 <= minute < 180:
        return capacity + (10 if scenario_id == "insufficient" else 4)
    if scenario_id == "normal":
        return max(1, baseline - 1)
    return max(1, baseline)


def known_capacity(company: dict, scenario_id: str, minute: int) -> int:
    # The outage scenario is a currently-known maintenance window, not an
    # unknowable future failure. The plan is visible before 14:00.
    reduction = 2 if scenario_id == "outage" and 60 <= minute < 180 else 0
    return company["capacity"] - reduction


def forecast_window(company: dict, scenario_id: str, now_minute: int, latest_baseline: int) -> list[dict]:
    """Half-open five-minute intervals [now, now+180), using known plans only."""
    intervals = []
    # The stable-load estimate strips the known scheduled job from the latest
    # observation; otherwise that temporary job would leak beyond its end.
    baseline = min(latest_baseline, company["capacity"] - 1)
    for minute in range(now_minute, now_minute + HORIZON_MINUTES, STEP_MINUTES):
        demand = baseline
        if scenario_id in {"surge", "insufficient"} and 60 <= minute < 180:
            demand = company["capacity"] + (10 if scenario_id == "insufficient" else 4)
        capacity = known_capacity(company, scenario_id, minute)
        intervals.append({"minute": minute, "demand": demand, "capacity": capacity, "gap": max(0, demand - capacity)})
    return intervals


def _clock(minute: int) -> str:
    return (data.BASE_TIME + timedelta(minutes=minute)).strftime("%H:%M")


def _supply_window_evidence() -> str:
    windows = {(item["_available_from_minute"], item["_available_until_minute"], item["_quote_valid_until_minute"]) for item in data.SUPPLIERS}
    if len(windows) == 1:
        start, end, expiry = next(iter(windows))
        detail = f"本组模拟资源可供{_clock(start)}–{_clock(end)}、报价有效至{_clock(expiry)}。"
    else:
        detail = "；".join(f"{item['name']}：可供{_clock(item['_available_from_minute'])}–{_clock(item['_available_until_minute'])}，报价至{_clock(item['_quote_valid_until_minute'])}" for item in data.SUPPLIERS) + "。"
    return "逐家校验就绪时间、报价有效期，以及资源可供窗口是否覆盖整个缺口区间；" + detail + "超出自有容量的需求进入队列，GPU利用率最高显示100%。"


def _input(request: EvaluateRequest) -> dict:
    return {
        "company_id": request.company_id,
        "scenario_id": request.scenario_id,
        "minute": request.minute,
        "budget": None if request.budget is None else float(request.budget),
        "min_quality": request.min_quality,
        "sort_by": request.sort_by,
    }


def _empty_recommendation(status: str, gap: int | None = None) -> dict:
    return {"supplier_id": None, "supplier_name": None, "cost": None, "baseline_cost": None, "extra_cost": None, "covered_cards": 0 if gap is not None else None, "remaining_cards": gap, "summary": "", "status": status}


def _supplier_rows(company: dict, request: EvaluateRequest, intervals: list[dict], peak_gap: int, lead: int) -> list[dict]:
    rows = []
    for supplier in data.SUPPLIERS:
        row = {key: deepcopy(value) for key, value in supplier.items() if not key.startswith("_")}
        rate = Decimal(supplier["price_per_card_hour"])
        row["price_per_card_hour"] = money(rate)
        row["total_ready_minutes"] = row["ready_minutes"] + row["deployment_minutes"]
        row["partial"] = 0 < row["available_cards"] < peak_gap
        reasons = []
        compatible = row["gpu_model"] == company["gpu_model"]
        if not compatible:
            reasons.append("GPU型号不兼容，演示不进行跨型号折算")
        if row["partial"]:
            reasons.append(f"仅可供{row['available_cards']}张，无法完整覆盖{peak_gap}张缺口")
        if row["available_cards"] <= 0:
            reasons.append("暂无可供资源")
        if row["quality"] < request.min_quality:
            reasons.append(f"模拟服务评分{row['quality']}低于要求{request.min_quality:g}")
        if row["total_ready_minutes"] > lead:
            reasons.append(f"就绪与部署合计需{row['total_ready_minutes']}分钟，距首个缺口仅{lead}分钟")
        row["quote_valid"] = row["quote_valid"] and request.minute <= supplier["_quote_valid_until_minute"]
        if not row["quote_valid"]:
            reasons.append("报价已失效")
        required = [item for item in intervals if item["gap"] > 0]
        if required[0]["minute"] < supplier["_available_from_minute"] or required[-1]["minute"] + STEP_MINUTES > supplier["_available_until_minute"]:
            reasons.append(f"资源可供窗口{_clock(supplier['_available_from_minute'])}–{_clock(supplier['_available_until_minute'])}无法覆盖完整缺口时段")
        covered_hours = Decimal(sum(min(item["gap"], row["available_cards"]) * STEP_MINUTES for item in intervals)) / Decimal(60)
        raw_cost = covered_hours * rate
        row["cost"] = money(raw_cost) if compatible else None
        if compatible and request.budget is not None and Decimal(str(row["cost"])) > request.budget:
            reasons.append(f"预计成本{money(raw_cost)}元超出预算{money(request.budget)}元")
        row.update(eligible=not reasons, reasons=reasons, rank=None, selected=False)
        rows.append(row)
    eligible = [row for row in rows if row["eligible"]]
    if request.sort_by == "quality":
        eligible.sort(key=lambda row: (-row["quality"], Decimal(str(row["cost"])), row["total_ready_minutes"], row["id"]))
    else:
        eligible.sort(key=lambda row: (Decimal(str(row["cost"])), -row["quality"], row["total_ready_minutes"], row["id"]))
    for rank, row in enumerate(eligible, start=1):
        row["rank"] = rank
        row["selected"] = rank == 1
    return sorted(rows, key=lambda row: (row["rank"] is None, row["rank"] or 999, row["id"]))


def evaluate(payload: dict) -> dict:
    request = EvaluateRequest.model_validate(payload)
    params = _input(request)
    company = deepcopy(next(item for item in data.COMPANIES if item["id"] == request.company_id))
    scenario = deepcopy(next(item for item in data.SCENARIOS if item["id"] == request.scenario_id))
    now = data.BASE_TIME + timedelta(minutes=request.minute)
    stale = request.scenario_id == "stale"
    data_time = now - timedelta(minutes=45) if stale else now
    # Versioned data is part of snapshot identity, so changing a simulated
    # supplier never overwrites an earlier reviewable evaluation.
    identity = {"input": params, "rule_version": data.RULE_VERSION, "company": company, "suppliers": data.SUPPLIERS}
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    result = {
        "snapshot_id": f"s-{digest}", "input": params, "company": company, "scenario": scenario, "now": now.isoformat(),
        "metrics": {}, "risk": {}, "chart": [], "suppliers": [], "recommendation": {}, "evidence": [],
        "service_rules": deepcopy(data.SERVICE_RULES),
        "meta": {"simulation": True, "rule_version": data.RULE_VERSION, "forecast_method": "近期趋势与当前已知计划任务", "data_time": data_time.isoformat(), "note": "研究演示数据，采购成本非保险赔款"},
    }
    last_observation = request.minute - 45 if stale else request.minute
    observations = {minute: observed_demand(company, request.scenario_id, minute) for minute in range(request.minute - 60, last_observation + 1, STEP_MINUTES)}
    current = observations.get(request.minute)
    current_capacity = known_capacity(company, request.scenario_id, request.minute)
    if stale:
        result["metrics"] = {"capacity": current_capacity, "current_demand": None, "predicted_peak": None, "peak_gap": None, "shortage_card_hours": None, "first_shortage_at": None, "shortage_duration_minutes": None, "utilization": None, "headroom": None, "lead_minutes": None}
        result["risk"] = {"level": "unknown", "label": "数据失效", "reason": "企业指标已45分钟未更新，超过15分钟阈值，停止预测与资源匹配", "data_quality": "stale", "actions": ["恢复数据连接并更新指标后重新评估"]}
        rec = _empty_recommendation("data_unavailable")
        rec["summary"] = "数据失效，当前无法形成可靠的缺口与采购建议"
        result["recommendation"] = rec
        result["evidence"] = [{"id": "E-01", "title": "数据时效", "text": f"最后更新时间{data_time.strftime('%H:%M')}，数据年龄45分钟；未来预测与候选资源已停用。"}]
        for minute in range(request.minute - 60, request.minute + HORIZON_MINUTES + 1, STEP_MINUTES):
            result["chart"].append({"time": _clock(minute), "minute": minute, "demand": observations.get(minute), "forecast": None, "capacity": known_capacity(company, request.scenario_id, minute) if minute <= last_observation else None})
        return result

    assert current is not None
    intervals = forecast_window(company, request.scenario_id, request.minute, current)
    gaps = [item for item in intervals if item["gap"] > 0]
    peak_gap = max(item["gap"] for item in intervals)
    peak = max(item["demand"] for item in intervals)
    card_hours = Decimal(sum(item["gap"] * STEP_MINUTES for item in intervals)) / Decimal(60)
    lead = gaps[0]["minute"] - request.minute if gaps else None
    result["metrics"] = {"capacity": current_capacity, "current_demand": current, "predicted_peak": peak, "peak_gap": peak_gap, "shortage_card_hours": money(card_hours), "first_shortage_at": _clock(gaps[0]["minute"]) if gaps else None, "shortage_duration_minutes": len(gaps) * STEP_MINUTES, "utilization": min(100, round(current / current_capacity * 100, 1)), "headroom": max(0, current_capacity - current), "lead_minutes": lead}
    if not gaps:
        result["risk"] = {"level": "low", "label": "供需平稳", "reason": "未来180分钟内，当前已知计划需求未超过可调度容量", "data_quality": "valid", "actions": ["持续观察需求与可用容量"]}
        rec = _empty_recommendation("not_needed", 0)
        rec.update(cost=0, baseline_cost=0, extra_cost=0, summary="当前无需准备额外算力")
    else:
        result["risk"] = {"level": "high" if peak_gap / current_capacity >= 0.25 or lead <= 30 else "medium", "label": "需提前准备" if lead > 0 else "缺口已出现", "reason": f"当前已知计划最高需要{peak}张，可调度容量最低{min(item['capacity'] for item in gaps)}张，预计最大缺口{peak_gap}张", "data_quality": "valid", "actions": [f"提前准备{peak_gap}张同规格GPU" if lead > 0 else f"尽快处理{peak_gap}张GPU缺口"]}
        result["suppliers"] = _supplier_rows(company, request, intervals, peak_gap, lead)
        chosen = next((row for row in result["suppliers"] if row["selected"]), None)
        rec = _empty_recommendation("matched" if chosen else "unresolved", peak_gap)
        rec["baseline_cost"] = money(card_hours * Decimal(data.BASELINE_PRICE))
        if chosen:
            cost = Decimal(str(chosen["cost"]))
            rec.update(supplier_id=chosen["id"], supplier_name=chosen["name"], cost=chosen["cost"], extra_cost=money(max(Decimal(0), cost - card_hours * Decimal(data.BASELINE_PRICE))), covered_cards=peak_gap, remaining_cards=0, summary=f"预计采购成本{chosen['cost']}元，建议模拟确认；仅生成演示记录")
        else:
            rec["summary"] = f"没有供应商同时满足完整供给、交付时限、型号、评分和预算约束，仍有{peak_gap}张缺口；部分资源仅供解释"
    result["recommendation"] = rec
    forecast = {item["minute"]: item for item in intervals}
    # Endpoint is a displayed estimate and is excluded from half-open duration.
    endpoint = forecast_window(company, request.scenario_id, request.minute + HORIZON_MINUTES, current)[0]
    forecast[endpoint["minute"]] = endpoint
    for minute in range(request.minute - 60, request.minute + HORIZON_MINUTES + 1, STEP_MINUTES):
        result["chart"].append({"time": _clock(minute), "minute": minute, "demand": observations.get(minute), "forecast": forecast[minute]["demand"] if minute >= request.minute else None, "capacity": known_capacity(company, request.scenario_id, minute)})
    result["evidence"] = [
        {"id": "E-01", "title": "需求依据", "text": "预测仅使用当前及过去观测、当前已知的14:00–16:00任务或维护计划；未读取未来真实观测。"},
        {"id": "E-02", "title": "缺口计算", "text": f"从{now.strftime('%H:%M')}起向前看180分钟，按5分钟半开区间积分；剩余缺口{money(card_hours)}卡时，已过去的时段不重复计费。"},
        {"id": "E-03", "title": "匹配约束", "text": f"同型号、完整覆盖、就绪加部署不超过提前量、评分至少{request.min_quality:g}；{'优先服务评分' if request.sort_by == 'quality' else '优先最低采购成本'}。"},
        {"id": "E-04", "title": "费用口径", "text": f"模拟单卡时基准价{data.BASELINE_PRICE}元；采购成本、基准成本及差价只用于解释，均非保险赔款。"},
        {"id": "E-05", "title": "质量口径", "text": "供应商质量为合成服务评分，不代表经过测量的可用性或保险保障承诺；所有库存和报价均为模拟。"},
        {"id": "E-06", "title": "交付与有效时段", "text": _supply_window_evidence()},
    ]
    return result
