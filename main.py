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
from fastapi import FastAPI, Request, Form, Response, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import config
import db as database
import logging
from typing import Optional, Annotated
import asyncio
import config as cfg
from starlette.datastructures import Headers
from dataclasses import dataclass
from apis import enot, nicepay, pally

# настройка логгера до импорта других частей проекта, чтобы в них корректно работал logging.getLogger
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


class LavaWebhook(BaseModel):
    invoice_id: str
    order_id: str
    status: str
    pay_time: str
    amount: float
    custom_fields: Optional[str | None] = None
    credited: float


@app.post("/payment_service/lava_webhook/")
@app.post("/payment_service/lava_webhook")
async def lava_webhook(webhook: LavaWebhook, response: Response):
    pay_time = None
    try:
        pay_time = datetime.datetime.strptime(webhook.pay_time, "%Y-%m-%d %H:%M:%S")
    except ValueError as ex:
        logger.error(f"[LAVA WEBHOOK] Failed to parse pay time '{webhook.pay_time}'", exc_info=ex)

    try:
        invoice = await invoice_manager.set_invoice_payed_async(str(webhook.order_id), float(webhook.credited), payed=pay_time, payment_method_invoice_id=str(webhook.invoice_id))
    except Exception as ex:
        logger.error(f"[LAVA WEBHOOK] Failed to handle: invoice_id={webhook.invoice_id}, order_id={webhook.order_id}, amount={webhook.amount}", exc_info=ex)
        response.status_code = 500
        return JSONResponse({"success": False, "error": str(ex)})

    if invoice.webhook_url:
        send_webhook_thread = threading.Thread(target=send_webhook, args=(invoice,))
        send_webhook_thread.start()

    response.status_code = 200
    return JSONResponse({"success": True})


@app.post("/payment_service/enot_webhook/")
@app.post("/payment_service/enot_webhook")
async def enot_webhook(webhook: enot.EnotWebhook, response: Response):
    if webhook.status == enot.EnotWebhookStatus.success:
        try:
            invoice = await invoice_manager.set_invoice_payed_async(str(webhook.order_id), float(webhook.credited), payed=webhook.pay_time, payment_method_invoice_id=str(webhook.invoice_id))
        except Exception as ex:
            logger.error(f"[ENOT WEBHOOK] Failed to handle: invoice_id={webhook.invoice_id}, order_id={webhook.order_id}, amount={webhook.amount}", exc_info=ex)
            response.status_code = 500
            return JSONResponse({"success": False, "error": str(ex)})

        if invoice.webhook_url:
            send_webhook_thread = threading.Thread(target=send_webhook, args=(invoice,))
            send_webhook_thread.start()

        response.status_code = 200
        return JSONResponse({"success": True})
    elif webhook.status != enot.EnotWebhookStatus.refund:
        try:
            status = database.InvoiceStatus.TIMEOUT if webhook.status == webhook.status.expired else database.InvoiceStatus.ERROR
            invoice = await invoice_manager.set_invoice_status_async(str(webhook.order_id), status)
        except Exception as ex:
            logger.error(
                f"[ENOT WEBHOOK] Failed to handle: status={webhook.status}, invoice_id={webhook.invoice_id}, order_id={webhook.order_id}, amount={webhook.amount}",exc_info=ex)
            response.status_code = 500
            return JSONResponse({"success": False, "error": str(ex)})
        response.status_code = 200
        return JSONResponse({"success": True})


@app.get("/payment_service/nicepay_webhook/")
@app.get("/payment_service/nicepay_webhook")
async def nicepay_webhook(request: Request, webhook: Annotated[nicepay.NicepayWebhook, Query()], response: Response):
    if not nicepay.is_hash_valid(config.NICEPAY_SECRET_KEY, dict(request.query_params)):
        raise HTTPException(status_code=401, detail="Invalid hash")

    if webhook.result == nicepay.WebhookInvoiceStatus.success:
        try:
            invoice = await invoice_manager.set_invoice_payed_async(str(webhook.order_id), float(webhook.profit), payment_method_invoice_id=webhook.payment_id)
        except Exception as ex:
            logger.error(f"[NICEPAY WEBHOOK] Failed to handle: payment_id={webhook.payment_id}, order_id={webhook.order_id}, amount={webhook.amount}", exc_info=ex)
            response.status_code = 500
            return JSONResponse({"success": False, "error": str(ex)})

        if invoice.webhook_url:
            send_webhook_thread = threading.Thread(target=send_webhook, args=(invoice,))
            send_webhook_thread.start()

        response.status_code = 200
        return JSONResponse({"success": True})
    else:
        try:
            invoice = await invoice_manager.set_invoice_status_async(webhook.order_id, database.InvoiceStatus.ERROR)
        except Exception as ex:
            logger.error(
                f"[NICEPAY WEBHOOK] Failed to handle: status={webhook.result}, payment_id={webhook.payment_id}, order_id={webhook.order_id}, amount={webhook.amount}",exc_info=ex)
            response.status_code = 500
            return JSONResponse({"success": False, "error": str(ex)})
        response.status_code = 200
        return JSONResponse({"success": True})


@app.post("/payment_service/pally_webhook/")
@app.post("/payment_service/pally_webhook")
async def pally_webhook(request: Request, webhook: Annotated[pally.PostbackForm, Form()], response: Response):
    if not pally.is_signature_valid(webhook.SignatureValue, webhook.OutSum, webhook.InvId):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if webhook.Status in ("SUCCESS", "OVERPAID"):
        try:
            invoice = await invoice_manager.set_invoice_payed_async(
                str(webhook.InvId),
                float(webhook.OutSum),
            )
        except Exception as ex:
            logger.error(
                f"[PALLY WEBHOOK] Failed to handle: InvId={webhook.InvId}, OutSum={webhook.OutSum}",
                exc_info=ex,
            )
            response.status_code = 500
            return JSONResponse({"success": False, "error": str(ex)})

        if invoice.webhook_url:
            send_webhook_thread = threading.Thread(target=send_webhook, args=(invoice,))
            send_webhook_thread.start()

        response.status_code = 200
        return JSONResponse({"success": True})
    else:
        try:
            invoice = await invoice_manager.set_invoice_status_async(
                webhook.InvId, database.InvoiceStatus.ERROR
            )
        except Exception as ex:
            logger.error(
                f"[PALLY WEBHOOK] Failed to handle: Status={webhook.Status}, InvId={webhook.InvId}, ErrorCode={webhook.ErrorCode}, ErrorMessage={webhook.ErrorMessage}",
                exc_info=ex,
            )
            response.status_code = 500
            return JSONResponse({"success": False, "error": str(ex)})
        response.status_code = 200
        return JSONResponse({"success": True})


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
    instructions: str


@app.get("/payment_service/methods/")
@app.get("/payment_service/methods")
async def get_payment_methods() -> list[PaymentMethod]:
    methods = await db.get_payment_methods_async()
    return [PaymentMethod(m.method_id, m.name, m.description, m.icon_url, m.instructions or "") for m in methods]


# только для тестирования
async def debug():
    pass


if __name__ == "__main__":
    asyncio.run(debug(), debug=True)
