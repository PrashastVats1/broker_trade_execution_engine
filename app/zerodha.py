from __future__ import annotations

import csv
import hashlib
import io
from decimal import Decimal
from urllib.parse import urlencode

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


class ZerodhaAdapter(HttpBrokerAdapter):
    """Kite Connect v3 adapter.

    Contract source: https://kite.trade/docs/connect/v3/
    Verified: 2026-10-02.
    """

    name = BrokerName.ZERODHA
    base_url = "https://api.kite.trade"

    def headers(self) -> dict[str, str]:
        headers = {"X-Kite-Version": "3"}
        if self.credentials.access_token:
            headers["Authorization"] = (
                f"token {self.credentials.api_key}:{self.credentials.access_token}"
            )
        return headers

    def auth_url(self, state: str) -> str:
        params = urlencode(
            {
                "v": "3",
                "api_key": self.credentials.api_key,
                "redirect_params": f"state={state}",
            }
        )
        return f"https://kite.zerodha.com/connect/login?{params}"

    async def exchange_token(self, code: str) -> BrokerCredentials:
        if not self.credentials.api_secret:
            raise BrokerAuthenticationError("Zerodha api_secret is required")
        checksum = hashlib.sha256(
            f"{self.credentials.api_key}{code}{self.credentials.api_secret}".encode()
        ).hexdigest()
        data = await self.request(
            "POST",
            "/session/token",
            data={
                "api_key": self.credentials.api_key,
                "request_token": code,
                "checksum": checksum,
            },
        )
        try:
            token = str(data["data"]["access_token"])
        except (KeyError, TypeError) as exc:
            raise BrokerAuthenticationError("Zerodha token response is malformed") from exc
        return BrokerCredentials(
            api_key=self.credentials.api_key,
            api_secret=self.credentials.api_secret,
            access_token=token,
        )

    async def get_holdings(self) -> list[Holding]:
        rows = (await self.request("GET", "/portfolio/holdings", safe_to_retry=True)).get(
            "data", []
        )
        if not isinstance(rows, list):
            raise BrokerUnavailableError("Zerodha holdings response is malformed")
        return [
            Holding(
                instrument=ResolvedInstrument(
                    symbol=str(row["tradingsymbol"]),
                    exchange=str(row["exchange"]),
                    isin=row.get("isin"),
                    broker_symbol=str(row["tradingsymbol"]),
                    broker_token=(
                        str(row["instrument_token"]) if row.get("instrument_token") else None
                    ),
                ),
                quantity=int(row.get("quantity", 0)),
            )
            for row in rows
        ]

    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument:
        response = await self.client.get(
            f"{self.base_url}/instruments/{instrument.exchange}",
            headers=self.headers(),
        )
        response.raise_for_status()
        matches = [
            row
            for row in csv.DictReader(io.StringIO(response.text))
            if row.get("exchange") == instrument.exchange
            and row.get("tradingsymbol") == instrument.symbol
            and row.get("instrument_type") == "EQ"
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
            isin=instrument.isin,
            broker_symbol=str(row["tradingsymbol"]),
            broker_token=str(row["instrument_token"]),
        )

    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
        payload: dict[str, str | int | bool] = {
            "tradingsymbol": str(order.instrument.broker_symbol),
            "exchange": order.instrument.exchange,
            "transaction_type": order.side.value,
            "order_type": order.order_type,
            "quantity": order.quantity,
            "product": "CNC" if order.product == "DELIVERY" else "MIS",
            "validity": order.validity,
            "tag": order.client_order_id[:20],
            "autoslice": False,
        }
        if order.order_type == "MARKET":
            payload["market_protection"] = -1
        if order.price is not None:
            payload["price"] = str(order.price)
        data = await self.request(
            "POST",
            "/orders/regular",
            data=payload,
            ambiguous_on_failure=True,
        )
        result = data.get("data", {})
        if not isinstance(result, dict) or not result.get("order_id"):
            raise BrokerUnavailableError("Zerodha placement response is malformed")
        return BrokerOrderResult(OrderStatus.SUBMITTED, str(result["order_id"]))

    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult:
        if broker_order_id:
            rows = (
                await self.request(
                    "GET",
                    f"/orders/{broker_order_id}",
                    safe_to_retry=True,
                )
            ).get("data", [])
            row = rows[-1] if isinstance(rows, list) and rows else None
        else:
            rows = (await self.request("GET", "/orders", safe_to_retry=True)).get("data", [])
            matching = [
                row
                for row in rows
                if isinstance(row, dict) and row.get("tag") == client_order_id[:20]
            ]
            row = matching[0] if len(matching) == 1 else None
        if not isinstance(row, dict):
            return BrokerOrderResult(
                OrderStatus.UNKNOWN,
                broker_order_id,
                message="Zerodha order lookup was unresolved",
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
        await self.request("DELETE", f"/orders/regular/{broker_order_id}")
        return BrokerOrderResult(OrderStatus.CANCELLED, broker_order_id)
