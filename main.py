"""
Основной файл.
Команда для запуска: uvicorn main:app --reload
"""

import datetime
import os
import random

from fastapi import FastAPI
from pydantic import BaseModel, Field
import db as database
import logging
from typing import Optional
import asyncio
import lava_api


class CreateInvoiceRequest(BaseModel):
    """
    Модель запроса для выставления счета.
    """
    user_token: str    # токен пользователя
    amount: int    # сумма счета
    expire: int    # время жизни счета (по каким-то причинам не работает)


class InvoiceStatusRequest(BaseModel):
    """
    Модель запроса для получения информации о счете.
    """
    user_token: str    # токен пользователя
    id: str    # айди счета, состояние которого необходимо получить
    auto_withdraw: Optional[str] = Field(False)   # необязательный параметр. Если True, то после оплаты счета средства будут автоматически выведены


app = FastAPI(docs_url=None, redoc_url=None)    # docs_url и redoc_url отключают автоматическую документацию
#SECRET_KEY = "234567899"
SECRET_KEY = "1ffe6afc-01aa-4da9-b1e7-6f2ce521e506"
WALLET = "R10031991"
db = database.DatabaseManager("database.sqlite3")    # экземпляр класса для доступа к данным из БД.

logger = logging.getLogger("payment_api_logger")
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('logs/payment_api.log')
fh.setFormatter(logging.Formatter(fmt='[%(asctime)s: %(levelname)s] %(message)s'))
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)


class WithdrawException(Exception):
    """
    При выводе средств произошла ошибка
    """
    pass


async def withdraw(user: database.UserInfo, amount: int) -> None:
    """
    Выводит средства
    :param user: Информация о пользователе из БД
    :param amount: Сумма
    :return:
    """

    logger.info(f"Withdraw requested: user = {user.name}; service: {user.withdraw_service}; "
                f"wallet: {user.withdraw_wallet}; amount = {amount}")

    # если сервис вывода - 'lava', то создаем перевод средств между кошельками
    if user.withdraw_service == "lava":
        # см. https://dev.lava.ru/transfercreate
        fields = {
            "account_from": WALLET,
            "account_to": user.withdraw_wallet,
            "amount": f"{amount * (user.percent / 100):.2f}"
        }
        logger.info(f"Sended transfer request with fields: {fields}")
        response = dlltool.send("https://api.lava.ru/transfer/create", "POST", {"Authorization": SECRET_KEY},
                                fields)  # отправка данных в API (см. описание модуля)

    # иначе создаем вывод средств
    else:
        # см. https://dev.lava.ru/withdrawcreate
        fields = {
            "account": WALLET,
            "amount": f"{amount * (user.percent / 100):.2f}",
            "service": user.withdraw_service,
            "wallet_to": user.withdraw_wallet
        }
        logger.info(f"Sended withdraw request with fields: {fields}")
        response = dlltool.send("https://api.lava.ru/withdraw/create", "POST", {"Authorization": SECRET_KEY},
                                fields)  # отправка данных в API (см. описание модуля)

    if (status := response.get("status", "error")) != "success":
        logger.error(f"[WITHDRAW] Error while creating withdraw request: \nRequest: {fields};\n Response: {response};")
        raise WithdrawException(response.get("message", str(response)))

    logger.info(f"[WITHDRAW] Withdraw request successfully created: \nRequest: {fields}; \nResponse: {response};")


@app.post("/payment_service/get_invoice_status")
async def get_invoice_status(invoice_status_request: InvoiceStatusRequest):

    logger.info(f"Get invoice status requested: {invoice_status_request}")

    # если пользователь с полученым токеном не найден, то возвращает ошибку
    try:
        user = db.get_user_info(invoice_status_request.user_token)
    except database.UserNotFoundException:
        logger.error(f"User with token {invoice_status_request.user_token} not found")
        return {
            "status": "server error",
            "code": "-1",
            "message": "Invalid user token"
        }

    fields = {
        "id": invoice_status_request.id
    }

    logger.debug(f"Sending invoice status request with fields: {fields}")

    response = dlltool.send("https://api.lava.ru/invoice/info", "POST", {"Authorization": SECRET_KEY}, fields)    # отправка данных в API (см. описание модуля)

    logger.debug(f"Got response: {response}")

    # статус счета успешно получен
    if (status := response.get("status", "error")) == "success":

        # 'invoice' содержит словарь с данными о счете. См. https://dev.lava.ru/invoiceinfo
        if "invoice" not in response.keys():
            logger.error(f"No 'invoice' key in response: {response}")

            return {
                "status": "server error",
                "code": "-2",
                "message": "No 'invoice' key in response"
            }

        invoice_info = response['invoice']
        invoice_status = invoice_info.get("status", "cancel")
        logger.info(f"Got invoice status: id = {invoice_info.get('id', 'UNDEFINED')}; status = {invoice_status};")

        withdraw_status = "disabled"
        withdraw_message = ""

        # если счет оплачен и в запросе включен авто-вывод
        if invoice_status == "success" and invoice_status_request.auto_withdraw:
            try:
                await withdraw(user, int(float(invoice_info.get("sum", "0"))))    # создание запроса на вывод средств
                withdraw_status = "success"
                withdraw_message = ""
            except WithdrawException as ex:    # API вернул статус "error"
                withdraw_status = "error"
                withdraw_message = ex.args[0]

        return {
            "status": invoice_status,
            "withdraw_status": withdraw_status,
            "withdraw_message": withdraw_message
        }

    # при получении статуса счета произошла ошибка
    else:
        logger.error(f"[API ERROR] Error while getting invoice info: \nRequest fields: {fields} \nResponse: {response}")

        return {
            "status": status,
            "code": response.get("code", "UNDEFINED"),
            "message": response.get("message", "UNDEFINED")
        }


