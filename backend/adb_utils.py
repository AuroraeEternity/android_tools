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


if __name__ == '__main__':
    ADBUtils.capture_screenshot("123123")
