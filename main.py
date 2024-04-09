"""
Основной файл.
Команда для запуска: uvicorn main:app --reload
"""
import threading
import time

import fastapi
import requests
import datetime
import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
import db as database
import logging
from typing import Optional, Annotated
import asyncio
from typing import Dict, Any
import config as cfg
from starlette.datastructures import Headers
from dataclasses import dataclass
from invoice_manager import InvoiceManager, InvalidInvoiceStatusError, InvalidInvoiceError, InvalidPaymentMethodError, PaymentSystemError


app = FastAPI(docs_url=None, redoc_url=None)    # docs_url и redoc_url отключают автоматическую документацию
db = database.DatabaseManager(cfg.MYSQL_HOST, cfg.MYSQL_USER, cfg.MYSQL_PASSWORD, cfg.MYSQL_DATABASE)    # экземпляр класса для доступа к данным из БД.
invoice_manager = InvoiceManager(db)


origins = [
    "https://untstrong.ru",
    "null"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("payment_api_logger")
logger.setLevel(logging.DEBUG)
if not cfg.DEBUG:
    fh = logging.FileHandler(f'logs/log_{datetime.datetime.now().strftime("%m-%d-%Y-%H-%M-%S")}.log')
    fh.setFormatter(logging.Formatter(fmt='[%(asctime)s: %(levelname)s] %(message)s'))
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)


class APIException(Exception):
    def __init__(self, code: int | str, message: str):
        self.code = int(code)
        self.message = message


@app.exception_handler(APIException)
def api_exception_handler(request: Request, exc: APIException):
    return JSONResponse(status_code=exc.code,
                        content={"status": "error", "code": str(exc.code), "message": exc.message, "detail": exc.message})


def send_webhook(invoice_info: database.InvoiceInfo):
    retryings = 5
    pause = 5

    for trying in range(retryings):

        try:
            webhook_data = {
                "invoice_id": invoice_info.invoice_id,
                "sum": invoice_info.amount,
                "comment": invoice_info.comment,
                "custom_field": invoice_info.custom_fields,
            }
            resp = requests.post(invoice_info.webhook_url, json=webhook_data, headers={"User-Id": config.AUTH_TOKEN})
            if resp.status_code != 200:
                logger.error(f"Failed to send webhook with status code {resp.status_code}: id = {invoice_info.invoice_id}")
                time.sleep(pause)
                continue
            logger.info(f"[USER WEBHOOK] Sended successfully: id = {invoice_info.invoice_id}")
            return
        except Exception as ex:
            logger.exception(f"Internal error occured while sending webhook: id = {invoice_info.invoice_id}", exc_info=ex)
            time.sleep(pause)
            continue


@app.post("/payment_service/aaio_webhook/")
@app.post("/payment_service/aaio_webhook")
async def aaio_webhook(invoice_id=Form(), order_id=Form(), amount=Form(), currency=Form(), sign=Form(), profit=Form()):
    if not InvoiceManager.check_aaio_sign(str(sign), str(amount), str(currency), str(order_id)):
        logger.error(f"[AAIO WEBHOOK] Failed to check sign: invoice_id={invoice_id}, order_id={order_id}, amount={amount}, currency={currency}, sign={sign}")

    try:
        invoice = await invoice_manager.set_invoice_payed_async(str(order_id), float(profit), payment_method_invoice_id=str(invoice_id))
    except Exception as ex:
        logger.error(f"[AAIO WEBHOOK] Failed to handle: invoice_id={invoice_id}, order_id={order_id}, amount={amount}, currency={currency}, sign={sign}", exc_info=ex)
        return

    if invoice.webhook_url:
        send_webhook_thread = threading.Thread(target=send_webhook, args=(invoice,))
        send_webhook_thread.start()


