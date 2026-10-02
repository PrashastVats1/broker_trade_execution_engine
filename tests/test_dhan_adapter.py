from __future__ import annotations

import json

import httpx
import pytest

from app.brokers import BrokerCredentials
from app.dhan import DhanAdapter
from app.domain import (
    BrokerOrderRequest,
    InstrumentInput,
    OrderStatus,
    OrderStatusUnknownError,
    Side,
)


@pytest.mark.asyncio
async def test_dhan_full_contract() -> None:
    csv_body = (
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
        "SEM_TRADING_SYMBOL,SEM_SERIES\n"
        "NSE,E,1330,EQUITY,HDFC,EQ\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api-scrip-master.csv"):
            return httpx.Response(200, text=csv_body)
        assert request.headers["access-token"] == "token"
        if path == "/v2/holdings":
            return httpx.Response(
                200,
                json=[
                    {
                        "exchange": "NSE",
                        "tradingSymbol": "HDFC",
                        "securityId": "1330",
                        "isin": "INE001A01036",
                        "totalQty": 10,
                    }
                ],
            )
        if path == "/v2/orders" and request.method == "POST":
            body = json.loads(request.content)
            assert body["dhanClientId"] == "1000000001"
            assert body["securityId"] == "1330"
            assert body["correlationId"] == "client-order-1"
            return httpx.Response(200, json={"orderId": "D1", "orderStatus": "PENDING"})
        if path == "/v2/orders/D1" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "orderId": "D1",
                    "orderStatus": "TRADED",
                    "quantity": 2,
                    "filledQty": 2,
                    "averageTradedPrice": 2500,
                },
            )
        if path == "/v2/orders/D1" and request.method == "DELETE":
            return httpx.Response(202, json={"orderId": "D1", "orderStatus": "CANCELLED"})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = DhanAdapter(
            BrokerCredentials("app", "token", client_id="1000000001"),
            client,
        )
        holdings = await adapter.get_holdings()
        instrument = await adapter.resolve_instrument(InstrumentInput(symbol="HDFC"))
        placed = await adapter.place_order(
            BrokerOrderRequest(instrument, Side.BUY, 2, "client-order-1")
        )
        result = await adapter.get_order_status("D1", "client-order-1")
        cancelled = await adapter.cancel_order("D1")

    assert holdings[0].quantity == 10
    assert instrument.broker_token == "1330"
    assert instrument.segment == "NSE_EQ"
    assert placed.status == OrderStatus.OPEN
    assert result.status == OrderStatus.EXECUTED
    assert cancelled.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_dhan_consent_auth_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/generate-consent":
            assert request.headers["app_id"] == "app"
            assert request.url.params["client_id"] == "1000000001"
            return httpx.Response(200, json={"consentAppId": "consent-1"})
        if request.url.path == "/app/consumeApp-consent":
            assert request.url.params["tokenId"] == "token-id"
            return httpx.Response(
                200,
                json={"dhanClientId": "1000000001", "accessToken": "access"},
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = DhanAdapter(
            BrokerCredentials(
                api_key="app",
                api_secret="secret",
                client_id="1000000001",
            ),
            client,
        )
        consent = await adapter.generate_consent()
        credentials = await adapter.consume_consent("token-id")

    assert consent == "consent-1"
    assert "consentAppId=consent-1" in adapter.consent_login_url(consent)
    assert credentials.access_token == "access"


@pytest.mark.asyncio
async def test_dhan_status_uses_correlation_when_order_id_lost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/orders/external/client-order-1"
        return httpx.Response(
            200,
            json={
                "orderId": "recovered",
                "orderStatus": "PART_TRADED",
                "quantity": 10,
                "filledQty": 4,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = DhanAdapter(BrokerCredentials("app", "token"), client)
        result = await adapter.get_order_status(None, "client-order-1")

    assert result.broker_order_id == "recovered"
    assert result.status == OrderStatus.PARTIALLY_FILLED


@pytest.mark.asyncio
async def test_dhan_submit_timeout_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = DhanAdapter(
            BrokerCredentials("app", "token", client_id="1000000001"),
            client,
        )
        with pytest.raises(OrderStatusUnknownError):
            await adapter.place_order(
                BrokerOrderRequest(_instrument(), Side.BUY, 1, "client-order-1")
            )
    assert calls == 1


def _instrument():  # type: ignore[no-untyped-def]
    from app.domain import ResolvedInstrument

    return ResolvedInstrument(
        "HDFC",
        "NSE",
        segment="NSE_EQ",
        broker_symbol="HDFC",
        broker_token="1330",
    )
