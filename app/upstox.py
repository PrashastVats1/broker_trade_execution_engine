from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

import httpx

from app.brokers import BrokerCredentials, HttpBrokerAdapter, normalize_status
from app.domain import (
    BrokerAuthenticationError,
    BrokerName,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerUnavailableError,
    Holding,
    InstrumentInput,
    InstrumentResolutionError,
    OrderStatus,
    ResolvedInstrument,
)


class UpstoxAdapter(HttpBrokerAdapter):
    """Upstox v2 account APIs and v3 HFT order APIs.

    Contract source: https://upstox.com/developer/api-documentation/
    Verified: 2026-10-02.
    """

    name = BrokerName.UPSTOX
    base_url = "https://api.upstox.com"
    order_base_url = "https://api-hft.upstox.com"

    def auth_url(self, state: str) -> str:
        if not self.credentials.redirect_uri:
            raise BrokerAuthenticationError("Upstox redirect_uri is missing")
        params = urlencode(
            {
                "client_id": self.credentials.api_key,
                "redirect_uri": self.credentials.redirect_uri,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{self.base_url}/v2/login/authorization/dialog?{params}"

    async def exchange_token(self, code: str) -> BrokerCredentials:
        if not self.credentials.api_secret or not self.credentials.redirect_uri:
            raise BrokerAuthenticationError("Upstox API secret and redirect_uri are required")
        try:
            response = await self.client.post(
                f"{self.base_url}/v2/login/authorization/token",
                headers={"Accept": "application/json"},
                data={
                    "code": code,
                    "client_id": self.credentials.api_key,
                    "client_secret": self.credentials.api_secret,
                    "redirect_uri": self.credentials.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            data = response.json()
            token = str(data["access_token"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise BrokerAuthenticationError("Upstox token exchange failed") from exc
        return BrokerCredentials(
            api_key=self.credentials.api_key,
            api_secret=self.credentials.api_secret,
            redirect_uri=self.credentials.redirect_uri,
            access_token=token,
        )

    async def get_holdings(self) -> list[Holding]:
        rows = (
            await self.request("GET", "/v2/portfolio/long-term-holdings", safe_to_retry=True)
        ).get("data", [])
        if not isinstance(rows, list):
            raise BrokerUnavailableError("Upstox holdings response is malformed")
        return [
            Holding(
                instrument=ResolvedInstrument(
                    symbol=str(row["tradingsymbol"]),
                    exchange=str(row["exchange"]),
                    isin=row.get("isin"),
                    broker_symbol=str(row["tradingsymbol"]),
                    broker_token=str(row["instrument_token"]),
                ),
                quantity=int(row.get("quantity", 0)),
            )
            for row in rows
        ]

    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument:
        path = self.query(
            "/v2/instruments/search",
            {
                "query": instrument.symbol,
                "exchanges": instrument.exchange,
                "segments": f"{instrument.exchange}_EQ",
            },
        )
        rows = (await self.request("GET", path, safe_to_retry=True)).get("data", [])
        matches = [
            row
            for row in rows
            if row.get("trading_symbol") == instrument.symbol
            and str(row.get("exchange", "")).startswith(instrument.exchange)
            and (instrument.isin is None or row.get("isin") == instrument.isin)
        ]
        if len(matches) != 1:
            raise InstrumentResolutionError(
                f"{instrument.exchange}:{instrument.symbol} resolved to {len(matches)} instruments"
            )
        row = matches[0]
        return ResolvedInstrument(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            segment=instrument.segment,
            isin=row.get("isin"),
            broker_symbol=str(row["trading_symbol"]),
            broker_token=str(row["instrument_key"]),
        )

    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
        payload = {
            "quantity": order.quantity,
            "product": "D" if order.product == "DELIVERY" else "I",
            "validity": order.validity,
            "price": float(order.price or 0),
            "instrument_token": order.instrument.broker_token,
            "order_type": order.order_type,
            "transaction_type": order.side.value,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "tag": order.client_order_id[:20],
            "slice": False,
            "market_protection": -1 if order.order_type == "MARKET" else 0,
        }
        data = await self.request(
            "POST",
            "/v3/order/place",
            base_url=self.order_base_url,
            json=payload,
        )
        order_ids = data.get("data", {}).get("order_ids", [])
        if not isinstance(order_ids, list) or len(order_ids) != 1:
            raise BrokerUnavailableError(
                "Upstox returned an unexpected number of order IDs with slicing disabled"
            )
        return BrokerOrderResult(OrderStatus.SUBMITTED, str(order_ids[0]))

    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult:
        params = (
            {"order_id": broker_order_id}
            if broker_order_id
            else {"tag": client_order_id[:20]}
        )
        row = (
            await self.request(
                "GET",
                self.query("/v2/order/details", params),
                safe_to_retry=True,
            )
        ).get("data", {})
        if not isinstance(row, dict) or not row:
            return BrokerOrderResult(
                OrderStatus.UNKNOWN,
                broker_order_id,
                message="Upstox order lookup was unresolved",
            )
        filled = int(row.get("filled_quantity", 0))
        quantity = int(row.get("quantity", 0))
        average = row.get("average_price")
        return BrokerOrderResult(
            status=normalize_status(str(row.get("status", "")), filled=filled, quantity=quantity),
            broker_order_id=str(row.get("order_id") or broker_order_id),
            filled_quantity=filled,
            average_price=Decimal(str(average)) if average not in {None, ""} else None,
            message=row.get("status_message"),
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        await self.request(
            "DELETE",
            self.query("/v3/order/cancel", {"order_id": broker_order_id}),
            base_url=self.order_base_url,
        )
        return BrokerOrderResult(OrderStatus.CANCELLED, broker_order_id)
