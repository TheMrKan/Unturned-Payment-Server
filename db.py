"""
Модуль дял работы с базой данных пользователей (SQLite3).
"""
import asyncio
import datetime

import aiomysql
from aiomysql import Pool
import asyncio
import secrets
from typing import Tuple
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import config


class InvoiceStatus(Enum):
    CREATED = "created"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    DELEGATED = "delegated"


@dataclass
class InvoiceInfo:
    """
    Содержит информацию о счете.
    """
    invoice_id: str  # номер счета
    status: InvoiceStatus
    amount: float  # сумма счета
    credited: float  # сумма, зачисленная после оплаты счета
    created: datetime.datetime  # время создания счета
    payed: datetime.datetime | None  # время оплаты счета
    comment: str  # комментарий
    custom_fields: str
    webhook_url: str
    payment_method: str | None
    payment_url: str
    payment_method_invoice_id: Optional[str | None] = None    # айди счета в системе оплаты


@dataclass
class PaymentMethod:
    method_id: str
    name: str
    description: str
    icon_url: str
    instructions: str | None
    delegate_url: str = ""


class DatabaseManager:
    _host: str
    _user: str
    _password: str
    _db_name: str

    _GET_INVOICES_QUERY = "SELECT * FROM invoices WHERE invoice_id = %s;"
    _SAVE_INVOICE_QUERY = "INSERT INTO invoices VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) " \
                          "ON DUPLICATE KEY UPDATE invoice_id = %s, status = %s, amount = %s, credited = %s, created = %s, payed = %s, comment = %s, custom_fields = %s, webhook_url = %s, payment_method = %s, payment_url = %s, payment_method_invoice_id = %s;"
    _GET_PAYMENT_METHODS_QUERY = "SELECT * FROM payment_methods;"
    _GET_PAYMENT_METHOD_QUERY = "SELECT * FROM payment_methods WHERE method_id = %s;"

    def __init__(self, host: str, user: str, password: str, db_name: str):
        self._host = host
        self._user = user
        self._password = password
        self._db_name = db_name

    def _get_connection(self):
        return aiomysql.connect(host=self._host, user=self._user, password=self._password, db=self._db_name)

    async def get_invoice_info_async(self, invoice_id: str) -> InvoiceInfo | None:
        async with self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._GET_INVOICES_QUERY, invoice_id)
                rows = await cur.fetchall()

        if not any(rows):
            return None

        inv = InvoiceInfo(*rows[0])
        inv.status = InvoiceStatus(inv.status)
        return inv

    async def save_invoice_info_async(self, invoice_info: InvoiceInfo):
        async with self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._SAVE_INVOICE_QUERY,
                                  (invoice_info.invoice_id, invoice_info.status.value, invoice_info.amount,
                                   invoice_info.credited, invoice_info.created, invoice_info.payed,
                                   invoice_info.comment, invoice_info.custom_fields,
                                   invoice_info.webhook_url, invoice_info.payment_method, invoice_info.payment_url, invoice_info.payment_method_invoice_id, invoice_info.invoice_id, invoice_info.status.value,
                                   invoice_info.amount,
                                   invoice_info.credited, invoice_info.created, invoice_info.payed,
                                   invoice_info.comment, invoice_info.custom_fields,
                                   invoice_info.webhook_url, invoice_info.payment_method, invoice_info.payment_url, invoice_info.payment_method_invoice_id))
                await conn.commit()

    async def get_payment_methods_async(self) -> list[PaymentMethod]:
        async with self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._GET_PAYMENT_METHODS_QUERY)
                rows = await cur.fetchall()

        if not any(rows):
            return []
        return [PaymentMethod(*r) for r in rows]

    async def get_payment_method_async(self, method_id: str) -> PaymentMethod | None:
        async with self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._GET_PAYMENT_METHOD_QUERY, method_id)
                rows = await cur.fetchall()

        if not any(rows):
            return None

        return PaymentMethod(*rows[0])

    async def create_tables_async(self):
        async with self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS invoices "
                    "(invoice_id VARCHAR(36) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'created', "
                    "amount REAL NOT NULL, credited REAL NOT NULL, created DATETIME NOT NULL, "
                    "payed DATETIME, comment VARCHAR(256) NOT NULL DEFAULT '',"
                    "custom_fields VARCHAR(128) NOT NULL DEFAULT '{}', webhook_url VARCHAR(128) NOT NULL DEFAULT '', payment_method VARCHAR(32), payment_url VARCHAR(512) NOT NULL, payment_method_invoice_id VARCHAR(128), PRIMARY KEY (invoice_id));")
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS payment_methods "
                    "(method_id VARCHAR(32) NOT NULL, name VARCHAR(64) NOT NULL, description VARCHAR(256) NOT NULL DEFAULT '', icon_url VARCHAR(256) NOT NULL, instructions TEXT, PRIMARY KEY (method_id));"
                )
                await conn.commit()


async def debug():
    manager = DatabaseManager(config.MYSQL_HOST, config.MYSQL_USER, config.MYSQL_PASSWORD, config.MYSQL_DATABASE)

    await manager.create_tables_async()

    #invoice = InvoiceInfo("test_inv", InvoiceStatus.CREATED, 10, 10, "2024-27-03 22:25:00", None, "comment", "", "", None, "")
    #await manager.save_invoice_info_async(invoice)

    #invoice = await manager.get_invoice_info_async("test_inv")
    #print(invoice)


if __name__ == "__main__":
    asyncio.run(debug(), debug=True)

