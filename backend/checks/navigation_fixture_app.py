"""Disposable application for real login/JWT/DB navigation integration checks.

Uses production routers and guards; excludes unrelated startup seeds, workers,
and external integrations. Never imports app.main or connects to a shared DB.
"""
from functools import lru_cache
from pathlib import Path
import os
import uuid

from fastapi import Depends, FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.auth import hash_password
from backend.app.database import get_db
from backend.app.navigation_guard import enforce_navigation_policy
from backend.app.routers import auth, config, navigation, webhooks
from backend.app.session_models import AuthRefreshToken, AuthSession
from backend.app.tickets.models import WebhookSubscription, WebhookDeliveryLog

TENANTS = {"a": uuid.UUID("a1111111-1111-4111-8111-111111111111"), "b": uuid.UUID("b2222222-2222-4222-8222-222222222222")}
PASSWORD = "readiness-fixture-password"


@lru_cache(maxsize=1)
def fixture_password():
    return hash_password(PASSWORD)


def create_fixture_app(path: Path):
    review_url = os.getenv('ZEA_REVIEW_POSTGRES_URL')
    cleanup = lambda: None
    if review_url:
        target = make_url(review_url)
        if target.host != '127.0.0.1' or target.database != 'zea_review' or target.username != 'zea_review':
            raise RuntimeError('PostgreSQL checks require the disposable local zea_review database')
        schema = f'nav_app_{uuid.uuid4().hex}'
        admin = create_engine(review_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(review_url, connect_args={'options': f'-csearch_path={schema}'})
        def cleanup():
            engine.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
    else:
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    tables = [models.Department, models.User, models.AvatarAsset, models.NavigationPolicy,
              models.Reward, models.RewardClaim, models.AuditLog, models.ApiConfig, models.SmtpConfig, models.MultipleSmtpConfig,
              models.EmailTemplate, models.OAuthConfig, WebhookSubscription, WebhookDeliveryLog,
              AuthSession, AuthRefreshToken]
    models.Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with Session(engine) as db:
        for tenant_name, tenant in TENANTS.items():
            for role in models.RoleEnum:
                db.add(models.User(id=str(uuid.uuid5(tenant, role.value)), tenant_id=tenant,
                    name=f"Readiness {role.value} {tenant_name}", email=f"{role.value}-{tenant_name}@readiness.example.com",
                    hashed_password=fixture_password(), role=role, status=models.UserStatusEnum.ACTIVE))
            db.add(models.ApiConfig(tenant_id=str(tenant), provider="Fixture provider", api_key=f"tenant-{tenant_name}-fixture-key"))
        db.commit()
    app = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
    for router in (auth.router, config.router, navigation.router, webhooks.router, webhooks.internal_router):
        app.include_router(router)
        app.include_router(router, prefix="/api")
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = session
    # Authentication/config ancillary audit workers use the process global
    # SessionLocal. Suppress those in this disposable app. Navigation audit is
    # transactionally written by its real router and remains enabled.
    auth.audit_logger.log_event = lambda entry: None
    app.state.fixture_engine = engine
    app.state.fixture_cleanup = cleanup
    return app
