from __future__ import annotations

import hashlib
from urllib.parse import parse_qs

import httpx
import pytest

from app.brokers import BrokerCredentials
from app.domain import (
    BrokerOrderRequest,
    DeliveryAuthorizationRequired,
    InstrumentInput,
    OrderStatus,
    OrderStatusUnknownError,
    Side,
)
from app.zerodha import ZerodhaAdapter


@pytest.mark.asyncio
async def test_zerodha_full_contract() -> None:
    csv_body = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
        "tick_size,lot_size,instrument_type,segment,exchange\n"
        "738561,2885,RELIANCE,Reliance,0,,,0.05,1,EQ,NSE,NSE\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assert request.headers["x-kite-version"] == "3"
        if path == "/portfolio/holdings":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [
                        {
                            "tradingsymbol": "RELIANCE",
                            "exchange": "NSE",
                            "isin": "INE002A01018",
                            "instrument_token": 738561,
                            "quantity": 10,
                        }
                    ],
                },
            )
        if path == "/instruments/NSE":
            return httpx.Response(200, text=csv_body)
        if path == "/orders/regular" and request.method == "POST":
            body = parse_qs(request.content.decode())
            assert body["tag"] == ["client-order-1"]
            assert body["market_protection"] == ["-1"]
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "Z1"}})
        if path == "/orders/Z1":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "order_id": "Z1",
                            "status": "COMPLETE",
                            "quantity": 2,
                            "filled_quantity": 2,
                            "average_price": 2500,
                        }
                    ]
                },
            )
        if path == "/orders/regular/Z1":
            return httpx.Response(200, json={"data": {"order_id": "Z1"}})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ZerodhaAdapter(BrokerCredentials("key", "token"), client)
        holdings = await adapter.get_holdings()
        instrument = await adapter.resolve_instrument(InstrumentInput(symbol="RELIANCE"))
        placed = await adapter.place_order(
            BrokerOrderRequest(instrument, Side.BUY, 2, "client-order-1")
        )
        result = await adapter.get_order_status("Z1", "client-order-1")
        cancelled = await adapter.cancel_order("Z1")

    assert holdings[0].quantity == 10
    assert instrument.broker_token == "738561"
    assert placed.broker_order_id == "Z1"
    assert result.status == OrderStatus.EXECUTED
    assert cancelled.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_zerodha_auth_checksum() -> None:
    expected = hashlib.sha256(b"keyrequestsecret").hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        assert body["checksum"] == [expected]
        return httpx.Response(200, json={"data": {"access_token": "new-token"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ZerodhaAdapter(
            BrokerCredentials(api_key="key", api_secret="secret"),
            client,
        )
        exchanged = await adapter.exchange_token("request")

    assert exchanged.access_token == "new-token"


@pytest.mark.asyncio
async def test_zerodha_edis_required_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(428, json={"message": "Authorisation required"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ZerodhaAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(DeliveryAuthorizationRequired):
            await adapter.place_order(
                BrokerOrderRequest(
                    _resolved(),
                    Side.SELL,
                    1,
                    "client-order-1",
                )
            )


@pytest.mark.asyncio
async def test_zerodha_submit_timeout_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ZerodhaAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(OrderStatusUnknownError):
            await adapter.place_order(
                BrokerOrderRequest(_resolved(), Side.BUY, 1, "client-order-1")
            )
    assert calls == 1


def _resolved():  # type: ignore[no-untyped-def]
    from app.domain import ResolvedInstrument

    return ResolvedInstrument(
        symbol="RELIANCE",
        exchange="NSE",
        broker_symbol="RELIANCE",
        broker_token="738561",
    )
