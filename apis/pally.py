from typing import Literal
import aiohttp
from dataclasses import dataclass
from pydantic import BaseModel
import hashlib
import decimal

import config


@dataclass
class PallyBillInfo:
    id: str
    url: str


class APIError(Exception):
    """Базовый класс для всех ошибок, возвращаемых API"""

    error_text: str
    status_code: int

    def __init__(self, response: dict):
        super().__init__(str(response))


async def create_bill_async(shop_id: str,
                            secret_key: str,
                            amount: float,
                            order_id: str,
                            name: str,
                            description: str,
                            ):
    data = {
        "shop_id": shop_id,
        "amount": amount,
        "name": name,
        "description": description,
        "order_id": order_id
    }

    headers = __build_headers(secret_key)

    async with aiohttp.ClientSession() as session:
        async with session.post("https://pal24.pro/api/v1/bill/create",
                                headers=headers,
                                data=data) as response:
            if response.status != 200:
                try:
                    response_json = await response.json(encoding="utf-8")
                except Exception as e:
                    response_json = {
                        "code": response.status,
                        "error": f"Failed to read JSON response: {str(e)}",
                    }

                raise APIError(response_json)

            response_data: dict = (await response.json(encoding="utf-8"))
            return PallyBillInfo(
                response_data["bill_id"], response_data["link_page_url"]
            )


def __build_headers(secret_key: str) -> dict[str, str]:
    """Возвращает словарь с заголовками для запросов к API"""
    return {
        "Accept": "application/json",
        'Content-Type': 'application/x-www-form-urlencoded',
        "Authorization": f"Bearer {secret_key}",
    }


class PostbackForm(BaseModel):
    InvId: str
    OutSum: decimal.Decimal
    Commission: decimal.Decimal
    TrsId: str
    Status: Literal["SUCCESS", "UNDERPAID", "OVERPAID", "SUCCESS"]
    ErrorCode: int | None = None
    ErrorMessage: str | None = None
    SignatureValue: str


def is_signature_valid(signature: str, out_sum: decimal.Decimal, invoice_id: str) -> bool:
    string = f"{out_sum}:{invoice_id}:{config.PALLY_SECRET_KEY}"
    sig = hashlib.md5(string.encode("utf-8")).hexdigest().lower()
    return sig == signature.lower()
