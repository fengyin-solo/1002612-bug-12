"""引导入位业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "marshalling"
REQUIRED_FIELDS = ["引导编号", "对应航班", "机位编号"]
STATUS_ORDER = ["待下达", "已下达", "已到位", "已取消"]
# 在途口径：还没到位也没取消的引导单，队列面板与看板都按这个口径统计
ACTIVE_STATUSES = ["待下达", "已下达"]
# 每个动作允许的起始状态与目标状态；已取消是终态，不在任何起始状态里
ACTION_RULES = {
    "下达引导": {"from": ["待下达"], "to": "已下达"},
    "确认到位": {"from": ["已下达"], "to": "已到位"},
    "取消引导": {"from": ["待下达", "已下达"], "to": "已取消"},
}


class MarshallingService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("引导编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        rows = store.rows(MODULE)
        flight = str(values.get("对应航班") or "").strip()
        for row in rows:
            same_flight = str(row.get("对应航班") or "").strip() == flight
            if same_flight and row.get("status") in ACTIVE_STATUSES:
                return row, [], f"航段 {flight} 已有在途引导单（{row.get('引导编号')}），重复下达以第一次为准"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["引导状态"] = STATUS_ORDER[0]
        entry["实际到位"] = ""
        entry["取消原因"] = ""
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], "引导任务已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"引导任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于引导入位可执行范围"
        status = str(entry.get("status") or "")
        if status == "已取消":
            return None, "引导单已取消，不能再执行任何状态流转"
        if action == "下达引导" and status == "已下达":
            return entry, "该引导单已下达，重复下达以第一次为准"
        rule = ACTION_RULES[action]
        if status not in rule["from"]:
            expects = "、".join(str(item) for item in rule["from"])
            return None, f"当前状态「{status}」不允许{action}，仅「{expects}」状态可执行"
        target = str(rule["to"])
        if action == "确认到位":
            entry["实际到位"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if action == "取消引导":
            reason = str(values.get("取消原因") or "").strip()
            if not reason:
                return None, "取消引导必须填写取消原因"
            entry["引导车编号"] = ""
            entry["取消原因"] = reason
        entry["status"] = target
        entry["引导状态"] = target
        entry["pending"] = target in ACTIVE_STATUSES
        entry["abnormal"] = target == "已取消"
        return entry, f"引导任务已{action}"
