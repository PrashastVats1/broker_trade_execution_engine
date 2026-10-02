from __future__ import annotations

import csv
import io
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


class DhanAdapter(HttpBrokerAdapter):
    """DhanHQ API v2 adapter.

    Contract source: https://dhanhq.co/docs/v2/
    Verified: 2026-10-02.
    """

    name = BrokerName.DHAN
    base_url = "https://api.dhan.co/v2"
    auth_base_url = "https://auth.dhan.co"
    instrument_url = "https://images.dhan.co/api-data/api-scrip-master.csv"

    def headers(self) -> dict[str, str]:
        if not self.credentials.access_token:
            raise BrokerAuthenticationError("Dhan access token is missing")
        return {
            "access-token": self.credentials.access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def generate_consent(self) -> str:
        if not self.credentials.api_secret:
            raise BrokerAuthenticationError("Dhan app secret is required")
        try:
            response = await self.client.post(
                f"{self.auth_base_url}/app/generate-consent",
                params={"client_id": self.credentials.client_id or ""},
                headers={
                    "app_id": self.credentials.api_key,
                    "app_secret": self.credentials.api_secret,
                },
            )
            response.raise_for_status()
            return str(response.json()["consentAppId"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise BrokerAuthenticationError("Dhan consent generation failed") from exc

    def consent_login_url(self, consent_app_id: str) -> str:
        return f"{self.auth_base_url}/login/consentApp-login?consentAppId={consent_app_id}"

    async def consume_consent(self, token_id: str) -> BrokerCredentials:
        if not self.credentials.api_secret:
            raise BrokerAuthenticationError("Dhan app secret is required")
        try:
            response = await self.client.get(
                f"{self.auth_base_url}/app/consumeApp-consent",
                params={"tokenId": token_id},
                headers={
                    "app_id": self.credentials.api_key,
                    "app_secret": self.credentials.api_secret,
                },
            )
            response.raise_for_status()
            row = response.json()
            access_token = str(row["accessToken"])
            client_id = str(row["dhanClientId"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise BrokerAuthenticationError("Dhan consent exchange failed") from exc
        return BrokerCredentials(
            api_key=self.credentials.api_key,
            api_secret=self.credentials.api_secret,
            client_id=client_id,
            access_token=access_token,
        )

    async def get_holdings(self) -> list[Holding]:
        rows = await self.request("GET", "/holdings", safe_to_retry=True)
        if not isinstance(rows, list):
            raise BrokerUnavailableError("Dhan holdings response is malformed")
        return [
            Holding(
                instrument=ResolvedInstrument(
                    symbol=str(row["tradingSymbol"]),
                    exchange=str(row.get("exchange", "ALL")),
                    isin=str(row["isin"]) if row.get("isin") else None,
                    broker_symbol=str(row["tradingSymbol"]),
                    broker_token=str(row["securityId"]),
                ),
                quantity=int(row.get("totalQty", 0)),
            )
            for row in rows
        ]

    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument:
        response = await self.client.get(self.instrument_url)
        response.raise_for_status()
        segment = "NSE_EQ" if instrument.exchange == "NSE" else "BSE_EQ"
        matches = [
            row
            for row in csv.DictReader(io.StringIO(response.text))
            if row.get("SEM_EXM_EXCH_ID") == instrument.exchange
            and row.get("SEM_SEGMENT") == "E"
            and row.get("SEM_TRADING_SYMBOL") == instrument.symbol
            and row.get("SEM_INSTRUMENT_NAME") == "EQUITY"
            and row.get("SEM_SERIES") in {"EQ", "A"}
        ]
        if len(matches) != 1:
            raise InstrumentResolutionError(
                f"{instrument.exchange}:{instrument.symbol} resolved to {len(matches)} instruments"
            )
        row = matches[0]
        return ResolvedInstrument(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            segment=segment,
            isin=instrument.isin,
            broker_symbol=str(row["SEM_TRADING_SYMBOL"]),
            broker_token=str(row["SEM_SMST_SECURITY_ID"]),
        )

    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
        if not self.credentials.client_id:
            raise BrokerAuthenticationError("Dhan client ID is missing")
        payload = {
            "dhanClientId": self.credentials.client_id,
            "correlationId": order.client_order_id[:30],
            "transactionType": order.side.value,
            "exchangeSegment": order.instrument.segment,
            "productType": "CNC" if order.product == "DELIVERY" else "INTRADAY",
            "orderType": order.order_type,
            "validity": order.validity,
            "securityId": order.instrument.broker_token,
            "quantity": order.quantity,
            "disclosedQuantity": 0,
            "price": float(order.price or 0),
            "triggerPrice": 0,
            "afterMarketOrder": False,
        }
        row = await self.request("POST", "/orders", json=payload)
        if not row.get("orderId"):
            raise BrokerUnavailableError("Dhan placement response is malformed")
        return BrokerOrderResult(
            normalize_status(str(row.get("orderStatus", ""))),
            str(row["orderId"]),
        )

    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult:
        path = (
            f"/orders/{broker_order_id}"
            if broker_order_id
            else f"/orders/external/{client_order_id[:30]}"
        )
        row = await self.request("GET", path, safe_to_retry=True)
        if not row:
            return BrokerOrderResult(OrderStatus.UNKNOWN, broker_order_id)
        filled = int(row.get("filledQty", 0))
        quantity = int(row.get("quantity", 0))
        average = row.get("averageTradedPrice")
        return BrokerOrderResult(
            status=normalize_status(
                str(row.get("orderStatus", "")), filled=filled, quantity=quantity
            ),
            broker_order_id=str(row.get("orderId") or broker_order_id),
            filled_quantity=filled,
            average_price=Decimal(str(average)) if average not in {None, ""} else None,
            message=row.get("omsErrorDescription"),
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        await self.request("DELETE", f"/orders/{broker_order_id}")
        return BrokerOrderResult(OrderStatus.CANCELLED, broker_order_id)
