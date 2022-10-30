from flask import render_template, request, jsonify, Flask, make_response
import json
import requests

app = Flask(__name__)


@app.route('/bridge', methods=["POST"])
def create_invoice():
    try:
        data = request.json
        res = requests.post(data.get("url"), json=data.get("data", {}))
        response = make_response(res.json())
        '''if res.json().get("status", "error") == "success":
            response.set_cookie("saved_user_token", data.get("user_token", ""))'''
        return response
    except Exception as ex:
        print(ex)
        return {"status": "error", "message": str(ex)}


@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html')


app.run("127.0.0.1", debug=True)
