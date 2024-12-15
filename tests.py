import config
import asyncio

def test_nicepay_hash_validation():
    from apis import nicepay
    data = {
        "result": "success",
        "payment_id": "bVz657-bd8755-040148-6c9b6c-e47dld",
        "merchant_id": "657b475da365fbeb3e5cfaf6",
        "order_id": "100423",
        "amount": 5670,
        "amount_currency": "USD",
        "profit": 5370,
        "profit_currency": "USDT",
        "method": "paypal_usd",
        "hash": "c28021...60d72f"
    }
    print(nicepay.is_hash_valid(config.NICEPAY_SECRET_KEY, data))


async def test_nicepay_create_invoice():
    from apis import nicepay
    print(await nicepay.create_invoice_async(config.NICEPAY_MERCHANT_ID, config.NICEPAY_SECRET_KEY, "order_id_1234", "test@example.com", 1500, "RUB", "Test invoice"))


async def main():
    test_nicepay_hash_validation()
    await test_nicepay_create_invoice()


if __name__ == '__main__':
    asyncio.run(main())