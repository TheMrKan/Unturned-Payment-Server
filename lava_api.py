"""
Получение и отправка пакетов с Lava API
"""
from typing import Dict, Any
import requests
import json
import hmac
import hashlib
import base64


def get_signature(token: str, fields: dict) -> str:

    digest = hmac.new(token.encode("utf-8"), msg=json.dumps(fields, sort_keys=True).encode("utf-8"),
                      digestmod=hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()

    return signature


def create_invoice(token: str,
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
    :param order_id: Айди счета
    :param shop_id: Айди магазина (равен токену пользователя из БД)
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
    response = requests.post("https://api.lava.ru/business/invoice/create",
                             data=json.dumps(fields),
                             headers={"Accept": "application/json"})

    return response.json()


if __name__ == "__main__":
    print(create_invoice("1ffe6afc-01aa-4da9-b1e7-6f2ce521e506", 30, "order1234", "1ffe6afc-01aa-4da9-b1e7-6f2ce521e506", 600, "some_json_data", "Comment"))
