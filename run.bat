@echo off

REM 检查是否有 "-" 参数，如果有则跳转到启动部分
if "%1"=="-" goto :START_HIDDEN

REM ========================================
REM 第一部分：用户双击运行这里
REM ========================================

REM 使用 PowerShell 以隐藏窗口模式重新运行当前的 bat 文件
REM %~f0 代表当前批处理文件的完整路径
REM Start-Process 是 PowerShell 的启动进程命令
REM -WindowStyle Hidden 表示隐藏窗口
PowerShell -WindowStyle Hidden -Command "Start-Process cmd -ArgumentList '/c \"%~f0 -\"' -WindowStyle Hidden"

REM 退出第一个（可见的）窗口，让它在后台运行
exit

REM ========================================
REM 第二部分：后台隐藏运行的部分
REM ========================================
:START_HIDDEN

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 激活 conda 环境
call C:\software\miniconda3\Scripts\activate.bat texteller

REM 启动 GUI
python gui.py