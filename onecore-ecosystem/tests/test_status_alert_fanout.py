from types import SimpleNamespace

from app.api.portal_workflows import _queue_status_alert_deliveries
from app.core.models import PortalWorkflowRecord, StatusAlertDelivery, User


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        self.rows = [
            row for row in self.rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _DB:
    bind = None

    def __init__(self, subscriptions, users, channel_preferences=()):
        self.info = {}
        self.subscriptions = subscriptions
        self.channel_preferences = list(channel_preferences)
        self.users = users
        self.added = []

    def query(self, model):
        if model is PortalWorkflowRecord:
            return _Query(self.subscriptions + self.channel_preferences)
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
        SimpleNamespace(owner_user_id=1, portal_key="status", record_type="alert_subscription", status="active", payload={"service": "API"}),
        SimpleNamespace(owner_user_id=1, portal_key="status", record_type="alert_subscription", status="active", payload={"service": "all"}),
        SimpleNamespace(owner_user_id=2, portal_key="status", record_type="alert_subscription", status="active", payload={"service": "all"}),
        SimpleNamespace(owner_user_id=3, portal_key="status", record_type="alert_subscription", status="active", payload={"service": "Payments"}),
        SimpleNamespace(owner_user_id=4, portal_key="status", record_type="alert_subscription", status="active", payload={"service": "API"}),
    ]
    users = [
        SimpleNamespace(id=1, is_active=True, email="api@example.test"),
        SimpleNamespace(id=2, is_active=True, email="all@example.test"),
        SimpleNamespace(id=3, is_active=True, email="payments@example.test"),
        SimpleNamespace(id=4, is_active=True, email="optout@example.test"),
    ]
    channel_preferences = [
        SimpleNamespace(owner_user_id=4, portal_key="status", record_type="notification_preference", status="active",
                        payload={"channel": "email", "service": "API", "enabled": False}),
    ]
    db = _DB(subscriptions, users, channel_preferences)
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
    assert len({(row.user_id, row.event_key) for row in db.added}) == 2
