import os
import subprocess
import sys

# 패키지 설치를 확인하고 필요한 경우 설치하는 함수
def install_and_import(package, package_name=None):
    if not package_name:
        package_name = package
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

# 필요한 패키지 목록
packages = [
    ("dotenv", "python-dotenv"),
    ("telegram", "python-telegram-bot"),
    ("korail2", "git+https://github.com/carpedm20/korail2"),
    ("SRT", "SRTrain")
]

# 패키지 설치 확인 및 설치
for module_name, package_name in packages:
    install_and_import(module_name, package_name)

# .env 파일 로드
from dotenv import load_dotenv

load_dotenv()

# 환경 변수를 불러오기
KORAIL_USER = os.getenv("KORAIL_USER")
KORAIL_PASS = os.getenv("KORAIL_PASS")
SRT_USER = os.getenv("SRT_USER")
SRT_PASS = os.getenv("SRT_PASS")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 환경 변수 확인
if not all([KORAIL_USER, KORAIL_PASS, SRT_USER, SRT_PASS, TELEGRAM_BOT_TOKEN]):
    raise ValueError("환경 변수가 제대로 설정되지 않았습니다. .env 파일을 확인하세요.")
