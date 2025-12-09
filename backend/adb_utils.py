import subprocess
import datetime
import os
import time
import shutil
from pathlib import Path
from threading import Lock


class ADBUtils:
    BASE_DIR = Path(__file__).resolve().parent.parent
    UPLOAD_DIR = BASE_DIR / "uploads"
    CAPTURE_DIR = BASE_DIR / "captures"
    LOG_DIR = BASE_DIR / "logs"
    for _dir in (UPLOAD_DIR, CAPTURE_DIR, LOG_DIR):
        _dir.mkdir(parents=True, exist_ok=True)

    _screen_record_jobs = {}
    _screen_lock = Lock()
    _monkey_jobs = {}
    _monkey_lock = Lock()
    _original_resolution = {}
    _scrcpy_processes = {}
    _scrcpy_lock = Lock()
    _tcpdump_jobs = {}
    _tcpdump_lock = Lock()
    _network_profiles = {}

    @staticmethod
    def run_adb_command(command, device_id=None):
        """
        执行 ADB 命令的底层封装方法
        :param command: 命令参数列表，例如 ['shell', 'ls']
        :param device_id: 设备序列号，如果提供则添加 -s 参数
        :return: (stdout, stderr) 元组
        """
        cmd = ['adb']
        if device_id:
            cmd.extend(['-s', device_id])
        cmd.extend(command)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            return "", "ADB not found. Please make sure adb is in your PATH."

    @staticmethod
    def get_devices():
        """
        获取当前连接的设备列表 (状态为 device 的设备)
        :return: 设备 ID 列表
        """
        output, error = ADBUtils.run_adb_command(['devices'])
        if error and "ADB not found" in error:
            return []

        devices = []
        lines = output.split('\n')
        # 跳过第一行 "List of devices attached"
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) >= 2 and parts[1] == 'device':
                devices.append(parts[0])
        return devices

    @staticmethod
    def ensure_device_available(device_id):
        devices = ADBUtils.get_devices()
        if device_id not in devices:
            raise ValueError(f"设备 {device_id} 未连接或未授权")
        return True

    @staticmethod
    def package_exists(device_id, package_name):
        stdout, stderr = ADBUtils.run_adb_command(['shell', 'pm', 'path', package_name], device_id)
        if stderr:
            return False
        return stdout.strip().startswith('package:')

    @staticmethod
    def clear_and_restart_app(device_id, package_name, activity_name=None):
        """
        清理并重启应用
        流程: pm clear -> am force-stop -> am start (或 monkey 启动)
        """
        ADBUtils.ensure_device_available(device_id)
        if not ADBUtils.package_exists(device_id, package_name):
            raise ValueError(f"设备 {device_id} 上不存在包 {package_name}")

        stdout, stderr = ADBUtils.run_adb_command(['shell', 'pm', 'clear', package_name], device_id)
        if stderr or 'Failed' in stdout:
            raise RuntimeError(f"清理应用失败: {stderr or stdout}")

        stdout, stderr = ADBUtils.run_adb_command(['shell', 'am', 'force-stop', package_name], device_id)
        if stderr and 'Unknown package' in stderr:
            raise RuntimeError(f"强行停止失败: {stderr}")

        if activity_name:
            stdout, stderr = ADBUtils.run_adb_command(['shell', 'am', 'start', '-n', f"{package_name}/{activity_name}"], device_id)
            if stderr or 'Error' in stdout:
                raise RuntimeError(f"启动 Activity 失败: {stderr or stdout}")
        else:
            stdout, stderr = ADBUtils.run_adb_command(
                ['shell', 'monkey', '-p', package_name, '-c', 'android.intent.category.LAUNCHER', '1'], device_id)
            if 'No activities found' in stdout or stderr:
                raise RuntimeError(f"无法通过 monkey 启动应用: {stderr or stdout}")
        return True

    @staticmethod
    def set_time(device_id, timestamp_iso):
        """
        尝试修改设备系统时间
        :param timestamp_iso: ISO 格式的时间字符串 e.g. "2023-10-27T10:00:00"
        :return: (success, message)
        """
        try:
            dt = datetime.datetime.fromisoformat(timestamp_iso)
            # 格式化为 date 命令接受的格式: MMDDhhmmYYYY.ss
            date_str = dt.strftime("%m%d%H%M%Y.%S")

            # 检查是否具有 Root 权限
            out, _ = ADBUtils.run_adb_command(['shell', 'id'], device_id)
            if 'uid=0(root)' in out:
                # Root 设备直接修改时间
                ADBUtils.run_adb_command(['shell', 'date', date_str], device_id)
                return True, "Time set via root command"

            # 非 Root 设备无法直接修改系统时间，降级方案为打开设置页
            ADBUtils.open_date_settings(device_id)
            return False, "Device not rooted. Opened Date Settings."
        except Exception as e:
            return False, str(e)

    @staticmethod
    def open_date_settings(device_id):
        """打开系统的日期设置页面"""
        ADBUtils.run_adb_command(['shell', 'am', 'start', '-a', 'android.settings.DATE_SETTINGS'], device_id)

    @staticmethod
    def get_logs(device_id, grep=None, lines=2000):
        """
        获取设备日志
        :param grep: 过滤关键词 (不区分大小写)
        :param lines: 获取的行数
        """
        # 命令: adb logcat -d -v time -t <lines>
        # -d: dump log 并退出，不阻塞
        cmd = ['logcat', '-d', '-v', 'time', '-t', str(lines)]
        output, _ = ADBUtils.run_adb_command(cmd, device_id)

        if not output:
            return []

        log_lines = output.split('\n')

        # 在 Python 端进行简单的 grep 过滤
        filtered_lines =[]
        for line in log_lines:
            if not line.strip():
                continue

            if grep:
                if grep.lower() in line.lower():
                    filtered_lines.append(line)
            else:
                filtered_lines.append(line)

        return filtered_lines

    @staticmethod
    def stream_logcat(device_id, grep=None):
        """
        持续监听 logcat 输出，逐行 yield 以支持服务端推送
        """
        cmd = ['adb']
        if device_id:
            cmd.extend(['-s', device_id])
        cmd.extend(['logcat', '-v', 'time'])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        try:
            for line in process.stdout:
                if not line:
                    continue
                line = line.rstrip()
                if not line:
                    continue
                if grep and grep.lower() not in line.lower():
                    continue
                yield line
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()

    @staticmethod
    def stream_crash_events(device_id):
        """
        监听 logcat，捕获 FATAL EXCEPTION / ANR 事件，逐个 yield 事件字典
        """
        cmd = ['adb']
        if device_id:
            cmd.extend(['-s', device_id])
        cmd.extend(['logcat', '-v', 'time'])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            errors='replace'
        )

        def make_event(event_type, summary, lines):
            return {
                "type": event_type,
                "summary": summary,
                "lines": lines,
                "timestamp": datetime.datetime.utcnow().isoformat()
            }

        try:
            collecting = False
            event_type = None
            summary = ""
            buffer = []
            for line in process.stdout:
                if not line:
                    continue
                stripped = line.rstrip('\n')
                if 'FATAL EXCEPTION' in stripped:
                    collecting = True
                    event_type = 'CRASH'
                    summary = stripped
                    buffer = [stripped]
                    continue
                if 'ANR in' in stripped or 'Application Not Responding' in stripped:
                    collecting = True
                    event_type = 'ANR'
                    summary = stripped
                    buffer = [stripped]
                    continue
                if collecting:
                    buffer.append(stripped)
                    # 以空行或日志分割线作为事件结束
                    if not stripped or stripped.startswith('--------- beginning of'):
                        yield make_event(event_type, summary, buffer)
                        collecting = False
                        buffer = []
                        summary = ""
                        event_type = None
                # 防止一直收集
                if collecting and len(buffer) >= 120:
                    yield make_event(event_type, summary, buffer)
                    collecting = False
                    buffer = []
                    summary = ""
                    event_type = None
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()

    # ----------- 应用与包管理 -----------
    @staticmethod
    def get_foreground_app(device_id):
        output, _ = ADBUtils.run_adb_command(['shell', 'dumpsys', 'window', 'windows'], device_id)
        package = None
        activity = None
        for line in output.splitlines():
            if 'mCurrentFocus' in line or 'mFocusedApp' in line:
                parts = line.split()
                target = parts[-1]
                if '/' in target:
                    package, activity = target.split('/', 1)
                    activity = activity.rstrip('}')
                    break
        return package, activity

    @staticmethod
    def list_installed_packages(device_id):
        output, _ = ADBUtils.run_adb_command(['shell', 'pm', 'list', 'package'], device_id)
        apps = []
        for line in output.splitlines():
            if line.startswith('package:'):
                apps.append(line.split(':', 1)[1])
        return sorted(apps)

    @staticmethod
    def search_packages(device_id, keyword):
        keyword = (keyword or '').lower()
        if not keyword:
            return []
        return [pkg for pkg in ADBUtils.list_installed_packages(device_id) if keyword in pkg.lower()]

    @staticmethod
    def clear_app_data(device_id, package_name):
        ADBUtils.run_adb_command(['shell', 'pm', 'clear', package_name], device_id)
        ADBUtils.run_adb_command(['shell', 'am', 'force-stop', package_name], device_id)
        return True

    @staticmethod
    def install_apk(device_id, apk_path):
        stdout, stderr = ADBUtils.run_adb_command(['install', '-r', apk_path], device_id)
        return "Success" in stdout and (not stderr)

    @staticmethod
    def uninstall_app(device_id, package_name):
        stdout, stderr = ADBUtils.run_adb_command(['uninstall', package_name], device_id)
        return 'Success' in stdout and (not stderr)

    @staticmethod
    def open_url(device_id, url):
        ADBUtils.run_adb_command(['shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', url], device_id)
        return True

    @staticmethod
    def send_text(device_id, text):
        safe_text = text.replace(' ', '%s')
        ADBUtils.run_adb_command(['shell', 'input', 'text', safe_text], device_id)
        return True

    # ----------- scrcpy 控制 -----------
    @staticmethod
    def start_scrcpy(device_id, bit_rate=None, max_size=None, extra_args=None):
        """
        启动本机 scrcpy 进程，用于投屏到桌面客户端
        """
        if shutil.which('scrcpy') is None:
            raise FileNotFoundError("scrcpy 命令未找到，请确保已在本机安装 scrcpy")

        cmd = ['scrcpy']
        if device_id:
            cmd += ['-s', device_id]
        if bit_rate:
            cmd += ['--bit-rate', str(bit_rate)]
        if max_size:
            cmd += ['--max-size', str(max_size)]
        if extra_args:
            cmd += [str(arg) for arg in extra_args if arg]

        with ADBUtils._scrcpy_lock:
            proc = ADBUtils._scrcpy_processes.get(device_id)
            if proc and proc.poll() is None:
                return False, "scrcpy 已在运行"
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ADBUtils._scrcpy_processes[device_id] = process
        return True, "scrcpy 已启动"

    @staticmethod
    def stop_scrcpy(device_id):
        """
        停止指定设备对应的 scrcpy 进程
        """
        with ADBUtils._scrcpy_lock:
            proc = ADBUtils._scrcpy_processes.pop(device_id, None)
        if not proc:
            return False, "当前没有运行中的 scrcpy"
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        return True, "scrcpy 已关闭"

    @staticmethod
    def restart_scrcpy(device_id, bit_rate=None, max_size=None, extra_args=None):
        """
        重新启动 scrcpy：先停止再启动
        """
        ADBUtils.stop_scrcpy(device_id)
        time.sleep(0.3)
        return ADBUtils.start_scrcpy(device_id, bit_rate=bit_rate, max_size=max_size, extra_args=extra_args)

    # ----------- 网络抓包与弱网注入 -----------
    @staticmethod
    def start_tcpdump(device_id, interface='any'):
        filename = f"netcap_{device_id}_{int(time.time())}.pcap"
        remote_path = f"/sdcard/{filename}"
        cmd = ['adb']
        if device_id:
            cmd += ['-s', device_id]
        cmd += ['shell', 'tcpdump', '-i', interface, '-p', '-s', '0', '-w', remote_path]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise FileNotFoundError("tcpdump 不存在，请在设备上安装 tcpdump 后重试")
        with ADBUtils._tcpdump_lock:
            ADBUtils._tcpdump_jobs[device_id] = {
                "process": proc,
                "remote": remote_path,
                "filename": filename,
                "interface": interface
            }
        return remote_path

    @staticmethod
    def stop_tcpdump(device_id):
        with ADBUtils._tcpdump_lock:
            job = ADBUtils._tcpdump_jobs.pop(device_id, None)
        if not job:
            return None
        proc = job['process']
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        local_path = ADBUtils.LOG_DIR / job['filename']
        pull_cmd = ['adb']
        if device_id:
            pull_cmd += ['-s', device_id]
        pull_cmd += ['pull', job['remote'], str(local_path)]
        subprocess.run(pull_cmd, check=True)
        ADBUtils.run_adb_command(['shell', 'rm', job['remote']], device_id)
        return local_path

    @staticmethod
    def apply_network_profile(device_id, delay_ms=None, loss_percent=None, rate_kbps=None, interface='wlan0'):
        base_cmd = ['tc', 'qdisc', 'replace', 'dev', interface, 'root', 'netem']
        has_option = False
        if delay_ms:
            base_cmd += ['delay', f'{int(delay_ms)}ms']
            has_option = True
        if loss_percent:
            base_cmd += ['loss', f'{float(loss_percent)}%']
            has_option = True
        if rate_kbps:
            base_cmd += ['rate', f'{int(rate_kbps)}kbit']
            has_option = True
        if not has_option:
            raise ValueError("请至少填写一个弱网参数")
        shell_cmd = ' '.join(base_cmd)
        stdout, stderr = ADBUtils.run_adb_command(['shell', shell_cmd], device_id)
        if 'Permission denied' in stderr or 'not found' in stderr.lower():
            stdout, stderr = ADBUtils.run_adb_command(['shell', 'su', '-c', shell_cmd], device_id)
        if 'Permission denied' in stderr:
            raise PermissionError("应用弱网策略失败，可能需要 Root 权限或 tc 命令不存在")
        ADBUtils._network_profiles[device_id] = {
            "interface": interface,
            "delay_ms": delay_ms,
            "loss_percent": loss_percent,
            "rate_kbps": rate_kbps
        }
        return True

    @staticmethod
    def reset_network_profile(device_id, interface='wlan0'):
        cmd = f"tc qdisc del dev {interface} root"
        stdout, stderr = ADBUtils.run_adb_command(['shell', cmd], device_id)
        if 'Permission denied' in stderr or 'not found' in stderr.lower():
            stdout, stderr = ADBUtils.run_adb_command(['shell', 'su', '-c', cmd], device_id)
        ADBUtils._network_profiles.pop(device_id, None)
        return True

    # ----------- 媒体工具 -----------
    @staticmethod
    def capture_screenshot(device_id):
        filename = f"screenshot_{device_id}_{int(time.time())}.png"
        local_path = ADBUtils.CAPTURE_DIR / filename
        with open(local_path, 'wb') as fp:
            cmd = ['adb']
            if device_id:
                cmd += ['-s', device_id]
            cmd += ['exec-out', 'screencap', '-p']
            subprocess.run(cmd, check=True, stdout=fp)
        return local_path

    @staticmethod
    def start_screen_record(device_id, duration=180, size="1280x720"):
        filename = f"record_{device_id}_{int(time.time())}.mp4"
        remote_path = f"/sdcard/{filename}"
        cmd = ['adb']
        if device_id:
            cmd += ['-s', device_id]
        cmd += ['shell', 'screenrecord', '--time-limit', str(duration)]
        if size:
            cmd += ['--size', size]
        cmd += [remote_path]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with ADBUtils._screen_lock:
            ADBUtils._screen_record_jobs[device_id] = {
                'process': proc,
                'remote': remote_path,
                'filename': filename,
                'start': time.time()
            }
        return filename

    @staticmethod
    def stop_screen_record(device_id):
        with ADBUtils._screen_lock:
            job = ADBUtils._screen_record_jobs.pop(device_id, None)
        if not job:
            return None
        proc = job['process']
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        local_path = ADBUtils.CAPTURE_DIR / job['filename']
        pull_cmd = ['adb']
        if device_id:
            pull_cmd += ['-s', device_id]
        pull_cmd += ['pull', job['remote'], str(local_path)]
        subprocess.run(pull_cmd, check=True)
        ADBUtils.run_adb_command(['shell', 'rm', job['remote']], device_id)
        return local_path

    # ----------- Monkey 与日志 -----------
    @staticmethod
    def start_monkey(device_id, package_name, event_count=10000, throttle=300):
        cmd = [
            'adb'
        ]
        if device_id:
            cmd += ['-s', device_id]
        cmd += [
            'shell', 'monkey', '-p', package_name,
            '--throttle', str(throttle),
            '--pct-touch', '80',
            '--pct-motion', '20',
            '--pct-trackball', '0',
            '--pct-nav', '0',
            '--pct-syskeys', '0',
            '--pct-appswitch', '0',
            '--pct-flip', '0',
            '--pct-anyevent', '0',
            str(event_count)
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with ADBUtils._monkey_lock:
            ADBUtils._monkey_jobs[device_id] = proc
        return True

    @staticmethod
    def stop_monkey(device_id):
        with ADBUtils._monkey_lock:
            proc = ADBUtils._monkey_jobs.pop(device_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        # 兜底：直接杀死 monkey 进程
        ADBUtils.run_adb_command(['shell', 'pkill', '-f', 'monkey'], device_id)
        return True

    @staticmethod
    def export_logcat(device_id, destination, grep=None):
        output, _ = ADBUtils.run_adb_command(['shell', 'logcat', '-d', '-v', 'time'], device_id)
        if grep:
            filtered = [line for line in output.splitlines() if grep.lower() in line.lower()]
            destination.write_text('\n'.join(filtered))
        else:
            destination.write_text(output or "")
        return destination

    @staticmethod
    def export_js_log(device_id, destination):
        output, _ = ADBUtils.run_adb_command(['shell', 'logcat', '-d'], device_id)
        filtered = [line for line in output.splitlines() if 'js' in line.lower()]
        destination.write_text('\n'.join(filtered))
        return destination

    # ----------- 分辨率 -----------
    @staticmethod
    def get_current_resolution(device_id):
        output, _ = ADBUtils.run_adb_command(['shell', 'wm', 'size'], device_id)
        for line in output.splitlines():
            if 'Physical size:' in line:
                size = line.split(':')[-1].strip()
                if 'x' in size:
                    return size
        return None

    @staticmethod
    def change_resolution(device_id, resolution):
        if device_id not in ADBUtils._original_resolution:
            ADBUtils._original_resolution[device_id] = ADBUtils.get_current_resolution(device_id)
        ADBUtils.run_adb_command(['shell', 'wm', 'size', resolution], device_id)
        return True

    @staticmethod
    def restore_resolution(device_id):
        orig = ADBUtils._original_resolution.get(device_id)
        if orig:
            ADBUtils.run_adb_command(['shell', 'wm', 'size', orig], device_id)
        else:
            ADBUtils.run_adb_command(['shell', 'wm', 'size', 'reset'], device_id)
        return True

    # ----------- 性能指标 -----------
    @staticmethod
    def get_memory_usage(device_id, package_name):
        output, _ = ADBUtils.run_adb_command(['shell', 'dumpsys', 'meminfo', package_name], device_id)
        for line in output.splitlines():
            if line.strip().startswith('TOTAL'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        return round(int(parts[1]) / 1024, 2)
                    except ValueError:
                        return 0
        return 0

    @staticmethod
    def get_cpu_usage(device_id, package_name):
        cpu_count_output, _ = ADBUtils.run_adb_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
        cpu_count = cpu_count_output.lower().count('processor')
        top_output, _ = ADBUtils.run_adb_command(['shell', 'top', '-n', '1', '-d', '1', '-b'], device_id)
        for line in top_output.splitlines():
            if package_name in line:
                parts = line.split()
                try:
                    cpu_usage = float(parts[8])
                    return round(cpu_usage / max(cpu_count, 1), 2)
                except (ValueError, IndexError):
                    return 0
        return 0

    @staticmethod
    def get_frame_rate(device_id, package_name):
        output, _ = ADBUtils.run_adb_command(['shell', 'dumpsys', 'gfxinfo', package_name], device_id)
        total = None
        janky = None
        for line in output.splitlines():
            if 'Total frames rendered:' in line:
                total = int(line.split(':')[-1].strip())
            if 'Janky frames:' in line:
                janky = int(line.split(':')[-1].strip().split()[0])
        if total:
            if janky is None:
                janky = 0
            if total > 0:
                good = total - janky
                return round((good / total) * 60, 2)
        return 0

    @staticmethod
    def get_gfx_metrics(device_id, package_name):
        output, _ = ADBUtils.run_adb_command(['shell', 'dumpsys', 'gfxinfo', package_name], device_id)
        metrics = {
            "jank_percent": 0.0,
            "percentile_90": 0.0,
            "percentile_95": 0.0
        }
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith('Janky frames:') and '%' in line:
                try:
                    percent = line.split('(')[-1].split('%')[0]
                    metrics["jank_percent"] = float(percent)
                except (ValueError, IndexError):
                    continue
            if line.startswith('90th percentile:'):
                value = line.split(':')[-1].strip().replace('ms', '').strip()
                try:
                    metrics["percentile_90"] = float(value)
                except ValueError:
                    pass
            if line.startswith('95th percentile:'):
                value = line.split(':')[-1].strip().replace('ms', '').strip()
                try:
                    metrics["percentile_95"] = float(value)
                except ValueError:
                    pass
        return metrics
