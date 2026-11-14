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

class CadastroProduto(Base):
    __tablename__ = "cadastro_produtos"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False)
    produto = Column(String(255), nullable=False)

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

# Cria as 3 tabelas automaticamente no Supabase caso ainda não existam
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
def home(request: Request, aba: str = "vendas"):
    db = SessionLocal()
    try:
        cadastros = db.query(CadastroProduto).order_by(CadastroProduto.produto.asc()).all()
        estoque_itens = db.query(Estoque).order_by(Estoque.produto.asc()).all()
        vendas = db.query(Venda).order_by(Venda.id.desc()).limit(30).all()
        
        cadastros_json = [
            {
                "id": c.id,
                "codigo": c.codigo,
                "produto": c.produto
            }
            for c in cadastros
        ]

        estoque_json = [
            {
                "id": p.id,
                "codigo": p.codigo,
                "produto": p.produto,
                "quantidade": p.quantidade,
                "vl_custo": float(p.vl_custo),
                "vl_venda": float(p.vl_venda)
            }
            for p in estoque_itens
        ]
        
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "cadastros": cadastros,
                "produtos": estoque_itens,
                "vendas": vendas,
                "cadastros_json": cadastros_json,
                "estoque_json": estoque_json,
                "data_hoje": date.today().isoformat(),
                "aba_ativa": aba
            },
            media_type="text/html; charset=utf-8"
        )
    finally:
        db.close()

# ==========================================
# ROTAS: CADASTRO DE PRODUTOS (CATÁLOGO)
# ==========================================

@app.post("/cadastro-produtos/salvar")
def salvar_cadastro_produto(
    cadastro_id: str = Form(""),
    codigo: str = Form(...),
    produto: str = Form(...)
):
    db = SessionLocal()
    try:
        codigo_fmt = codigo.strip().upper()
        produto_fmt = formatar_titulo(produto)

        if cadastro_id:
            item = db.query(CadastroProduto).filter(CadastroProduto.id == int(cadastro_id)).first()
            if item:
                codigo_antigo = item.codigo
                item.codigo = codigo_fmt
                item.produto = produto_fmt

                # Sincroniza nome/código caso o item já exista no estoque
                item_est = db.query(Estoque).filter(Estoque.codigo == codigo_antigo).first()
                if item_est:
                    item_est.codigo = codigo_fmt
                    item_est.produto = produto_fmt
        else:
            novo = CadastroProduto(codigo=codigo_fmt, produto=produto_fmt)
            db.add(novo)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Erro ao salvar cadastro de produto: {str(e)}")
    finally:
        db.close()
    return RedirectResponse(url="/?aba=cadastro", status_code=303)

@app.post("/cadastro-produtos/excluir/{id}")
def excluir_cadastro_produto(id: int):
    db = SessionLocal()
    try:
        item = db.query(CadastroProduto).filter(CadastroProduto.id == id).first()
        if item:
            db.delete(item)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/?aba=cadastro", status_code=303)

# ==========================================
# ROTAS: LANÇAMENTO EM ESTOQUE
# ==========================================

@app.post("/estoque/salvar")
def salvar_estoque(
    produto_id: str = Form(""),
    codigo: str = Form(...),
    produto: str = Form(...),
    quantidade: int = Form(...),
    vl_custo: float = Form(...),
    vl_venda: float = Form(...)
):
    db = SessionLocal()
    try:
        codigo_fmt = codigo.strip().upper()
        produto_fmt = formatar_titulo(produto)

        if produto_id:
            # Edição direta de uma linha existente no estoque (substitui valores)
            item = db.query(Estoque).filter(Estoque.id == int(produto_id)).first()
            if item:
                item.codigo = codigo_fmt
                item.produto = produto_fmt
                item.quantidade = quantidade
                item.vl_custo = Decimal(str(vl_custo))
                item.vl_venda = Decimal(str(vl_venda))
        else:
            # Novo lançamento de chegada de mercadoria: se já existir no estoque, soma a quantidade
            item_existente = db.query(Estoque).filter(Estoque.codigo == codigo_fmt).first()
            if item_existente:
                item_existente.quantidade += quantidade
                item_existente.vl_custo = Decimal(str(vl_custo))
                item_existente.vl_venda = Decimal(str(vl_venda))
            else:
                novo_item = Estoque(
                    codigo=codigo_fmt,
                    produto=produto_fmt,
                    quantidade=quantidade,
                    vl_custo=Decimal(str(vl_custo)),
                    vl_venda=Decimal(str(vl_venda))
                )
                db.add(novo_item)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Erro ao lançar no estoque: {str(e)}")
    finally:
        db.close()
    return RedirectResponse(url="/?aba=estoque", status_code=303)

@app.post("/estoque/excluir/{id}")
def excluir_estoque(id: int):
    db = SessionLocal()
    try:
        item = db.query(Estoque).filter(Estoque.id == id).first()
        if item:
            db.delete(item)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/?aba=estoque", status_code=303)

# ==========================================
# ROTAS: REGISTRO DE VENDAS
# ==========================================

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

        # Dá baixa na tabela estoque
        item_estoque = db.query(Estoque).filter(Estoque.codigo == codigo.strip().upper()).first()
        if item_estoque:
            item_estoque.quantidade = max(0, item_estoque.quantidade - quantidade)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Erro ao registrar venda: {str(e)}")
    finally:
        db.close()
    return RedirectResponse(url="/?aba=vendas", status_code=303)