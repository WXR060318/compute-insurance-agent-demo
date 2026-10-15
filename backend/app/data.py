"""Versioned, synthetic inputs. No production systems or future observations."""

from datetime import datetime
from zoneinfo import ZoneInfo

RULE_VERSION = "demo-1.0"
GPU_MODEL = "Demo GPU 80GB"
BASE_TIME = datetime(2026, 10, 15, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
BASELINE_PRICE = "8"

COMPANIES = [
    {"id": "xinghe", "name": "星河模型", "industry": "AI模型研发", "region": "华东", "gpu_model": GPU_MODEL, "capacity": 8, "description": "模拟企业：研发训练与计划批处理任务"},
    {"id": "haichuan", "name": "海川视觉", "industry": "工业视觉", "region": "华南", "gpu_model": GPU_MODEL, "capacity": 6, "description": "模拟企业：图像推理与模型训练任务"},
    {"id": "yunling", "name": "云岭智研", "industry": "科研计算", "region": "华北", "gpu_model": GPU_MODEL, "capacity": 10, "description": "模拟企业：科研计算与计划批处理任务"},
]

SCENARIOS = [
    {"id": "surge", "name": "需求激增", "subtitle": "计划任务带来未来缺口"},
    {"id": "normal", "name": "平稳运行", "subtitle": "供需处于安全范围"},
    {"id": "outage", "name": "供给下降", "subtitle": "已知维护窗口内部分资源不可用"},
    {"id": "insufficient", "name": "供应不足", "subtitle": "外部资源无法完整补齐"},
    {"id": "stale", "name": "数据失效", "subtitle": "过期数据停止判断"},
]

# Prices are strings so constructing Decimal never passes through binary floats.
SUPPLIERS = [
    {"id": "a", "name": "澄海算力", "region": "华东", "gpu_model": GPU_MODEL, "available_cards": 4, "price_per_card_hour": "12", "quality": 99.5, "ready_minutes": 10, "deployment_minutes": 15, "quote_valid": True},
    {"id": "b", "name": "北辰算力", "region": "华北", "gpu_model": GPU_MODEL, "available_cards": 6, "price_per_card_hour": "9.5", "quality": 98.8, "ready_minutes": 60, "deployment_minutes": 30, "quote_valid": True},
    {"id": "c", "name": "青禾云", "region": "华东", "gpu_model": GPU_MODEL, "available_cards": 2, "price_per_card_hour": "11", "quality": 98.7, "ready_minutes": 5, "deployment_minutes": 10, "quote_valid": True},
    {"id": "d", "name": "远帆计算", "region": "华南", "gpu_model": "Demo GPU 48GB", "available_cards": 8, "price_per_card_hour": "8", "quality": 99.7, "ready_minutes": 5, "deployment_minutes": 10, "quote_valid": True},
    {"id": "e", "name": "恒稳云", "region": "华东", "gpu_model": GPU_MODEL, "available_cards": 6, "price_per_card_hour": "14.5", "quality": 99.9, "ready_minutes": 5, "deployment_minutes": 15, "quote_valid": True},
]

for _supplier in SUPPLIERS:
    # Same-day replay minutes relative to 13:00. Every eligibility check must
    # cover the whole shortage interval, not only resource readiness.
    _supplier["_available_from_minute"] = 0
    _supplier["_available_until_minute"] = 420
    _supplier["_quote_valid_until_minute"] = 240

SERVICE_RULES = [
    {"id": "R-01", "title": "预警条件", "status": "演示规则", "text": "未来180分钟内，当前已知计划需求高于可调度容量即预警；数据超过15分钟未更新时停止预测与匹配。"},
    {"id": "R-02", "title": "服务条件", "status": "待确认", "text": "服务资格和费用承担待保险同学确认；模拟确认仅保存预案，不锁定或采购真实算力。"},
    {"id": "R-03", "title": "给付条件", "status": "待确认", "text": "双指数与差价补偿机制尚未定义；采购成本和差价均非保险赔款。"},
]
