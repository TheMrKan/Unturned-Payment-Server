"""
Получение и отправка пакетов с Lava API
"""
from typing import Dict, Any
import aiohttp
import json
import hmac
import hashlib
import base64


def get_signature(secret_key: str, fields: dict) -> str:

    digest = hmac.new(secret_key.encode("utf-8"), msg=json.dumps(fields, sort_keys=True).encode("utf-8"),
                      digestmod=hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()

    return signature


async def create_invoice(token: str,
                         amount: float,
                         order_id: str,
                         shop_id: str,
                         expire: int = 600,
                         custom_field: str = None,
                         comment: str = None
                         ) -> Dict[str, Any]:
    """
    Отправляет запрос на выставление счета (см. https://dev.lava.ru/api-invoice-create).

    :param token: Токен авторизации
    :param amount: Сумма
    :param order_id: Айди счета (должен быть уникальным)
    :param shop_id: Айди магазина
    :param expire: Время жизни счсета в минутах
    :param custom_field: Дополнительная информация, которая будет передана в Webhook после оплаты
    :param comment: Комментарий к платежу
    :return: Словарь с ответом платежной системы
    """

    fields = {
        "sum": amount,
        "orderId": order_id,
        "shopId": shop_id,
        "expire": expire,
    }

    if custom_field is not None:
        fields["customFields"] = custom_field
    if comment is not None:
        fields["comment"] = comment

    fields["signature"] = get_signature(token, fields)
    print(fields)
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.lava.ru/business/invoice/create", ) as response:
    response = requests.post(,
                             data=json.dumps(fields),
                             headers={"Accept": "application/json"})

    return response.json()


if __name__ == "__main__":
    print(create_invoice("1ffe6afc-01aa-4da9-b1e7-6f2ce521e506", 30, "order1234", "1ffe6afc-01aa-4da9-b1e7-6f2ce521e506", 600, "some_json_data", "Comment"))
