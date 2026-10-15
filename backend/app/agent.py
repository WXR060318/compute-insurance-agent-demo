"""Bounded tool-calling adapter. All business decisions remain in the rule engine."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import storage
from .engine import evaluate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_ROUNDS = 4
MAX_TOOL_CALLS = 10
LIVE_TIMEOUT_SECONDS = 45


class _EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _MatchArgs(_EmptyArgs):
    budget: Decimal | None = Field(default=None, gt=0, le=1000000, allow_inf_nan=False)
    min_quality: float = Field(default=98, ge=0, le=100, allow_inf_nan=False)
    sort_by: Literal["cost", "quality"] = "cost"


class _PlanArgs(_EmptyArgs):
    supplier_id: str | None = Field(default=None, min_length=1, max_length=40)


class _ChatInput(_EmptyArgs):
    snapshot_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1200)


TOOL_LABELS = {
    "get_company_snapshot": "读取企业快照",
    "forecast_shortage": "测算未来缺口",
    "match_suppliers": "筛选备用资源",
    "get_service_rules": "查询服务规则",
    "create_response_plan": "生成处置预案",
}
ARG_MODELS = {
    "get_company_snapshot": _EmptyArgs,
    "forecast_shortage": _EmptyArgs,
    "match_suppliers": _MatchArgs,
    "get_service_rules": _EmptyArgs,
    "create_response_plan": _PlanArgs,
}
TOOL_DESCRIPTIONS = {
    "get_company_snapshot": "读取本轮已选企业的模拟快照、当前输入与数据时点。参数为空。",
    "forecast_shortage": "读取规则引擎计算的未来剩余窗口缺口；数据失效时不预测。参数为空。",
    "match_suppliers": "按用户明确指定的预算、最低质量和排序方式重筛资源。不得自行更改用户约束；未更改的参数可省略。",
    "get_service_rules": "读取预警、服务资格、给付条件的现有演示规则及待确认事项。参数为空。",
    "create_response_plan": "仅当用户明确要求生成预案或草稿时，为本轮合格供应商生成模拟草稿；不确认、不采购、不占库存。",
}


def _tools() -> list[dict[str, Any]]:
    result = []
    for name, model in ARG_MODELS.items():
        schema = model.model_json_schema()
        # JSON numbers are sufficient for the API; Decimal is still used at validation.
        if name == "match_suppliers":
            schema["properties"]["budget"] = {
                "anyOf": [{"type": "number", "exclusiveMinimum": 0, "maximum": 1000000}, {"type": "null"}],
                "default": None,
            }
        result.append({"type": "function", "function": {"name": name, "description": TOOL_DESCRIPTIONS[name], "parameters": schema}})
    return result


def _config() -> dict[str, str]:
    """Only the new project's .env and explicit process environment are consulted."""
    local = dotenv_values(PROJECT_ROOT / ".env", interpolate=False)
    keys = ("AI_MODE", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL")
    values = {key: str(os.environ.get(key, local.get(key) or "")).strip() for key in keys}
    values["AI_MODE"] = values["AI_MODE"].lower() or "offline"
    values["DEEPSEEK_BASE_URL"] = values["DEEPSEEK_BASE_URL"] or "https://api.deepseek.com"
    return values


def model_configured() -> bool:
    config = _config()
    return config["AI_MODE"] == "live" and bool(config["DEEPSEEK_API_KEY"] and config["DEEPSEEK_MODEL"])


def _intent_updates(message: str) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if re.search(r"取消预算|不限预算|不设预算|预算不限|预算不限制", message):
        changes["budget"] = None
    else:
        match = re.search(r"预算(?:只有|为|是|上限|限制|不超过|最多|控制在|设为|调到|调整为|调整到|改为|改成|改到)?\s*[：:=]?\s*[¥￥]?\s*(-?\d+(?:\.\d+)?)\s*(?:元|块)?", message)
        if match:
            changes["budget"] = Decimal(match.group(1))
    if re.search(r"质量优先|优先质量|优先(?:选择)?质量(?:更高|较高|高)|按质量|服务质量优先|可靠性优先|最可靠", message):
        changes["sort_by"] = "quality"
    elif re.search(r"价格优先|成本优先|按价格|按成本|最低价优先", message):
        changes["sort_by"] = "cost"
    quality = re.search(r"(?:最低质量|质量评分|服务评分|质量)(?:不低于|至少|大于等于|>=|≥|为|是)?\s*[：:]?\s*(\d+(?:\.\d+)?)", message)
    if quality:
        changes["min_quality"] = float(quality.group(1))
    return changes


def _wants_plan(message: str) -> bool:
    wants = False
    for clause in re.split(r"[，,。；;！!？?\n]", message):
        requested = re.search(r"(?:生成|创建|起草|给我|出一份|做一份).{0,12}(?:预案|草稿|处置单)|(?:预案|处置单).{0,8}(?:生成|创建)", clause)
        if requested:
            wants = not bool(re.search(r"(?:不要|别|无需|不需要|不想|暂不|不用).{0,16}(?:生成|创建|起草|预案|草稿|处置单)|不(?:生成|创建)", clause))
    return wants


def _requested_supplier(message: str, evaluation: dict[str, Any]) -> str | None:
    patterns = (
        r"供应商\s*([ABCDEabcde])",
        r"([ABCDEabcde])\s*(?:供应商|方案|的?(?:预案|草稿))",
        r"(?:给|为|选|选择|用|使用|采用)\s*([ABCDEabcde])(?:\s|[，,。.!！?？]|生成|创建|起草|做|出|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1).lower()
    for supplier in evaluation.get("suppliers", []):
        if supplier.get("name") and supplier["name"] in message:
            return supplier["id"]
    return None


@dataclass
class _Context:
    evaluation: dict[str, Any]
    message: str
    authorized_changes: dict[str, Any]
    trace: list[dict[str, str]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    plan: dict[str, Any] | None = None


class _ToolRejected(ValueError):
    pass


def _summary(evaluation: dict[str, Any]) -> str:
    status = evaluation.get("recommendation", {}).get("status")
    if status == "data_unavailable":
        return "数据已失效，停止预测与资源推荐"
    if status == "not_needed":
        return "当前预测窗口无须补充资源"
    eligible = sum(bool(item.get("eligible")) for item in evaluation.get("suppliers", []))
    return f"{eligible}家满足完整匹配条件；状态：{'已匹配' if status == 'matched' else '待解决'}"


def _same_value(value: Any, other: Any) -> bool:
    if value is None or other is None:
        return value is other
    if isinstance(value, (int, float, Decimal)) and isinstance(other, (int, float, Decimal)):
        return Decimal(str(value)) == Decimal(str(other))
    return value == other


def _run_tool(context: _Context, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """The sole execution boundary for offline rules and model-requested tools."""
    if name not in ARG_MODELS:
        raise _ToolRejected("该工具未在允许列表中，未执行")
    try:
        parsed = ARG_MODELS[name].model_validate(arguments)
        evaluation = context.evaluation
        if name == "get_company_snapshot":
            result = {key: evaluation.get(key) for key in ("snapshot_id", "input", "company", "scenario", "now", "meta")}
            summary = "已读取当前企业模拟快照与数据时点"
        elif name == "forecast_shortage":
            result = {key: evaluation.get(key) for key in ("metrics", "risk", "evidence", "meta")}
            summary = "数据已失效，未给出可靠预测" if evaluation.get("recommendation", {}).get("status") == "data_unavailable" else f"未来峰值缺口{(evaluation.get('metrics') or {}).get('peak_gap', 0)}张"
        elif name == "match_suppliers":
            changes = parsed.model_dump(exclude_unset=True, mode="python")
            current_input = evaluation["input"]
            for key, value in changes.items():
                permitted = context.authorized_changes.get(key, current_input.get(key))
                # Decimal comparison avoids JSON number/string representation mismatches.
                if not _same_value(value, permitted):
                    raise _ToolRejected("工具试图更改用户未指定的筛选条件，未执行")
            new_input = {**current_input, **changes}
            if new_input != current_input:
                evaluation = evaluate(new_input)
                storage.save_snapshot(evaluation)
                context.evaluation = evaluation
                context.plan = None
            result = {key: evaluation.get(key) for key in ("snapshot_id", "input", "suppliers", "recommendation")}
            summary = _summary(evaluation)
        elif name == "get_service_rules":
            result = {"service_rules": evaluation.get("service_rules", []), "simulation": True}
            summary = "已读取演示规则，服务资格与给付规则仍待确认"
        else:
            if not _wants_plan(context.message):
                raise _ToolRejected("用户未要求生成预案，未创建草稿")
            if evaluation.get("recommendation", {}).get("status") != "matched":
                raise _ToolRejected("当前缺口未获得完整匹配，不能生成预案")
            permitted = _requested_supplier(context.message, evaluation) or evaluation["recommendation"].get("supplier_id")
            requested = parsed.supplier_id or permitted
            if requested != permitted:
                raise _ToolRejected("供应商与用户指定不符，未创建草稿")
            if not any(item.get("id") == requested and item.get("eligible") for item in evaluation.get("suppliers", [])):
                raise _ToolRejected("该供应商未通过本快照的完整筛选，未创建草稿")
            seed = f"{evaluation['snapshot_id']}|{requested}|{context.message}".encode()
            context.plan = storage.create_plan(evaluation["snapshot_id"], requested, "chat-" + hashlib.sha256(seed).hexdigest())
            result = {"plan": {key: context.plan.get(key) for key in ("id", "status", "status_label", "snapshot_id", "supplier_id", "supplier_name", "cost")}}
            summary = "已返回此前模拟确认的同一预案记录" if context.plan.get("status") == "simulation_confirmed" else "已保存模拟预案草稿，等待人工确认"
        context.trace.append({"tool": name, "label": TOOL_LABELS[name], "status": "success", "summary": summary})
        return result
    except ValidationError as exc:
        context.trace.append({"tool": name, "label": TOOL_LABELS[name], "status": "error", "summary": "参数校验失败，未更改当前结果"})
        raise _ToolRejected("参数无效：预算须大于0且不超过1000000元，质量须在0至100之间，且不允许额外字段") from exc
    except (HTTPException, _ToolRejected) as exc:
        context.trace.append({"tool": name, "label": TOOL_LABELS[name], "status": "error", "summary": "工具条件未满足，未执行该操作"})
        if isinstance(exc, HTTPException):
            raise _ToolRejected("存储中的快照或供应商状态不支持该操作") from exc
        raise


def _money(value: Any) -> str:
    if value is None:
        return "未确定"
    return format(Decimal(str(value)).normalize(), "f")


def _rule_answer(context: _Context) -> str:
    evaluation = context.evaluation
    recommendation = evaluation.get("recommendation", {})
    metrics = evaluation.get("metrics") or {}
    status = recommendation.get("status")
    sections: list[str] = []
    if status == "data_unavailable":
        sections.append("当前模拟数据已经过期，无法可靠判断未来缺口、供应商库存和采购成本。请切换到有效数据场景后重新评估；此时不能生成可确认的预案。")
    elif status == "not_needed":
        sections.append("当前剩余预测窗口没有算力缺口，无须补充外部资源。这里依据的是当前已知计划任务，不能保证之后不会出现新的需求。")
    else:
        sections.append(f"当前模拟评估预计从{metrics.get('first_shortage_at') or '预测窗口内'}出现缺口，峰值缺{metrics.get('peak_gap', 0)}张同规格GPU，剩余缺口采购量为{_money(metrics.get('shortage_card_hours'))}卡时。")
        if status == "matched":
            sections.append(f"按当前条件推荐{recommendation.get('supplier_name') or '匹配供应商'}，采购成本{_money(recommendation.get('cost'))}元，覆盖{recommendation.get('covered_cards', 0)}张，剩余{recommendation.get('remaining_cards', 0)}张。基准成本{_money(recommendation.get('baseline_cost'))}元，演示差价{_money(recommendation.get('extra_cost'))}元。")
        else:
            sections.append(f"当前没有一家供应商能完整满足全部条件，仍有{recommendation.get('remaining_cards', metrics.get('peak_gap', 0))}张缺口未解决。部分资源仅供说明，不能当作完整匹配或自动拼单。")
        if "budget" in context.authorized_changes:
            budget = evaluation.get("input", {}).get("budget")
            if not _same_value(budget, context.authorized_changes["budget"]):
                sections.append("新预算未通过校验，当前仍使用之前的有效筛选条件。")
            elif budget is None:
                sections.append("已按你的要求取消预算上限并重新筛选。")
            else:
                sections.append(f"当前预算上限为{_money(budget)}元；交付时间、规格、数量和质量门槛仍需同时满足。")
        if context.authorized_changes.get("sort_by") == "quality" and evaluation.get("input", {}).get("sort_by") == "quality":
            sections.append("已在通过硬条件的完整候选中按质量优先排序。质量分是演示合成评分，不代表已验证的可用性保证。")
        if re.search(r"(?:供应商\s*)?[BbＢ]|便宜|低价|为什么|为何", context.message):
            supplier_b = next((item for item in evaluation.get("suppliers", []) if item.get("id") == "b"), None)
            if supplier_b:
                reasons = supplier_b.get("reasons") or []
                reason_text = "；".join(str(reason) for reason in reasons)
                if not supplier_b.get("eligible"):
                    sections.append(f"B供应商（{supplier_b.get('name', 'B')}）单价为{_money(supplier_b.get('price_per_card_hour'))}元/卡时，但未通过硬条件：{reason_text or '未满足完整供给要求'}。价格低不能弥补交付或供给条件不足。")
                elif not supplier_b.get("selected"):
                    sections.append(f"B供应商已满足硬条件；本次未排在首位，是当前排序方式及报价比较的结果。其质量分为{_money(supplier_b.get('quality'))}，预计成本{_money(supplier_b.get('cost'))}元。")
                else:
                    sections.append("当前时点与条件下，B供应商已经是规则推荐方案；之前时点的筛选结论不能直接沿用。")
    if context.plan:
        if context.plan.get("status") == "simulation_confirmed":
            sections.append(f"这份{context.plan.get('supplier_name', '')}预案此前已模拟确认，金额{_money(context.plan.get('cost'))}元；本次重复请求返回同一记录。")
        else:
            sections.append(f"已保存{context.plan.get('supplier_name', '')}的模拟预案草稿，金额{_money(context.plan.get('cost'))}元；请在预案记录中人工模拟确认。")
    sections.append("采购成本与演示差价均不是保险赔款。服务资格、费用承担、双指数及给付公式仍待团队确认；系统不会执行真实采购、占用库存或支付。")
    return "\n\n".join(sections)


def _offline(context: _Context) -> None:
    for name, arguments in (
        ("get_company_snapshot", {}),
        ("forecast_shortage", {}),
        ("match_suppliers", context.authorized_changes),
        ("get_service_rules", {}),
    ):
        try:
            _run_tool(context, name, arguments)
        except _ToolRejected as exc:
            context.limitations.append(str(exc))
    if _wants_plan(context.message):
        try:
            selected = _requested_supplier(context.message, context.evaluation)
            _run_tool(context, "create_response_plan", {"supplier_id": selected} if selected else {})
        except _ToolRejected as exc:
            context.limitations.append(str(exc))


SYSTEM_PROMPT = """你是算力智保的模拟演示助手。所有企业、价格、库存和质量评分都是模拟数据。
必须使用业务工具查询本轮事实；只有明确提出的预算、最低质量或排序条件才可改动。
不得变更企业、场景、回放时间、金额、价格、库存、责任和规则。未授权不得生成草稿。
create_response_plan只生成草稿，不能确认、采购、占库存、支付或承诺理赔。
数据失效时停止预测；匹配失败时直说未解决。不要假称调用过工具。
最后只写简短定性解释，不要重复数字、金额或库存；服务器会附上当前规则计算结果。
服务资格、费用承担、双指数和给付公式尚未确定，不能当成正式保险条款。"""


async def _completion(client: httpx.AsyncClient, endpoint: str, config: dict[str, str], messages: list[dict[str, Any]]) -> dict[str, Any]:
    response = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {config['DEEPSEEK_API_KEY']}"},
        json={"model": config["DEEPSEEK_MODEL"], "messages": messages, "tools": _tools(), "stream": False, "max_tokens": 1800},
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    if not isinstance(message, dict):
        raise ValueError("Invalid completion message")
    return message


async def _live(context: _Context, config: dict[str, str]) -> str:
    base_url = config["DEEPSEEK_BASE_URL"].rstrip("/")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in ("https", "http") or not parsed_url.hostname or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
        raise ValueError("Invalid configured base URL")
    endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    evaluation = context.evaluation
    # No transcript history, personal knowledge base, or secrets are sent to the model.
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"message": context.message, "snapshot": {key: evaluation.get(key) for key in ("snapshot_id", "company", "scenario", "input", "meta")}, "authorized_changes": context.authorized_changes}, ensure_ascii=False, default=str)},
    ]
    tool_count = 0
    used_ids: set[str] = set()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=False) as client:
        for _ in range(MAX_ROUNDS):
            message = await _completion(client, endpoint, config, messages)
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise ValueError("Invalid tool call collection")
            if not calls:
                content = message.get("content")
                if not isinstance(content, str) or not content.strip() or not any(step["status"] == "success" for step in context.trace):
                    raise ValueError("Missing final text or actual tool use")
                # A model cannot silently skip an explicit changed constraint.
                if any(not _same_value(context.evaluation["input"].get(key), value) for key, value in context.authorized_changes.items()):
                    raise ValueError("Requested constraint was not applied")
                if _wants_plan(context.message) and context.evaluation.get("recommendation", {}).get("status") == "matched" and context.plan is None:
                    raise ValueError("Requested draft was not created")
                return content.strip()[:3000]
            tool_count += len(calls)
            if tool_count > MAX_TOOL_CALLS:
                raise ValueError("Tool budget exceeded")
            assistant = {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
            # Some configured reasoning models need this field echoed privately to the API.
            # It is never logged, persisted, included in trace, or returned to the caller.
            if isinstance(message.get("reasoning_content"), str):
                assistant["reasoning_content"] = message["reasoning_content"]
            messages.append(assistant)
            for call in calls:
                if not isinstance(call, dict) or call.get("type") != "function":
                    raise ValueError("Invalid tool call")
                call_id = call.get("id")
                function = call.get("function") or {}
                if not isinstance(call_id, str) or not call_id or call_id in used_ids or not isinstance(function, dict):
                    raise ValueError("Invalid tool call identity")
                used_ids.add(call_id)
                name = function.get("name")
                if name not in ARG_MODELS:
                    raise ValueError("Tool outside allowlist")
                try:
                    raw_arguments = function.get("arguments", "{}")
                    if not isinstance(raw_arguments, str) or len(raw_arguments) > 5000:
                        raise _ToolRejected("工具参数格式无效，未执行")
                    arguments = json.loads(raw_arguments)
                    if not isinstance(arguments, dict):
                        raise _ToolRejected("工具参数必须是对象，未执行")
                    result = _run_tool(context, name, arguments)
                except (json.JSONDecodeError, _ToolRejected) as exc:
                    result = {"error": str(exc) if isinstance(exc, _ToolRejected) else "工具参数不是有效JSON，未执行"}
                messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, default=str)})
    raise ValueError("Model did not finish within the round limit")


