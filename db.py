"""
Модуль дял работы с базой данных пользователей (SQLite3).
"""

import sqlite3
from sqlite3.dbapi2 import Cursor, Connection
import secrets
from typing import Tuple


class UserNotFoundException(Exception):
    """
    Пользователь не найден в базе данных.
    """
    pass


class InvoiceNotFoundException(Exception):
    """
    Счет не найден в базе данных.
    """
    pass


class InvoiceInfo:
    """
    Содержит информацию о счете.
    """
    order_id: str    # номер счета
    creator: str   # токен пользователя, для которого создан счет
    status: str    # статус счета
    amount: float    # сумма счета
    credited: float    # сумма, зачисленная после оплаты счета
    created: str    # время создания счета
    payed: str    # время оплаты счета
    auto_withdraw: bool    # автовывод средств при True
    withdraw_service: str    # способ вывода
    withdraw_wallet: str    # номер кошелька для вывода
    comment: str    # комментарий

    def __init__(self, fields: Tuple):
        if len(fields) != 11:
            raise ValueError(f"Ожидаемое количество элементов в fields: 11. Получено: {len(fields)}")

        self.order_id, self.creator, self.status, self.amount, self.credited, self.created, \
            self.payed, self.auto_withdraw, self.comment, self.withdraw_service, self.withdraw_wallet = fields


class UserInfo:
    """
    Содержит информацию о пользователе.
    """
    token: str    # уникальный токен пользователя
    name: str    # имя (в коде не используется. Нужно исключительно для понятности в БД.)
    percent: int    # процент от оплаченых счетов, который будет автоматически выводиться
    withdraw_service: str    # Устаревшее! способ вывода (https://dev.lava.ru/methods) + 'lava' для перевода на другой лава кошелек
    withdraw_wallet: str    # Устаревшее! номер счета, на который производится вывод. Подробнее: https://dev.lava.ru/withdrawcreate

    def __init__(self, fields: Tuple = None, token: str = None, name: str = None,
                 percent: int = None, withdraw_service: str = None, withdraw_wallet: str = None):
        """
        Создает экземпляр класса с данными пользователя по заданым параметрам.

        :param fields: Кортеж данных, получаемых из БД. Порядок: token, name, percent, withdraw_service, withdraw_wallet.
        :param token: Токен пользователя. Перезаписывает токен из fields.
        :param name: Имя пользователя. Перезаписвает имя из fields.
        :param percent: Процент, получаемый пользователем. Перезаписывает процент из fields.
        :param withdraw_service: Устаревшее! Способ вывода указывается при создании счета. Способ авто-вывода средств. Перезаписывает сервис из fields.
        :param withdraw_wallet: Устаревшее! Номер кошелька указывается при создании счета. Номер счета для авто-вывода. Перезаписывает номер счета из fields.
        """
        # распаковываем данные из fields
        if len(fields) == 5:
            self.token, self.name, self.percent, self.withdraw_service, self.withdraw_wallet = fields

        # если параметр указан, то перезаписываем параметр из fields
        if token is not None:
            self.token = token
        if name is not None:
            self.name = name
        if percent is not None:
            self.percent = percent
        if withdraw_service is not None:
            self.withdraw_service = withdraw_service
        if withdraw_wallet is not None:
            self.withdraw_wallet = withdraw_wallet


class DatabaseManager:
    """
    Предоставляет доступ к базе данных пользователей.
    """

    def __init__(self, filename: str):
        """
        Создает экземпляр менеджера базы данных для указанного файла.
        :param filename: Путь до файла базы данных.
        """
        self.connection = sqlite3.connect(filename)
        self.cursor = self.connection.cursor()

    def get_invoice_info(self, order_id: str) -> InvoiceInfo:
        """
        Находит информацию о счете по айди.
        :param order_id: Айди счета
        :return: Данные о счете.
        """
        self.cursor.execute("SELECT * FROM invoices WHERE order_id = ?", (order_id,))

        rows = self.cursor.fetchall()

        # если список строк пуст, значит счет не найден
        if not rows:
            raise InvoiceNotFoundException(f"Счет с айди {order_id} не найден.")

        invoice_info = InvoiceInfo(rows[0])

        return invoice_info

    def save_invoice_info(self, invoice_info: InvoiceInfo):
        """
        Сохраняет данные о счете.
        :param invoice_info: Данные о счете, которые нужно сохранить
        :return:
        """
        try:
            self.cursor.execute(
                "INSERT INTO invoices (order_id, creator, status, amount, credited, created, payed, auto_withdraw, comment, withdraw_service, withdraw_wallet) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (invoice_info.order_id, invoice_info.creator, invoice_info.status, invoice_info.amount,
                 invoice_info.credited, invoice_info.created, invoice_info.payed,  int(invoice_info.auto_withdraw),
                 invoice_info.comment, invoice_info.withdraw_service, invoice_info.withdraw_wallet))
            "ON DUPLICATE KEY UPDATE "
        except sqlite3.IntegrityError:
            self.cursor.execute(
                "UPDATE invoices SET order_id = ?, creator = ?, status = ?, amount = ?, credited = ?, created = ?, payed = ?, auto_withdraw = ?, comment = ?, withdraw_service = ?, withdraw_wallet = ? WHERE order_id = ?;",
                (invoice_info.order_id, invoice_info.creator, invoice_info.status, invoice_info.amount,
                 invoice_info.credited, invoice_info.created, invoice_info.payed, int(invoice_info.auto_withdraw),
                 invoice_info.comment, invoice_info.withdraw_service, invoice_info.withdraw_wallet, invoice_info.order_id))
        self.connection.commit()

    def get_user_info(self, token: str) -> UserInfo:
        """
        Находит информацию о пользователе по токену.

        :param token: Токен пользователя. Указывается в настройках плагина и передается в запросе create_invoice в поле merchant_token.
        :return: Данные о пользователе.
        :raises UserNotFoundException: Пользователь с указаным токеном не найден.
        """
        self.cursor.execute("SELECT * FROM users WHERE token = ?", (token, ))

        rows = self.cursor.fetchall()

        # если список строк пуст, значит пользователь не найден
        if not rows:
            raise UserNotFoundException(f"Пользователь с токеном {token} не найден.")

        user_info = UserInfo(rows[0])    # получаем информацию из первого пользователя в списке

        return user_info


