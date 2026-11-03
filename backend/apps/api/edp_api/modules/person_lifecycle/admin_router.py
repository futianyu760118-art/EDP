"""人员状态同步的管理员查询：只显示通俗状态，不泄露签名和内部错误。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.modules.person_lifecycle import service
from edp_api.modules.person_lifecycle.models import PersonLifecycleDelivery, PersonLifecycleEvent
from edp_api.modules.tenantmgmt.dependencies import require_tenant_admin


STATUS_LABELS = {
    'synced': '已完成', 'skipped': '已跳过', 'pending_confirmation': '待管理员确认',
    'pending': '待处理', 'scheduled': '待处理', 'retrying': '处理中',
    'failed': '处理失败', 'dlq': '处理失败', 'stale': '已跳过', 'duplicate': '已完成',
}


def status_label(value: str) -> str:
    return STATUS_LABELS.get(str(value or '').lower(), '处理中')


admin_router = APIRouter(prefix='/api/v1/person-lifecycle/admin', tags=['person-lifecycle-admin'])


@admin_router.get('/events/{event_id}/summary')
async def lifecycle_summary(
    event_id: str,
    principal: Annotated[Principal, Depends(require_tenant_admin)],
    sess: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    event = (await sess.execute(select(PersonLifecycleEvent).where(
        PersonLifecycleEvent.tenant_id == principal.tenant_id,
        PersonLifecycleEvent.event_id == event_id,
    ))).scalar_one_or_none()
    if event is None:
        raise EdpError.not_found('人员状态同步记录不存在')
    deliveries = list((await sess.execute(select(PersonLifecycleDelivery).where(
        PersonLifecycleDelivery.tenant_id == principal.tenant_id,
        PersonLifecycleDelivery.event_id == event_id,
    ).order_by(PersonLifecycleDelivery.delivery_id))).scalars())
    status = event.status.lower()
    return {
        'event_id': event.event_id,
        'status': status,
        'status_text': status_label(status),
        'event_type': event.event_type,
        'object_id': event.object_id,
        'targets': [
            {'system_id': row.target_system, 'status': row.status.lower(), 'status_text': status_label(row.status)}
            for row in deliveries
        ],
    }
