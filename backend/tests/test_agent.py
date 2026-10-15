"""Rule/adapter integration tests. No test calls an external model."""

import asyncio
from copy import deepcopy
import json

from fastapi import HTTPException
import httpx
import pytest

from app import agent, storage
from app.engine import evaluate


@pytest.fixture(autouse=True)
def agent_environment(monkeypatch, tmp_path, isolated_db):
    monkeypatch.setattr(agent, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AI_MODE", "offline")
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    async def forbidden_network(*args, **kwargs):
        raise AssertionError("Tests must replace the external completion boundary")

    monkeypatch.setattr(agent, "_completion", forbidden_network)


def snapshot(**changes):
    result = evaluate({"company_id": "xinghe", "scenario_id": "surge", "minute": 30, "budget": None, "min_quality": 98, "sort_by": "cost", **changes})
    storage.save_snapshot(result)
    return result


def chat(evaluation, message):
    return asyncio.run(agent.handle_chat({"snapshot_id": evaluation["snapshot_id"], "message": message}))


def live_mode(monkeypatch):
    monkeypatch.setenv("AI_MODE", "live")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("DEEPSEEK_MODEL", "configured-test-model")


def function_call(name, arguments=None, call_id="call-1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {})}}


def completions(monkeypatch, responses):
    sent = []
    queue = iter(responses)

    async def fake(client, endpoint, config, messages):
        sent.append({"endpoint": endpoint, "model": config["DEEPSEEK_MODEL"], "messages": deepcopy(messages)})
        return next(queue)

    monkeypatch.setattr(agent, "_completion", fake)
    return sent


def test_offline_explains_cheaper_supplier_without_creating_plan():
    current = snapshot()
    result = chat(current, "为什么不选更便宜的B？")
    assert result["mode"] == "offline"
    assert "96元" in result["answer"]
    assert "B供应商" in result["answer"]
    assert "未通过硬条件" in result["answer"]
    assert "保险赔款" in result["answer"]
    assert result["evaluation"] == current
    assert result["plan"] is None
    assert storage.list_plans() == []
    assert [step["tool"] for step in result["trace"]] == ["get_company_snapshot", "forecast_shortage", "match_suppliers", "get_service_rules"]


@pytest.mark.parametrize("message", ["预算只有80元怎么办？", "把预算改成80元，重新匹配"])
def test_budget_change_is_recomputed_persisted_and_honestly_unresolved(message):
    current = snapshot()
    result = chat(current, message)
    updated = result["evaluation"]
    assert updated["input"]["budget"] == 80
    assert updated["recommendation"]["status"] == "unresolved"
    assert updated["recommendation"]["remaining_cards"] == 4
    assert "没有一家供应商" in result["answer"]
    assert "80元" in result["answer"]
    assert storage.get_snapshot(updated["snapshot_id"]) == updated
    assert storage.get_snapshot(current["snapshot_id"])["input"]["budget"] is None


@pytest.mark.parametrize("message", ["按质量优先重新筛选", "优先选择质量更高的资源"])
def test_quality_priority_selects_high_quality_eligible_alternative(message):
    result = chat(snapshot(), message)
    assert result["evaluation"]["input"]["sort_by"] == "quality"
    assert result["evaluation"]["recommendation"]["supplier_id"] == "e"
    assert "合成评分" in result["answer"]


@pytest.mark.parametrize("scenario", ["stale", "insufficient", "normal"])
def test_non_matched_states_never_create_a_confirmable_plan(scenario):
    result = chat(snapshot(scenario_id=scenario), "生成处置预案")
    assert result["plan"] is None
    assert storage.list_plans() == []
    assert result["limitations"]
    if scenario == "stale":
        assert "数据已经过期" in result["answer"]
        assert result["evaluation"]["suppliers"] == []
        assert "96元" not in result["answer"]
    elif scenario == "normal":
        assert "无须补充" in result["answer"]
    else:
        assert "缺口未解决" in result["answer"]


@pytest.mark.parametrize("message", ["生成A预案", "给A生成预案", "为供应商A生成草稿", "生成A的预案", "生成澄海算力预案"])
def test_requested_supplier_is_respected_even_when_quality_order_favors_e(message):
    current = snapshot(sort_by="quality")
    assert current["recommendation"]["supplier_id"] == "e"
    result = chat(current, message)
    assert result["plan"]["supplier_id"] == "a"
    assert result["plan"]["cost"] == 96
    assert result["plan"]["status"] == "draft"
    assert result["plan"]["confirmed_at"] is None
    repeated = chat(current, message)
    assert repeated["plan"]["id"] == result["plan"]["id"]
    assert len(storage.list_plans()) == 1
    assert storage.get_snapshot(current["snapshot_id"]) == current


@pytest.mark.parametrize("message", ["不要生成预案", "不要给A生成预案", "暂不创建草稿"])
def test_negative_plan_request_does_not_create_draft(message):
    result = chat(snapshot(), message)
    assert result["plan"] is None
    assert storage.list_plans() == []


@pytest.mark.parametrize("message", ["不要改预算，生成A的预案", "不需要赔付，给我生成预案"])
def test_negation_of_another_action_does_not_block_requested_draft(message):
    result = chat(snapshot(), message)
    assert result["plan"]["status"] == "draft"
    assert result["plan"]["supplier_id"] == "a"


def test_repeated_chat_after_manual_confirmation_returns_existing_status():
    current = snapshot()
    initial = chat(current, "生成预案")
    confirmed = storage.confirm_plan(initial["plan"]["id"], "测试操作员")
    result = chat(current, "生成预案")
    assert result["plan"] == confirmed
    assert "此前已模拟确认" in result["answer"]
    assert "请在预案记录中人工模拟确认" not in result["answer"]
    assert len(storage.list_plans()) == 1


def test_invalid_budget_does_not_silently_reset_existing_valid_budget():
    current = snapshot(budget=150)
    result = chat(current, "预算改为0元")
    assert result["evaluation"]["input"]["budget"] == 150
    assert "新预算未通过校验" in result["answer"]
    assert "取消预算" not in result["answer"]
    assert any(step["status"] == "error" for step in result["trace"])


def test_local_environment_only_and_process_values_take_precedence(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("AI_MODE=live\nDEEPSEEK_API_KEY=\nDEEPSEEK_MODEL=local-configured-model\n", encoding="utf-8")
    monkeypatch.delenv("AI_MODE")
    assert not agent.model_configured()
    result = chat(snapshot(), "说明当前方案")
    assert result["mode"] == "offline"
    assert "未完整配置" in "".join(result["limitations"])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-placeholder")
    assert agent.model_configured()
    monkeypatch.setenv("AI_MODE", "offline")
    assert not agent.model_configured()


def test_unknown_snapshot_and_empty_question_are_rejected():
    with pytest.raises(HTTPException) as missing:
        asyncio.run(agent.handle_chat({"snapshot_id": "s-missing", "message": "解释"}))
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as blank:
        chat(snapshot(), "   ")
    assert blank.value.status_code == 422


def test_live_tool_cycle_uses_actual_tools_preserves_decimal_equivalence(monkeypatch):
    live_mode(monkeypatch)
    sent = completions(monkeypatch, [
        {"content": None, "tool_calls": [function_call("match_suppliers", {"budget": 80.0})], "reasoning_content": "private internal text"},
        {"content": "预算限制下需要继续寻找符合交付要求的资源。"},
    ])
    result = chat(snapshot(), "预算为80.00元")
    assert result["mode"] == "live"
    assert result["evaluation"]["input"]["budget"] == 80
    assert result["evaluation"]["recommendation"]["status"] == "unresolved"
    assert len(result["trace"]) == 1
    assert result["trace"][0]["tool"] == "match_suppliers"
    assert "private internal text" not in json.dumps(result, ensure_ascii=False)
    assert "test-only-placeholder" not in json.dumps(result)
    assert sent[1]["messages"][-1]["role"] == "tool"
    assert sent[1]["messages"][-1]["tool_call_id"] == "call-1"
    assert sent[0]["model"] == "configured-test-model"
    assert "80元" in result["answer"]


def test_live_rejects_unapproved_budget_and_injected_money(monkeypatch):
    live_mode(monkeypatch)
    completions(monkeypatch, [
        {"content": None, "tool_calls": [function_call("match_suppliers", {"budget": 999, "cost": 1}), function_call("forecast_shortage", call_id="call-2")]},
        {"content": "需要同时检查交付条件与预算。"},
    ])
    result = chat(snapshot(), "解释当前方案")
    assert result["mode"] == "live"
    assert result["evaluation"]["input"]["budget"] is None
    assert result["evaluation"]["recommendation"]["cost"] == 96
    assert result["trace"][0]["status"] == "error"
    assert result["trace"][1]["status"] == "success"


def test_live_cannot_generate_unrequested_draft(monkeypatch):
    live_mode(monkeypatch)
    completions(monkeypatch, [
        {"tool_calls": [function_call("create_response_plan", {"supplier_id": "a"}), function_call("get_service_rules", call_id="call-2")]},
        {"content": "当前仅提供方案解释，具体服务条件仍待团队确认。"},
    ])
    result = chat(snapshot(), "解释当前方案")
    assert result["plan"] is None
    assert storage.list_plans() == []
    assert result["trace"][0]["status"] == "error"


@pytest.mark.parametrize("case", ["http_failure", "timeout", "unknown_tool", "no_tool", "ignored_budget"])
def test_model_failures_use_honest_fallback_without_exposing_errors(monkeypatch, case):
    live_mode(monkeypatch)
    if case == "http_failure":
        async def failure(*args):
            raise httpx.ConnectError("test-only-placeholder hidden diagnostic")
        monkeypatch.setattr(agent, "_completion", failure)
    elif case == "timeout":
        async def timeout(*args):
            raise asyncio.TimeoutError()
        monkeypatch.setattr(agent, "_completion", timeout)
    elif case == "unknown_tool":
        completions(monkeypatch, [{"tool_calls": [function_call("confirm_real_purchase")]}])
    elif case == "no_tool":
        completions(monkeypatch, [{"content": "已完成评估。"}])
    else:
        completions(monkeypatch, [{"tool_calls": [function_call("forecast_shortage")]}, {"content": "预算已经按要求调整。"}])
    result = chat(snapshot(), "预算80元")
    assert result["mode"] == "fallback"
    assert result["evaluation"]["input"]["budget"] == 80
    assert result["evaluation"]["recommendation"]["status"] == "unresolved"
    assert "test-only-placeholder" not in json.dumps(result)
    assert any("回退" in item for item in result["limitations"])
    assert all(step["tool"] in agent.TOOL_LABELS for step in result["trace"])


def test_model_cannot_override_canonical_amounts_in_final_text(monkeypatch):
    live_mode(monkeypatch)
    completions(monkeypatch, [{"tool_calls": [function_call("match_suppliers")]}, {"content": "采购成本仅1元，已支付并完成采购。"}])
    result = chat(snapshot(), "解释当前方案")
    assert result["mode"] == "live"
    assert "96元" in result["answer"]
    assert "仅1元" not in result["answer"]
    assert "已支付" not in result["answer"]
    assert any("未独立核验" in item for item in result["limitations"])


def test_model_cannot_claim_unrequested_draft_exists(monkeypatch):
    live_mode(monkeypatch)
    completions(monkeypatch, [{"tool_calls": [function_call("forecast_shortage")]}, {"content": "已生成并保存处置预案。"}])
    result = chat(snapshot(), "解释当前方案")
    assert result["plan"] is None
    assert "已生成并保存处置预案" not in result["answer"]
    assert any("未独立核验" in item for item in result["limitations"])


def test_model_cannot_assert_unconfirmed_insurance_coverage_or_cost_liability(monkeypatch):
    live_mode(monkeypatch)
    current = snapshot()
    invented_terms = "本保险覆盖全部短缺损失，保险公司承担费用并提供差价补偿。"
    completions(monkeypatch, [{"tool_calls": [function_call("get_service_rules")]}, {"content": invented_terms}])
    result = chat(current, "本保险会承担哪些费用？")
    assert result["mode"] == "live"
    assert invented_terms not in result["answer"]
    assert "保险公司承担费用" not in result["answer"]
    assert "费用承担、双指数及给付公式仍待团队确认" in result["answer"]
    assert result["evaluation"]["service_rules"] == current["service_rules"]
    assert result["trace"][0]["tool"] == "get_service_rules"
    assert any("未经确认的保险责任" in item for item in result["limitations"])


def test_tool_loop_is_bounded_then_falls_back(monkeypatch):
    live_mode(monkeypatch)
    sent = completions(monkeypatch, [{"tool_calls": [function_call("get_company_snapshot", call_id=f"loop-{index}")]} for index in range(agent.MAX_ROUNDS)])
    result = chat(snapshot(), "解释方案")
    assert result["mode"] == "fallback"
    assert len(sent) == agent.MAX_ROUNDS
    assert len(result["trace"]) == agent.MAX_ROUNDS + 4


def test_completion_http_payload_is_compatible_and_uses_configured_model():
    captured = {}

    def handle(request):
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "定性解释"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            # The autouse no-network boundary is deliberately bypassed with the original
            # function retained on this module before monkeypatching.
            return await ORIGINAL_COMPLETION(client, "https://model.test/v1/chat/completions", {"DEEPSEEK_API_KEY": "test-secret", "DEEPSEEK_MODEL": "configured-model"}, [{"role": "user", "content": "模拟问题"}])

    result = asyncio.run(run())
    assert result["content"] == "定性解释"
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["payload"]["model"] == "configured-model"
    assert captured["authorization"] == "Bearer test-secret"
    assert {item["function"]["name"] for item in captured["payload"]["tools"]} == set(agent.TOOL_LABELS)


ORIGINAL_COMPLETION = agent._completion
