from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from app.brokers import BrokerCredentials
from app.domain import (
    BrokerOrderRequest,
    InstrumentInput,
    InstrumentResolutionError,
    OrderStatus,
    OrderStatusUnknownError,
    Side,
)
from app.groww import GrowwAdapter


@pytest.mark.asyncio
async def test_groww_full_contract() -> None:
    csv_body = (
        "exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,"
        "segment,series,isin,buy_allowed,sell_allowed\n"
        "NSE,2885,RELIANCE,NSE-RELIANCE,Reliance,EQ,CASH,EQ,INE002A01018,1,1\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/instruments/instrument.csv":
            return httpx.Response(200, text=csv_body)
        assert request.headers["x-api-version"] == "1.0"
        if path == "/v1/holdings/user":
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "payload": {
                        "holdings": [
                            {
                                "isin": "INE002A01018",
                                "trading_symbol": "RELIANCE",
                                "quantity": 10,
                            }
                        ]
                    },
                },
            )
        if path == "/v1/order/create":
            body = json.loads(request.content)
            assert body["order_reference_id"] == "client-order-1"
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "payload": {
                        "groww_order_id": "G1",
                        "order_status": "OPEN",
                        "remark": "accepted",
                    },
                },
            )
        if path == "/v1/order/status/G1":
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "payload": {
                        "groww_order_id": "G1",
                        "order_status": "EXECUTED",
                        "filled_quantity": 2,
                        "average_fill_price": 2500,
                    },
                },
            )
        if path == "/v1/order/cancel":
            return httpx.Response(200, json={"status": "SUCCESS", "payload": {}})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GrowwAdapter(BrokerCredentials("key", "token"), client)
        holdings = await adapter.get_holdings()
        instrument = await adapter.resolve_instrument(InstrumentInput(symbol="RELIANCE"))
        placed = await adapter.place_order(
            BrokerOrderRequest(instrument, Side.BUY, 2, "client-order-1")
        )
        result = await adapter.get_order_status("G1", "client-order-1")
        cancelled = await adapter.cancel_order("G1")

    assert holdings[0].quantity == 10
    assert instrument.broker_token == "2885"
    assert placed.status == OrderStatus.OPEN
    assert result.status == OrderStatus.EXECUTED
    assert cancelled.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_groww_token_generation_contract() -> None:
    timestamp = 1719830400
    expected = hashlib.sha256(f"secret{timestamp}".encode()).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer key"
        assert body == {
            "key_type": "approval",
            "checksum": expected,
            "timestamp": str(timestamp),
        }
        return httpx.Response(200, json={"token": "new-token", "isActive": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GrowwAdapter(BrokerCredentials("key", api_secret="secret"), client)
        credentials = await adapter.generate_access_token(timestamp)

    assert credentials.access_token == "new-token"


@pytest.mark.asyncio
async def test_groww_rejects_ambiguous_instrument() -> None:
    csv_body = (
        "exchange,exchange_token,trading_symbol,instrument_type,segment,series,isin\n"
        "NSE,1,TCS,EQ,CASH,EQ,INE467B01029\n"
        "NSE,2,TCS,EQ,CASH,EQ,INE467B01029\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv_body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GrowwAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(InstrumentResolutionError):
            await adapter.resolve_instrument(InstrumentInput(symbol="TCS"))


@pytest.mark.asyncio
async def test_groww_submit_timeout_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GrowwAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(OrderStatusUnknownError):
            await adapter.place_order(
                BrokerOrderRequest(
                    instrument=_instrument(),
                    side=Side.BUY,
                    quantity=1,
                    client_order_id="client-order-1",
                )
            )
    assert calls == 1


def _instrument():  # type: ignore[no-untyped-def]
    from app.domain import ResolvedInstrument

    return ResolvedInstrument("RELIANCE", "NSE", broker_symbol="RELIANCE")
