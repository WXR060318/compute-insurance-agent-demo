"""Local-only demo HTTP API and compiled frontend hosting."""

from copy import deepcopy
import csv
import html
import io
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

from . import data, engine, storage
from .schemas import ChatRequest, EvaluateRequest, PlanConfirmRequest, PlanCreateRequest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Agent configuration reads only this project's .env and explicit process env.
# Avoid mutating process env here so editing the project .env takes effect.
DIST_PATH = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI(title="算力智保 · 模拟演示", version=data.RULE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5175", "http://localhost:5175", "http://[::1]:5175"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def _model_configured() -> bool:
    from .agent import model_configured
    return model_configured()


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "compute-insurance-demo", "simulation": True, "model_configured": _model_configured()}


@app.get("/api/catalog")
def catalog():
    return {"companies": deepcopy(data.COMPANIES), "scenarios": deepcopy(data.SCENARIOS), "meta": {"rule_version": data.RULE_VERSION, "model_configured": _model_configured(), "simulation": True}}


@app.post("/api/evaluate")
def evaluate(request: EvaluateRequest):
    evaluation = engine.evaluate(request.model_dump())
    storage.save_snapshot(evaluation)
    return evaluation


@app.post("/api/chat")
async def chat(request: ChatRequest):
    from .agent import handle_chat
    return await handle_chat(request.model_dump())


@app.get("/api/plans")
def plans():
    return {"plans": storage.list_plans()}


@app.post("/api/plans")
def create_plan(request: PlanCreateRequest):
    return storage.create_plan(**request.model_dump())


@app.post("/api/plans/{plan_id}/confirm")
def confirm_plan(plan_id: str, request: PlanConfirmRequest):
    return storage.confirm_plan(plan_id, request.reviewer)


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet imports must not interpret user strings as formulas.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _export_html(plan: dict) -> str:
    esc = lambda value: html.escape("—" if value is None else str(value), quote=True)
    evaluation = plan["evaluation"]
    values = [("预案编号", plan["id"]), ("企业", plan["company_name"]), ("场景", plan["scenario_name"]), ("评估时刻", evaluation["now"]), ("供应商", plan["supplier_name"]), ("状态", plan["status_label"]), ("预计采购成本（元）", plan["cost"]), ("最大缺口（张）", evaluation["metrics"]["peak_gap"]), ("剩余缺口（卡时）", evaluation["metrics"]["shortage_card_hours"]), ("操作员", plan["reviewer"]), ("模拟确认时刻", plan["confirmed_at"])]
    rows = "".join(f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>" for key, value in values)
    rules = "".join(f"<li><strong>{esc(rule['title'])} · {esc(rule['status'])}</strong>：{esc(rule['text'])}</li>" for rule in evaluation["service_rules"])
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>算力智保 · 模拟预案</title><style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 24px;color:#172b35;line-height:1.65}}h1{{margin-bottom:6px}}.badge{{color:#127262}}table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}th{{width:38%}}li{{margin-bottom:12px}}footer{{border-top:1px solid #ddd;margin-top:30px;padding-top:15px;color:#596b70}}</style></head><body><h1>算力智保 · 模拟预案</h1><p class="badge">全部为研究演示数据 · 不形成真实采购、预留或赔款</p><table>{rows}</table><h2>本预案方案</h2><p>选择{esc(plan['supplier_name'])}，预计采购成本{esc(plan['cost'])}元。当前状态：{esc(plan['status_label'])}。</p><h2>原始自动推荐</h2><p>{esc(evaluation['recommendation']['summary'])}</p><h2>服务规则</h2><ul>{rules}</ul><footer>该报告保留生成预案时的评估快照；模拟服务评分不代表实际可用性保障。</footer></body></html>"""


@app.get("/api/plans/{plan_id}/export")
def export_plan(plan_id: str, format: Literal["json", "html", "csv"] = "json"):
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise HTTPException(404, "预案不存在")
    headers = {"Content-Disposition": f'attachment; filename="{plan["id"]}.{format}"'}
    if format == "json":
        return Response(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"), media_type="application/json; charset=utf-8", headers=headers)
    if format == "html":
        return HTMLResponse(_export_html(plan), headers=headers)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["预案编号", "企业", "场景", "供应商", "状态", "预计采购成本（元）", "最大缺口（张）", "剩余缺口（卡时）", "评估时刻", "操作员", "模拟确认时刻", "说明"])
    writer.writerow([_csv_safe(value) for value in [plan["id"], plan["company_name"], plan["scenario_name"], plan["supplier_name"], plan["status_label"], plan["cost"], plan["evaluation"]["metrics"]["peak_gap"], plan["evaluation"]["metrics"]["shortage_card_hours"], plan["evaluation"]["now"], plan["reviewer"], plan["confirmed_at"], "全部模拟；采购成本非保险赔款；未锁定真实资源"]])
    return Response(("\ufeff" + stream.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    # Unknown API routes must remain errors and must never return the SPA.
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    candidate = (DIST_PATH / path).resolve()
    if candidate.is_relative_to(DIST_PATH.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    if path and (path.startswith("assets/") or Path(path).suffix):
        raise HTTPException(404, "静态文件不存在")
    index = DIST_PATH / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<h1>算力智保 Demo API 已启动</h1><p>前端尚未构建。请先构建 frontend，或通过 <a href='/docs'>API 文档</a>查看接口。</p>", status_code=503)
