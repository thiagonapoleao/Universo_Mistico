import os
import re
import json
import unicodedata
from datetime import datetime, date
from decimal import Decimal
from urllib.parse import quote
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker

DEFAULT_SUPABASE_URL = "postgresql://postgres:napoleao140205@db.awqxrriqpjipzygnwmin.supabase.co:5432/postgres"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SUPABASE_URL)

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
    n_pedido = Column(String(30), index=True, nullable=False)
    codigo = Column(String(50), nullable=False)
    produto = Column(String(255), nullable=False)
    quantidade = Column(Integer, nullable=False, default=1)
    vl_custo = Column(Numeric(10, 2), nullable=False, default=0.00)
    vl_venda = Column(Numeric(10, 2), nullable=False, default=0.00)
    status = Column(String(20), nullable=False, default="CONCLUIDA")
    data_venda = Column(DateTime(timezone=True), server_default=func.now())

class MovimentacaoEstoque(Base):
    __tablename__ = "movimentacoes_estoque"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), nullable=False)
    produto = Column(String(255), nullable=False)
    tipo = Column(String(30), nullable=False)
    quantidade = Column(Integer, nullable=False)
    saldo_anterior = Column(Integer, nullable=False)
    saldo_atual = Column(Integer, nullable=False)
    venda_id = Column(Integer, nullable=True)
    motivo = Column(String(150), nullable=True)
    data_movimentacao = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Universo Místico - Estoque & Vendas")

os.makedirs("static/img", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def formatar_titulo(texto: str) -> str:
    return " ".join(palavra.capitalize() for palavra in texto.strip().split())

def extrair_prefixo_codigo(nome_produto: str) -> str:
    """Remove acentos e extrai as 3 primeiras letras em maiúsculo (XXX)."""
    sem_acento = unicodedata.normalize("NFD", nome_produto).encode("ascii", "ignore").decode("utf-8")
    apenas_letras = re.sub(r"[^A-Za-z]", "", sem_acento).upper()
    return (apenas_letras + "PRD")[:3]

def obter_proxima_sequencia_cadastro(db) -> int:
    """Calcula a próxima sequência numérica (01, 02, ...) baseada nos cadastros existentes."""
    todos = db.query(CadastroProduto).all()
    maior_seq = 0
    for item in todos:
        if item.id and item.id > maior_seq:
            maior_seq = item.id
        if item.codigo and "-" in item.codigo:
            sufixo = item.codigo.split("-")[-1]
            if sufixo.isdigit():
                maior_seq = max(maior_seq, int(sufixo))
    return maior_seq + 1

def gerar_proximo_numero_pedido(db) -> str:
    ultimo_id = db.query(func.max(Venda.id)).scalar() or 0
    return f"PED-{ultimo_id + 1:04d}"

# --- ROTA PRINCIPAL ---

@app.get("/", response_class=HTMLResponse)
def home(request: Request, aba: str = "vendas", erro: str = "", ok: str = ""):
    db = SessionLocal()
    try:
        cadastros = db.query(CadastroProduto).order_by(CadastroProduto.produto.asc()).all()
        estoque_itens = db.query(Estoque).order_by(Estoque.produto.asc()).all()
        vendas_todas = db.query(Venda).order_by(Venda.id.desc()).all()
        movimentacoes = db.query(MovimentacaoEstoque).order_by(MovimentacaoEstoque.id.desc()).limit(40).all()
        proximo_pedido = gerar_proximo_numero_pedido(db)
        proxima_seq_cadastro = obter_proxima_sequencia_cadastro(db)

        # Totalizadores do Estoque
        total_unidades_estoque = sum(p.quantidade for p in estoque_itens)
        valor_total_venda_estoque = sum((Decimal(str(p.vl_venda)) * p.quantidade) for p in estoque_itens)

        # Serializa vendas concluídas para os gráficos e tabelas dinâmicas do Dashboard
        vendas_concluidas = [v for v in vendas_todas if v.status == "CONCLUIDA"]
        vendas_dashboard_json = [
            {
                "id": v.id,
                "n_pedido": v.n_pedido or f"PED-{v.id:04d}",
                "codigo": v.codigo,
                "produto": v.produto,
                "quantidade": v.quantidade,
                "vl_custo": float(v.vl_custo),
                "vl_venda": float(v.vl_venda),
                "custo_total": float(Decimal(str(v.vl_custo)) * v.quantidade),
                "subtotal": float(Decimal(str(v.vl_venda)) * v.quantidade),
                "lucro": float((Decimal(str(v.vl_venda)) - Decimal(str(v.vl_custo))) * v.quantidade),
                "data_iso": v.data_venda.strftime("%Y-%m-%d") if v.data_venda else date.today().isoformat(),
                "mes_iso": v.data_venda.strftime("%Y-%m") if v.data_venda else date.today().strftime("%Y-%m")
            }
            for v in vendas_concluidas
        ]

        # Agrupa todas as vendas por n_pedido em JSON para filtro dinâmico por data na aba Vendas
        pedidos_agrupados_json = []
        mapa_pedidos = {}
        for v in vendas_todas:
            num = v.n_pedido or f"PED-{v.id:04d}"
            data_iso = v.data_venda.strftime("%Y-%m-%d") if v.data_venda else date.today().isoformat()
            data_fmt = v.data_venda.strftime("%d/%m/%Y %H:%M") if v.data_venda else "-"
            if num not in mapa_pedidos:
                grupo = {
                    "n_pedido": num,
                    "data_iso": data_iso,
                    "data_fmt": data_fmt,
                    "status": v.status,
                    "itens": [],
                    "total_pedido": 0.0
                }
                mapa_pedidos[num] = grupo
                pedidos_agrupados_json.append(grupo)
            subtotal = float(Decimal(str(v.vl_venda)) * v.quantidade)
            mapa_pedidos[num]["itens"].append({
                "codigo": v.codigo,
                "produto": v.produto,
                "quantidade": v.quantidade,
                "vl_venda": float(v.vl_venda),
                "subtotal": subtotal
            })
            mapa_pedidos[num]["total_pedido"] += subtotal

        cadastros_json = [
            {"id": c.id, "codigo": c.codigo, "produto": c.produto}
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
        
        hoje = date.today()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "cadastros": cadastros,
                "produtos": estoque_itens,
                "movimentacoes": movimentacoes,
                "cadastros_json": cadastros_json,
                "estoque_json": estoque_json,
                "vendas_dashboard_json": vendas_dashboard_json,
                "pedidos_agrupados_json": pedidos_agrupados_json,
                "total_unidades_estoque": total_unidades_estoque,
                "valor_total_venda_estoque": valor_total_venda_estoque,
                "data_hoje": hoje.isoformat(),
                "mes_atual": hoje.strftime("%Y-%m"),
                "proximo_pedido": proximo_pedido,
                "proxima_seq_cadastro": proxima_seq_cadastro,
                "aba_ativa": aba,
                "erro": erro,
                "ok": ok
            },
            media_type="text/html; charset=utf-8"
        )
    finally:
        db.close()

