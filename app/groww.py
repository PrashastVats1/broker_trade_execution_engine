from __future__ import annotations

import csv
import hashlib
import io
import time
from decimal import Decimal

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


class GrowwAdapter(HttpBrokerAdapter):
    """Groww Trading API v1 adapter.

    Contract source: https://groww.in/trade-api/docs/curl
    Verified: 2026-10-02.
    """

    name = BrokerName.GROWW
    base_url = "https://api.groww.in"
    instrument_url = "https://growwapi-assets.groww.in/instruments/instrument.csv"

    def headers(self) -> dict[str, str]:
        headers = super().headers()
        headers["X-API-VERSION"] = "1.0"
        return headers

    async def generate_access_token(self, timestamp: int | None = None) -> BrokerCredentials:
        if not self.credentials.api_secret:
            raise BrokerAuthenticationError("Groww API secret is required")
        epoch = timestamp if timestamp is not None else int(time.time())
        checksum = hashlib.sha256(
            f"{self.credentials.api_secret}{epoch}".encode()
        ).hexdigest()
        try:
            response = await self.client.post(
                f"{self.base_url}/v1/token/api/access",
                headers={
                    "Authorization": f"Bearer {self.credentials.api_key}",
                    "Content-Type": "application/json",
                },
                json={"key_type": "approval", "checksum": checksum, "timestamp": str(epoch)},
            )
            response.raise_for_status()
            data = response.json()
            token = str(data.get("token") or data["access_token"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise BrokerAuthenticationError("Groww token generation failed") from exc
        return BrokerCredentials(
            api_key=self.credentials.api_key,
            api_secret=self.credentials.api_secret,
            access_token=token,
        )

    async def get_holdings(self) -> list[Holding]:
        payload = (
            await self.request("GET", "/v1/holdings/user", safe_to_retry=True)
        ).get("payload", {})
        rows = payload.get("holdings", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise BrokerUnavailableError("Groww holdings response is malformed")
        return [
            Holding(
                instrument=ResolvedInstrument(
                    symbol=str(row["trading_symbol"]),
                    exchange="NSE",
                    isin=row.get("isin"),
                    broker_symbol=str(row["trading_symbol"]),
                ),
                quantity=int(row.get("quantity", 0)),
            )
            for row in rows
        ]

    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument:
        response = await self.client.get(self.instrument_url)
        response.raise_for_status()
        matches = [
            row
            for row in csv.DictReader(io.StringIO(response.text))
            if row.get("exchange") == instrument.exchange
            and row.get("trading_symbol") == instrument.symbol
            and row.get("segment") == "CASH"
            and row.get("instrument_type") == "EQ"
            and row.get("series") in {"EQ", "A"}
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
            broker_token=row.get("exchange_token"),
        )

    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
        payload: dict[str, str | int | float] = {
            "trading_symbol": str(order.instrument.broker_symbol),
            "quantity": order.quantity,
            "validity": order.validity,
            "exchange": order.instrument.exchange,
            "segment": "CASH",
            "product": "CNC" if order.product == "DELIVERY" else "MIS",
            "order_type": order.order_type,
            "transaction_type": order.side.value,
            "order_reference_id": order.client_order_id[:20],
        }
        if order.price is not None:
            payload["price"] = float(order.price)
        row = (await self.request("POST", "/v1/order/create", json=payload)).get("payload", {})
        if not isinstance(row, dict) or not row.get("groww_order_id"):
            raise BrokerUnavailableError("Groww placement response is malformed")
        return BrokerOrderResult(
            status=normalize_status(str(row.get("order_status", ""))),
            broker_order_id=str(row["groww_order_id"]),
            message=row.get("remark"),
        )

    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult:
        path = (
            f"/v1/order/status/{broker_order_id}"
            if broker_order_id
            else f"/v1/order/status/reference/{client_order_id[:20]}"
        )
        row = (
            await self.request(
                "GET",
                self.query(path, {"segment": "CASH"}),
                safe_to_retry=True,
            )
        ).get("payload", {})
        if not isinstance(row, dict) or not row:
            return BrokerOrderResult(
                OrderStatus.UNKNOWN,
                broker_order_id,
                message="Groww order lookup was unresolved",
            )
        filled = int(row.get("filled_quantity", 0))
        average = row.get("average_fill_price")
        return BrokerOrderResult(
            status=normalize_status(str(row.get("order_status", "")), filled=filled),
            broker_order_id=str(row.get("groww_order_id") or broker_order_id),
            filled_quantity=filled,
            average_price=Decimal(str(average)) if average not in {None, ""} else None,
            message=row.get("remark"),
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        await self.request(
            "POST",
            "/v1/order/cancel",
            json={"segment": "CASH", "groww_order_id": broker_order_id},
        )
        return BrokerOrderResult(OrderStatus.CANCELLED, broker_order_id)
