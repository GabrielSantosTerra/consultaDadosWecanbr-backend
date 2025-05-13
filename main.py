from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.connection import engine
from app.models import user  # importa o módulo completo, não uma classe
from app.routers import user as usuario_router  # este é seu routers/user.py

# cria as tabelas a partir das classes dentro de user.py
user.Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # ou ["*"] para liberar geral
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(usuario_router.router)

@app.get("/")
def root():
    return {"msg": "API ok"}
