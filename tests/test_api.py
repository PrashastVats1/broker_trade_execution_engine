import httpx
import pytest

from app.config import Settings
from app.domain import (
    BrokerAuthenticationError,
    BrokerRateLimitError,
    BrokerUnavailableError,
    DeliveryAuthorizationRequired,
    InstrumentResolutionError,
)
from app.main import create_app
from app.mock_broker import MockBrokerState


@pytest.mark.asyncio
async def test_mock_execution_and_idempotent_readback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}"),
        mock_state=MockBrokerState(),
    )
    payload = {
        "broker": "mock",
        "workflow": "REBALANCE",
        "orders": [
            {"symbol": "RELIANCE", "side": "SELL", "quantity": 5},
            {"symbol": "INFY", "side": "BUY", "quantity": 10},
        ],
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "api-rebalance-1"},
                json=payload,
            )
            replay = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "api-rebalance-1"},
                json=payload,
            )
            fetched = await client.get(f"/api/v1/executions/{response.json()['id']}")
            openapi = await client.get("/openapi.json")

    assert response.status_code == 201
    assert response.json()["status"] == "SUCCESS"
    assert replay.json()["id"] == response.json()["id"]
    assert fetched.status_code == 200
    assert openapi.status_code == 200
    assert "/api/v1/executions" in openapi.json()["paths"]


@pytest.mark.asyncio
async def test_api_partial_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'partial.db'}"),
        mock_state=MockBrokerState(reject_symbols={"INFY"}),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "api-partial-1"},
                json={
                    "broker": "mock",
                    "workflow": "REBALANCE",
                    "orders": [
                        {"symbol": "RELIANCE", "side": "SELL", "quantity": 5},
                        {"symbol": "INFY", "side": "BUY", "quantity": 10},
                    ],
                },
            )

    assert response.status_code == 201
    assert response.json()["status"] == "PARTIAL_SUCCESS"
    assert response.json()["orders"][1]["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_api_requires_idempotency_header_and_valid_quantity(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'validation.db'}"))
    payload = {
        "broker": "mock",
        "workflow": "REBALANCE",
        "orders": [{"symbol": "TCS", "side": "BUY", "quantity": 0}],
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            missing_header = await client.post("/api/v1/executions", json=payload)
            invalid_quantity = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "validation-key"},
                json=payload,
            )

    assert missing_header.status_code == 422
    assert invalid_quantity.status_code == 422


@pytest.mark.asyncio
async def test_api_idempotency_payload_conflict_returns_409(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'conflict.db'}")
    )
    payload = {
        "broker": "mock",
        "workflow": "REBALANCE",
        "orders": [{"symbol": "TCS", "side": "BUY", "quantity": 1}],
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "api-conflict"},
                json=payload,
            )
            conflict = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "api-conflict"},
                json={
                    **payload,
                    "orders": [{"symbol": "TCS", "side": "BUY", "quantity": 2}],
                },
            )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_mock_scenario_timeout_reconciles_without_another_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'scenario.db'}",
        allow_live_trading=False,
    )
    state = MockBrokerState()
    app = create_app(settings, mock_state=state)
    payload = {
        "broker": "mock",
        "workflow": "REBALANCE",
        "orders": [{"symbol": "INFY", "side": "BUY", "quantity": 1}],
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            initial = await client.get("/api/v1/brokers/mock/scenario")
            selected = await client.post(
                "/api/v1/brokers/mock/scenario",
                json={"scenario": "EXECUTED_BUT_RESPONSE_TIMEOUT"},
            )
            created = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "scenario-timeout-1"},
                json=payload,
            )
            replay = await client.post(
                "/api/v1/executions",
                headers={"Idempotency-Key": "scenario-timeout-1"},
                json=payload,
            )
            execution_id = created.json()["id"]
            reconciled = await client.post(f"/api/v1/executions/{execution_id}/reconcile")
            repeated = await client.post(f"/api/v1/executions/{execution_id}/reconcile")

    assert settings.allow_live_trading is False
    assert initial.json() == {"scenario": "NORMAL"}
    assert selected.json() == {"scenario": "EXECUTED_BUT_RESPONSE_TIMEOUT"}
    assert created.status_code == 201
    assert created.json()["status"] == "RECONCILIATION_REQUIRED"
    assert created.json()["orders"][0]["status"] == "UNKNOWN"
    assert replay.json()["id"] == execution_id
    assert reconciled.json()["status"] == "SUCCESS"
    assert reconciled.json()["orders"][0]["status"] == "EXECUTED"
    assert reconciled.json()["orders"][0]["broker_order_id"] == "mock-1"
    assert repeated.json()["orders"][0]["broker_order_id"] == "mock-1"
    assert state.recorded_executions == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (BrokerAuthenticationError("missing token"), 401),
        (BrokerRateLimitError("limited"), 429),
        (BrokerUnavailableError("unavailable"), 503),
        (DeliveryAuthorizationRequired("authorize delivery"), 409),
        (InstrumentResolutionError("not found"), 422),
    ],
)
async def test_api_maps_domain_errors(
    tmp_path, error: Exception, expected_status: int  # type: ignore[no-untyped-def]
) -> None:
    app = create_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / f'errors-{expected_status}.db'}")
    )

    @app.get("/test/error")
    async def raise_domain_error() -> None:
        raise error

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/test/error")

    assert response.status_code == expected_status
