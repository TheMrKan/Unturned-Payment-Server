"""
Получение и отправка пакетов с Lava API
"""

# 16f19d969d6ef8f2771430ffd9f49e989236732e3339c3b802fe3ff31e19f0ca

from typing import Dict, Any
import requests
import json
import hmac
import hashlib
from collections import OrderedDict
import base64
import codecs
import copy


def get_signature(token: str, fields: dict) -> str:

    odict = OrderedDict(sorted(fields.items()))

    # separators приводит json в нужный вид. В php при сериализации в json после запятых и двоеточий нет пробела, а в python - есть
    # json, полученный в python: {"orderId": "6555214", "shopId": "4d499d82-2b99-4a7e-be26-5742c41e69e7"}
    # json, полученный в php:    {"orderId":"6555214","shopId":"4d499d82-2b99-4a7e-be26-5742c41e69e7"}
    msg = json.dumps(odict, separators=(',', ':'))
    digest = hmac.new(token.encode("utf-8"), msg=msg.encode("utf-8"),
                      digestmod=hashlib.sha256)

    signature = digest.hexdigest()
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

    fields = {"orderId": order_id, "shopId": shop_id, "sum": amount, "expire": expire}

    if custom_field is not None:
        fields["customFields"] = custom_field
    if comment is not None:
        fields["comment"] = comment

    fields["signature"] = get_signature(token, fields)

    response = requests.post("https://api.lava.ru/business/invoice/create",
                             json=fields,
                             headers={"Accept": "application/json"})

    return response.json()


def test_get_signature():
    fields = {
        "orderId": "6555215",
        "sum": 30,
        "shopId": "1ffe6afc-01aa-4da9-b1e7-6f2ce521e506",
    }
    secret_key = "9de2257f00f5a8ca54b71197cd3b465e7bdfc8b3"

    signature = get_signature(secret_key, fields)

    assert signature == "d5e0f60d8566c908b58dd60dbf5812e78fc2784828da1a447b24797a220ce0d7"


if __name__ == "__main__":
    test_get_signature()
    print(create_invoice("9de2257f00f5a8ca54b71197cd3b465e7bdfc8b3", 30, "6555235", "1ffe6afc-01aa-4da9-b1e7-6f2ce521e506", 60, "some_json_data", "Comment"))

