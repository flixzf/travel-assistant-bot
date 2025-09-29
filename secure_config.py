"""
보안 설정 관리 - 민감한 정보를 안전하게 로드
"""
import os
import json
from pathlib import Path
from crypto_utils import SecureConfig, get_secure_env

class ConfigManager:
    def __init__(self):
        self.secure_config = SecureConfig()
        self._credentials = {}
        self._load_credentials()

    def _load_credentials(self):
        """다양한 소스에서 안전하게 크리덴셜 로드"""

        # 방법 1: 암호화된 환경변수에서 로드
        if os.getenv('USE_ENCRYPTED_ENV') == 'true':
            self._load_from_encrypted_env()

        # 방법 2: 로컬 암호화 파일에서 로드 (개발용)
        elif os.path.exists('credentials.enc'):
            self._load_from_encrypted_file()

        # 방법 3: 일반 환경변수에서 로드 (기본값)
        else:
            self._load_from_env()

    def _load_from_encrypted_env(self):
        """암호화된 환경변수에서 로드"""
        encrypted_vars = [
            'TELEGRAM_BOT_TOKEN_ENC',
            'KORAIL_USER_ENC',
            'KORAIL_PASS_ENC',
            'KORAIL_PASS_BANK_ENC',
            'Card_Num1_korail_ENC',
            'Card_Num2_korail_ENC',
            'Card_Num3_korail_ENC',
            'Card_Num4_korail_ENC',
            'Card_Num5_korail_ENC',
            'CARD_MONTH_ENC',
            'Id_Num1_korail_ENC',
            'SRT_ID_ENC',
            'SRT_PWD_ENC'
        ]

        for enc_var in encrypted_vars:
            original_key = enc_var.replace('_ENC', '')
            decrypted_value = get_secure_env(enc_var, self.secure_config)
            if decrypted_value:
                self._credentials[original_key] = decrypted_value

    def _load_from_encrypted_file(self):
        """로컬 암호화 파일에서 로드 (개발용)"""
        try:
            with open('credentials.enc', 'r') as f:
                encrypted_data = f.read()

            decrypted_json = self.secure_config.decrypt(encrypted_data)
            self._credentials = json.loads(decrypted_json)
        except Exception as e:
            print(f"암호화 파일 로드 실패: {e}")

    def _load_from_env(self):
        """일반 환경변수에서 로드"""
        env_vars = [
            'TELEGRAM_BOT_TOKEN',
            'KORAIL_USER',
            'KORAIL_PASS',
            'KORAIL_PASS_BANK',
            'Card_Num1_korail',
            'Card_Num2_korail',
            'Card_Num3_korail',
            'Card_Num4_korail',
            'Card_Num5_korail',
            'CARD_MONTH',
            'Id_Num1_korail',
            'SRT_ID',
            'SRT_PWD'
        ]

        for var in env_vars:
            value = os.getenv(var)
            if value:
                self._credentials[var] = value

    def get(self, key: str, default: str = None) -> str:
        """안전하게 크리덴셜 가져오기"""
        return self._credentials.get(key, default)

    def get_all_credentials(self) -> dict:
        """모든 크리덴셜 반환 (디버깅용 - 마스킹 처리)"""
        masked = {}
        for key, value in self._credentials.items():
            if value:
                if len(value) > 4:
                    masked[key] = value[:2] + '*' * (len(value) - 4) + value[-2:]
                else:
                    masked[key] = '*' * len(value)
            else:
                masked[key] = 'NOT_SET'
        return masked

    def create_encrypted_file(self, credentials: dict, filename: str = 'credentials.enc'):
        """크리덴셜을 암호화해서 파일로 저장 (개발용)"""
        json_data = json.dumps(credentials, indent=2)
        encrypted_data = self.secure_config.encrypt(json_data)

        with open(filename, 'w') as f:
            f.write(encrypted_data)

        print(f"암호화된 크리덴셜이 {filename}에 저장되었습니다.")
        print("이 파일을 .gitignore에 추가하세요!")

# 전역 설정 매니저
config_manager = ConfigManager()

# 편의 함수들
def get_credential(key: str, default: str = None) -> str:
    """크리덴셜 가져오기"""
    return config_manager.get(key, default)

def validate_credentials() -> bool:
    """필수 크리덴셜이 모두 설정되었는지 확인"""
    required = [
        'TELEGRAM_BOT_TOKEN',
        'KORAIL_USER',
        'KORAIL_PASS',
        'SRT_ID',
        'SRT_PWD'
    ]

    missing = []
    for key in required:
        if not config_manager.get(key):
            missing.append(key)

    if missing:
        print(f"❌ 누락된 필수 크리덴셜: {', '.join(missing)}")
        return False

    print("✅ 모든 필수 크리덴셜이 설정되었습니다.")
    return True

if __name__ == "__main__":
    # 크리덴셜 상태 확인
    print("=== 크리덴셜 상태 ===")
    credentials = config_manager.get_all_credentials()
    for key, value in credentials.items():
        print(f"{key}: {value}")

    print(f"\n=== 유효성 검사 ===")
    validate_credentials()