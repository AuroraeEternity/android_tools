from flask import Flask, jsonify, request

from backend.adb_utils import ADBUtils
from pathlib import Path

app = Flask(__name__)  # 实例化应用

BASE_DIR = Path(__file__).resolve().parent.parent


def _require_device(param_source):
    device_id = param_source.get('device_id')
    if not device_id:
        raise ValueError('Missing device_id')
    return device_id


def _file_url(path: Path):
    relative = path.relative_to(BASE_DIR)
    return f"/api/files?path={relative.as_posix()}"


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


@app.route('/api/screenshot', methods=['GET'])
def screenshot():
    # 对当前屏幕进行截图操作
    try:
        device_id = _require_device(request.args)
        path = ADBUtils.capture_screenshot(device_id)
        return jsonify({"path": str(path), "url": _file_url(path)})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # 运行，可调试、指定端口号
    app.run(debug=True, port=5100)
