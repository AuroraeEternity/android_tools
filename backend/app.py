import os
import json
from collections import defaultdict, deque
from pathlib import Path
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

from adb_utils import ADBUtils
from database import init_db, get_packages, add_or_update_package, get_event_expectations, replace_event_expectations

app = Flask(__name__)
CORS(app)  # 允许跨域请求，方便前端 Vue 访问

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
CAPTURE_DIR = BASE_DIR / "captures"
LOG_DIR = BASE_DIR / "logs"
for directory in (UPLOAD_DIR, CAPTURE_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

PERF_SESSIONS = {}
MEDIA_EXTENSIONS = {
    "screenshots": {".png", ".jpg", ".jpeg"},
    "recordings": {".mp4", ".mov", ".mkv"}
}
CRASH_HISTORY = defaultdict(lambda: deque(maxlen=50))


def _require_device(param_source):
    device_id = param_source.get('device_id')
    if not device_id:
        raise ValueError("Missing device_id")
    return device_id


def _file_url(path: Path):
    relative = path.relative_to(BASE_DIR)
    return f"/api/files?path={relative.as_posix()}"


# 初始化数据库表结构
init_db()


@app.route('/api/devices', methods=['GET'])
def list_devices():
    try:
        devices = ADBUtils.get_devices()
        return jsonify({"devices": devices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/foreground', methods=['GET'])
def get_foreground():
    try:
        device_id = _require_device(request.args)
        package, activity = ADBUtils.get_foreground_app(device_id)
        return jsonify({"package": package, "activity": activity})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apps', methods=['GET'])
def get_apps():
    try:
        device_id = _require_device(request.args)
        apps = ADBUtils.list_installed_packages(device_id)
        return jsonify({"apps": apps})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apps/search', methods=['GET'])
def search_apps():
    try:
        device_id = _require_device(request.args)
        query = request.args.get('query', '')
        matches = ADBUtils.search_packages(device_id, query)
        return jsonify({"matches": matches})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/restart_app', methods=['POST'])
def restart_app():
    data = request.json
    device_id = data.get('device_id')
    package_name = data.get('package_name')
    activity_name = data.get('activity_name')
    if not device_id or not package_name:
        return jsonify({"error": "Missing device_id or package_name"}), 400

    try:
        ADBUtils.ensure_device_available(device_id)
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    if not ADBUtils.package_exists(device_id, package_name):
        return jsonify({"error": f"包 {package_name} 不存在或未安装在设备 {device_id} 上"}), 400

    try:
        add_or_update_package(package_name, activity_name)
    except Exception as e:
        app.logger.warning("保存包名失败: %s", e)

    try:
        success = ADBUtils.clear_and_restart_app(device_id, package_name, activity_name)
        return jsonify({"success": success})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/app/clear', methods=['POST'])
def clear_app():
    data = request.json
    device_id = data.get('device_id')
    package_name = data.get('package_name')
    if not device_id or not package_name:
        return jsonify({"error": "Missing device_id or package_name"}), 400
    try:
        ADBUtils.clear_app_data(device_id, package_name)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/app/uninstall', methods=['POST'])
def uninstall_app():
    data = request.json
    device_id = data.get('device_id')
    package_name = data.get('package_name')
    if not device_id or not package_name:
        return jsonify({"error": "Missing device_id or package_name"}), 400
    try:
        success = ADBUtils.uninstall_app(device_id, package_name)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apk/install', methods=['POST'])
def install_apk():
    device_id = request.form.get('device_id')
    file = request.files.get('file')
    if not device_id or not file:
        return jsonify({"error": "Missing device_id or file"}), 400
    filename = secure_filename(file.filename or "app.apk")
    local_path = UPLOAD_DIR / filename
    file.save(local_path)
    try:
        success = ADBUtils.install_apk(device_id, str(local_path))
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if local_path.exists():
            local_path.unlink()


@app.route('/api/url/open', methods=['POST'])
def open_url():
    data = request.json
    device_id = data.get('device_id')
    url = data.get('url')
    if not device_id or not url:
        return jsonify({"error": "Missing parameters"}), 400
    try:
        ADBUtils.open_url(device_id, url)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/text/send', methods=['POST'])
def send_text():
    data = request.json
    device_id = data.get('device_id')
    text = data.get('text', '')
    if not device_id or text is None:
        return jsonify({"error": "Missing parameters"}), 400
    try:
        ADBUtils.send_text(device_id, text)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/set_time', methods=['POST'])
def set_time():
    data = request.json
    device_id = data.get('device_id')
    timestamp = data.get('timestamp')
    if not device_id or not timestamp:
        return jsonify({"error": "Missing parameters"}), 400
    success, message = ADBUtils.set_time(device_id, timestamp)
    return jsonify({"success": success, "message": message})


@app.route('/api/screenshot', methods=['GET'])
def screenshot():
    try:
        device_id = _require_device(request.args)
        path = ADBUtils.capture_screenshot(device_id)
        return jsonify({"path": str(path), "url": _file_url(path)})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/record/start', methods=['POST'])
def start_record():
    data = request.json
    device_id = data.get('device_id')
    duration = data.get('duration', 180)
    size = data.get('size', "1280x720")
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        filename = ADBUtils.start_screen_record(device_id, duration=duration, size=size)
        return jsonify({"job_id": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/record/stop', methods=['POST'])
def stop_record():
    data = request.json
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        path = ADBUtils.stop_screen_record(device_id)
        if not path:
            return jsonify({"error": "No recording in progress"}), 400
        return jsonify({"path": str(path), "url": _file_url(path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/monkey/start', methods=['POST'])
def start_monkey():
    data = request.json
    device_id = data.get('device_id')
    package_name = data.get('package_name')
    event_count = data.get('event_count', 10000)
    throttle = data.get('throttle', 300)
    if not device_id or not package_name:
        return jsonify({"error": "Missing parameters"}), 400
    try:
        ADBUtils.start_monkey(device_id, package_name, event_count=event_count, throttle=throttle)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/monkey/stop', methods=['POST'])
def stop_monkey():
    data = request.json
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        ADBUtils.stop_monkey(device_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    device_id = request.args.get('device_id')
    grep = request.args.get('grep')
    lines = request.args.get('lines', default=2000, type=int)
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        logs = ADBUtils.get_logs(device_id, grep, lines)
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/logs/stream', methods=['GET'])
def stream_logs():
    device_id = request.args.get('device_id')
    grep = request.args.get('grep')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400

    def event_stream():
        for line in ADBUtils.stream_logcat(device_id, grep):
            yield f"data: {line}\n\n"

    response = Response(stream_with_context(event_stream()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@app.route('/api/logs/export', methods=['GET'])
def export_logs():
    device_id = request.args.get('device_id')
    grep = request.args.get('grep')
    lines = request.args.get('lines', default=2000, type=int)
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        logs = ADBUtils.get_logs(device_id, grep, lines)
        payload = '\n'.join(logs)
        filename = f"logcat-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.txt"
        response = Response(payload, mimetype='text/plain')
        response.headers['Content-Disposition'] = f'attachment; filename=\"{filename}\"'
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/logs/js', methods=['GET'])
def export_js_logs():
    try:
        device_id = _require_device(request.args)
        filename = f"jslog-{device_id}-{int(datetime.utcnow().timestamp())}.txt"
        destination = LOG_DIR / filename
        ADBUtils.export_js_log(device_id, destination)
        return jsonify({"path": str(destination), "url": _file_url(destination)})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/events/crash/history', methods=['GET'])
def crash_history():
    try:
        device_id = _require_device(request.args)
        history = list(CRASH_HISTORY.get(device_id, []))
        return jsonify({"events": history})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400


@app.route('/api/events/crash/stream', methods=['GET'])
def crash_stream():
    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400

    def event_stream():
        for event in ADBUtils.stream_crash_events(device_id):
            record = {
                "device_id": device_id,
                **event
            }
            CRASH_HISTORY[device_id].append(record)
            yield f"data: {json.dumps(record)}\n\n"

    response = Response(stream_with_context(event_stream()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@app.route('/api/packages', methods=['GET'])
def list_packages():
    try:
        pkgs = get_packages()
        return jsonify({"packages": pkgs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/script/run', methods=['POST'])
def run_script():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "Missing file"}), 400
    filename = secure_filename(file.filename or 'script.py')
    local_path = UPLOAD_DIR / filename
    file.save(local_path)
    try:
        result = subprocess.run(['python3', str(local_path)], capture_output=True, text=True)
        return jsonify({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        })
    finally:
        if local_path.exists():
            local_path.unlink()


@app.route('/api/resolution/list', methods=['GET'])
def list_resolutions():
    PRESETS = [
        "1080x1920", "1080x2400", "1440x3200", "720x1280", "800x1280",
        "640x1136", "768x1024", "540x960", "480x854", "2160x3840"
    ]
    device_id = request.args.get('device_id')
    current = None
    if device_id:
        current = ADBUtils.get_current_resolution(device_id)
    return jsonify({"presets": PRESETS, "current": current})


@app.route('/api/resolution/change', methods=['POST'])
def change_resolution():
    data = request.json
    device_id = data.get('device_id')
    resolution = data.get('resolution')
    if not device_id or not resolution:
        return jsonify({"error": "Missing parameters"}), 400
    try:
        ADBUtils.change_resolution(device_id, resolution)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/resolution/restore', methods=['POST'])
def restore_resolution():
    data = request.json
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        ADBUtils.restore_resolution(device_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/perf/start', methods=['POST'])
def perf_start():
    data = request.json
    device_id = data.get('device_id')
    package_name = data.get('package_name')
    if not device_id or not package_name:
        return jsonify({"error": "Missing parameters"}), 400
    PERF_SESSIONS[device_id] = {"package": package_name}
    return jsonify({"success": True})


@app.route('/api/perf/stop', methods=['POST'])
def perf_stop():
    data = request.json
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    PERF_SESSIONS.pop(device_id, None)
    return jsonify({"success": True})


@app.route('/api/perf/data', methods=['GET'])
def perf_data():
    device_id = request.args.get('device_id')
    package_name = request.args.get('package_name')
    if not device_id or not package_name:
        return jsonify({"error": "Missing parameters"}), 400
    data = {
        "memory": ADBUtils.get_memory_usage(device_id, package_name),
        "cpu": ADBUtils.get_cpu_usage(device_id, package_name),
        "fps": ADBUtils.get_frame_rate(device_id, package_name),
        "gpu": ADBUtils.get_gfx_metrics(device_id, package_name)
    }
    return jsonify(data)


@app.route('/api/files', methods=['GET'])
def serve_files():
    path_param = request.args.get('path')
    if not path_param:
        return jsonify({"error": "Missing path"}), 400
    full_path = (BASE_DIR / path_param).resolve()
    if not str(full_path).startswith(str(BASE_DIR)):
        return jsonify({"error": "Invalid path"}), 400
    if not full_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(full_path, as_attachment=True)


@app.route('/api/media/list', methods=['GET'])
def list_media():
    screenshots = []
    recordings = []
    for path in sorted(CAPTURE_DIR.glob('*')):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        item = {
            "name": path.name,
            "url": f"http://127.0.0.1:5000{_file_url(path)}",
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        }
        if suffix in MEDIA_EXTENSIONS['screenshots']:
            screenshots.append(item)
        elif suffix in MEDIA_EXTENSIONS['recordings']:
            recordings.append(item)
    return jsonify({"screenshots": screenshots, "recordings": recordings})


@app.route('/api/media/delete', methods=['POST'])
def delete_media():
    data = request.json or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "Missing file name"}), 400
    target = (CAPTURE_DIR / name).resolve()
    if not str(target).startswith(str(CAPTURE_DIR)) or not target.exists():
        return jsonify({"error": "File not found"}), 404
    target.unlink()
    return jsonify({"success": True})


@app.route('/api/network/capture/start', methods=['POST'])
def start_network_capture():
    data = request.json or {}
    device_id = data.get('device_id')
    interface = data.get('interface', 'any')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        remote_path = ADBUtils.start_tcpdump(device_id, interface=interface)
        return jsonify({"success": True, "remote_path": remote_path})
    except FileNotFoundError as fnf:
        return jsonify({"error": str(fnf)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/network/capture/stop', methods=['POST'])
def stop_network_capture():
    data = request.json or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        path = ADBUtils.stop_tcpdump(device_id)
        if not path:
            return jsonify({"error": "No active capture"}), 400
        return jsonify({"success": True, "path": str(path), "url": f"http://127.0.0.1:5000{_file_url(path)}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/network/profile/apply', methods=['POST'])
def apply_network_profile():
    data = request.json or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    delay_ms = data.get('delay_ms')
    loss_percent = data.get('loss_percent')
    rate_kbps = data.get('rate_kbps')
    interface = data.get('interface', 'wlan0')
    try:
        ADBUtils.apply_network_profile(device_id, delay_ms=delay_ms, loss_percent=loss_percent, rate_kbps=rate_kbps, interface=interface)
        return jsonify({"success": True})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/network/profile/reset', methods=['POST'])
def reset_network_profile():
    data = request.json or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    interface = data.get('interface', 'wlan0')
    try:
        ADBUtils.reset_network_profile(device_id, interface=interface)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/events/expectations', methods=['GET'])
def list_event_expectations():
    rules = get_event_expectations()
    return jsonify({"rules": rules})


@app.route('/api/events/expectations', methods=['POST'])
def save_event_expectations():
    data = request.json or {}
    rules = data.get('rules', [])
    try:
        replace_event_expectations(rules)
        return jsonify({"success": True, "count": len(rules)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/events/expectations/validate', methods=['POST'])
def validate_event_expectations():
    data = request.json or {}
    device_id = data.get('device_id')
    try:
        lines = int(data.get('lines', 4000))
    except (TypeError, ValueError):
        lines = 4000
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    rules = get_event_expectations()
    log_lines = ADBUtils.get_logs(device_id, lines=lines)
    log_text = '\n'.join(log_lines)
    log_text_lower = log_text.lower()

    def find_line(keyword, exact=True):
        lowered = keyword.lower()
        for line in log_lines:
            hay = line if exact else line.lower()
            target = keyword if exact else lowered
            if target in hay:
                return line.strip()
        return None

    results = []
    for rule in rules:
        keyword = rule.get('keyword')
        if not keyword:
            continue
        if rule.get('exact_match', True):
            count = log_text.count(keyword)
            sample = find_line(keyword, exact=True)
        else:
            count = log_text_lower.count(keyword.lower())
            sample = find_line(keyword, exact=False)
        results.append({
            "id": rule.get('id'),
            "keyword": keyword,
            "description": rule.get('description'),
            "exact_match": rule.get('exact_match', True),
            "count": count,
            "passed": count > 0,
            "sample": sample
        })
    return jsonify({"results": results, "total": len(results)})


@app.route('/api/scrcpy/start', methods=['POST'])
def scrcpy_start():
    data = request.json or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    bit_rate = data.get('bit_rate')
    max_size = data.get('max_size')
    extra_args = data.get('extra_args') or []
    try:
        success, message = ADBUtils.start_scrcpy(
            device_id,
            bit_rate=bit_rate,
            max_size=max_size,
            extra_args=extra_args
        )
        return jsonify({"success": success, "message": message})
    except FileNotFoundError as fnf:
        return jsonify({"error": str(fnf)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/scrcpy/stop', methods=['POST'])
def scrcpy_stop():
    data = request.json or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    try:
        success, message = ADBUtils.stop_scrcpy(device_id)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/scrcpy/restart', methods=['POST'])
def scrcpy_restart():
    data = request.json or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400
    bit_rate = data.get('bit_rate')
    max_size = data.get('max_size')
    extra_args = data.get('extra_args') or []
    try:
        success, message = ADBUtils.restart_scrcpy(
            device_id,
            bit_rate=bit_rate,
            max_size=max_size,
            extra_args=extra_args
        )
        return jsonify({"success": success, "message": message})
    except FileNotFoundError as fnf:
        return jsonify({"error": str(fnf)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
