from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from app.angel_one import AngelOneAdapter
from app.brokers import BrokerAdapter, BrokerCredentials, BrokerRegistry, HttpBrokerAdapter
from app.config import Settings, get_settings
from app.dhan import DhanAdapter
from app.domain import (
    BrokerName,
    ExecutionRequest,
    ExecutionView,
    ExistingHoldingsError,
    IdempotencyConflictError,
    TradeEngineError,
)
from app.groww import GrowwAdapter
from app.mock_broker import MockBrokerAdapter, MockBrokerState
from app.notifications import (
    CompositeNotifier,
    ConsoleNotifier,
    NotificationService,
    WebhookNotifier,
)
from app.persistence import ExecutionRepository, create_engine_and_session, create_schema
from app.services import ExecutionService
from app.upstox import UpstoxAdapter
from app.zerodha import ZerodhaAdapter

logger = logging.getLogger("kalpi")


class BrokerAuthComplete(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str | None = Field(default=None, min_length=16, max_length=256)


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


def _singleton(adapter: BrokerAdapter) -> Callable[[], BrokerAdapter]:
    return lambda: adapter


def create_app(
    settings: Settings | None = None,
    *,
    mock_state: MockBrokerState | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine, sessions = create_engine_and_session(settings.database_url)
    registry = BrokerRegistry()
    mock_adapter = MockBrokerAdapter(mock_state)
    registry.register(BrokerName.MOCK, lambda: mock_adapter)
    real_adapters: list[BrokerAdapter] = [
        ZerodhaAdapter(
            BrokerCredentials(
                api_key=settings.zerodha_api_key or "",
                api_secret=_secret(settings.zerodha_api_secret),
                access_token=_secret(settings.zerodha_access_token),
            )
        ),
        DhanAdapter(
            BrokerCredentials(
                api_key=settings.dhan_client_id or "",
                client_id=settings.dhan_client_id,
                api_secret=_secret(settings.dhan_api_secret),
                access_token=_secret(settings.dhan_access_token),
            )
        ),
        AngelOneAdapter(
            BrokerCredentials(
                api_key=settings.angel_one_api_key or "",
                access_token=_secret(settings.angel_one_access_token),
            ),
            client_local_ip=settings.angel_one_client_local_ip,
            client_public_ip=settings.angel_one_client_public_ip,
            mac_address=settings.angel_one_mac_address,
        ),
        GrowwAdapter(
            BrokerCredentials(
                api_key=settings.groww_api_key or "",
                access_token=_secret(settings.groww_access_token),
            )
        ),
        UpstoxAdapter(
            BrokerCredentials(
                api_key=settings.upstox_api_key or "",
                api_secret=_secret(settings.upstox_api_secret),
                access_token=_secret(settings.upstox_access_token),
                redirect_uri=f"{settings.broker_redirect_base_url}/upstox/callback",
            )
        ),
    ]
    for adapter in real_adapters:
        registry.register(adapter.name, _singleton(adapter))
    pending_auth_states: dict[BrokerName, str] = {}
    notifiers: list[NotificationService] = [ConsoleNotifier()]
    if settings.webhook_url:
        notifiers.append(WebhookNotifier(settings.webhook_url))
    repository = ExecutionRepository(sessions)
    service = ExecutionService(
        repository,
        registry,
        CompositeNotifier(notifiers),
        allow_live_trading=settings.allow_live_trading,
        poll_attempts=settings.order_poll_attempts,
        poll_interval_seconds=settings.order_poll_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        await create_schema(engine)
        yield
        for adapter in real_adapters:
            await adapter.client.aclose()  # type: ignore[attr-defined]
        await engine.dispose()

    app = FastAPI(
        title="Kalpi Portfolio Trade Execution Engine",
        version="0.1.0",
        description=(
            "Assignment demonstration. Live trading is disabled by default and "
            "the service does not claim exactly-once broker execution."
        ),
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.repository = repository
    app.state.registry = registry

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        request: Request, exc: IdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})

    @app.exception_handler(ExistingHoldingsError)
    async def existing_holdings(request: Request, exc: ExistingHoldingsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})

    @app.exception_handler(TradeEngineError)
    async def trade_engine_error(request: Request, exc: TradeEngineError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"code": exc.code, "detail": str(exc)})

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/api/v1/brokers", tags=["brokers"])
    async def list_brokers(request: Request) -> list[dict[str, str | bool]]:
        names = request.app.state.registry.names()
        return [
            {
                "name": name.value,
                "mode": "mock" if name == BrokerName.MOCK else "real",
                "live_certified": False,
            }
            for name in names
        ]

    @app.get("/api/v1/brokers/{broker}/status", tags=["brokers"])
    async def broker_status(broker: BrokerName) -> dict[str, str | bool]:
        adapter = registry.get(broker)
        token_configured = (
            isinstance(adapter, HttpBrokerAdapter) and bool(adapter.credentials.access_token)
        )
        return {
            "name": broker.value,
            "mode": "mock" if broker == BrokerName.MOCK else "real",
            "configured": broker == BrokerName.MOCK or token_configured,
            "live_certified": False,
        }

    @app.get("/api/v1/brokers/{broker}/auth/start", tags=["brokers"])
    async def broker_auth_start(broker: BrokerName) -> dict[str, str]:
        adapter = registry.get(broker)
        if isinstance(adapter, DhanAdapter):
            consent = await adapter.generate_consent()
            return {"authorization_url": adapter.consent_login_url(consent)}
        state = secrets.token_urlsafe(32)
        auth_url = adapter.auth_url(state)
        if auth_url is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This broker uses token or interactive login setup; "
                    "see broker documentation."
                ),
            )
        pending_auth_states[broker] = state
        return {"authorization_url": auth_url}

    @app.post("/api/v1/brokers/{broker}/auth/complete", tags=["brokers"])
    async def broker_auth_complete(
        broker: BrokerName, payload: BrokerAuthComplete
    ) -> dict[str, str]:
        adapter = registry.get(broker)
        if isinstance(adapter, DhanAdapter):
            credentials = await adapter.consume_consent(payload.code)
        else:
            expected_state = pending_auth_states.pop(broker, None)
            if not expected_state or not payload.state or not secrets.compare_digest(
                expected_state, payload.state
            ):
                raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
            credentials = await adapter.exchange_token(payload.code)
        adapter.credentials = credentials  # type: ignore[attr-defined]
        return {"broker": broker.value, "status": "connected"}

    @app.post(
        "/api/v1/executions",
        response_model=ExecutionView,
        status_code=status.HTTP_201_CREATED,
        tags=["executions"],
    )
    async def execute(
        payload: ExecutionRequest,
        request: Request,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=8, max_length=128),
        ],
    ) -> ExecutionView:
        try:
            return await service.execute(payload, idempotency_key)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get(
        "/api/v1/executions/{execution_id}",
        response_model=ExecutionView,
        tags=["executions"],
    )
    async def get_execution(execution_id: UUID, request: Request) -> ExecutionView:
        result = await repository.view(execution_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        return result

    @app.get(
        "/api/v1/executions/{execution_id}/orders",
        tags=["executions"],
    )
    async def get_execution_orders(execution_id: UUID, request: Request):  # type: ignore[no-untyped-def]
        result = await repository.view(execution_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        return result.orders

    @app.post(
        "/api/v1/executions/{execution_id}/reconcile",
        response_model=ExecutionView,
        tags=["executions"],
    )
    async def reconcile(execution_id: UUID, request: Request) -> ExecutionView:
        try:
            return await service.reconcile(execution_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Execution not found") from exc

    return app


app = create_app()
