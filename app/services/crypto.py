import base64
from cryptography.fernet import Fernet
from app.config import Config

class CryptoService:
    @staticmethod
    def _get_fernet() -> Fernet:
        key = Config.ENCRYPTION_KEY
        if not key:
            raise ValueError("ENCRYPTION_KEY is not configured in environment")
        return Fernet(key.encode() if isinstance(key, str) else key)

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """
        Encrypts sensitive text (such as Stripe API keys) using AES-128-CBC + HMAC (Fernet).
        """
        if not plaintext:
            return ""
        fernet = cls._get_fernet()
        encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """
        Decrypts Fernet ciphertext back to plaintext.
        """
        if not ciphertext:
            return ""
        fernet = cls._get_fernet()
        decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
