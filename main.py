import os
from datetime import datetime, date
from decimal import Decimal
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker

# String de conexão do Supabase (usa variável de ambiente DATABASE_URL do Render se existir)
DEFAULT_SUPABASE_URL = "postgresql://postgres:napoleao140205@db.awqxrriqpjipzygnwmin.supabase.co:5432/postgres"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SUPABASE_URL)

# Garante o prefixo postgresql+psycopg:// para compatibilidade com Python 3.14
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELOS DAS TABELAS ---

class Estoque(Base):
    __tablename__ = "estoque"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False)
    produto = Column(String(255), nullable=False)
    quantidade = Column(Integer, nullable=False, default=0)
    vl_custo = Column(Numeric(10, 2), nullable=False, default=0.00)
    vl_venda = Column(Numeric(10, 2), nullable=False, default=0.00)

class Venda(Base):
    __tablename__ = "vendas"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), nullable=False)
    produto = Column(String(255), nullable=False)
    quantidade = Column(Integer, nullable=False, default=1)
    vl_custo = Column(Numeric(10, 2), nullable=False, default=0.00)
    vl_venda = Column(Numeric(10, 2), nullable=False, default=0.00)
    data_venda = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Universo Místico - Estoque & Vendas")

os.makedirs("static/img", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Função auxiliar para garantir a primeira letra maiúscula de cada palavra
def formatar_titulo(texto: str) -> str:
    return " ".join(palavra.capitalize() for palavra in texto.strip().split())

# --- ROTAS DO SISTEMA ---

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = SessionLocal()
    try:
        produtos = db.query(Estoque).order_by(Estoque.produto.asc()).all()
        vendas = db.query(Venda).order_by(Venda.id.desc()).limit(30).all()
        
        produtos_json = [
            {
                "id": p.id,
                "codigo": p.codigo,
                "produto": p.produto,
                "quantidade": p.quantidade,
                "vl_custo": float(p.vl_custo),
                "vl_venda": float(p.vl_venda)
            }
            for p in produtos
        ]
        
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "produtos": produtos,
                "vendas": vendas,
                "produtos_json": produtos_json,
                "data_hoje": date.today().isoformat()
            },
            media_type="text/html; charset=utf-8"
        )
    finally:
        db.close()

# Salvar (Novo Cadastro ou Edição) na tabela estoque
@app.post("/estoque/salvar")
def salvar_produto(
    produto_id: str = Form(""),
    codigo: str = Form(...),
    produto: str = Form(...),
    quantidade: int = Form(...),
    vl_custo: float = Form(...),
    vl_venda: float = Form(...)
):
    db = SessionLocal()
    try:
        codigo_formatado = codigo.strip().upper()
        produto_formatado = formatar_titulo(produto)

        if produto_id:
            item = db.query(Estoque).filter(Estoque.id == int(produto_id)).first()
            if item:
                item.codigo = codigo_formatado
                item.produto = produto_formatado
                item.quantidade = quantidade
                item.vl_custo = Decimal(str(vl_custo))
                item.vl_venda = Decimal(str(vl_venda))
        else:
            novo_item = Estoque(
                codigo=codigo_formatado,
                produto=produto_formatado,
                quantidade=quantidade,
                vl_custo=Decimal(str(vl_custo)),
                vl_venda=Decimal(str(vl_venda))
            )
            db.add(novo_item)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Erro ao salvar produto: {str(e)}")
    finally:
        db.close()
    return RedirectResponse(url="/", status_code=303)

# Excluir produto da tabela estoque
@app.post("/estoque/excluir/{id}")
def excluir_produto(id: int):
    db = SessionLocal()
    try:
        item = db.query(Estoque).filter(Estoque.id == id).first()
        if item:
            db.delete(item)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/", status_code=303)

# Registrar venda na tabela vendas e dar baixa no estoque
@app.post("/vendas/registrar")
def registrar_venda(
    codigo: str = Form(...),
    produto: str = Form(...),
    quantidade: int = Form(...),
    vl_custo: float = Form(...),
    vl_venda: float = Form(...),
    data_venda: str = Form(...)
):
    db = SessionLocal()
    try:
        # Converte a data selecionada (YYYY-MM-DD) combinando com o horário atual
        data_parsed = datetime.strptime(data_venda, "%Y-%m-%d")
        agora = datetime.now()
        data_final = data_parsed.replace(hour=agora.hour, minute=agora.minute, second=agora.second)

        nova_venda = Venda(
            codigo=codigo.strip().upper(),
            produto=formatar_titulo(produto),
            quantidade=quantidade,
            vl_custo=Decimal(str(vl_custo)),
            vl_venda=Decimal(str(vl_venda)),
            data_venda=data_final
        )
        db.add(nova_venda)

        item_estoque = db.query(Estoque).filter(Estoque.codigo == codigo.strip().upper()).first()
        if item_estoque:
            item_estoque.quantidade = max(0, item_estoque.quantidade - quantidade)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Erro ao registrar venda: {str(e)}")
    finally:
        db.close()
    return RedirectResponse(url="/", status_code=303)