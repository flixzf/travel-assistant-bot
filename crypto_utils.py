"""
보안 유틸리티 - 민감한 정보 암호화/복호화
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecureConfig:
    def __init__(self, master_password: str = None):
        """
        마스터 패스워드로 암호화/복호화 키 생성
        """
        if not master_password:
            master_password = os.getenv('MASTER_PASSWORD', 'default-change-this-key')

        # 마스터 패스워드에서 암호화 키 생성
        password = master_password.encode()
        salt = b'salt_1234567890'  # 실제 운영에서는 랜덤 salt 사용

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        self.cipher = Fernet(key)

    def encrypt(self, text: str) -> str:
        """텍스트 암호화"""
        if not text:
            return ""
        encrypted = self.cipher.encrypt(text.encode())
        return base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, encrypted_text: str) -> str:
        """텍스트 복호화"""
        if not encrypted_text:
            return ""
        try:
            encrypted = base64.urlsafe_b64decode(encrypted_text.encode())
            decrypted = self.cipher.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            print(f"복호화 실패: {e}")
            return ""

def get_secure_env(key: str, secure_config: SecureConfig = None) -> str:
    """
    환경변수에서 암호화된 값을 가져와 복호화
    """
    if not secure_config:
        secure_config = SecureConfig()

    encrypted_value = os.getenv(key)
    if not encrypted_value:
        return ""

    return secure_config.decrypt(encrypted_value)

# 사용 예시
if __name__ == "__main__":
    # 암호화 도구
    config = SecureConfig("your-secret-master-password")

    # 암호화 (한 번만 실행해서 결과를 환경변수에 저장)
    telegram_token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
    korail_user = "1234567890"
    korail_pass = "your_password"

    print("=== 암호화된 값들 (환경변수에 저장하세요) ===")
    print(f"TELEGRAM_BOT_TOKEN_ENC={config.encrypt(telegram_token)}")
    print(f"KORAIL_USER_ENC={config.encrypt(korail_user)}")
    print(f"KORAIL_PASS_ENC={config.encrypt(korail_pass)}")