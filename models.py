from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# =========================
# CENTRO DE CUSTO / CAIXA
# =========================
class CentroCusto(db.Model):
    __tablename__ = "centros_custo"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    saldo = db.Column(db.Float, default=0)


# =========================
# FORNECEDOR
# =========================
class Fornecedor(db.Model):
    __tablename__ = "fornecedores"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)


# =========================
# ORDEM DE COMPRA
# =========================
class OrdemCompra(db.Model):
    __tablename__ = "ordens_compra"

    id = db.Column(db.Integer, primary_key=True)

    fornecedor = db.Column(db.String(120), nullable=False)
    centro_custo = db.Column(db.String(120), nullable=False)

    descricao_itens = db.Column(db.Text, nullable=False)
    valor = db.Column(db.Float, nullable=False)

    status = db.Column(db.String(30), default="Pendente")

    aprovador = db.Column(db.String(120))
    aprovado_por = db.Column(db.String(120))
    aprovado_em = db.Column(db.DateTime)

    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ NOTA FISCAL (ANEXO)
    nota_fiscal = db.Column(db.String(255))
    data_compra = db.Column(db.Date)

    # ===============================
    # RELACIONAMENTO COM ITENS
    # ===============================
    itens = db.relationship(
        "ItemOrdem",
        backref="ordem",
        lazy=True,
        cascade="all, delete-orphan"
    )


# =========================
# SALDO POR APROVADOR
# =========================
class SaldoAprovador(db.Model):
    __tablename__ = "saldos_aprovador"

    id = db.Column(db.Integer, primary_key=True)
    nome_aprovador = db.Column(db.String(120), unique=True, nullable=False)
    saldo = db.Column(db.Float, default=0)


# =========================
# USUÁRIO / FUNCIONÁRIO
# =========================
class Usuario(db.Model, UserMixin):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(50), nullable=False)


# ===============================
# PRODUTOS (ESTOQUE)
# ===============================
class Produto(db.Model):
    __tablename__ = "produto"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), unique=True, nullable=False)
    estoque_atual = db.Column(db.Integer, default=0)
    estoque_minimo = db.Column(db.Integer, default=0)

    itens_ordem = db.relationship(
        "ItemOrdem",
        backref="produto",
        lazy=True
    )

    def __repr__(self):
        return f"<Produto {self.nome}>"


# ===============================
# ITENS DA ORDEM (CARRINHO)
# ===============================
class ItemOrdem(db.Model):
    __tablename__ = "item_ordem"

    id = db.Column(db.Integer, primary_key=True)

    ordem_id = db.Column(
        db.Integer,
        db.ForeignKey("ordens_compra.id"),
        nullable=False
    )

    produto_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=False
    )

    quantidade = db.Column(db.Integer, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)

    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def subtotal(self):
        return self.quantidade * self.valor_unitario

    def __repr__(self):
        return f"<ItemOrdem Ordem:{self.ordem_id} Produto:{self.produto_id}>"