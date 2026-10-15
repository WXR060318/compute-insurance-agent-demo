# 算力智保 Demo API contract

2026-10-15。All data simulated. Python/FastAPI backend, React/TS frontend. Owner: root integration. Backend agent owns `backend/app/{main,engine,data,storage,schemas}.py` and backend tests except agent tests. Agent integration agent owns `backend/app/agent.py`, `backend/tests/test_agent.py`. Frontend agent owns all `frontend/` files. Root owns scripts, docs, environment and browser QA. Do not touch original projects/documents or credentials.

## Catalog

`GET /api/catalog` returns:

```json
{"companies":[{"id":"xinghe","name":"星河模型","industry":"AI模型研发","region":"华东","gpu_model":"Demo GPU 80GB","capacity":8,"description":"模拟企业"}],"scenarios":[{"id":"surge","name":"需求激增","subtitle":"计划任务带来未来缺口"},{"id":"normal","name":"平稳运行","subtitle":"供需处于安全范围"},{"id":"outage","name":"供给下降","subtitle":"模拟部分资源不可用"},{"id":"insufficient","name":"供应不足","subtitle":"外部资源无法完整补齐"},{"id":"stale","name":"数据失效","subtitle":"过期数据停止判断"}],"meta":{"rule_version":"demo-1.0","model_configured":false,"simulation":true}}
```

3 companies, 5 suppliers. First company is xinghe, capacity8. All inputs carry simulated labels. Model key from this new project's `.env` or process env only; never read old secrets.

## Evaluation

`POST /api/evaluate` body:
`{"company_id":"xinghe","scenario_id":"surge","minute":30,"budget":null,"min_quality":98,"sort_by":"cost"}`

minute range 0..240 (step5), clock starts at 13:00+08:00 on 2026-10-15. default minute30. budget null or positive number <=1000000, min_quality range0..100, sort_by cost|quality. Reject invalid/unknown IDs with422. Pure engine evaluate(payload:dict)->dict has no DB writes. Server persists returned snapshot via storage.save_snapshot(evaluation).

Response shape (all fields present; null where unavailable):

```json
{
 "snapshot_id":"s-<hash>","input":{"company_id":"xinghe","scenario_id":"surge","minute":30,"budget":null,"min_quality":98,"sort_by":"cost"},
 "company":{"id":"xinghe","name":"星河模型","industry":"AI模型研发","region":"华东","gpu_model":"Demo GPU 80GB","capacity":8,"description":"模拟企业"},
 "scenario":{"id":"surge","name":"需求激增","subtitle":"计划任务带来未来缺口"},
 "now":"2026-10-15T13:30:00+08:00",
 "metrics":{"capacity":8,"current_demand":7,"predicted_peak":12,"peak_gap":4,"shortage_card_hours":8,"first_shortage_at":"14:00","shortage_duration_minutes":120,"utilization":87.5,"headroom":1,"lead_minutes":30},
 "risk":{"level":"high","label":"需提前准备","reason":"未来计划任务需要12张，可调度8张","data_quality":"valid","actions":["提前准备4张同规格GPU"]},
 "chart":[{"time":"12:00","minute":-60,"demand":6,"forecast":null,"capacity":8},{"time":"14:00","minute":60,"demand":null,"forecast":12,"capacity":8}],
 "suppliers":[{"id":"a","name":"澄海算力","region":"华东","gpu_model":"Demo GPU 80GB","available_cards":4,"price_per_card_hour":12,"quality":99.5,"ready_minutes":10,"deployment_minutes":15,"total_ready_minutes":25,"quote_valid":true,"eligible":true,"partial":false,"reasons":[],"cost":96,"rank":1,"selected":true}],
 "recommendation":{"supplier_id":"a","supplier_name":"澄海算力","cost":96,"baseline_cost":64,"extra_cost":32,"covered_cards":4,"remaining_cards":0,"summary":"预计采购成本96元，建议模拟确认","status":"matched"},
 "evidence":[{"id":"E-01","title":"需求依据","text":"当前可见的计划任务，非未来真实观测"}],
 "service_rules":[{"id":"R-01","title":"预警条件","status":"演示规则","text":"预计需求高于容量"},{"id":"R-02","title":"服务条件","status":"待确认","text":"服务资格和费用承担待保险同学确认"},{"id":"R-03","title":"给付条件","status":"待确认","text":"双指数与差价补偿机制尚未定义"}],
 "meta":{"simulation":true,"rule_version":"demo-1.0","forecast_method":"近期趋势与当前已知计划任务","data_time":"2026-10-15T13:30:00+08:00","note":"研究演示数据，采购成本非保险赔款"}
}
```

