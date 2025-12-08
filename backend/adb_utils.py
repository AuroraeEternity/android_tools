import subprocess
import time
from pathlib import Path


class ADBUtils:
    BASE_DIR = Path(__file__).resolve().parent.parent
    CAPTURE_DIR = BASE_DIR / "captures"

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
            # 考虑可以有多个 adb 连接的情况，返回列表
            if len(parts) >= 2 and parts[1] == 'device':
                devices.append(parts[0])
        return devices

    @staticmethod
    def send_text(device_id, text):
        """
        在输入框中输入指定文本
        :param device_id:
        :param text:
        :return:
        """
        # adb 将 %s 识别为空格，需要将输入文本中的空格替换为 %s
        safe_text = text.replace(' ', '%s')
        ADBUtils.run_adb_command(['shell', 'input', 'text', safe_text], device_id)
        return True

    @staticmethod
    def capture_screenshot(device_id):
        """
        截图并将图片传输到本地
        :param device_id:
        :return:
        """
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
    def package_exists(device_id, package_name):
        """
        检查对应包名是否存在
        :param package_name:
        :return:
        """
        # 获取标准输出结果和错误提示
        stdout, error = ADBUtils.run_adb_command(['shell', 'pm1', 'path', package_name], device_id)
        if error:
            return False
        return stdout.strip().startswith('package:')

    @staticmethod
    def ensure_device_available(device_id):
        """
        校验 device_id是否正确
        :param device_id:
        :return:
        """
        devices = ADBUtils.get_devices()
        # 查看 device_id是否在列表中
        if device_id not in devices:
            raise ValueError(f"设备 {device_id} 未连接或未授权")
        return True

    @staticmethod
    def clear_and_restart_app(device_id, package_name, activity_name=None):
        """
        清理并重启 app
        流程: pm clear -> am force-stop -> am start (或 monkey 启动)

        :param device_id:
        :param package_name:
        :param activity_name:
        :return:
        """
        # 1. 清除应用缓存和数据
        ADBUtils.ensure_device_available(device_id)
        if not ADBUtils.package_exists(device_id, package_name):
            raise ValueError(f"设备 {device_id} 上不存在包 {package_name}")

        stdout, stderr = ADBUtils.run_adb_command(['shell', 'pm', 'clear', package_name], device_id)
        if stderr or 'Failed' in stdout:
            raise RuntimeError(f"清理应用失败: {stderr or stdout}")
        # 2. 强制停止应用进程
        stdout, stderr = ADBUtils.run_adb_command(['shell', 'am', 'force-stop', package_name], device_id)
        if stderr and 'Unknown package' in stderr:
            raise RuntimeError(f"强行停止失败: {stderr}")  # 3. 启动应用
        if activity_name:
            stdout, stderr = ADBUtils.run_adb_command(['shell', 'am', 'start', '-n', f"{package_name}/{activity_name}"],
                                                      device_id)
            if stderr or 'Error' in stdout:
                raise RuntimeError(f"启动 Activity 失败: {stderr or stdout}")
        else:
            stdout, stderr = ADBUtils.run_adb_command(
                ['shell', 'monkey', '-p', package_name, '-c', 'android.intent.category.LAUNCHER', '1'], device_id)
            if 'No activities found' in stdout or stderr:
                raise RuntimeError(f"无法通过 monkey 启动应用: {stderr or stdout}")
        return True
