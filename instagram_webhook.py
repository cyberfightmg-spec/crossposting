from flask import Flask, request, jsonify
import os

app = Flask(__name__)
VERIFY_TOKEN = "mytoken123"

@app.route('/webhook', methods=['GET'])
def verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return challenge, 200
    return 'Forbidden', 403

@app.route('/webhook', methods=['POST'])
def handle_event():
    data = request.json
    print(data)
    return 'OK', 200

if __name__ == '__main__':
    app.run(port=5000)