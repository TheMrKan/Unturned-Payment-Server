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


class UserInfo:
    """
    Содержит информацию о пользователе.
    """
    token: str    # уникальный токен пользователя
    name: str    # имя (в коде не используется. Нужно исключительно для понятности в БД.)
    percent: int    # процент от оплаченых счетов, который будет автоматически выводиться
    withdraw_service: str    # способ вывода (https://dev.lava.ru/methods) + 'lava' для перевода на другой лава кошелек
    withdraw_wallet: str    # номер счета, на который производится вывод. Подробнее: https://dev.lava.ru/withdrawcreate

    def __init__(self, fields: Tuple = None, token: str = None, name: str = None,
                 percent: int = None, withdraw_service: str = None, withdraw_wallet: str = None):
        """
        Создает экземпляр класса с данными пользователя по заданым параметрам.

        :param fields: Кортеж данных, получаемых из БД. Порядок: token, name, percent, withdraw_service, withdraw_wallet.
        :param token: Токен пользователя. Перезаписывает токен из fields.
        :param name: Имя пользователя. Перезаписвает имя из fields.
        :param percent: Процент, получаемый пользователем. Перезаписывает процент из fields.
        :param withdraw_service: Способ авто-вывода средств. Перезаписывает сервис из fields.
        :param withdraw_wallet: Номер счета для авто-вывода. Перезаписывает номер счета из fields.
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

    def get_user_info(self, token: str):
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
    connection.commit()


def __drop_table(connection: Connection, cursor: Cursor):
    cursor.execute("DROP TABLE IF EXISTS users;")
    connection.commit()


def __add_user(connection: Connection, cursor: Cursor, name: str, percent: int, withdraw_service: str, withdraw_wallet: str, token: str = None):
    if token is None:
        token = secrets.token_urlsafe(32)    # генерирует токен из случайных символов длиной 32 символа

    cursor.execute("INSERT INTO users (token, name, percent, withdraw_service, withdraw_wallet) VALUES (?, ?, ?, ?, ?);",
                   (token, name, percent, withdraw_service, withdraw_wallet))
    connection.commit()

    return token


def __get_all_users(connection: Connection, cursor: Cursor):
    cursor.execute("SELECT * FROM users")

    return cursor.fetchall()


if __name__ == "__main__":
    dbm = DatabaseManager("database.sqlite3")
    #__drop_table(dbm.connection, dbm.cursor)
    #__create_table(dbm.connection, dbm.cursor)
    #print(__add_user(dbm.connection, dbm.cursor, "SOZ", 100, "qiwi", "+79608357711"))
    #dbm.get_user_info("-RKZE_bga7T-27GkEowwR6JqRWfJ9mzVkUW3u0g-1-w")
    print(__get_all_users(dbm.connection, dbm.cursor))