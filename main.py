"""
Основной файл.
Команда для запуска: uvicorn main:app --reload
"""
import datetime

"""
{'invoice_id': 'b0491e7e-590e-9bea-bb64-44432f62dbdd', 'status': 'success', 'pay_time': 1665961760, 'amount': '20.00', 'order_id': None, 'pay_service': 'qiwi', 'payer_details': None, 'custom_fields': '', 'type': 1, 'credited': '19.00', 'merchant_id': 'TestPayment'}
"""

import os
from fastapi import FastAPI
from pydantic import BaseModel, Field
import dlltool
import db as database
import logging
from typing import Optional
import asyncio
from typing import Dict, Any
import config as cfg


class CreateInvoiceRequest(BaseModel):
    """
    Модель запроса для выставления счета.
    """
    user_token: str    # токен пользователя
    amount: int    # сумма счета
    expire: int    # время жизни счета (по каким-то причинам не работает)
    comment: Optional[str] = Field("")   # комментарий
    auto_withdraw: Optional[bool] = Field(True)  # авто-вывод
    withdraw_service: Optional[str] = ""    # способ вывода (см. https://dev.lava.ru/methods)
    withdraw_wallet: Optional[str] = ""    # номер кошелька для вывода


class InvoiceStatusRequest(BaseModel):
    """
    Модель запроса для получения информации о счете.
    """
    user_token: str    # токен пользователя
    id: str    # айди счета, состояние которого необходимо получить
    auto_withdraw: Optional[bool] = Field(False)   # необязательный параметр. Если True, то после оплаты счета средства будут автоматически выведены


app = FastAPI(docs_url=None, redoc_url=None)    # docs_url и redoc_url отключают автоматическую документацию
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


async def get_balance(wallet: str) -> float:
    """
    Получает текущий баланс кошелька

    :param wallet: Номер кошелька
    :return: Баланс
    """

    response = dlltool.send("https://api.lava.ru/wallet/list", "POST", {"Authorization": cfg.TOKEN}, {"empty": "field"})    # см. https://dev.lava.ru/walletlist

    for subdict in response:
        if subdict.get("account", "") == wallet:
            return float(subdict.get("balance", 0))


async def withdraw(withdraw_service: str, withdraw_wallet: str, amount: float, comment: str) -> None:
    """
    Выводит средства
    :param withdraw_service: Способ вывода (см. https://dev.lava.ru/methods)
    :param withdraw_wallet: Номер кошелька для вывода
    :param amount: Сумма
    :param comment: Комментарий
    :return:
    """
    amount = float(amount)
    logger.info(f"Withdraw requested: service: {withdraw_service}; "
                f"wallet: {withdraw_wallet}; amount = {amount}")

    # если сервис вывода - 'lava', то создаем перевод средств между кошельками
    if withdraw_service == "lava":
        # см. https://dev.lava.ru/transfercreate
        fields = {
            "account_from": cfg.WALLET,
            "account_to": withdraw_wallet,
            "amount": f"{amount:.2f}",
            "comment": comment

        }
        logger.info(f"Sended transfer request with fields: {fields}")
        response = dlltool.send("https://api.lava.ru/transfer/create", "POST", {"Authorization": cfg.TOKEN},
                                fields)  # отправка данных в API (см. описание модуля)

    # иначе создаем вывод средств
    else:
        # см. https://dev.lava.ru/withdrawcreate
        fields = {
            "account": cfg.WALLET,
            "amount": f"{amount:.2f}",
            "service": withdraw_service,
            "wallet_to": withdraw_wallet
        }
        logger.info(f"Sended withdraw request with fields: {fields}")
        response = dlltool.send("https://api.lava.ru/withdraw/create", "POST", {"Authorization": cfg.TOKEN},
                                fields)  # отправка данных в API (см. описание модуля)

    if (status := response.get("status", "error")) != "success":
        logger.error(f"[WITHDRAW] Error while creating withdraw request: \nRequest: {fields};\n Response: {response};")
        raise WithdrawException(response.get("message", str(response)))

    logger.info(f"[WITHDRAW] Withdraw request successfully created: \nRequest: {fields}; \nResponse: {response};")


@app.post("/payment_service/webhook")
async def webhook(data: Dict[Any, Any]):
    logger.info(f"[WEBHOOK] Received: {data}")
    try:
        invoice_info = db.get_invoice_info(data.get("invoice_id", "UNDEFINED"))
    except database.InvoiceNotFoundException:
        return
    if invoice_info.status != "created":
        return

    invoice_info.credited = float(data.get("credited", -1))
    invoice_info.payed = str(datetime.datetime.now())
    invoice_info.status = "payed"

    db.save_invoice_info(invoice_info)

    logger.info(f"[WEBHOOK] Invoice payed: {invoice_info.order_id} {invoice_info.creator} {invoice_info.comment}")

    # если при создании счета был включен автовывод, то выводим средства пользователю
    if invoice_info.auto_withdraw and invoice_info.credited != -1:
        try:
            user = db.get_user_info(invoice_info.creator)
        except database.UserNotFoundException:
            logger.error(f"User with token {invoice_info.creator} not found")
            return {
                "status": "server error",
                "code": "-1",
                "message": "Invalid user token"
            }

        # если при создании запроса небыл указан способ или кошелек, то берем стандартные для аккаунта
        service = invoice_info.withdraw_service
        wallet = invoice_info.withdraw_wallet
        if service == "" or wallet == "":
            service, wallet = user.withdraw_service, user.withdraw_wallet

        try:
            await withdraw(service, wallet, invoice_info.credited * (user.percent / 100),
                           invoice_info.comment)  # создание запроса на вывод средств
            invoice_info.status = "withdrawed"
            db.save_invoice_info(invoice_info)
        except WithdrawException as ex:  # API вернул статус "error"
            withdraw_status = "error"
            withdraw_message = ex.args[0]
            logger.exception(ex)

        balance = await get_balance(cfg.WALLET)

        # вывод средств, полученых с комиссии, администраторам
        if cfg.ADMIN_AUTOWITHDRAW_ENABLED and balance > cfg.ADMIN_AUTOWITHDRAW_SUM:
            admins = cfg.ADMIN_AUTOWITHDRAW_USERS

            for admin_data in admins:
                try:
                    await withdraw(admin_data[0], admin_data[1], balance / 100 * admin_data[2], "Admin autowithdraw")
                    logger.info(f"[ADMIN WITHDRAW] SUCCESS {admin_data}")
                except WithdrawException as ex:
                    logger.info(f"[ADMIN WITHDRAW] ERROR {admin_data}; MESSAGE: {ex.args[0]}")


