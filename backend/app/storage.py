"""SQLite snapshots and simulation plans. No external reservations are made."""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _encode(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@contextmanager
def _connection():
    path = Path(os.environ.get("DEMO_DB_PATH", str(PROJECT_ROOT / "runtime" / "demo.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, snapshot_id TEXT NOT NULL REFERENCES snapshots(id), supplier_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        yield connection
    finally:
        connection.close()


def save_snapshot(evaluation: dict):
    with _connection() as connection:
        connection.execute("INSERT OR IGNORE INTO snapshots(id,payload,created_at) VALUES(?,?,?)", (evaluation["snapshot_id"], _encode(evaluation), _now()))
    return evaluation


def get_snapshot(snapshot_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT payload FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def create_plan(snapshot_id: str, supplier_id: str, idempotency_key: str) -> dict:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(422, "幂等键不能为空")
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = connection.execute("SELECT payload FROM plans WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                plan = json.loads(existing["payload"])
                if plan["snapshot_id"] != snapshot_id or plan["supplier_id"] != supplier_id:
                    raise HTTPException(409, "该幂等键已用于另一个预案")
                connection.commit()
                return plan
            snapshot_row = connection.execute("SELECT payload FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not snapshot_row:
                raise HTTPException(404, "评估快照不存在，请先运行评估")
            evaluation = json.loads(snapshot_row["payload"])
            supplier = next((row for row in evaluation["suppliers"] if row["id"] == supplier_id), None)
            if supplier is None:
                raise HTTPException(422, "供应商不在该评估的候选资源中")
            if evaluation["recommendation"]["status"] != "matched" or not supplier.get("eligible") or supplier.get("cost") is None:
                raise HTTPException(409, "该评估或供应商不满足完整匹配条件，不能保存可确认预案")
            created_at = _now()
            plan = {
                "id": "p-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24],
                "created_at": created_at, "status": "draft", "status_label": "预案草稿",
                "snapshot_id": snapshot_id, "supplier_id": supplier_id, "supplier_name": supplier["name"], "cost": supplier["cost"],
                "company_name": evaluation["company"]["name"], "scenario_name": evaluation["scenario"]["name"],
                "evaluation": evaluation, "confirmed_at": None, "reviewer": None,
            }
            connection.execute("INSERT INTO plans(id,idempotency_key,snapshot_id,supplier_id,payload,created_at) VALUES(?,?,?,?,?,?)", (plan["id"], idempotency_key, snapshot_id, supplier_id, _encode(plan), created_at))
            connection.commit()
            return plan
        except BaseException:
            connection.rollback()
            raise


def list_plans() -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT payload FROM plans ORDER BY created_at DESC, id DESC").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def get_plan(plan_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT payload FROM plans WHERE id=?", (plan_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def confirm_plan(plan_id: str, reviewer: str) -> dict:
    if not reviewer or not reviewer.strip() or len(reviewer.strip()) > 80:
        raise HTTPException(422, "请输入1至80字的演示操作员姓名")
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute("SELECT payload FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row:
                raise HTTPException(404, "预案不存在")
            plan = json.loads(row["payload"])
            if plan["status"] == "simulation_confirmed":
                connection.commit()
                return plan
            evaluation = plan["evaluation"]
            supplier = next((item for item in evaluation["suppliers"] if item["id"] == plan["supplier_id"]), None)
            if evaluation["recommendation"]["status"] != "matched" or not supplier or not supplier.get("eligible"):
                raise HTTPException(409, "该预案的快照不满足完整匹配条件")
            plan.update(status="simulation_confirmed", status_label="已模拟确认", confirmed_at=_now(), reviewer=reviewer.strip())
            connection.execute("UPDATE plans SET payload=? WHERE id=?", (_encode(plan), plan_id))
            connection.commit()
            return plan
        except BaseException:
            connection.rollback()
            raise