# служебные функции для изменения и просмотра БД. Использовать только при запуске скрипта напрямую.


def __create_table(connection: Connection, cursor: Cursor):
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(token VARCHAR(32) NOT NULL, name VARCHAR(32) NOT NULL, percent INT UNSIGNED NOT NULL, "
        "withdraw_service VARCHAR(16) NOT NULL, withdraw_wallet VARCHAR(32), PRIMARY KEY (token, name));")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS invoices "
        "(order_id VARCHAR(32) NOT NULL, creator VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL, "
        "amount REAL NOT NULL, credited REAL NOT NULL, created VARCHAR(32) NOT NULL, "
        "payed VARCHAR(32) NOT NULL, auto_withdraw BIT NOT NULL, "
        "comment VARCHAR(32) NOT NULL, withdraw_service VARCHAR(32), withdraw_wallet VARCHAR(32), PRIMARY KEY (order_id));")
    connection.commit()


def __drop_table(connection: Connection, cursor: Cursor):
    cursor.execute("DROP TABLE IF EXISTS invoices;")
    connection.commit()


def __add_user(connection: Connection, cursor: Cursor, name: str, percent: int, withdraw_service: str, withdraw_wallet: str, token: str = None):
    if token is None:
        token = secrets.token_urlsafe(32)    # генерирует токен из случайных символов длиной 32 символа

    cursor.execute("INSERT INTO users (token, name, percent, withdraw_service, withdraw_wallet) VALUES (?, ?, ?, ?, ?);",
                   (token, name, percent, withdraw_service, withdraw_wallet))
    connection.commit()

    return token


def __edit_user(connection: Connection, cursor: Cursor):
    cursor.execute("UPDATE users SET withdraw_service='lava', withdraw_wallet='R10135783' WHERE name = 'TestUser';")
    connection.commit()


def __get_all_users(connection: Connection, cursor: Cursor):
    cursor.execute("SELECT * FROM users")

    return cursor.fetchall()


def __get_all_invoices(connection: Connection, cursor: Cursor):
    cursor.execute("SELECT * FROM invoices")

    return cursor.fetchall()


def __migrate(connection: Connection, cursor: Cursor):
    cursor.execute("ALTER TABLE invoices ADD COLUMN withdraw_service VARCHAR(32);")
    cursor.execute("ALTER TABLE invoices ADD COLUMN withdraw_wallet VARCHAR(32);")
    connection.commit()


if __name__ == "__main__":
    dbm = DatabaseManager("database.sqlite3")
    #__drop_table(dbm.connection, dbm.cursor)
    #__create_table(dbm.connection, dbm.cursor)
    #print(__add_user(dbm.connection, dbm.cursor, "LavaWithdraw", 100, "lava", "R10135783"))
    #dbm.get_user_info("-RKZE_bga7T-27GkEowwR6JqRWfJ9mzVkUW3u0g-1-w")
    #ii = InvoiceInfo(("123456-123-1234-123456", "-RKZE_bga7T-27GkEowwR6JqRWfJ9mzVkUW3u0g-1-w", "created",
                      #20, 19, "1:1:1 1:1:1", "2:3:1 1:1:1", True, "Comment"))
    #dbm.save_invoice_info(ii)
    #print(dbm.get_invoice_info("ae8c2701-8f8b-1de9-08a3-d2fce55ddf4e"))
    #__edit_user(dbm.connection, dbm.cursor)
    #__migrate(dbm.connection, dbm.cursor)
    print(__get_all_users(dbm.connection, dbm.cursor))
    #print(__get_all_invoices(dbm.connection, dbm.cursor))