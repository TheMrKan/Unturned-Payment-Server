import requests
import time
import json

fields = {
    "user_token": "R9V5-qb47j34w9nMXNxmZEiqFVqDn1HZwojxnaOdPHo",
    "amount": 20,
    "expire": 600,
    "comment": "Comment",
    "auto_withdraw": True,
    "webhook_url": "http://127.0.0.1:8000/payment_service/webhook"
}

response = requests.post("http://127.0.0.1:8000/payment_service/create_invoice/", json=fields)

try:
    print(response.json())
except:
    print(response.raw)

id = response.json().get("id", "undefined")
if id == "undefined":
    print("Exiting...")
    exit()
print(id)

'''i = 20

while i > 0:
    i -= 1
  
    fields = {
    "user_token": "2qxm3GWCHnUxSO3e7fWJFcbKRPpmYWEaK7HcPoPxu1M",
    "id": id,
    }

    response = requests.post("http://127.0.0.1:8000/payment_service/get_invoice_status", json=fields)
    print(response.json())
    
    time.sleep(5)'''


'''time.sleep(5)

from lava_api.business import LavaBusinessAPI
import config as cfg
api = LavaBusinessAPI(cfg.TOKEN)

fields = {'invoice_id': id, 'status': 'success', 'pay_time': 1666009808, 'amount': '20.00', 'order_id': None, 'pay_service': 'qiwi', 'payer_details': None, 'custom_fields': '', 'type': 1, 'credited': '19.00', 'merchant_id': 'TestUser'}
response = requests.post("http://127.0.0.1:8000/payment_service/webhook/", json=fields, headers={"Authorization": api.generate_signature(json.dumps(fields))})
print(response.content)'''