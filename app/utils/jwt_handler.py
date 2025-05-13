# app/utils/jwt_handler.py
from jose import jwt, JWTError
from datetime import datetime, timedelta

SECRET_KEY = "chave-muito-secreta"
ALGORITHM = "HS256"

def criar_token(payload: dict, expires_in: int):
    exp = datetime.utcnow() + timedelta(minutes=expires_in)
    payload.update({"exp": exp})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verificar_token(token: str):
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded
    except JWTError:
        return None
