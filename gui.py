import tkinter as tk
from tkinter import scrolledtext, messagebox
import subprocess
import sys
import os
import threading
import queue
import pystray
import configparser  # 【新增】导入配置解析库
from PIL import Image, ImageDraw
import socket  # 用于获取IP
import uuid

# 用于处理线程间通信的队列
log_queue = queue.Queue()


class TexTellerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TexTeller-OAIO 服务管理器")
        self.root.geometry("600x400")

        self.process = None
        self.is_running = False
        self.icon = None
        self.running_image = None
        self.stopped_image = None

        # 【新增】启动时检查配置文件，没有则自动创建
        self.check_config_file()

        # 生成图标图片
        self.create_tray_images()

        # --- 界面布局 ---
        control_frame = tk.Frame(root)
        control_frame.pack(pady=10, fill=tk.X)

        self.btn_start = tk.Button(control_frame, text="启动服务", command=self.start_service, bg="#ddffdd", width=15)
        self.btn_start.pack(side=tk.LEFT, padx=20)

        self.btn_stop = tk.Button(control_frame, text="停止服务", command=self.stop_service, bg="#ffdddd",
                                  state=tk.DISABLED, width=15)
        self.btn_stop.pack(side=tk.LEFT, padx=20)

        self.lbl_status = tk.Label(control_frame, text="状态: 未运行", fg="red", font=("Arial", 10, "bold"))
        self.lbl_status.pack(side=tk.RIGHT, padx=20)

        tk.Label(root, text="服务日志:").pack(anchor=tk.W, padx=10)
        self.log_area = scrolledtext.ScrolledText(root, width=70, height=15, state='disabled')
        self.log_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        bottom_frame = tk.Frame(root)
        bottom_frame.pack(pady=5, fill=tk.X)
        tk.Button(bottom_frame, text="打开配置文件 (config.ini)", command=self.open_config).pack(side=tk.LEFT, padx=10)

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.after(100, self.update_log_area)
        self.setup_tray()

    def check_config_file(self):
        """检查并创建默认配置文件"""
        if not os.path.exists("config.ini"):
            # 【新增】生成随机的 API Key (格式模仿 OpenAI: sk-...)
            random_key = f"sk-{uuid.uuid4().hex}"

            # 使用你提供的新模板内容
            default_content = f"""[server]
# 服务绑定的地址和端口
host = 0.0.0.0
port = 8000

[auth]
# API Key，你可以随便改，但必须和 WriteTex 里设置的一致
api_key = {random_key}

[model]
# 模型配置：是否使用 ONNX Runtime (True) 或 PyTorch (False)
use_onnx = True
"""
            try:
                with open("config.ini", "w", encoding='utf-8') as f:
                    f.write(default_content)
                # 打印日志，方便用户看到生成的 Key
                self.append_log(f"已自动生成配置文件。")
                self.append_log(f"随机 API Key: {random_key}")
                self.append_log("请记下此 Key 用于 WriteTex 配置。")
            except Exception as e:
                print(f"生成配置文件失败: {e}")

    def get_config_port(self):
        """【新增】从配置文件读取端口"""
        try:
            config = configparser.ConfigParser()
            config.read('config.ini', encoding='utf-8')
            return config.get('server', 'port')
        except:
            return "8000"

    def get_local_ip(self):
        """获取本机局域网 IP 地址"""
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            return local_ip
        except Exception:
            return "127.0.0.1"

    def create_tray_images(self):
        width = 64
        height = 64
        image1 = Image.new('RGB', (width, height), (0, 128, 0))
        dc1 = ImageDraw.Draw(image1)
        dc1.text((10, 10), "Run", fill="white")
        self.running_image = image1

        image2 = Image.new('RGB', (width, height), (128, 128, 128))
        dc2 = ImageDraw.Draw(image2)
        dc2.text((10, 10), "Stop", fill="white")
        self.stopped_image = image2

    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self.show_window),
            pystray.MenuItem("退出程序", self.quit_application)
        )
        self.icon = pystray.Icon("TexTeller-OAIO", self.stopped_image, "TexTeller-OAIO: 已停止", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def update_tray_status(self):
        if self.icon:
            if self.is_running:
                self.icon.icon = self.running_image
                self.icon.title = "TexTeller-OAIO: 运行中"
            else:
                self.icon.icon = self.stopped_image
                self.icon.title = "TexTeller-OAIO: 已停止"

    def show_window(self, icon=None, item=None):
        self.root.deiconify()

    def hide_window(self):
        if self.is_running:
            self.root.withdraw()
        else:
            self.quit_application()

    def quit_application(self, icon=None, item=None):
        if self.is_running:
            self.stop_service()
        if self.icon:
            self.icon.stop()
        self.root.destroy()
        os._exit(0)

    def append_log(self, message):
        log_queue.put(message)

    def update_log_area(self):
        try:
            while True:
                msg = log_queue.get_nowait()
                self.log_area.config(state='normal')
                self.log_area.insert(tk.END, msg + '\n')
                self.log_area.see(tk.END)
                self.log_area.config(state='disabled')
        except queue.Empty:
            pass
        self.root.after(100, self.update_log_area)

    def start_service(self):
        if self.is_running:
            return

        # 检查配置文件是否存在（再次确认）
        if not os.path.exists("config.ini"):
            messagebox.showerror("错误", "找不到 config.ini 文件，无法启动！")
            return

        self.append_log("正在启动服务...")

        # 【修改】动态获取端口
        port = self.get_config_port()

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host", "0.0.0.0",
            "--port", port  # 使用读取到的端口
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace'
            )

            self.is_running = True
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.lbl_status.config(text="状态: 运行中", fg="green")

            self.update_tray_status()
            threading.Thread(target=self.read_output, daemon=True).start()

            # 【修改】打印动态地址
            local_ip = self.get_local_ip()
            self.append_log("-" * 40)
            self.append_log("服务启动成功！")
            self.append_log(f"请在 WriteTex 中配置以下地址：")
            self.append_log(f"Base URL: http://{local_ip}:{port}/v1")
            self.append_log("-" * 40)

        except Exception as e:
            self.append_log(f"启动失败: {e}")

    def read_output(self):
        try:
            for line in self.process.stdout:
                self.append_log(line.strip())
        except Exception as e:
            self.append_log(f"读取日志出错: {e}")
        finally:
            if self.is_running:
                self.stop_service()

    def stop_service(self):
        if not self.is_running or not self.process:
            return

        self.append_log("正在停止服务...")

        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        except Exception as e:
            self.append_log(f"停止服务时出错: {e}")

        self.is_running = False
        self.process = None
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.lbl_status.config(text="状态: 未运行", fg="red")

        self.update_tray_status()
        self.append_log("服务已停止。")

    def open_config(self):
        try:
            if os.path.exists("config.ini"):
                os.system("notepad.exe config.ini")
            else:
                messagebox.showwarning("提示", "config.ini 文件不存在")
        except Exception as e:
            messagebox.showerror("错误", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = TexTellerGUI(root)
    root.mainloop()