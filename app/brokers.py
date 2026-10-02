from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from app.domain import (
    BrokerAuthenticationError,
    BrokerName,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerRateLimitError,
    BrokerUnavailableError,
    DeliveryAuthorizationRequired,
    Holding,
    InstrumentInput,
    OrderRejectedError,
    OrderStatus,
    OrderStatusUnknownError,
    ResolvedInstrument,
)


@dataclass(frozen=True, slots=True)
class BrokerCredentials:
    api_key: str
    access_token: str | None = field(default=None, repr=False)
    api_secret: str | None = field(default=None, repr=False)
    client_id: str | None = None
    redirect_uri: str | None = None

    def __repr__(self) -> str:
        return (
            "BrokerCredentials("
            f"api_key={self.api_key!r}, "
            "access_token=<redacted>, "
            "api_secret=<redacted>, "
            f"client_id={self.client_id!r}, "
            f"redirect_uri={self.redirect_uri!r})"
        )


class BrokerAdapter(ABC):
    name: BrokerName
    live: bool = True

    @abstractmethod
    async def get_holdings(self) -> list[Holding]: ...

    @abstractmethod
    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument: ...

    @abstractmethod
    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult: ...

    @abstractmethod
    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult: ...

    def auth_url(self, state: str) -> str | None:
        return None

    async def exchange_token(self, code: str) -> BrokerCredentials:
        raise BrokerAuthenticationError(f"{self.name.value} token exchange is not configured")


class BrokerRegistry:
    def __init__(self) -> None:
        self._factories: dict[BrokerName, Callable[[], BrokerAdapter]] = {}

    def register(self, name: BrokerName, factory: Callable[[], BrokerAdapter]) -> None:
        self._factories[name] = factory

    def get(self, name: BrokerName) -> BrokerAdapter:
        try:
            return self._factories[name]()
        except KeyError as exc:
            raise ValueError(f"Unsupported broker: {name.value}") from exc

    def names(self) -> list[BrokerName]:
        return sorted(self._factories, key=str)


class HttpBrokerAdapter(BrokerAdapter):
    base_url: str

    def __init__(
        self,
        credentials: BrokerCredentials,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.credentials = credentials
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    def headers(self) -> dict[str, str]:
        if not self.credentials.access_token:
            raise BrokerAuthenticationError(f"{self.name.value} access token is missing")
        return {
            "Authorization": f"Bearer {self.credentials.access_token}",
            "Accept": "application/json",
        }

    @staticmethod
    def retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
        base_delay = 0.05 * (2**attempt)
        jittered: float = base_delay * float(random.uniform(0.8, 1.2))
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return min(max(float(retry_after), 0.0), 5.0)
                except ValueError:
                    pass
        return jittered

    async def request(
        self,
        method: str,
        path: str,
        *,
        safe_to_retry: bool = False,
        ambiguous_on_failure: bool = False,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> Any:
        attempts = 3 if safe_to_retry else 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = await self.client.request(
                    method,
                    f"{base_url or self.base_url}{path}",
                    headers=self.headers(),
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if not safe_to_retry:
                    raise OrderStatusUnknownError("broker request timed out") from exc
                if attempt + 1 == attempts:
                    raise BrokerUnavailableError("broker timed out") from exc
                await asyncio.sleep(self.retry_delay(attempt))
                continue
            except httpx.TransportError as exc:
                if ambiguous_on_failure:
                    raise OrderStatusUnknownError(
                        "broker connection failed after order submission started"
                    ) from exc
                if not safe_to_retry or attempt + 1 == attempts:
                    raise BrokerUnavailableError("broker connection failed") from exc
                await asyncio.sleep(self.retry_delay(attempt))
                continue

            if response.status_code == 429:
                if safe_to_retry and attempt + 1 < attempts:
                    await asyncio.sleep(self.retry_delay(attempt, response))
                    continue
                raise BrokerRateLimitError("broker rate limit exceeded")
            if response.status_code in {401, 403}:
                raise BrokerAuthenticationError("broker authentication failed")
            if response.status_code == 428:
                raise DeliveryAuthorizationRequired("delivery authorization is required")
            if response.status_code >= 500:
                if safe_to_retry and attempt + 1 < attempts:
                    await asyncio.sleep(self.retry_delay(attempt))
                    continue
                if ambiguous_on_failure:
                    raise OrderStatusUnknownError(
                        f"broker returned {response.status_code} after submission"
                    )
                raise BrokerUnavailableError(f"broker returned {response.status_code}")
            if response.status_code >= 400:
                message = response.text[:500]
                raise OrderRejectedError(message or f"broker returned {response.status_code}")
            try:
                data = response.json()
            except ValueError as exc:
                if ambiguous_on_failure:
                    raise OrderStatusUnknownError(
                        "broker returned a malformed placement response"
                    ) from exc
                raise BrokerUnavailableError("malformed broker response") from exc
            return data
        raise BrokerUnavailableError("broker request failed")

    @staticmethod
    def query(path: str, params: dict[str, str]) -> str:
        return f"{path}?{urlencode(params)}"


def normalize_status(value: str, *, filled: int = 0, quantity: int | None = None) -> OrderStatus:
    status = value.upper().replace(" ", "_")
    if status in {"COMPLETE", "COMPLETED", "TRADED", "FILLED", "EXECUTED"}:
        return OrderStatus.EXECUTED
    if status in {"REJECTED", "FAILED"}:
        return OrderStatus.REJECTED
    if status in {"CANCELLED", "CANCELED"}:
        return OrderStatus.CANCELLED
    if quantity and 0 < filled < quantity:
        return OrderStatus.PARTIALLY_FILLED
    if status in {"OPEN", "PENDING", "TRIGGER_PENDING", "PUT_ORDER_REQ_RECEIVED"}:
        return OrderStatus.OPEN
    return OrderStatus.SUBMITTED