def generate_invoice_id(user_name: str) -> str:
    """
    Генерирует уникальный идентификатор счета

    :param user_name: Имя продавца, который выставляет счет
    :return: SHA256 хеш
    """

    return f"{user_name}-{datetime.datetime.now().strftime('%d-%m-%Y-%H-%M-%S')}-{random.randint(0, 256)}"

@app.post("/payment_service/create_invoice/")
async def create_invoice(invoice_request: CreateInvoiceRequest):
    """
    Выставление счета.

    Счет успешно выставлен: {"status": "success", "id": "айди счета в системе Lava", "url": "url для оплаты"}.

    Ошибка при выставлении счета: {"status": "error", "code": "код ошибки (см. https://dev.lava.ru/errors)",
    "message": "сообщение об ошибке от Lava"}

    :param invoice_request: Информация о счете.
    :return: JSON словарь с информацией
    """
    logger.info(f"Create invoice requested: {invoice_request}")

    # если пользователь с полученым токеном не найден, то возвращает ошибку
    try:
        user = db.get_user_info(invoice_request.user_token)
    except database.UserNotFoundException:
        logger.error(f"User with token {invoice_request.user_token} not found")
        return {
            "status": "server error",
            "code": "-1",
            "message": "Invalid user token"
        }

    response = lava_api.create_invoice(SECRET_KEY,
                                       invoice_request.amount,
                                       generate_invoice_id(user.name),
                                       SECRET_KEY)
    print(response)
    # счет успешно выставлен
    if (status := response.get("status", "error")) == "success":
        data: dict = response.get("data", {})
        logger.info(f"Invoice created successfully: id = {data.get('id', 'UNDEFINED')}; "
                    f"sum = {data.get('amount', 'UNDEFINED')}; url = {data.get('url', 'UNDEFINED')}")

        return {
            "status": status,
            "id": response.get("id", "UNDEFINED"),
            "url": response.get("url", "UNDEFINED")
        }
    # ошибка при выставлении счета
    else:

        logger.error(f"[API ERROR] Error while creating invoice: \nResponse: {response}")

        return {
            "status": status,
            "code": response.get("status", "UNDEFINED"),
            "message": response.get("error", {"UNDEFINED": [""]})
        }


# только для тестирования
async def main():
    test_invoice_creation_request = CreateInvoiceRequest(user_token="0WH5bBJrq2nA1x6Wpk85vxBvOpC5zLydSuj9YIcOPa8",
                                                         amount=20, expire=60)
    test_invoice_response = await create_invoice(test_invoice_creation_request)
    print(test_invoice_response)
    '''
    test_invoice_status_request = InvoiceStatusRequest(id=test_invoice_response.get("id", "UNDEFINED"),
                         user_token="vw9NAdhy-vNB0L-hXWY7Z3TEGookB3Eg9kDDeu_hqf0", auto_withdraw=True)

    tryings_left = 10
    while tryings_left > 0:
        print(f"Waiting for payment... Trying: {10 - tryings_left}")
        test_invoice_status = await get_invoice_status(test_invoice_status_request)
        print(test_invoice_status)

        if test_invoice_status.get("status", "pending") == "success":
            break

        tryings_left -= 1
        await asyncio.sleep(10)

    print("RESULT: ", test_invoice_status)
'''
    #user = db.get_user_info("2qxm3GWCHnUxSO3e7fWJFcbKRPpmYWEaK7HcPoPxu1M")
    pass


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