# ==========================================
# ROTAS: CADASTRO DE PRODUTOS (CÓDIGO XXX-00)
# ==========================================

@app.post("/cadastro-produtos/salvar")
def salvar_cadastro_produto(
    cadastro_id: str = Form(""),
    codigo: str = Form(""),
    produto: str = Form(...)
):
    db = SessionLocal()
    try:
        produto_fmt = formatar_titulo(produto)
        prefixo = extrair_prefixo_codigo(produto_fmt)

        if cadastro_id:
            item = db.query(CadastroProduto).filter(CadastroProduto.id == int(cadastro_id)).first()
            if item:
                codigo_antigo = item.codigo
                if "-" in codigo_antigo and codigo_antigo.split("-")[-1].isdigit():
                    seq_existente = int(codigo_antigo.split("-")[-1])
                else:
                    seq_existente = item.id

                codigo_fmt = f"{prefixo}-{seq_existente:02d}"
                item.codigo = codigo_fmt
                item.produto = produto_fmt

                item_est = db.query(Estoque).filter(Estoque.codigo == codigo_antigo).first()
                if item_est:
                    item_est.codigo = codigo_fmt
                    item_est.produto = produto_fmt

                db.query(Venda).filter(Venda.codigo == codigo_antigo).update(
                    {"codigo": codigo_fmt, "produto": produto_fmt},
                    synchronize_session=False
                )
                db.query(MovimentacaoEstoque).filter(MovimentacaoEstoque.codigo == codigo_antigo).update(
                    {"codigo": codigo_fmt, "produto": produto_fmt},
                    synchronize_session=False
                )
        else:
            seq = obter_proxima_sequencia_cadastro(db)
            codigo_fmt = f"{prefixo}-{seq:02d}"
            while db.query(CadastroProduto).filter(CadastroProduto.codigo == codigo_fmt).first():
                seq += 1
                codigo_fmt = f"{prefixo}-{seq:02d}"

            novo = CadastroProduto(codigo=codigo_fmt, produto=produto_fmt)
            db.add(novo)
        db.commit()
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/?aba=cadastro&erro={quote(str(e))}", status_code=303)
    finally:
        db.close()
    return RedirectResponse(url=f"/?aba=cadastro&ok={quote(f'Produto salvo com código {codigo_fmt}')}", status_code=303)

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
    return RedirectResponse(url="/?aba=cadastro&ok=Produto+removido+do+cadastro", status_code=303)

