from flask import Flask, jsonify, request

from backend.adb_utils import ADBUtils

app = Flask(__name__)  # 实例化应用


@app.route('/api/devices', methods=['GET'])
def list_devices():
    try:
        devices = ADBUtils.get_devices()
        return jsonify({'devices': devices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/text/send', methods=['POST'])
def send_text():
    # 获取请求 json 数据
    data = request.json
    device_id = data.get('device_id')
    text = data.get('text', '')
    # 判断传入数据是否正确，需要 device_id 和 text
    if not device_id or text is None:
        return jsonify({"error": "Missing parameters"}), 400
    try:
        ADBUtils.send_text(device_id, text)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # 运行，可调试、指定端口号
    app.run(debug=True, port=5100)