def _safe_model_text(text: str, context: _Context) -> str:
    """Generated prose is optional; unsupported numeric/action claims are discarded."""
    # Insurance terms have not been agreed. Even qualitative model prose must not
    # turn the draft into coverage, liability, compensation, or payment promises.
    insurance_topic = re.search(r"保险|承保|保单|责任|保障|赔付|理赔|给付|赔偿|补偿|免赔|免责|承担|负担|报销|兜底|费用归属|服务资格|双指数", text)
    if insurance_topic:
        context.limitations.append("模型自由文案涉及未经确认的保险责任或费用承担，已仅展示既有规则说明")
        return ""
    unsafe = re.search(r"\d|[零一二三四五六七八九十百千万两]+(?:元|张|卡时|分钟|小时)|已(?:支付|付款|下单|采购|预订|锁定|确认|赔付|给付|理赔|扣款|承保)|全额赔付|保证|必定|一定会", text)
    unmatched_claim = context.evaluation.get("recommendation", {}).get("status") != "matched" and re.search(r"已匹配|可以采购|可以确认|推荐采购|推荐启用", text)
    invented_draft = context.plan is None and re.search(r"已(?:生成|创建|保存).{0,12}(?:预案|草稿|处置单)|(?:预案|草稿|处置单).{0,8}已(?:生成|创建|保存)", text)
    if unsafe or unmatched_claim or invented_draft:
        context.limitations.append("模型文字含未独立核验的数值或执行结论，已仅展示规则结果")
        return ""
    return text


