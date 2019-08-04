import subprocess
# Constants
XBt_TO_XBT = 100000000  # 单位转换1BTC=100 000 000聪
VERSION = 'v1.1'
try:
    VERSION = str(subprocess.check_output(["git", "describe", "--tags"], stderr=subprocess.DEVNULL).rstrip())
except Exception as e:
    # git not available, ignore
    pass