# ==========================================
# ROTAS: MOVIMENTAÇÃO DE ESTOQUE
# ==========================================

@app.post("/estoque/salvar")
def salvar_estoque(
    produto_id: str = Form(""),
    tipo_operacao: str = Form("ENTRADA"),
    motivo_ajuste: str = Form(""),
    codigo: str = Form(...),
    produto: str = Form(...),
    quantidade: int = Form(...),
    vl_custo: float = Form(0.0),
    vl_venda: float = Form(0.0)
):
    db = SessionLocal()
    try:
        codigo_fmt = codigo.strip().upper()
        produto_fmt = formatar_titulo(produto)

        if produto_id:
            item = db.query(Estoque).filter(Estoque.id == int(produto_id)).with_for_update().first()
            if item:
                saldo_ant = item.quantidade
                item.codigo = codigo_fmt
                item.produto = produto_fmt
                item.quantidade = quantidade
                item.vl_custo = Decimal(str(vl_custo))
                item.vl_venda = Decimal(str(vl_venda))

                db.add(MovimentacaoEstoque(
                    codigo=codigo_fmt,
                    produto=produto_fmt,
                    tipo="AJUSTE_MANUAL",
                    quantidade=quantidade - saldo_ant,
                    saldo_anterior=saldo_ant,
                    saldo_atual=quantidade,
                    motivo=motivo_ajuste.strip() or "Edição direta de saldo"
                ))
            db.commit()
            return RedirectResponse(url="/?aba=estoque&ok=Registro+de+estoque+atualizado", status_code=303)

        if tipo_operacao == "AJUSTE_BAIXA":
            if quantidade <= 0:
                return RedirectResponse(url="/?aba=estoque&erro=Informe+uma+quantidade+maior+que+zero+para+baixa", status_code=303)

            item_existente = db.query(Estoque).filter(Estoque.codigo == codigo_fmt).with_for_update().first()
            if not item_existente:
                return RedirectResponse(url=f"/?aba=estoque&erro={quote(f'O produto {produto_fmt} ainda não possui saldo lançado no estoque.')}", status_code=303)

            if item_existente.quantidade < quantidade:
                msg = f"Saldo insuficiente para baixar {quantidade} un. de {produto_fmt}. Saldo atual: {item_existente.quantidade} un."
                return RedirectResponse(url=f"/?aba=estoque&erro={quote(msg)}", status_code=303)

            saldo_ant = item_existente.quantidade
            saldo_novo = saldo_ant - quantidade
            item_existente.quantidade = saldo_novo

            motivo_final = formatar_titulo(motivo_ajuste) if motivo_ajuste.strip() else "Perda / Quebra"

            db.add(MovimentacaoEstoque(
                codigo=codigo_fmt,
                produto=produto_fmt,
                tipo="PERDA_QUEBRA",
                quantidade=-quantidade,
                saldo_anterior=saldo_ant,
                saldo_atual=saldo_novo,
                motivo=motivo_final
            ))
            db.commit()
            return RedirectResponse(url=f"/?aba=estoque&ok={quote(f'Baixa de {quantidade} un. ({motivo_final}) registrada com sucesso!')}", status_code=303)

        item_existente = db.query(Estoque).filter(Estoque.codigo == codigo_fmt).with_for_update().first()
        if item_existente:
            saldo_ant = item_existente.quantidade
            saldo_novo = saldo_ant + quantidade
            item_existente.quantidade = saldo_novo
            item_existente.vl_custo = Decimal(str(vl_custo))
            item_existente.vl_venda = Decimal(str(vl_venda))
        else:
            saldo_ant = 0
            saldo_novo = quantidade
            novo_item = Estoque(
                codigo=codigo_fmt,
                produto=produto_fmt,
                quantidade=saldo_novo,
                vl_custo=Decimal(str(vl_custo)),
                vl_venda=Decimal(str(vl_venda))
            )
            db.add(novo_item)

        db.add(MovimentacaoEstoque(
            codigo=codigo_fmt,
            produto=produto_fmt,
            tipo="ENTRADA",
            quantidade=quantidade,
            saldo_anterior=saldo_ant,
            saldo_atual=saldo_novo,
            motivo="Entrada de mercadoria"
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/?aba=estoque&erro={quote(str(e))}", status_code=303)
    finally:
        db.close()
    return RedirectResponse(url="/?aba=estoque&ok=Entrada+lançada+no+estoque+com+sucesso", status_code=303)

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
    return RedirectResponse(url="/?aba=estoque&ok=Item+removido+do+estoque", status_code=303)

# ==========================================
# ROTAS: VENDAS MULTI-ITENS + BAIXA ATÔMICA
# ==========================================

@app.post("/vendas/registrar")
def registrar_venda(
    n_pedido: str = Form(...),
    data_venda: str = Form(...),
    itens_pedido_json: str = Form(...)
):
    db = SessionLocal()
    try:
        itens = json.loads(itens_pedido_json)
        if not itens:
            return RedirectResponse(url="/?aba=vendas&erro=Adicione+pelo+menos+um+produto+ao+pedido", status_code=303)

        pedido_fmt = n_pedido.strip().upper()
        data_parsed = datetime.strptime(data_venda, "%Y-%m-%d")
        agora = datetime.now()
        data_final = data_parsed.replace(hour=agora.hour, minute=agora.minute, second=agora.second)

        soma_por_codigo = {}
        for item in itens:
            cod = item["codigo"].strip().upper()
            qtd = int(item["quantidade"])
            if qtd <= 0:
                return RedirectResponse(url="/?aba=vendas&erro=Quantidade+deve+ser+maior+que+zero", status_code=303)
            soma_por_codigo[cod] = soma_por_codigo.get(cod, 0) + qtd

        estoques_travados = {}
        for cod, qtd_total in soma_por_codigo.items():
            est = db.query(Estoque).filter(Estoque.codigo == cod).with_for_update().first()
            if not est:
                db.rollback()
                return RedirectResponse(url=f"/?aba=vendas&erro={quote(f'Produto {cod} não encontrado no estoque')}", status_code=303)
            if est.quantidade < qtd_total:
                db.rollback()
                msg = f"Saldo insuficiente para {est.produto}. Pedido: {qtd_total} un. | Disponível: {est.quantidade} un."
                return RedirectResponse(url=f"/?aba=vendas&erro={quote(msg)}", status_code=303)
            estoques_travados[cod] = est

        for item in itens:
            cod = item["codigo"].strip().upper()
            prod_fmt = formatar_titulo(item["produto"])
            qtd = int(item["quantidade"])
            vl_custo = Decimal(str(item["vl_custo"]))
            vl_venda = Decimal(str(item["vl_venda"]))

            nova_venda = Venda(
                n_pedido=pedido_fmt,
                codigo=cod,
                produto=prod_fmt,
                quantidade=qtd,
                vl_custo=vl_custo,
                vl_venda=vl_venda,
                status="CONCLUIDA",
                data_venda=data_final
            )
            db.add(nova_venda)
            db.flush()

            est = estoques_travados[cod]
            saldo_ant = est.quantidade
            saldo_novo = saldo_ant - qtd
            est.quantidade = saldo_novo

            db.add(MovimentacaoEstoque(
                codigo=cod,
                produto=prod_fmt,
                tipo="SAIDA_VENDA",
                quantidade=-qtd,
                saldo_anterior=saldo_ant,
                saldo_atual=saldo_novo,
                venda_id=nova_venda.id,
                motivo=f"Venda {pedido_fmt}"
            ))

        db.commit()
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/?aba=vendas&erro={quote(str(e))}", status_code=303)
    finally:
        db.close()
    return RedirectResponse(url=f"/?aba=vendas&ok={quote(f'Pedido {pedido_fmt} registrado e estoque baixado!')}", status_code=303)

@app.post("/vendas/estornar-pedido/{n_pedido}")
def estornar_pedido(n_pedido: str):
    db = SessionLocal()
    try:
        pedido_fmt = n_pedido.strip().upper()
        itens_venda = db.query(Venda).filter(
            Venda.n_pedido == pedido_fmt,
            Venda.status == "CONCLUIDA"
        ).with_for_update().all()

        if not itens_venda:
            return RedirectResponse(url="/?aba=vendas&erro=Pedido+já+estornado+ou+inexistente", status_code=303)

        for v in itens_venda:
            est = db.query(Estoque).filter(Estoque.codigo == v.codigo).with_for_update().first()
            if est:
                saldo_ant = est.quantidade
                saldo_novo = saldo_ant + v.quantidade
                est.quantidade = saldo_novo

                db.add(MovimentacaoEstoque(
                    codigo=v.codigo,
                    produto=v.produto,
                    tipo="ESTORNO_VENDA",
                    quantidade=v.quantidade,
                    saldo_anterior=saldo_ant,
                    saldo_atual=saldo_novo,
                    venda_id=v.id,
                    motivo=f"Estorno {pedido_fmt}"
                ))
            v.status = "CANCELADA"

        db.commit()
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/?aba=vendas&erro={quote(str(e))}", status_code=303)
    finally:
        db.close()
    return RedirectResponse(url=f"/?aba=vendas&ok={quote(f'Pedido {pedido_fmt} estornado e itens devolvidos ao estoque!')}", status_code=303)