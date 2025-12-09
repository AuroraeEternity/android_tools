from flask import Flask
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许跨域请求，方便前端 Vue 访问


@app.route('/', methods=['GET'])
def index():
    return 'Hello World!'


if __name__ == '__main__':
    app.run(debug=True, port=5100)