'''@app.post("/payment_service/webhook")
async def webhook(request: fastapi.Request, data: Dict[Any, Any]):
    try:
        logger.info(f"[WEBHOOK] Received: {data}")

        api = LavaBusinessAPI(cfg.KEY)
        sucessful_invoice_info = api.handle_webhook(data, dict(request.headers))
        #print(sucessful_invoice_info)

        try:
            invoice_info = db.get_invoice_info(data.get("invoice_id", "UNDEFINED"))
        except database.InvoiceNotFoundException:
            return
        if invoice_info.status != "created":
            return

        data.setdefault("custom_fields", "")
        if data["custom_fields"] is None:
            data["custom_fields"] = ""
        custom_fields = data["custom_fields"]

        invoice_info.credited = float(data.get("credited", -1))
        invoice_info.payed = str(datetime.datetime.now())
        invoice_info.status = "payed"
        #print(f"Invoice info before save: {invoice_info.credited} {invoice_info.payed} {invoice_info.status}")
        db.save_invoice_info(invoice_info)
        _invoice_info = db.get_invoice_info(invoice_info.order_id)
        #print(f"Invoice info after save: {_invoice_info.credited} {_invoice_info.payed} {_invoice_info.status}")
        logger.info(f"[WEBHOOK] Invoice payed: {invoice_info.order_id} {invoice_info.creator} {invoice_info.comment}")

        if invoice_info.webhook_url:
            send_webhook_thread = threading.Thread(target=send_webhook, args=(invoice_info, custom_fields))
            send_webhook_thread.start()

    except Exception as ex:
        logger.exception(ex)'''


@dataclass
class ResponseCreateInvoice:
    status: str
    id: str
    url: str


class CreateInvoiceRequest(BaseModel):
    user_token: str
    amount: int    # сумма счета
    comment: Optional[str] = Field("")   # комментарий
    webhook_url: Optional[str] = ""    # URL для отправки вебхука при оплате
    webhook_field: Optional[str] = ""    # дополнительное поле, которое будет передано в вебхук


@app.post("/payment_service/create_invoice/")
@app.post("/payment_service/create_invoice")
async def create_invoice(request: fastapi.Request, invoice_request: CreateInvoiceRequest) -> ResponseCreateInvoice:
    if invoice_request.user_token != config.AUTH_TOKEN:
        raise APIException(403, "Invalid user token")

    try:
        invoice = await invoice_manager.create_invoice_async(invoice_request.amount, invoice_request.comment, invoice_request.webhook_field, invoice_request.webhook_url)
        return ResponseCreateInvoice("success", invoice.invoice_id, invoice.payment_url)
    except Exception as ex:
        logger.exception("An error occured in create_invoice", exc_info=ex)
        raise APIException(500, "Internal server error")


@dataclass
class RequestProcessInvoice:
    invoice_id: str
    method_id: str


@dataclass
class ResponseProcessInvoice:
    status: str
    id: str
    payment_url: str


@app.post("/payment_service/process_invoice/")
@app.post("/payment_service/process_invoice")
async def process_invoice(request: RequestProcessInvoice) -> ResponseProcessInvoice:
    try:
        invoice = await invoice_manager.process_invoice_async(request.invoice_id, request.method_id)
        return ResponseProcessInvoice("success", invoice.invoice_id, invoice.payment_url)
    except InvalidInvoiceError as ex:
        logger.exception(str(ex), exc_info=ex)
        raise APIException(404, str(ex))
    except InvalidInvoiceStatusError as ex:
        logger.exception(str(ex), exc_info=ex)
        raise APIException(409, str(ex))
    except InvalidPaymentMethodError as ex:
        logger.exception(str(ex), exc_info=ex)
        raise APIException(405, str(ex))
    except PaymentSystemError as ex:
        logger.exception(str(ex), exc_info=ex)
        raise APIException(500, str(ex))

    except Exception as ex:
        logger.exception("An error occured in process_invoice", exc_info=ex)
        raise APIException(500, "Internal server error")


@dataclass
class PaymentMethod:
    id: str
    name: str
    description: str
    icon_url: str


@app.get("/payment_service/methods/")
@app.get("/payment_service/methods")
async def get_payment_methods() -> list[PaymentMethod]:
    methods = await db.get_payment_methods_async()
    return [PaymentMethod(m.method_id, m.name, m.description, m.icon_url) for m in methods]


# только для тестирования
async def debug():
    pass


if __name__ == "__main__":
    asyncio.run(debug(), debug=True)