@app.post("/payment_service/get_invoice_status")
async def get_invoice_status(invoice_status_request: InvoiceStatusRequest):

    try:
        invoice_info = db.get_invoice_info(invoice_status_request.id)
    except database.InvoiceNotFoundException:
        return {
            "status": "server error",
            "code": "-2",
            "message": "Invalid invoice id"
        }

    if invoice_info.status == 'payed':
        return {
            "status": "success",
            "withdraw_status": "waiting" if invoice_info.auto_withdraw else "disabled",
            "withdraw_message": ""
        }
    elif invoice_info.status == "withdrawed":
        return {
            "status": "success",
            "withdraw_status": "success",
            "withdraw_message": ""
        }
    elif invoice_info.status == "created":
        return {
            "status": "pending",
            "withdraw_status": "disabled",
            "withdraw_message": ""
        }


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

    # см. https://dev.lava.ru/invoicecreate
    fields = {
        "wallet_to": cfg.WALLET,
        "sum": f"{invoice_request.amount:.2f}",
        "expire": "600",
        "merchant_id": user.name,
        "comment": invoice_request.comment,
        "hook_url": "http://185.189.255.220:8100/payment_service/webhook"
    }

    logger.debug(f"Sending create invoice request with fields: {fields}")

    response = dlltool.send("https://api.lava.ru/invoice/create", "POST", {"Authorization": cfg.TOKEN}, fields)    # отправка данных в API (см. описание модуля)

    logger.debug(f"Got response: {response}")

    # счет успешно выставлен
    if (status := response.get("status", "error")) == "success":

        logger.info(f"Invoice created successfully: id = {response.get('id', 'UNDEFINED')}; "
                    f"sum = {invoice_request.amount}; url = {response.get('url', 'UNDEFINED')}")

        # если при создании запроса небыл указан способ или кошелек, то берем стандартные для аккаунта
        service = invoice_request.withdraw_service
        wallet = invoice_request.withdraw_wallet
        if service == "" or wallet == "":
            service, wallet = user.withdraw_service, user.withdraw_wallet

        invoice_info = database.InvoiceInfo((response.get('id', 'UNDEFINED'), user.token, 'created',
                                             invoice_request.amount, -1, str(datetime.datetime.now()), "",
                                             invoice_request.auto_withdraw, invoice_request.comment, service, wallet))
        db.save_invoice_info(invoice_info)

        return {
            "status": status,
            "id": response.get("id", "UNDEFINED"),
            "url": response.get("url", "UNDEFINED")
        }
    # ошибка при выставлении счета
    else:

        logger.error(f"[API ERROR] Error while creating invoice: \nRequest fields: {fields} \nResponse: {response}")

        return {
            "status": status,
            "code": response.get("code", "UNDEFINED"),
            "message": response.get("message", "UNDEFINED")
        }


async def test_webhook():
    test_invoice_info = database.InvoiceInfo(("test_invoice_1234", "R9V5-qb47j34w9nMXNxmZEiqFVqDn1HZwojxnaOdPHo", 'created',
                                             10, -1, str(datetime.datetime.now()), "",
                                             True, "Webhook test", "qiwi", "+79608357711"))
    db.save_invoice_info(test_invoice_info)

    lava_data_emitter = {
        "invoice_id": "test_invoice_1234",
        "credited": 0,
    }
    webhook_response = await webhook(lava_data_emitter)

    print("Webhook response:", webhook_response)


# только для тестирования
async def main():
    '''test_invoice_creation_request = CreateInvoiceRequest(user_token="R9V5-qb47j34w9nMXNxmZEiqFVqDn1HZwojxnaOdPHo",
                                                         amount=20, expire=60)
    test_invoice_response = await create_invoice(test_invoice_creation_request)

    print(test_invoice_response)

    test_invoice_status_request = InvoiceStatusRequest(id=test_invoice_response.get("id", "UNDEFINED"),
                         user_token="R9V5-qb47j34w9nMXNxmZEiqFVqDn1HZwojxnaOdPHo", auto_withdraw=True)

    tryings_left = 10
    while tryings_left > 0:
        print(f"Waiting for payment... Trying: {10 - tryings_left}")
        test_invoice_status = await get_invoice_status(test_invoice_status_request)
        print(test_invoice_status)

        if test_invoice_status.get("status", "pending") == "success":
            break

        tryings_left -= 1
        await asyncio.sleep(10)

    print("RESULT: ", test_invoice_status)'''

    """user = db.get_user_info("R9V5-qb47j34w9nMXNxmZEiqFVqDn1HZwojxnaOdPHo")
    test_withdraw_response = await withdraw("test", "123456", 1, "Comment")
    print(test_withdraw_response)"""

    print(await get_balance(cfg.WALLET))

    #await test_webhook()

    pass


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
