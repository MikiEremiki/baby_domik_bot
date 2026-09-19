from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ScheduleSyncItem(BaseModel):
    item_id: str
    event_id: int
    change_ids: List[int]
    operation: Literal['create', 'update']
    expected: Optional[Dict[str, Any]] = None
    desired: Dict[str, Any]
    fields: List[str]


class ScheduleSyncTask(BaseModel):
    action: Literal['sync_schedule'] = 'sync_schedule'
    sheet_id: str
    run_id: str
    items: List[ScheduleSyncItem]


class ScheduleSyncItemResult(BaseModel):
    item_id: str
    event_id: int
    change_ids: List[int]
    status: Literal['created', 'updated', 'already_equal', 'conflict', 'failed']
    details: Optional[Dict[str, Any]] = None
    unsupported_fields: List[str] = Field(default_factory=list)


class ScheduleSyncRunResult(BaseModel):
    action: Literal['schedule_sync_result'] = 'schedule_sync_result'
    sheet_id: str
    run_id: str
    item_results: List[ScheduleSyncItemResult]
    error: Optional[str] = None
