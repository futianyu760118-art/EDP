from edp_api.modules.person_lifecycle.admin_router import STATUS_LABELS, status_label


def test_person_lifecycle_admin_uses_plain_chinese_status_labels():
    assert status_label('synced') == '已完成'
    assert status_label('skipped') == '已跳过'
    assert status_label('pending_confirmation') == '待管理员确认'
    assert status_label('pending') == '待处理'
    assert status_label('retrying') == '处理中'
    assert status_label('dlq') == '处理失败'
    assert all(label for label in STATUS_LABELS.values())
