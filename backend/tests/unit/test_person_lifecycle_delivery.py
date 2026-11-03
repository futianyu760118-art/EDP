from edp_worker.person_lifecycle_delivery import ALLOWED_TARGET_STATUSES


def test_delivery_does_not_treat_failure_or_unknown_status_as_success():
    assert 'failed' in ALLOWED_TARGET_STATUSES
    assert 'retrying' in ALLOWED_TARGET_STATUSES
    assert 'scheduled' not in ALLOWED_TARGET_STATUSES
    assert 'stale' not in ALLOWED_TARGET_STATUSES
