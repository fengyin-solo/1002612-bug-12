"""引导入位接口：维护引导任务，覆盖下达引导、确认到位、取消引导等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.marshalling import MarshallingService

router = APIRouter(prefix="/api/marshalling", tags=["引导入位"])

service = MarshallingService()

LIST_FIELDS = ["引导编号", "对应航班", "机位编号", "引导车编号", "引导员", "预计到位", "实际到位", "引导状态", "取消原因"]
STATUSES = ["待下达", "已下达", "已到位", "已取消"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按引导编号检索"),
    flight: str | None = Query(default=None, description="按对应航班检索"),
    stand: str | None = Query(default=None, description="按机位编号检索"),
    status: str | None = Query(default=None, description="待下达、已下达、已到位、已取消"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按引导编号、航班、机位与状态过滤引导入位列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, flight=flight, stand=stand, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 固定路径要放在 /{entry_id} 之前，否则 "stats"、"export" 会被当成 entry_id 解析，直接 422。
@router.get("/stats")
def stats() -> dict[str, int]:
    """看板计数：在途引导单数与队列同源，随每次状态流转重算。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出引导入位清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "marshalling", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条引导任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"引导任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条引导任务；同一航段已有进行中的引导单时返回原单，不重复登记。"""
    entry, missing, message = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条引导任务执行下达引导、确认到位、取消引导；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