chart starts at least60min before now and ends at now+180min, 5min granularity. Forecast uses current/past information+currently-known planned tasks; no future actual data. Surge planned demand12 from14:00 to16:00, capacity8. At13:30 main case must give peak_gap4, shortage_card_hours8, A cost96, baseline64, extra32. B has6 cards price9.5 but90min readiness, C2cards price11 partial only, D incompatible model, E6cards price14.5 quality99.9 ready20min total (valid alternative). Rank eligible by cost or quality; partial resources are explanatory only, not full match. Quality is a synthetic service score, not a measured availability guarantee.

Risk level low|medium|high|unknown. Stale gives unknown, recommendation status data_unavailable; suppress candidates, no predictions or costs represented as reliable. normal recommendation status not_needed. Other recommendation status matched|unresolved; no full candidate -> remaining_cards=peak_gap. No fake reservation, no cash settlement. Forecast only the remaining future window, so after16:00 surge has no remaining gap. Monotonic shortage amount as replay proceeds is okay. All arithmetic for money uses Decimal.

## Persistence and plans

`GET /api/plans` -> `{"plans":[plan,...]}`.
`POST /api/plans` body `{"snapshot_id":"...","supplier_id":"a","idempotency_key":"<client uuid>"}` -> plan.
`POST /api/plans/{id}/confirm` body `{"reviewer":"演示操作员"}` -> plan. Require supplier exists and is eligible in the stored evaluation; no confirmation if unavailable/unmatched. Repeated confirmation is idempotent. Never decrement real stock; state is only a simulation record.

plan: `{"id":"p-...","created_at":"...","status":"draft|simulation_confirmed","status_label":"预案草稿|已模拟确认","snapshot_id":"...","supplier_id":"a","supplier_name":"澄海算力","cost":96,"company_name":"星河模型","scenario_name":"需求激增","evaluation":<full evaluation>,"confirmed_at":null,"reviewer":null}`

storage module interface: `save_snapshot(evaluation)`, `get_snapshot(id)->dict|None`, `create_plan(snapshot_id,supplier_id,idempotency_key)->dict`, `list_plans()->list`, `confirm_plan(id,reviewer)->dict`. DB path env `DEMO_DB_PATH` default project/runtime/demo.sqlite3. sqlite connections per operation closed, uniqueness transaction for idempotency. Raise HTTPException404/409/422 as appropriate.

`GET /api/plans/{id}/export?format=json|html|csv` downloads UTF8 JSON/HTML/CSV attachment. HTML escapes all user strings. GET root serves built frontend/dist with API routes prioritized. CORS only loopback dev origins5175. `GET /api/health` -> `{"status":"ok","simulation":true,"model_configured":false}`. Backend port default8765.

## Assistant

`POST /api/chat` body `{"snapshot_id":"...","message":"为什么不选更便宜的B？"}` max1200 chars. Main uses async `from .agent import handle_chat; await handle_chat(payload)`.

response `{"mode":"offline|live|fallback","answer":"...","trace":[{"tool":"match_suppliers","label":"筛选备用资源","status":"success","summary":"1家符合条件"}],"evaluation":<evaluation>,"plan":null,"limitations":["离线规则助手，未调用大模型"]}`

Backend main implements chat route; agent handles optional DeepSeek tool-calling adapter. Agent imports `engine.evaluate`, `storage` only, no main import. Expose get_company_snapshot/forecast_shortage/match_suppliers/get_service_rules/create_response_plan in tool calls, validate all arguments via backend/Pydantic. Offline adapter may understand explicit budget change (e.g.预算80元) and quality priority, return deterministic explanation with logged rule steps and honest mode. Save updated evaluation snapshot before returning. No external calls in default tests. Model env `AI_MODE=offline|live`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL=https://api.deepseek.com`, `DEEPSEEK_MODEL` user configured; allow compatible chat/completions. No hidden reasoning traces, only actual tool input/output summaries. No key is an ordinary offline mode; configured model error is fallback.

## UI direction

Product name 算力智保 (demo working name). Chinese language, dark navy sidebar, warm/offwhite workspace, restrained teal/green accent, excellent dashboard information hierarchy, monospace numbers, large forecast SVG chart with capacity and clear solid history/dashed forecast and now marker. Four navigable views; top scenario and company controls, replay clock+play/step/reset. Clear persistent simulation badge. Responsive at1440 and390px. Errors and loading surfaced, no dummy nonfunctional buttons. Document title custom, all controls labeled. No external fonts/images needed.
