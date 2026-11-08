import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_verified_organization_context_is_positive_and_persists_for_new_transactions():
    from app.core.security import set_verified_organization_context

    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        set_verified_organization_context(db, 42)
        assert db.info["onecore_organization_id"] == 42
        with pytest.raises(ValueError):
            set_verified_organization_context(db, 0)
    engine.dispose()


def test_provider_callback_context_does_not_store_raw_callback_secrets():
    from app.core.security import set_provider_callback_token_context

    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        set_provider_callback_token_context(db, "a" * 64)
        assert "onecore_user_id" not in db.info
        assert "onecore_organization_id" not in db.info
    engine.dispose()
