from db import DatabaseManager, InvoiceInfo, InvoiceStatus, PaymentMethod
import uuid
import datetime
import logging
import config
import hashlib

from AaioAsync import AaioAsync
from lava_api.business import LavaBusinessAPI, CreateInvoiceException, InvoiceInfo as LavaInvoiceInfo
from apis import enot, nicepay, pally


class InvalidInvoiceStatusError(Exception):
    def __init__(self, invoice_id: str, invoice_status: InvoiceStatus, *args, **kwargs):
        super().__init__(f"The operation cannot be performed on the invoice '{invoice_id}' with status '{invoice_status}'.", *args)


class InvalidInvoiceError(Exception):
    def __init__(self, invoice_id: str, *args, **kwargs):
        super().__init__(f"Invoice '{invoice_id}' not found.", *args)


class InvalidPaymentMethodError(Exception):
    def __init__(self, method_id: str, *args, **kwargs):
        super().__init__(f"Payment method {method_id} not found or currently unavailable.", *args)


class PaymentSystemError(Exception):
    def __init__(self, method_id: str, *args, **kwargs):
        super().__init__(f"An error occured in '{method_id}' payment method.", *args)


class InvoiceManager:

    _db_manager: DatabaseManager
    _logger: logging.Logger
    _aaio: AaioAsync
    _lava: LavaBusinessAPI

    def __init__(self, db_manager: DatabaseManager):
        self._db_manager = db_manager
        self._logger = logging.getLogger("payment_api_logger")

        self._aaio = AaioAsync(config.AAIO_API_KEY, config.AAIO_SHOP_ID, config.AAIO_KEY1)
        self._lava = LavaBusinessAPI(config.LAVA_SECRET_KEY)

    @staticmethod
    def get_choose_method_url(invoice_id: str):
        return config.CHOOSE_METHOD_URL.format(invoice_id)

    async def create_invoice_async(self, amount: float, comment: str, custom_fields: str, webhook_url: str) -> InvoiceInfo:
        invoice_id = str(uuid.uuid4())

        invoice = InvoiceInfo(invoice_id, InvoiceStatus.CREATED, amount, 0, datetime.datetime.now(), None, comment, custom_fields, webhook_url, None, self.get_choose_method_url(invoice_id))
        await self._db_manager.save_invoice_info_async(invoice)

        self._logger.info(f"Created invoice: {invoice}")

        return invoice

    async def process_invoice_async(self, invoice_id: str, method_id: str) -> InvoiceInfo:
        invoice_info = await self._db_manager.get_invoice_info_async(invoice_id)
        if invoice_info is None:
            raise InvalidInvoiceError(invoice_id)

        if invoice_info.status != InvoiceStatus.CREATED or invoice_info.payment_method is not None:
            raise InvalidInvoiceStatusError(invoice_info.invoice_id, invoice_info.status)

        method = await self._db_manager.get_payment_method_async(method_id)
        if method is None:
            raise InvalidPaymentMethodError(method_id)

        invoice_info.status = InvoiceStatus.PROCESSING

        match method.method_id:
            case "aaio":
                invoice_info.payment_url = await self._create_aaio_invoice(invoice_info)
            case "lava":
                lava_invoice_info = await self._create_lava_invoice(invoice_info)
                invoice_info.payment_url = lava_invoice_info.url
                invoice_info.payment_method_invoice_id = lava_invoice_info.invoice_id
            case "enot":
                enot_invoice_info = await self._create_enot_invoice(invoice_info)
                invoice_info.payment_url = enot_invoice_info.url
                invoice_info.payment_method_invoice_id = enot_invoice_info.invoice_id
            case "nicepay":
                nicepay_invoice_info = await self._create_nicepay_invoice(invoice_info)
                invoice_info.payment_url = nicepay_invoice_info.link
                invoice_info.payment_method_invoice_id = nicepay_invoice_info.payment_id
            case "pally":
                pally_invoice_info = await self._create_pally_invoice(invoice_info)
                invoice_info.payment_url = pally_invoice_info.url
                invoice_info.payment_method_invoice_id = pally_invoice_info.id
            case _:
                await self._delegate_invoice_async(invoice_info, method)

        invoice_info.payment_method = method.method_id

        await self._db_manager.save_invoice_info_async(invoice_info)

        self._logger.info(f"Processed invoice: {invoice_info}")

        return invoice_info

    async def _create_aaio_invoice(self, invoice_info: InvoiceInfo) -> str:
        try:
            return await self._aaio.generatepaymenturl(invoice_info.amount, invoice_info.invoice_id, desc=invoice_info.comment)
        except Exception as ex:
            raise PaymentSystemError("aaio") from ex

    async def _create_lava_invoice(self, invoice_info: InvoiceInfo) -> LavaInvoiceInfo:
        try:
            return await self._lava.create_invoice(invoice_info.amount, config.LAVA_SHOP_ID,
                                                   order_id=invoice_info.invoice_id,
                                                   comment=invoice_info.comment,
                                                   webhook_url=config.LAVA_WEBHOOK_URL,
                                                   success_url=config.SUCCESS_URL,
                                                   fail_url=config.FAILED_URL)
        except CreateInvoiceException as ex:
            raise PaymentSystemError("lava") from ex

    @staticmethod
    async def _create_enot_invoice(invoice_info: InvoiceInfo) -> enot.EnotInvoiceInfo:
        try:
            return await enot.create_invoice_async(
                shop_id=config.ENOT_SHOP_ID,
                secret_key=config.ENOT_SECRET_KEY,
                amount=invoice_info.amount,
                order_id=invoice_info.invoice_id,
                hook_url=config.ENOT_WEBHOOK_URL,
                comment=invoice_info.comment,
                success_url=config.SUCCESS_URL,
                fail_url=config.FAILED_URL,
            )
        except enot.APIError as e:
            raise PaymentSystemError("enot") from e

    @staticmethod
    async def _create_nicepay_invoice(invoice_info: InvoiceInfo) -> nicepay.NicepayInvoiceInfo:
        try:
            return await nicepay.create_invoice_async(config.NICEPAY_MERCHANT_ID,
                                                      config.NICEPAY_SECRET_KEY,
                                                      invoice_info.invoice_id,
                                                      "customer@untstrong.ru",
                                                      invoice_info.amount,
                                                      "RUB",
                                                      description=invoice_info.comment,
                                                      success_url=config.SUCCESS_URL,
                                                      fail_url=config.FAILED_URL,
                                                      )
        except nicepay.APIError as e:
            raise PaymentSystemError("nicepay") from e

    @staticmethod
    async def _create_pally_invoice(invoice_info: InvoiceInfo) -> pally.PallyBillInfo:
        try:
            return await pally.create_bill_async(
                config.PALLY_SHOP_ID,
                config.PALLY_SECRET_KEY,
                invoice_info.amount,
                invoice_info.invoice_id,
                invoice_info.comment,
                invoice_info.comment,
            )
        except pally.APIError as e:
            raise PaymentSystemError("pally") from e

    @staticmethod
    async def _delegate_invoice_async(invoice_info: InvoiceInfo, method: PaymentMethod):
        invoice_info.payment_url = method.delegate_url
        invoice_info.status = InvoiceStatus.DELEGATED

    @staticmethod
    def _get_aaio_webhook_sign(shop_id: str, amount: str, currency: str, key2: str, invoice_id: str):
        return hashlib.sha256(f"{shop_id}:{amount}:{currency}:{key2}:{invoice_id}".encode('utf-8')).hexdigest()

    @staticmethod
    def check_aaio_sign(sign: str, amount: str, currency: str, invoice_id: str) -> bool:
        s = InvoiceManager._get_aaio_webhook_sign(config.AAIO_SHOP_ID, amount, currency, config.AAIO_KEY2, invoice_id)
        return s == sign

    async def set_invoice_payed_async(self, invoice_id: str, credited: float | None = None, payed: datetime.datetime | None = None, payment_method_invoice_id: str | None = None) -> InvoiceInfo:
        invoice_info = await self._db_manager.get_invoice_info_async(invoice_id)
        if invoice_info is None:
            raise InvalidInvoiceError(invoice_id)

        if invoice_info.status == InvoiceStatus.SUCCESS or invoice_info.status == InvoiceStatus.ERROR:
            raise InvalidInvoiceStatusError(invoice_info.invoice_id, invoice_info.status)

        invoice_info.status = InvoiceStatus.SUCCESS
        invoice_info.credited = credited or invoice_info.amount
        invoice_info.payed = payed or datetime.datetime.now()
        invoice_info.payment_method_invoice_id = payment_method_invoice_id

        await self._db_manager.save_invoice_info_async(invoice_info)

        self._logger.info(f"Invoice payed: {invoice_info}")

        return invoice_info

    async def set_invoice_status_async(self, invoice_id: str, status: InvoiceStatus) -> InvoiceInfo:
        if status == InvoiceStatus.SUCCESS:
            return await self.set_invoice_payed_async(invoice_id)

        invoice_info = await self._db_manager.get_invoice_info_async(invoice_id)
        if invoice_info is None:
            raise InvalidInvoiceError(invoice_id)

        if invoice_info.status == InvoiceStatus.SUCCESS or invoice_info.status == InvoiceStatus.ERROR:
            raise InvalidInvoiceStatusError(invoice_info.invoice_id, invoice_info.status)

        invoice_info.status = status
        invoice_info.credited = 0
        invoice_info.payed = None

        await self._db_manager.save_invoice_info_async(invoice_info)

        self._logger.info("Invoice status updated: [%s] %s", status, invoice_id)

        return invoice_info
