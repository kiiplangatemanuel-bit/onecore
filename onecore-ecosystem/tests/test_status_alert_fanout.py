from types import SimpleNamespace

from app.api.portal_workflows import _queue_status_alert_deliveries
from app.core.models import PortalWorkflowRecord, StatusAlertDelivery, User


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _DB:
    bind = None

    def __init__(self, subscriptions, users):
        self.info = {}
        self.subscriptions = subscriptions
        self.users = users
        self.added = []

    def query(self, model):
        if model is PortalWorkflowRecord:
            return _Query(self.subscriptions)
        if model is User:
            # The helper queries one recipient at a time; filter in a fresh query.
            return _UserQuery(self.users)
        raise AssertionError(f"unexpected query model: {model}")

    def add(self, item):
        self.added.append(item)


class _UserQuery(_Query):
    def __init__(self, users):
        super().__init__([])
        self.users = users

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        self.rows = [
            user for user in self.users
            if all(getattr(user, key) == value for key, value in kwargs.items())
        ]
        return self


def test_public_status_incident_fanout_targets_only_matching_active_subscribers():
    subscriptions = [
        SimpleNamespace(owner_user_id=1, payload={"service": "API"}),
        SimpleNamespace(owner_user_id=2, payload={"service": "all"}),
        SimpleNamespace(owner_user_id=3, payload={"service": "Payments"}),
    ]
    users = [
        SimpleNamespace(id=1, is_active=True, email="api@example.test"),
        SimpleNamespace(id=2, is_active=True, email="all@example.test"),
        SimpleNamespace(id=3, is_active=True, email="payments@example.test"),
    ]
    db = _DB(subscriptions, users)
    incident = SimpleNamespace(
        id=77,
        payload={"title": "API degraded", "service": "API", "severity": "major", "summary": "Elevated errors"},
    )

    _queue_status_alert_deliveries(db, incident, "published")

    assert db.info["onecore_status_alert_incident_id"] == 77
    assert len(db.added) == 2
    assert all(isinstance(row, StatusAlertDelivery) for row in db.added)
    assert {row.user_id for row in db.added} == {1, 2}
    assert all(row.incident_record_id == 77 and row.status == "pending" for row in db.added)
    assert len({row.event_key for row in db.added}) == 2
