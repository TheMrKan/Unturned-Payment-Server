import aiohttp
import json
from dataclasses import dataclass
import datetime
import hmac
import hashlib
from enum import Enum
from pydantic import BaseModel, validator


@dataclass
class EnotInvoiceInfo:
    invoice_id: str
    """ID операции в системе enot.io"""
    amount: float
    currency: str
    url: str
    expired: datetime.datetime


class APIError(Exception):
    """Базовый класс для всех ошибок, возвращаемых API"""
    error_text: str
    status_code: int
    def __init__(self, response: dict):
        self.error_text = response.get("error", "Unknown error")
        self.status_code = int(response.get("status", 0))
        super().__init__(f"({self.status_code}) {self.error_text}")


# https://docs.enot.io/e/new/create-invoice
async def create_invoice_async(
        shop_id: str,
        secret_key: str,
        amount: float,
        order_id: str,    # ID заказа в системе приложения
        currency: str | None = None,
        hook_url: str | None = None,
        custom_fields: dict | None = None,
        comment: str | None = None,
        fail_url: str | None = None,
        success_url: str | None = None,
        expire_minutes: int | None = None,
        include_services: list[str] | None = None,
        exclude_services: str | None = None
):
    """
    Создает счет на оплату в сервисе enot.io
    """

    data ={
        "shop_id": shop_id,
        "amount": amount,
        "order_id": order_id,
    }

    if currency is not None:
        data["currency"] = currency
    if hook_url is not None:
        data["hook_url"] = hook_url
    if custom_fields is not None:
        data["custom_fields"] = custom_fields
    if comment:    # пустую строку передавать нельзя
        data["comment"] = comment
    if fail_url:
        data["fail_url"] = fail_url
    if success_url:
        data["success_url"] = success_url
    if expire_minutes is not None:
        data["expire"] = expire_minutes
    if include_services is not None:
        data["include_service"] = include_services
    if exclude_services is not None:
        data["exclude_service"] = exclude_services

    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.enot.io/invoice/create",
                                headers=__build_headers(secret_key),
                                json=data,
                                ) as response:
            if response.status != 200:
                try:
                    response_json = await response.json(encoding="utf-8")
                except Exception as e:
                    response_json = {"code": response.status, "error": f"Failed to read JSON response: {str(e)}"}

                raise APIError(response_json)

            response_data: dict = (await response.json(encoding="utf-8")).get("data", {})
            invoice_info = EnotInvoiceInfo(
                response_data.get("id"),
                float(response_data.get("amount")),
                response_data.get("currency"),
                response_data.get("url"),
                datetime.datetime.strptime(response_data["expired"], "%Y-%m-%d %H:%M:%S")
            )
            return invoice_info


def __build_headers(secret_key: str) -> dict[str, str]:
    """Возвращает словарь с заголовками для запросов к API"""
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": secret_key
    }


# https://docs.enot.io/e/new/webhook
def check_signature(hook_body: dict, header_signature, secret_key) -> bool:
  sorted_hook_json = json.dumps(hook_body, sort_keys=True, separators=(', ', ': '))
  calc_sign = hmac.new(
    secret_key,
    msg=sorted_hook_json.encode('utf-8'),
    digestmod=hashlib.sha256
  ).hexdigest()
  return hmac.compare_digest(header_signature, calc_sign)


class EnotWebhookStatus(Enum):
    success = "success"
    fail = "fail"
    expired = "expired"
    refund = "refund"


class EnotWebhookType(Enum):
    payment = 1
    refund = 2


class EnotWebhookCode(Enum):
    success = 1
    refund_success = 20
    expired = 31
    error = 32


class EnotWebhook(BaseModel):
    invoice_id: str
    status: EnotWebhookStatus
    amount: str
    currency: str
    order_id: str
    pay_service: str | None = None
    payer_details: str | None = None
    custom_fields: str | None = None
    type: EnotWebhookType
    credited: str | None = None
    pay_time: datetime.datetime | None = None
    code: EnotWebhookCode
    reject_time: datetime.datetime | None = None
    refund_amount: str | None = None
    refund_reason: str | None = None
    refund_time: datetime.datetime | None = None


    @validator('pay_time', 'reject_time', 'refund_time', pre=True)
    def parse_datetime(cls, value):
        return datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
