from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.connection import engine
from app.models import user  # importa o módulo completo, não uma classe
from app.routers import user as usuario_router  # este é seu routers/user.py
from app.routers import ged as ged_router       # este é seu routers/ged.py
from app.routers import document as documents_router
from app.routers import gustavo as gustavo_routers ####NÃO COMITAR

# cria as tabelas a partir das classes dentro de user.py
user.Base.metadata.create_all(bind=engine)

app = FastAPI()

# ✅ Configuração CORS para frontend local e produção Firebase Hosting

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://3.17.64.91:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# rotas
app.include_router(documents_router.router, tags=["Documentos"])
app.include_router(usuario_router.router, tags=["Usuários"])
app.include_router(ged_router.router, tags=["GED"])
app.include_router(gustavo_routers.router, tags=["Gustavo"])

@app.get("/")
def root():
    return {"msg": "API ok"}