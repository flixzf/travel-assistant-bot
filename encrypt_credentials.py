#!/usr/bin/env python3
"""
크리덴셜 암호화 유틸리티

사용법:
1. 환경변수 암호화: python encrypt_credentials.py --env
2. 파일 암호화: python encrypt_credentials.py --file

이 스크립트는 민감한 정보(비밀번호, API 토큰 등)를 안전하게 암호화합니다.
"""

import sys
import os
import getpass
from crypto_utils import SecureConfig

def get_credentials_from_user():
    """사용자로부터 크리덴셜 입력 받기"""
    credentials = {}

    print("=== 크리덴셜 입력 ===")
    print("(필요하지 않은 항목은 엔터를 눌러 건너뛰세요)\n")

    # 텔레그램 봇 토큰
    token = getpass.getpass("Telegram Bot Token: ").strip()
    if token:
        credentials['TELEGRAM_BOT_TOKEN'] = token

    # 코레일 계정
    korail_user = input("코레일 회원번호/휴대폰번호: ").strip()
    if korail_user:
        credentials['KORAIL_USER'] = korail_user

    korail_pass = getpass.getpass("코레일 비밀번호: ").strip()
    if korail_pass:
        credentials['KORAIL_PASS'] = korail_pass

    korail_pass_bank = getpass.getpass("카드 비밀번호 6자리: ").strip()
    if korail_pass_bank:
        credentials['KORAIL_PASS_BANK'] = korail_pass_bank

    # 카드 정보
    print("\n=== 카드 정보 ===")
    card_num1 = input("카드번호 첫 번째 4자리: ").strip()
    if card_num1:
        credentials['Card_Num1_korail'] = card_num1

    card_num2 = input("카드번호 두 번째 4자리: ").strip()
    if card_num2:
        credentials['Card_Num2_korail'] = card_num2

    card_num3 = input("카드번호 세 번째 4자리: ").strip()
    if card_num3:
        credentials['Card_Num3_korail'] = card_num3

    card_num4 = input("카드번호 네 번째 4자리: ").strip()
    if card_num4:
        credentials['Card_Num4_korail'] = card_num4

    card_num5 = getpass.getpass("카드 비밀번호 앞 2자리: ").strip()
    if card_num5:
        credentials['Card_Num5_korail'] = card_num5

    card_month = input("카드 유효월 (MM): ").strip()
    if card_month:
        credentials['CARD_MONTH'] = card_month

    # 개인정보
    id_num = getpass.getpass("주민번호 앞 6자리: ").strip()
    if id_num:
        credentials['Id_Num1_korail'] = id_num

    # SRT 계정
    print("\n=== SRT 계정 ===")
    srt_id = input("SRT 아이디: ").strip()
    if srt_id:
        credentials['SRT_ID'] = srt_id

    srt_pwd = getpass.getpass("SRT 비밀번호: ").strip()
    if srt_pwd:
        credentials['SRT_PWD'] = srt_pwd

    return credentials

def encrypt_for_env_vars(credentials, master_password):
    """환경변수용 암호화된 값들 생성"""
    config = SecureConfig(master_password)

    print("\n" + "="*60)
    print("환경변수에 설정할 암호화된 값들:")
    print("="*60)
    print("# 마스터 패스워드도 함께 설정하세요")
    print(f"MASTER_PASSWORD={master_password}")
    print("USE_ENCRYPTED_ENV=true")
    print()

    for key, value in credentials.items():
        encrypted_value = config.encrypt(value)
        print(f"{key}_ENC={encrypted_value}")

    print("\n" + "="*60)
    print("⚠️  중요 사항:")
    print("1. 위의 환경변수들을 서버에 설정하세요")
    print("2. 마스터 패스워드는 별도 보관하세요")
    print("3. 원본 비밀번호는 삭제하세요")
    print("="*60)

def encrypt_for_file(credentials, master_password):
    """파일용 암호화"""
    from secure_config import config_manager

    config_manager.secure_config = SecureConfig(master_password)
    config_manager.create_encrypted_file(credentials, 'credentials.enc')

    print("\n" + "="*60)
    print("암호화 파일 생성 완료!")
    print("="*60)
    print("1. credentials.enc 파일이 생성되었습니다")
    print("2. .gitignore에 추가하여 Git에 업로드되지 않도록 하세요")
    print("3. 마스터 패스워드를 환경변수 MASTER_PASSWORD에 설정하세요")
    print(f"   export MASTER_PASSWORD='{master_password}'")
    print("="*60)

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ['--env', '--file']:
        print("사용법:")
        print("  python encrypt_credentials.py --env   # 환경변수용 암호화")
        print("  python encrypt_credentials.py --file  # 파일용 암호화")
        sys.exit(1)

    mode = sys.argv[1]

    print("🔐 크리덴셜 암호화 유틸리티")
    print("=" * 40)

    # 마스터 패스워드 입력
    master_password = getpass.getpass("\n마스터 패스워드를 입력하세요 (암호화/복호화용): ").strip()
    if not master_password:
        print("❌ 마스터 패스워드는 필수입니다.")
        sys.exit(1)

    # 마스터 패스워드 확인
    confirm_password = getpass.getpass("마스터 패스워드 확인: ").strip()
    if master_password != confirm_password:
        print("❌ 패스워드가 일치하지 않습니다.")
        sys.exit(1)

    # 크리덴셜 입력 받기
    credentials = get_credentials_from_user()

    if not credentials:
        print("❌ 입력된 크리덴셜이 없습니다.")
        sys.exit(1)

    print(f"\n✅ {len(credentials)}개의 크리덴셜을 입력받았습니다.")

    # 암호화 처리
    try:
        if mode == '--env':
            encrypt_for_env_vars(credentials, master_password)
        else:  # --file
            encrypt_for_file(credentials, master_password)
    except Exception as e:
        print(f"❌ 암호화 중 오류 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()