from fastapi import FastAPI
from app.database.connection import engine
from app.models import user  # importa o módulo completo, não uma classe
from app.routers import user as usuario_router  # este é seu routers/user.py

# cria as tabelas a partir das classes dentro de user.py
user.Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(usuario_router.router)

@app.get("/")
def root():
    return {"msg": "API ok"}
