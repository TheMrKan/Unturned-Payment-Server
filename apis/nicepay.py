import aiohttp
from dataclasses import dataclass
from datetime import datetime
from pydantic import BaseModel
from pydantic.functional_validators import AfterValidator
from enum import Enum
from typing import Annotated
import hmac
import hashlib

CREATE_INVOICE_URL = "https://nicepay.io/public/api/payment"

class APIError(Exception):
    """Базовый класс для всех ошибок, возвращаемых API"""
    error_text: str
    status: str
    def __init__(self, response: dict):
        self.status = response.get("status", "")
        if "data" in response.keys() and "message" in response["data"].keys():
            self.error_text = response["data"]["message"]
        else:
            self.error_text = "Unknown error"
        super().__init__(f"({self.status}) {self.error_text}")


@dataclass
class NicepayInvoiceInfo:
    payment_id: str
    amount: float
    currency: str
    link: str
    expired: datetime


async def create_invoice_async(merchant_id: str,
                               secret: str,
                               order_id: str,
                               customer: str,
                               amount: float,
                               currency: str,
                               description: str | None = None,
                               method: str | None = None,
                               success_url: str | None = None,
                               fail_url: str | None = None):
    """
    https://nicepay.io/ru/docs/merchant/payment
    """

    converted_amount = int(round(amount * 100))    # Сумма платежа в центах/копейках. Пример: 125.28 USD это 12528
    data = {"merchant_id": merchant_id, "secret": secret, "order_id": order_id, "customer": customer, "amount": converted_amount, "currency": currency}
    if description:
        data["description"] = description
    if method:
        data["method"] = method
    if success_url:
        data["success_url"] = success_url
    if fail_url:
        data["fail_url"] = fail_url

    async with aiohttp.ClientSession() as session:
        async with session.post(CREATE_INVOICE_URL, json=data) as response:
            if response.status != 200:
                try:
                    response_json = await response.json(encoding="utf-8")
                except Exception as e:
                    response_json = {"status": "HTTP " + str(response.status), "data": {"message": f"Failed to read JSON response: {str(e)}"}}

                raise APIError(response_json)

            json = await response.json(encoding="utf-8")
            if json["status"] != "success":
                raise APIError(json)

            response_data: dict = json.get("data", {})

            amount = response_data["amount"] / 100    # Сумма платежа в центах/копейках. Пример: 125.28 USD это 12528
            expired = datetime.fromtimestamp(float(response_data["expired"]))
            invoice_info = NicepayInvoiceInfo(response_data["payment_id"], amount, response_data["currency"], response_data["link"], expired)
            return invoice_info


class WebhookInvoiceStatus(Enum):
    success = "success"
    error = "error"


class NicepayWebhook(BaseModel):

    @staticmethod
    def __cents_to_dollars(api_amount):
        return api_amount / 100

    result: WebhookInvoiceStatus
    payment_id: str
    merchant_id: str
    order_id: str
    amount: Annotated[float, AfterValidator(__cents_to_dollars)]
    amount_currency: str
    profit: Annotated[float, AfterValidator(__cents_to_dollars)]
    profit_currency: str
    method: str
    hash: str


def is_hash_valid(secret_key: str, data: dict):
    hash_received = data.pop('hash')

    sorted_params = dict(sorted(data.items()))

    values = list(sorted_params.values()) + [secret_key]

    hash_string = "{np}".join(map(str, values))

    hash_calculated = hashlib.sha256(hash_string.encode()).hexdigest()

    return hash_received == hash_calculated