async def handle_chat(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        request = _ChatInput.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="需要有效快照和1至1200字的问题") from exc
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="问题不能为空")
    snapshot = storage.get_snapshot(request.snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="快照不存在，请先重新评估")
    context = _Context(snapshot, request.message.strip(), _intent_updates(request.message))
    config = _config()
    mode = "offline"
    model_text = ""
    if config["AI_MODE"] == "live" and config["DEEPSEEK_API_KEY"] and config["DEEPSEEK_MODEL"]:
        try:
            model_text = await asyncio.wait_for(_live(context, config), timeout=LIVE_TIMEOUT_SECONDS)
            model_text = _safe_model_text(model_text, context)
            mode = "live"
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, IndexError, TypeError):
            mode = "fallback"
            context.limitations.append("模型调用未完成或返回无效结果，已回退到本地规则助手；未重试外部调用")
            _offline(context)
    else:
        _offline(context)
        context.limitations.append("离线规则助手，未调用大模型")
        if config["AI_MODE"] == "live":
            context.limitations.append("当前工程未完整配置模型名称与密钥，采用离线模式")
    answer = _rule_answer(context)
    if model_text:
        answer = "模型解释：" + model_text + "\n\n规则计算结果：\n" + answer
    return {"mode": mode, "answer": answer, "trace": context.trace, "evaluation": context.evaluation, "plan": context.plan, "limitations": list(dict.fromkeys(context.limitations))}
