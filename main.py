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


class CreateInvoiceRequest(BaseModel):
    """
    Модель запроса для выставления счета.
    """
    user_token: str    # токен пользователя
    amount: int    # сумма счета
    expire: int    # время жизни счета (по каким-то причинам не работает)
    comment: Optional[str] = Field("")   # комментарий
    auto_withdraw: Optional[bool] = Field(True)  # авто-вывод


class InvoiceStatusRequest(BaseModel):
    """
    Модель запроса для получения информации о счете.
    """
    user_token: str    # токен пользователя
    id: str    # айди счета, состояние которого необходимо получить
    auto_withdraw: Optional[bool] = Field(False)   # необязательный параметр. Если True, то после оплаты счета средства будут автоматически выведены


app = FastAPI(docs_url=None, redoc_url=None)    # docs_url и redoc_url отключают автоматическую документацию
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1aWQiOiIxZmQwZDZlYi02YjZlLTVkYjYtM2IzYS1lNzk0ZmJlZTRiMGYiLCJ0aWQiOiJjNjdmYWFmMS1jYTIxLWJiMzQtOTA5Yi1lYjg1MDI1OGExOWMifQ.lkRc2IPMT2m_eWnP18fbq90J9EX1tQJzrGScrX66K-U"
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


async def withdraw(user: database.UserInfo, amount: float, comment: str) -> None:
    """
    Выводит средства
    :param user: Информация о пользователе из БД
    :param amount: Сумма
    :param comment: Комментарий
    :return:
    """
    amount = float(amount)
    logger.info(f"Withdraw requested: user = {user.name}; service: {user.withdraw_service}; "
                f"wallet: {user.withdraw_wallet}; amount = {amount}")

    # если сервис вывода - 'lava', то создаем перевод средств между кошельками
    if user.withdraw_service == "lava":
        # см. https://dev.lava.ru/transfercreate
        fields = {
            "account_from": WALLET,
            "account_to": user.withdraw_wallet,
            "amount": f"{amount * (user.percent / 100):.2f}",
            "comment": comment

        }
        logger.info(f"Sended transfer request with fields: {fields}")
        response = dlltool.send("https://api.lava.ru/transfer/create", "POST", {"Authorization": TOKEN},
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
        response = dlltool.send("https://api.lava.ru/withdraw/create", "POST", {"Authorization": TOKEN},
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

        try:
            await withdraw(user, invoice_info.credited,
                           invoice_info.comment)  # создание запроса на вывод средств
            invoice_info.status = "withdrawed"
            db.save_invoice_info(invoice_info)
        except WithdrawException as ex:  # API вернул статус "error"
            withdraw_status = "error"
            withdraw_message = ex.args[0]
            return {"status": withdraw_status, "message": withdraw_message}


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
    """
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

    response = dlltool.send("https://api.lava.ru/invoice/info", "POST", {"Authorization": TOKEN}, fields)    # отправка данных в API (см. описание модуля)

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




    # при получении статуса счета произошла ошибка
    else:
        logger.error(f"[API ERROR] Error while getting invoice info: \nRequest fields: {fields} \nResponse: {response}")

        return {
            "status": status,
            "code": response.get("code", "UNDEFINED"),
            "message": response.get("message", "UNDEFINED")
        }
    """

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
        "wallet_to": WALLET,
        "sum": f"{invoice_request.amount:.2f}",
        "expire": "600",
        "merchant_id": user.name,
        "comment": invoice_request.comment,
        "hook_url": "http://185.189.255.220:8100/payment_service/webhook"
    }

    logger.debug(f"Sending create invoice request with fields: {fields}")

    response = dlltool.send("https://api.lava.ru/invoice/create", "POST", {"Authorization": TOKEN}, fields)    # отправка данных в API (см. описание модуля)

    logger.debug(f"Got response: {response}")

    # счет успешно выставлен
    if (status := response.get("status", "error")) == "success":

        logger.info(f"Invoice created successfully: id = {response.get('id', 'UNDEFINED')}; "
                    f"sum = {invoice_request.amount}; url = {response.get('url', 'UNDEFINED')}")

        invoice_info = database.InvoiceInfo((response.get('id', 'UNDEFINED'), user.token, 'created',
                                             invoice_request.amount, -1, str(datetime.datetime.now()), "",
                                             invoice_request.auto_withdraw, invoice_request.comment))
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


# только для тестирования
async def main():
    test_invoice_creation_request = CreateInvoiceRequest(user_token="2qxm3GWCHnUxSO3e7fWJFcbKRPpmYWEaK7HcPoPxu1M",
                                                         amount=20, expire=60)
    test_invoice_response = await create_invoice(test_invoice_creation_request)
    print(test_invoice_response)

    test_invoice_status_request = InvoiceStatusRequest(id=test_invoice_response.get("id", "UNDEFINED"),
                         user_token="2qxm3GWCHnUxSO3e7fWJFcbKRPpmYWEaK7HcPoPxu1M", auto_withdraw=True)

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

    #user = db.get_user_info("aoTwBen_REaz44vuBtUPovGWHJiweYG1ZdwLrNueMEw")
    #test_withdraw_response = await withdraw(user, 10, "Hello World!")


    pass


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
