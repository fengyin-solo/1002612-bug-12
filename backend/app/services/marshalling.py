"""引导入位业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "marshalling"
REQUIRED_FIELDS = ["引导编号", "对应航班", "机位编号"]
STATUS_ORDER = ["待下达", "已下达", "已到位", "已取消"]
ACTIONS = ["下达引导", "确认到位", "取消引导"]

# 状态机：待下达 → 已下达 → 已到位，两个在途环节都可取消；已到位、已取消是终态，不再接受任何动作。
STATUS_FLOW: dict[str, dict[str, str]] = {
    "待下达": {"下达引导": "已下达", "取消引导": "已取消"},
    "已下达": {"确认到位": "已到位", "取消引导": "已取消"},
    "已到位": {},
    "已取消": {},
}
ACTIVE_STATUSES = ("待下达", "已下达")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class MarshallingService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        flight: str | None = None,
        stand: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("引导编号", ""))]
        if flight:
            rows = [row for row in rows if flight in str(row.get("对应航班", ""))]
        if stand:
            rows = [row for row in rows if stand in str(row.get("机位编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> dict[str, int]:
        """看板计数：与队列读同一份数据，每次流转后重算，保证两边一致。"""
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        return {
            "待下达": counts["待下达"],
            "在途引导": counts["已下达"],
            "已到位": counts["已到位"],
            "已取消": counts["已取消"],
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        rows = store.rows(MODULE)
        flight = str(values.get("对应航班") or "").strip()
        for row in rows:
            # 同一航段只保留一条进行中的引导单，重复下达以首次为准
            if str(row.get("对应航班") or "").strip() == flight and row.get("status") in ACTIVE_STATUSES:
                return row, [], f"航段 {flight} 已有进行中的引导单（{row.get('引导编号')}），重复下达以首次为准"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        for field in ("引导车编号", "引导员", "预计到位"):
            entry[field] = str(values.get(field) or "").strip()
        entry["实际到位"] = ""
        entry["下达时间"] = ""
        entry["取消原因"] = ""
        entry["取消时间"] = ""
        self._apply_status(entry, STATUS_ORDER[0])
        rows.append(entry)
        return entry, [], "引导任务已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"引导任务 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于引导入位可执行范围"
        status = str(entry.get("status") or STATUS_ORDER[0])
        # 幂等：同一引导单重复下达只认第一次，直接回当前状态，不改数据
        if action == "下达引导" and status == "已下达":
            return entry, "该引导单已下达，重复下达以首次为准"
        target = STATUS_FLOW.get(status, {}).get(action)
        if target is None:
            return None, self._reject_reason(status, action)
        values = values or {}
        if action == "下达引导":
            entry["下达时间"] = _now()
        elif action == "确认到位":
            entry["实际到位"] = _now()
        elif action == "取消引导":
            reason = str(values.get("取消原因") or "").strip()
            if not reason:
                return None, "取消引导必须填写取消原因"
            entry["引导车编号"] = ""
            entry["取消原因"] = reason
            entry["取消时间"] = _now()
        self._apply_status(entry, target)
        return entry, f"引导任务已{action}"

    def _apply_status(self, entry: dict[str, Any], status: str) -> None:
        """状态落库：内部状态、面板展示列与看板标记一次写齐，避免队列与单条记录不一致。"""
        entry["status"] = status
        entry["引导状态"] = status
        entry["pending"] = status in ACTIVE_STATUSES
        entry["abnormal"] = status == "已取消"

    def _reject_reason(self, status: str, action: str) -> str:
        if status == "已取消":
            return "引导任务已取消，不能再执行任何动作"
        if status == "已到位":
            return "引导任务已到位，流程已结束"
        if action == "确认到位":
            return "引导任务尚未下达，不能跳过下达直接确认到位"
        return f"当前状态「{status}」不允许执行「{action}」"
