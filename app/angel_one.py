from __future__ import annotations

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


class AngelOneAdapter(HttpBrokerAdapter):
    """Angel One SmartAPI adapter.

    Contract source: https://smartapi.angelone.in/docs
    Verified: 2026-10-02.
    """

    name = BrokerName.ANGEL_ONE
    base_url = "https://apiconnect.angelone.in"
    instrument_url = (
        "https://margincalculator.angelone.in/OpenAPI_File/files/"
        "OpenAPIScripMaster.json"
    )

    def __init__(
        self,
        credentials: BrokerCredentials,
        client: httpx.AsyncClient | None = None,
        *,
        client_local_ip: str | None = None,
        client_public_ip: str | None = None,
        mac_address: str | None = None,
    ) -> None:
        super().__init__(credentials, client)
        self.client_local_ip = client_local_ip
        self.client_public_ip = client_public_ip
        self.mac_address = mac_address

    def headers(self) -> dict[str, str]:
        headers = super().headers()
        headers.update(
            {
                "X-PrivateKey": self.credentials.api_key,
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "Content-Type": "application/json",
            }
        )
        if self.client_local_ip:
            headers["X-ClientLocalIP"] = self.client_local_ip
        if self.client_public_ip:
            headers["X-ClientPublicIP"] = self.client_public_ip
        if self.mac_address:
            headers["X-MACAddress"] = self.mac_address
        return headers

    async def login(
        self,
        *,
        client_code: str,
        pin: str,
        totp: str,
    ) -> BrokerCredentials:
        """Create the daily session without retaining PIN or TOTP."""
        try:
            response = await self.client.post(
                f"{self.base_url}/rest/auth/angelbroking/user/v1/loginByPassword",
                headers={
                    "X-PrivateKey": self.credentials.api_key,
                    "X-UserType": "USER",
                    "X-SourceID": "WEB",
                    "Content-Type": "application/json",
                },
                json={"clientcode": client_code, "password": pin, "totp": totp},
            )
            response.raise_for_status()
            row = response.json()["data"]
            token = str(row["jwtToken"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise BrokerAuthenticationError("Angel One login failed") from exc
        return BrokerCredentials(
            api_key=self.credentials.api_key,
            client_id=client_code,
            access_token=token,
        )

    async def get_holdings(self) -> list[Holding]:
        rows = (
            await self.request(
                "GET",
                "/rest/secure/angelbroking/portfolio/v1/getHolding",
                safe_to_retry=True,
            )
        ).get("data", [])
        if not isinstance(rows, list):
            raise BrokerUnavailableError("Angel One holdings response is malformed")
        return [
            Holding(
                instrument=ResolvedInstrument(
                    symbol=str(row["tradingsymbol"]).removesuffix("-EQ"),
                    exchange=str(row["exchange"]),
                    isin=row.get("isin"),
                    broker_symbol=str(row["tradingsymbol"]),
                    broker_token=str(row["symboltoken"]),
                ),
                quantity=int(row.get("quantity", 0)),
            )
            for row in rows
        ]

    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument:
        try:
            response = await self.client.get(self.instrument_url)
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrokerUnavailableError("Angel One instrument master is unavailable") from exc
        if not isinstance(rows, list):
            raise BrokerUnavailableError("Angel One instrument master is malformed")
        matches = [
            row
            for row in rows
            if row.get("name") == instrument.symbol
            and row.get("exch_seg") == instrument.exchange
            and str(row.get("symbol", "")).endswith("-EQ")
            and row.get("instrumenttype", "") in {"", "EQ"}
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
            broker_symbol=str(row["symbol"]),
            broker_token=str(row["token"]),
        )

    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
        payload: dict[str, str] = {
            "variety": "NORMAL",
            "tradingsymbol": str(order.instrument.broker_symbol),
            "symboltoken": str(order.instrument.broker_token),
            "transactiontype": order.side.value,
            "exchange": order.instrument.exchange,
            "ordertype": order.order_type,
            "producttype": "CNC" if order.product == "DELIVERY" else "MIS",
            "duration": order.validity,
            "price": str(order.price or 0),
            "triggerprice": "0",
            "quantity": str(order.quantity),
            "ordertag": order.client_order_id[:19],
        }
        row = (
            await self.request(
                "POST",
                "/rest/secure/angelbroking/order/v1/placeOrder",
                json=payload,
                ambiguous_on_failure=True,
            )
        ).get("data", {})
        broker_id = (
            row.get("uniqueorderid") or row.get("orderid") if isinstance(row, dict) else None
        )
        if not broker_id:
            raise BrokerUnavailableError("Angel One placement response is malformed")
        return BrokerOrderResult(OrderStatus.SUBMITTED, str(broker_id))

    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult:
        if not broker_order_id:
            return BrokerOrderResult(
                OrderStatus.UNKNOWN,
                message="Angel One unique order ID is required for reconciliation",
            )
        row = (
            await self.request(
                "GET",
                f"/rest/secure/angelbroking/order/v1/details/{broker_order_id}",
                safe_to_retry=True,
            )
        ).get("data", {})
        if not isinstance(row, dict) or not row:
            return BrokerOrderResult(OrderStatus.UNKNOWN, broker_order_id)
        filled = int(row.get("filledshares", 0))
        quantity = int(row.get("quantity", 0))
        average = row.get("averageprice")
        return BrokerOrderResult(
            status=normalize_status(
                str(row.get("orderstatus", "")), filled=filled, quantity=quantity
            ),
            broker_order_id=broker_order_id,
            filled_quantity=filled,
            average_price=Decimal(str(average)) if average not in {None, ""} else None,
            message=row.get("text"),
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        await self.request(
            "POST",
            "/rest/secure/angelbroking/order/v1/cancelOrder",
            json={"variety": "NORMAL", "orderid": broker_order_id},
        )
        return BrokerOrderResult(OrderStatus.CANCELLED, broker_order_id)
