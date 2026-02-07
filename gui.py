import tkinter as tk
from tkinter import scrolledtext, messagebox
import subprocess
import sys
import os
import threading
import queue
import pystray
from PIL import Image, ImageDraw
import socket

# 用于处理线程间通信的队列
log_queue = queue.Queue()


class TexTellerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TexTeller-OAIO 服务管理器")
        self.root.geometry("600x400")

        # 如果想实现“程序启动时直接最小化到托盘，不显示窗口”，可以解开下面这行的注释
        # self.root.withdraw()

        self.process = None
        self.is_running = False
        self.icon = None  # 托盘图标对象
        self.running_image = None  # 运行状态图标（绿色）
        self.stopped_image = None  # 停止状态图标（灰色）

        # 生成图标图片
        self.create_tray_images()

        # --- 界面布局 ---

        # 1. 顶部控制区
        control_frame = tk.Frame(root)
        control_frame.pack(pady=10, fill=tk.X)

        self.btn_start = tk.Button(control_frame, text="启动服务", command=self.start_service, bg="#ddffdd", width=15)
        self.btn_start.pack(side=tk.LEFT, padx=20)

        self.btn_stop = tk.Button(control_frame, text="停止服务", command=self.stop_service, bg="#ffdddd",
                                  state=tk.DISABLED, width=15)
        self.btn_stop.pack(side=tk.LEFT, padx=20)

        self.lbl_status = tk.Label(control_frame, text="状态: 未运行", fg="red", font=("Arial", 10, "bold"))
        self.lbl_status.pack(side=tk.RIGHT, padx=20)

        # 2. 中间日志显示区
        tk.Label(root, text="服务日志:").pack(anchor=tk.W, padx=10)
        self.log_area = scrolledtext.ScrolledText(root, width=70, height=15, state='disabled')
        self.log_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        # 3. 底部配置按钮
        bottom_frame = tk.Frame(root)
        bottom_frame.pack(pady=5, fill=tk.X)
        tk.Button(bottom_frame, text="打开配置文件 (config.ini)", command=self.open_config).pack(side=tk.LEFT, padx=10)

        # 4. 监听窗口关闭事件：改为隐藏到托盘
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # 5. 启动日志更新线程
        self.root.after(100, self.update_log_area)

        # 6. 设置系统托盘
        self.setup_tray()

    @staticmethod
    def get_local_ip():
        """获取本机局域网 IP 地址"""
        try:
            # 获取主机名
            hostname = socket.gethostname()
            # 通过主机名获取 IP
            local_ip = socket.gethostbyname(hostname)
            return local_ip
        except Exception:
            # 如果获取失败（如没联网），返回本地回环地址
            return "127.0.0.1"

    def create_tray_images(self):
        """生成简单的图标图片"""
        width = 64
        height = 64

        # 绿色图标（运行中）
        image1 = Image.new('RGB', (width, height), (0, 128, 0))
        dc1 = ImageDraw.Draw(image1)
        dc1.text((10, 10), "Run", fill="white")
        self.running_image = image1

        # 灰色图标（已停止）
        image2 = Image.new('RGB', (width, height), (128, 128, 128))
        dc2 = ImageDraw.Draw(image2)
        dc2.text((10, 10), "Stop", fill="white")
        self.stopped_image = image2

    def setup_tray(self):
        """初始化系统托盘图标"""
        # 定义菜单
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self.show_window),
            pystray.MenuItem("退出程序", self.quit_application)
        )

        # 创建图标 (初始状态为停止)
        self.icon = pystray.Icon("TexTeller-OAIO", self.stopped_image, "TexTeller-OAIO: 已停止", menu)

        # 在单独的线程中运行托盘，防止阻塞主界面
        threading.Thread(target=self.icon.run, daemon=True).start()

    def update_tray_status(self):
        """更新托盘图标的文字和图片"""
        if self.icon:
            if self.is_running:
                self.icon.icon = self.running_image
                self.icon.title = "TexTeller-OAIO: 运行中"
            else:
                self.icon.icon = self.stopped_image
                self.icon.title = "TexTeller-OAIO: 已停止"

    def show_window(self, icon=None, item=None):
        """从托盘恢复窗口显示"""
        self.root.deiconify()  # 显示窗口
        # self.root.lift()       # 提到最前 (可选)

    def hide_window(self):
        """隐藏窗口到托盘"""
        if self.is_running:
            # 如果服务正在跑，只隐藏窗口，不退出
            self.root.withdraw()
            # 可选：弹出气泡提示
            # self.icon.notify("程序已最小化到托盘", "TexTeller-OAIO")
        else:
            # 如果服务没跑，直接退出
            self.quit_application()

    def quit_application(self, icon=None, item=None):
        """完全退出程序"""
        if self.is_running:
            self.stop_service()

        # 停止托盘图标
        if self.icon:
            self.icon.stop()

        # 销毁窗口
        self.root.destroy()
        # 强制退出进程（确保托盘线程结束）
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

        if not os.path.exists("config.ini"):
            messagebox.showerror("错误", "找不到 config.ini 文件！")
            return

        self.append_log("正在启动服务...")

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host", "0.0.0.0",
            "--port", "8000"
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

            # 更新托盘图标
            self.update_tray_status()

            threading.Thread(target=self.read_output, daemon=True).start()

            # --- 【新增】获取并打印 API 地址 ---
            local_ip = self.get_local_ip()
            self.append_log("-" * 40)
            self.append_log("服务启动成功！")
            self.append_log(f"请在 WriteTex 中配置以下地址：")
            self.append_log(f"Base URL: http://{local_ip}:8000")
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

        # 更新托盘图标
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