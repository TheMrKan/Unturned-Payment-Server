"""
Модуль отвечающий за взаимодействие с функциями, написаными на C#.
API выдавал ошибку при работе с POST запросами через requests, поэтому был использован готовый C# код из плагина.
Проект в папке LavaAPI.
Платформа: .NET Framework 4.6.2
"""

import clr    # pip install pythonnet
from typing import Dict, Any
import json


clr.AddReference("LavaAPI/bin/Debug/LavaAPI")    # подключает dll библиотеку

# импорт всех необходимых C# библиотек
from DotNetModule import FormdataSender    # DotNetModule - пространство имен; FormdataSender - название класса.
from System.Collections.Generic import Dictionary
from System import String


def send(url: str, method: str, headers: Dict[str, str], fields: Dict[str, str]) -> Dict[Any, Any]:
    """
    Вызывает функцию из C# модуля для отправки multipart/form-data запросов.

    :param url: URL, на который будет отправлен запрос
    :param method: 'POST' или 'GET'
    :param headers: Словарь с заголовками, которые будут добавлены в запросу
    :param fields: Словарь с полями, которые будут добавлены в FormData
    :return: Десериализованный из JSON словарь с ответом API
    """
    # вызов C# функции. Возвращает string.
    cs_response = FormdataSender.Send(url, method, to_cs_dict(headers), to_cs_dict(fields))

    response = json.loads(cs_response)    # десериализация ответа
    return response


def to_cs_dict(py_dict: dict) -> Dictionary[String, String]:
    """
    Преобразует Python словарь в словарь C#.

    :param py_dict: Python словарь
    :return: Словарь с типом Dictionary[String, String], который можно передавать как аргумент в C# функции
    """
    cs_dict = Dictionary[String, String]()    # объект словаря из C# библиотеки
    for k, v in py_dict.items():
        cs_dict[k] = v
    return cs_dict

