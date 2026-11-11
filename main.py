if __package__:
    from .ui import AcidizingApp
else:
    # PyCharm 直接运行 main.py 和 python -m acidizing.main 都能启动
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acidizing.ui import AcidizingApp


def run() -> None:
    # print("开始创建主窗口")
    app = AcidizingApp()
    app.mainloop()


if __name__ == "__main__":
    run()
