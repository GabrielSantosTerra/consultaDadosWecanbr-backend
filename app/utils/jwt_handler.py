from datetime import datetime, timedelta
from jose import jwt, JWTError
from config.settings import settings

def criar_token(data: dict, expires_in: int):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_in)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def verificar_token(token: str):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
