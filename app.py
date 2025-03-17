from flask import Flask, request, jsonify
import pandas as pd

app = Flask(__name__)

@app.route('/add', methods=['POST'])
def add():
    data = request.get_json()
    a = data.get('a')
    b = data.get('b')
    result = a + b
    return jsonify({'result': result})

if __name__ == '__main__':
    app.run(debug=True)
