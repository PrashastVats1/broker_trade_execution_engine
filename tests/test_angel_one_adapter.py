from __future__ import annotations

import json

import httpx
import pytest

from app.angel_one import AngelOneAdapter
from app.brokers import BrokerCredentials
from app.domain import (
    BrokerOrderRequest,
    BrokerUnavailableError,
    InstrumentInput,
    OrderStatus,
    OrderStatusUnknownError,
    Side,
)


@pytest.mark.asyncio
async def test_angel_one_full_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("OpenAPIScripMaster.json"):
            return httpx.Response(
                200,
                json=[
                    {
                        "token": "2885",
                        "symbol": "RELIANCE-EQ",
                        "name": "RELIANCE",
                        "exch_seg": "NSE",
                        "instrumenttype": "",
                    }
                ],
            )
        assert request.headers["x-privatekey"] == "key"
        if path.endswith("/getHolding"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "tradingsymbol": "RELIANCE-EQ",
                            "exchange": "NSE",
                            "symboltoken": "2885",
                            "isin": "INE002A01018",
                            "quantity": 10,
                        }
                    ]
                },
            )
        if path.endswith("/placeOrder"):
            body = json.loads(request.content)
            assert body["symboltoken"] == "2885"
            assert body["ordertag"] == "client-order-1"
            return httpx.Response(
                200,
                json={"data": {"orderid": "A1", "uniqueorderid": "AU1"}},
            )
        if path.endswith("/details/AU1"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "orderstatus": "complete",
                        "quantity": "2",
                        "filledshares": "2",
                        "averageprice": "2500",
                    }
                },
            )
        if path.endswith("/cancelOrder"):
            return httpx.Response(200, json={"data": {"orderid": "A1"}})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AngelOneAdapter(BrokerCredentials("key", "token"), client)
        holdings = await adapter.get_holdings()
        instrument = await adapter.resolve_instrument(InstrumentInput(symbol="RELIANCE"))
        placed = await adapter.place_order(
            BrokerOrderRequest(instrument, Side.BUY, 2, "client-order-1")
        )
        result = await adapter.get_order_status("AU1", "client-order-1")
        cancelled = await adapter.cancel_order("A1")

    assert holdings[0].quantity == 10
    assert instrument.broker_symbol == "RELIANCE-EQ"
    assert placed.broker_order_id == "AU1"
    assert result.status == OrderStatus.EXECUTED
    assert cancelled.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_angel_one_login_does_not_persist_pin_or_totp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"clientcode": "C123", "password": "1234", "totp": "654321"}
        return httpx.Response(200, json={"data": {"jwtToken": "jwt", "refreshToken": "refresh"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AngelOneAdapter(BrokerCredentials("key"), client)
        credentials = await adapter.login(client_code="C123", pin="1234", totp="654321")

    assert credentials.access_token == "jwt"
    assert credentials.client_id == "C123"
    assert "1234" not in repr(credentials)
    assert "654321" not in repr(credentials)


@pytest.mark.asyncio
async def test_angel_one_rejects_truncated_instrument_master() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'[{"token":')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AngelOneAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(BrokerUnavailableError):
            await adapter.resolve_instrument(InstrumentInput(symbol="RELIANCE"))


@pytest.mark.asyncio
async def test_angel_one_submit_timeout_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AngelOneAdapter(BrokerCredentials("key", "token"), client)
        with pytest.raises(OrderStatusUnknownError):
            await adapter.place_order(
                BrokerOrderRequest(_instrument(), Side.BUY, 1, "client-order-1")
            )
    assert calls == 1


def _instrument():  # type: ignore[no-untyped-def]
    from app.domain import ResolvedInstrument

    return ResolvedInstrument(
        "RELIANCE",
        "NSE",
        broker_symbol="RELIANCE-EQ",
        broker_token="2885",
    )
