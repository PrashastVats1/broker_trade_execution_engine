from __future__ import annotations

import json

import httpx
import pytest

from app.brokers import BrokerCredentials
from app.domain import (
    BrokerAuthenticationError,
    BrokerOrderRequest,
    BrokerRateLimitError,
    BrokerUnavailableError,
    InstrumentInput,
    InstrumentResolutionError,
    OrderStatus,
    OrderStatusUnknownError,
    ResolvedInstrument,
    Side,
)
from app.upstox import UpstoxAdapter


@pytest.mark.asyncio
async def test_upstox_full_order_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/v2/portfolio/long-term-holdings":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [
                        {
                            "tradingsymbol": "RELIANCE",
                            "exchange": "NSE",
                            "isin": "INE002A01018",
                            "instrument_token": "NSE_EQ|INE002A01018",
                            "quantity": 10,
                        }
                    ],
                },
            )
        if path == "/v2/instruments/search":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [
                        {
                            "trading_symbol": "RELIANCE",
                            "exchange": "NSE_EQ",
                            "isin": "INE002A01018",
                            "instrument_key": "NSE_EQ|INE002A01018",
                        }
                    ],
                },
            )
        if path == "/v3/order/place":
            body = json.loads(request.content)
            assert body["instrument_token"] == "NSE_EQ|INE002A01018"
            assert body["tag"] == "client-order-1"
            assert body["slice"] is False
            assert body["market_protection"] == -1
            return httpx.Response(200, json={"status": "success", "data": {"order_ids": ["U1"]}})
        if path == "/v2/order/details":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "order_id": "U1",
                        "status": "complete",
                        "quantity": 3,
                        "filled_quantity": 3,
                        "average_price": 2510.25,
                    },
                },
            )
        if path == "/v3/order/cancel":
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "U1"}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(
            BrokerCredentials(api_key="key", access_token="token"),
            client,
        )
        holdings = await adapter.get_holdings()
        instrument = await adapter.resolve_instrument(InstrumentInput(symbol="RELIANCE"))
        placed = await adapter.place_order(
            BrokerOrderRequest(
                instrument=instrument,
                side=Side.BUY,
                quantity=3,
                client_order_id="client-order-1",
            )
        )
        status = await adapter.get_order_status(placed.broker_order_id, "client-order-1")
        cancelled = await adapter.cancel_order("U1")

    assert holdings[0].quantity == 10
    assert instrument.broker_token == "NSE_EQ|INE002A01018"
    assert placed.status == OrderStatus.SUBMITTED
    assert status.status == OrderStatus.EXECUTED
    assert status.filled_quantity == 3
    assert cancelled.status == OrderStatus.CANCELLED
    assert all(request.headers["authorization"] == "Bearer token" for request in seen)


@pytest.mark.asyncio
async def test_upstox_auth_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/login/authorization/token"
        assert b"grant_type=authorization_code" in request.content
        return httpx.Response(200, json={"access_token": "new-token"})

    credentials = BrokerCredentials(
        api_key="key",
        api_secret="secret",
        redirect_uri="https://example.test/callback",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(credentials, client)
        url = adapter.auth_url("csrf-state")
        exchanged = await adapter.exchange_token("single-use-code")

    assert "state=csrf-state" in url
    assert "client_id=key" in url
    assert exchanged.access_token == "new-token"


@pytest.mark.asyncio
async def test_upstox_rejects_ambiguous_instrument() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        row = {
            "trading_symbol": "RELIANCE",
            "exchange": "NSE_EQ",
            "instrument_key": "NSE_EQ|INE002A01018",
        }
        return httpx.Response(200, json={"data": [row, row | {"instrument_key": "duplicate"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(InstrumentResolutionError):
            await adapter.resolve_instrument(InstrumentInput(symbol="RELIANCE"))


@pytest.mark.asyncio
async def test_upstox_place_timeout_is_unknown_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost response", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(OrderStatusUnknownError):
            await adapter.place_order(
                BrokerOrderRequest(
                    instrument=ResolvedInstrument(
                        "RELIANCE",
                        "NSE",
                        broker_symbol="RELIANCE",
                        broker_token="NSE_EQ|INE002A01018",
                    ),
                    side=Side.BUY,
                    quantity=1,
                    client_order_id="client-order-1",
                )
            )

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, BrokerAuthenticationError),
        (429, BrokerRateLimitError),
        (503, BrokerUnavailableError),
    ],
)
async def test_upstox_normalizes_http_failures(status_code, expected) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "failure"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(expected):
            await adapter.get_holdings()


@pytest.mark.asyncio
async def test_upstox_rejects_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(BrokerUnavailableError):
            await adapter.get_holdings()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "content"),
    [
        (503, b'{"message":"upstream failure"}'),
        (200, b"not-json"),
    ],
)
async def test_upstox_ambiguous_placement_response_is_unknown(
    status_code: int, content: bytes
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = UpstoxAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(OrderStatusUnknownError):
            await adapter.place_order(
                BrokerOrderRequest(
                    instrument=ResolvedInstrument(
                        "RELIANCE",
                        "NSE",
                        broker_symbol="RELIANCE",
                        broker_token="NSE_EQ|INE002A01018",
                    ),
                    side=Side.BUY,
                    quantity=1,
                    client_order_id="ambiguous-placement",
                )
            )

    assert calls == 1
