# PyInstaller 打包入口: 直接拉起 GUI, 跳过 CLI argparse。
import sys

from ctxbox.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
