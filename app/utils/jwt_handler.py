from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import HTTPException, status
from config.settings import settings
from uuid import uuid4


def criar_token(data: dict, expires_in: int = 15) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_in)
    jti = str(uuid4())
    to_encode.update({"exp": expire, "jti": jti})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def verificar_token(token: str):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        )