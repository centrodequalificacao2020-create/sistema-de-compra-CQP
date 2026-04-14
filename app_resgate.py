print("### ESTE APP_RESAGATE ESTA SENDO EXECUTADO ###")

import io
import pandas as pd
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import Image as RLImage
from reportlab.pdfgen import canvas as rl_canvas

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, abort
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, text
from datetime import datetime
import os

from models import (
    db,
    OrdemCompra,
    Fornecedor,
    CentroCusto,
    Usuario,
    SaldoAprovador,
    Produto,
    ItemOrdem
)

import smtplib
from email.message import EmailMessage

# Centro de custo que exige dupla aprovacao
CENTRO_DUPLA_APROVACAO = "fundos_cqp"

# ===============================
# CONFIGURACAO DE E-MAIL (ZOHO)
# ===============================
EMAIL_REMETENTE = "sistema@cqpcursos.com.br"
EMAIL_DESTINO   = "compras@cqpcursos.com.br"
EMAIL_SMTP      = "smtp.zoho.com"
EMAIL_PORTA     = 587
EMAIL_SENHA     = os.environ.get("EMAIL_SENHA", "")

def enviar_email_nova_ordem(ordem):
    try:
        msg = EmailMessage()
        msg["From"]    = EMAIL_REMETENTE
        msg["To"]      = EMAIL_DESTINO
        msg["Subject"] = "Nova ordem de compra criada"
        msg.set_content(
            f"Fornecedor: {ordem.fornecedor}\n"
            f"Centro de Custo: {ordem.centro_custo}\n"
            f"Valor: R$ {float(ordem.valor or 0):.2f}\n"
            f"Aprovador: {ordem.aprovador}\n"
        )
        with smtplib.SMTP(EMAIL_SMTP, EMAIL_PORTA) as server:
            server.starttls()
            server.login(EMAIL_REMETENTE, EMAIL_SENHA)
            server.send_message(msg)
    except Exception as e:
        print("Erro ao enviar e-mail:", e)


# ===============================
# APP + CONFIG
# ===============================
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

app.config["SECRET_KEY"] = "cqp"

if os.environ.get("WEBSITE_SITE_NAME"):
    DB_PATH = "/home/ordem_compra.db"
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DB_PATH  = os.path.join(BASE_DIR, "instance", "ordem_compra.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"]        = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# ===============================
# LOGIN
# ===============================
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# ===============================
# LOGIN / LOGOUT
# ===============================
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = Usuario.query.filter_by(email=request.form["email"]).first()
        if usuario and check_password_hash(usuario.senha, request.form["senha"]):
            login_user(usuario)
            return redirect(url_for("dashboard"))
        flash("Email ou senha invalidos", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ===============================
# DASHBOARD
# ===============================
@app.route("/dashboard")
@login_required
def dashboard():
    ordens_pendentes = OrdemCompra.query.filter(
        OrdemCompra.status.in_(["Pendente", "Aguardando 2a Aprovacao"])
    ).all()
    total_pendentes = len(ordens_pendentes)
    valor_pendente  = sum(float(o.valor or 0) for o in ordens_pendentes)
    total_ordens    = OrdemCompra.query.count()

    aprovadores = (
        db.session.query(OrdemCompra.aprovador)
        .filter(OrdemCompra.aprovador.isnot(None))
        .distinct().all()
    )
    saldos_aprovadores = (
        db.session.query(SaldoAprovador)
        .join(Usuario, Usuario.nome == SaldoAprovador.nome_aprovador)
        .filter(Usuario.perfil == "aprovador")
        .order_by(SaldoAprovador.nome_aprovador)
        .all()
    )
    centros_custo = [
        c[0] for c in db.session.query(OrdemCompra.centro_custo).distinct().all() if c[0]
    ]
    fornecedores = [
        f[0] for f in db.session.query(OrdemCompra.fornecedor).distinct().all() if f[0]
    ]

    from sqlalchemy import extract
    ano_atual = datetime.now().year
    gastos_por_centro = (
        db.session.query(OrdemCompra.centro_custo, func.sum(OrdemCompra.valor))
        .filter(OrdemCompra.status == "Aprovada")
        .filter(OrdemCompra.centro_custo.isnot(None))
        .filter(OrdemCompra.centro_custo != "")
        .filter(extract("year", OrdemCompra.aprovado_em) == ano_atual)
        .group_by(OrdemCompra.centro_custo)
        .all()
    )
    labels_centros  = [g[0] for g in gastos_por_centro]
    valores_centros = [float(g[1] or 0) for g in gastos_por_centro]

    nomes_aprovadores_pendentes = [
        a[0] for a in (
            db.session.query(OrdemCompra.aprovador)
            .filter(OrdemCompra.status.in_(["Pendente", "Aguardando 2a Aprovacao"]))
            .filter(OrdemCompra.aprovador.isnot(None))
            .distinct().all()
        )
    ]

    page = request.args.get("page", 1, type=int)
    paginacao = Produto.query.order_by(Produto.nome).paginate(
        page=page, per_page=10, error_out=False
    )
    produtos_classificados = []
    for p in paginacao.items:
        minimo = p.estoque_minimo or 0
        atual  = p.estoque_atual  or 0
        if atual <= minimo:          status = "critico"
        elif atual <= minimo * 1.3:  status = "atencao"
        else:                        status = "normal"
        produtos_classificados.append({
            "nome": p.nome, "estoque_atual": atual,
            "estoque_minimo": minimo, "status": status
        })

    return render_template(
        "dashboard.html",
        total_pendentes=total_pendentes,
        valor_pendente=valor_pendente,
        total_ordens=total_ordens,
        aprovadores=aprovadores,
        saldos_aprovadores=saldos_aprovadores,
        centros_custo=centros_custo,
        fornecedores=fornecedores,
        ordens_pendentes=ordens_pendentes,
        labels_centros=labels_centros,
        valores_centros=valores_centros,
        nomes_aprovadores_pendentes=nomes_aprovadores_pendentes,
        produtos_classificados=produtos_classificados,
        paginacao=paginacao
    )

# ===============================
# FUNCIONARIOS
# ===============================
@app.route("/funcionarios", methods=["GET", "POST"])
@login_required
def funcionarios():
    if request.method == "POST":
        nome       = request.form.get("nome")
        email      = request.form.get("email")
        senha      = request.form.get("senha")
        perfil     = request.form.get("perfil")
        limite_str = request.form.get("limite_aprovacao", "").strip()

        if not all([nome, email, senha, perfil]):
            flash("Preencha todos os campos.", "warning")
            return redirect(url_for("funcionarios"))
        if Usuario.query.filter_by(email=email).first():
            flash("Email ja cadastrado.", "warning")
            return redirect(url_for("funcionarios"))

        limite = None
        if perfil == "aprovador" and limite_str:
            try:
                limite = float(limite_str)
            except ValueError:
                pass

        db.session.add(Usuario(
            nome=nome, email=email,
            senha=generate_password_hash(senha),
            perfil=perfil, limite_aprovacao=limite
        ))
        db.session.commit()
        flash("Funcionario cadastrado com sucesso.", "success")
        return redirect(url_for("funcionarios"))

    usuarios = Usuario.query.order_by(Usuario.id.desc()).all()
    return render_template("funcionarios.html", funcionarios=usuarios)

@app.route("/funcionarios/editar/<int:usuario_id>")
@login_required
def editar_funcionario(usuario_id):
    flash("Edicao de funcionario sera habilitada futuramente.", "info")
    return redirect(url_for("funcionarios"))

@app.route("/funcionarios/excluir/<int:usuario_id>", methods=["POST"])
@login_required
def excluir_funcionario(usuario_id):
    usuario = Usuario.query.get_or_404(usuario_id)
    if usuario.id == current_user.id:
        flash("Voce nao pode excluir seu proprio usuario.", "danger")
        return redirect(url_for("funcionarios"))
    db.session.delete(usuario)
    db.session.commit()
    flash("Funcionario excluido com sucesso.", "success")
    return redirect(url_for("funcionarios"))

# ===============================
# FINANCEIRO
# ===============================
@app.route("/financeiro")
@login_required
def financeiro():
    if current_user.perfil not in ["admin", "financeiro"]:
        flash("Acesso restrito.", "danger")
        return redirect(url_for("dashboard"))
    centros_custo      = CentroCusto.query.order_by(CentroCusto.nome).all()
    aprovadores        = Usuario.query.filter_by(perfil="aprovador").order_by(Usuario.nome).all()
    saldos_aprovadores = {s.nome_aprovador: s for s in SaldoAprovador.query.all()}
    return render_template(
        "financeiro.html",
        centros_custo=centros_custo,
        aprovadores=aprovadores,
        saldos_aprovadores=saldos_aprovadores
    )

@app.route("/financeiro/aprovador/editar/<string:nome_aprovador>", methods=["POST"])
@login_required
def editar_saldo_aprovador(nome_aprovador):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    valor    = float(request.form.get("saldo", 0))
    registro = SaldoAprovador.query.filter_by(nome_aprovador=nome_aprovador).first()
    if not registro:
        registro = SaldoAprovador(nome_aprovador=nome_aprovador, saldo=0)
        db.session.add(registro)
    registro.saldo = valor
    db.session.commit()
    flash(f"Saldo de {nome_aprovador} definido para R$ {valor:.2f}.", "success")
    return redirect(url_for("financeiro"))

@app.route("/financeiro/aprovador/creditar/<string:nome_aprovador>", methods=["POST"])
@login_required
def creditar_aprovador(nome_aprovador):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    try:
        credito = float(request.form.get("credito", 0))
    except (ValueError, TypeError):
        flash("Valor de credito invalido.", "danger")
        return redirect(url_for("financeiro"))
    if credito <= 0:
        flash("O valor de credito deve ser maior que zero.", "warning")
        return redirect(url_for("financeiro"))
    registro = SaldoAprovador.query.filter_by(nome_aprovador=nome_aprovador).first()
    if not registro:
        registro = SaldoAprovador(nome_aprovador=nome_aprovador, saldo=0)
        db.session.add(registro)
    registro.saldo = (registro.saldo or 0) + credito
    db.session.commit()
    flash(f"R$ {credito:.2f} adicionados a {nome_aprovador}. Novo saldo: R$ {registro.saldo:.2f}.", "success")
    return redirect(url_for("financeiro"))

@app.route("/financeiro/centro_custo/editar/<int:centro_id>", methods=["POST"])
@login_required
def editar_saldo_centro_custo(centro_id):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    centro        = CentroCusto.query.get_or_404(centro_id)
    centro.saldo  = float(request.form.get("saldo", 0))
    db.session.commit()
    flash(f"Saldo de '{centro.nome}' definido para R$ {centro.saldo:.2f}.", "success")
    return redirect(url_for("financeiro"))

@app.route("/financeiro/centro_custo/creditar/<int:centro_id>", methods=["POST"])
@login_required
def creditar_centro_custo(centro_id):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    centro = CentroCusto.query.get_or_404(centro_id)
    try:
        credito = float(request.form.get("credito", 0))
    except (ValueError, TypeError):
        flash("Valor de credito invalido.", "danger")
        return redirect(url_for("financeiro"))
    if credito <= 0:
        flash("O valor de credito deve ser maior que zero.", "warning")
        return redirect(url_for("financeiro"))
    centro.saldo = (centro.saldo or 0) + credito
    db.session.commit()
    flash(f"R$ {credito:.2f} adicionados a '{centro.nome}'. Novo saldo: R$ {centro.saldo:.2f}.", "success")
    return redirect(url_for("financeiro"))

# ===============================
# EXCLUIR CENTRO DE CUSTO
# ===============================
@app.route("/centro_custo/excluir/<int:centro_id>", methods=["POST"])
@login_required
def excluir_centro_custo_fin(centro_id):
    if current_user.perfil != "admin":
        abort(403)
    centro = CentroCusto.query.get_or_404(centro_id)
    if OrdemCompra.query.filter_by(centro_custo=centro.nome).first():
        flash("Centro de custo vinculado a ordens, nao pode ser excluido.", "warning")
        return redirect(url_for("fornecedores"))
    db.session.delete(centro)
    db.session.commit()
    flash("Centro de custo excluido com sucesso.", "success")
    return redirect(url_for("fornecedores"))

# ===============================
# FORNECEDORES
# ===============================
@app.route("/fornecedores")
@login_required
def fornecedores():
    return render_template(
        "fornecedores.html",
        fornecedores=Fornecedor.query.order_by(Fornecedor.nome).all(),
        centros_custo=CentroCusto.query.order_by(CentroCusto.nome).all()
    )

@app.route("/fornecedores/novo_fornecedor", methods=["POST"])
@login_required
def salvar_fornecedor():
    nome = request.form.get("nome")
    if not nome:
        return redirect(url_for("fornecedores"))
    if Fornecedor.query.filter_by(nome=nome).first():
        flash("Fornecedor ja existe.", "warning")
        return redirect(url_for("fornecedores"))
    db.session.add(Fornecedor(nome=nome))
    db.session.commit()
    flash("Fornecedor cadastrado com sucesso", "success")
    return redirect(url_for("fornecedores"))

@app.route("/fornecedores/excluir/<int:fornecedor_id>", methods=["POST"])
@login_required
def excluir_fornecedor(fornecedor_id):
    fornecedor = Fornecedor.query.get_or_404(fornecedor_id)
    db.session.delete(fornecedor)
    db.session.commit()
    flash("Fornecedor excluido com sucesso", "success")
    return redirect(url_for("fornecedores"))

# ===============================
# NOVO CENTRO DE CUSTO
# ===============================
@app.route("/financeiro/centro_custo/novo", methods=["POST"])
@login_required
def novo_centro_custo():
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    nome  = request.form.get("nome")
    saldo = float(request.form.get("saldo", 0))
    if not nome:
        flash("Nome do centro de custo e obrigatorio.", "warning")
        return redirect(url_for("financeiro"))
    if CentroCusto.query.filter_by(nome=nome).first():
        flash("Centro de custo ja existe.", "warning")
        return redirect(url_for("financeiro"))
    db.session.add(CentroCusto(nome=nome, saldo=saldo))
    db.session.commit()
    flash("Centro de custo criado com sucesso.", "success")
    return redirect(url_for("financeiro"))

# ===============================
# ORDENS
# ===============================
@app.route("/ordens")
@login_required
def ordens():
    lista       = OrdemCompra.query.order_by(OrdemCompra.id.desc()).all()
    aprovadores = Usuario.query.filter_by(perfil="aprovador").order_by(Usuario.nome).all()
    return render_template("ordens.html", ordens=lista, aprovadores=aprovadores)

# ===============================
# EDITAR APROVADOR DE ORDEM
# ===============================
@app.route("/ordens/editar_aprovador/<int:ordem_id>", methods=["POST"])
@login_required
def editar_aprovador_ordem(ordem_id):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    if ordem.status != "Pendente":
        flash("So e possivel editar o aprovador de ordens pendentes.", "warning")
        return redirect(url_for("ordens"))
    novo_aprovador = request.form.get("aprovador", "").strip()
    if not novo_aprovador:
        flash("Selecione um aprovador valido.", "warning")
        return redirect(url_for("ordens"))
    ordem.aprovador = novo_aprovador
    db.session.commit()
    flash(f"Aprovador da ordem #{ordem_id} atualizado para {novo_aprovador}.", "success")
    return redirect(url_for("ordens"))

# ===============================
# NOVA ORDEM
# ===============================
@app.route("/nova_ordem", methods=["GET", "POST"])
@login_required
def nova_ordem():
    fornecedores_list  = Fornecedor.query.order_by(Fornecedor.nome).all()
    centros_custo_list = CentroCusto.query.order_by(CentroCusto.nome).all()
    todos_produtos     = Produto.query.order_by(Produto.nome).all()

    aprovadores_com_limite = (
        Usuario.query.filter_by(perfil="aprovador")
        .filter(Usuario.limite_aprovacao.isnot(None))
        .order_by(Usuario.limite_aprovacao.asc()).all()
    )
    aprovadores_sem_limite = (
        Usuario.query.filter_by(perfil="aprovador")
        .filter(Usuario.limite_aprovacao.is_(None))
        .order_by(Usuario.nome).all()
    )
    aprovadores_faixas = aprovadores_com_limite + aprovadores_sem_limite

    if request.method == "POST":
        fornecedor        = request.form.get("fornecedor")
        centro_custo      = request.form.get("centro_custo")
        aprovador         = request.form.get("aprovador")
        produtos_ids      = request.form.getlist("produto_id[]")
        quantidades       = request.form.getlist("quantidade[]")
        valores_unitarios = request.form.getlist("valor_unitario[]")

        if not fornecedor or not centro_custo:
            flash("Fornecedor e Centro de Custo sao obrigatorios.", "warning")
            return redirect(url_for("nova_ordem"))
        if not produtos_ids:
            flash("Adicione pelo menos um produto.", "warning")
            return redirect(url_for("nova_ordem"))

        nova = OrdemCompra(
            fornecedor=fornecedor, centro_custo=centro_custo,
            aprovador=aprovador, descricao_itens="", valor=0
        )
        db.session.add(nova)
        db.session.flush()

        total = 0
        descricao_auto = []
        for i in range(len(produtos_ids)):
            try:
                pid  = int(produtos_ids[i])
                qtd  = int(quantidades[i])
                vuni = float(valores_unitarios[i])
            except (ValueError, IndexError):
                continue
            if qtd <= 0 or vuni < 0:
                continue
            produto = Produto.query.get(pid)
            if not produto:
                continue
            total += qtd * vuni
            descricao_auto.append(f"{produto.nome} ({qtd} un)")
            db.session.add(ItemOrdem(
                ordem_id=nova.id, produto_id=pid,
                quantidade=qtd, valor_unitario=vuni
            ))

        if total == 0:
            flash("Valores invalidos na ordem.", "warning")
            db.session.rollback()
            return redirect(url_for("nova_ordem"))

        nova.valor           = total
        nova.descricao_itens = "\n".join(descricao_auto)
        db.session.commit()
        flash("Ordem criada com sucesso.", "success")
        return redirect(url_for("ordens"))

    produtos_json = [{"id": p.id, "nome": p.nome} for p in todos_produtos]
    return render_template(
        "nova_ordem.html",
        fornecedores=fornecedores_list,
        centros_custo=centros_custo_list,
        produtos=produtos_json,
        aprovadores_faixas=aprovadores_faixas
    )

# ===============================
# 1a APROVACAO
# ===============================
@app.route("/aprovar/<int:ordem_id>", methods=["POST"])
@login_required
def aprovar(ordem_id):
    if current_user.perfil not in ["admin", "aprovador"]:
        abort(403)

    ordem = OrdemCompra.query.get_or_404(ordem_id)
    if ordem.status != "Pendente":
        flash("Esta ordem nao esta pendente.", "warning")
        return redirect(url_for("ordens"))

    valor    = float(ordem.valor or 0)
    saldo_ap = SaldoAprovador.query.filter_by(nome_aprovador=ordem.aprovador).first()
    if not saldo_ap or saldo_ap.saldo < valor:
        flash("Saldo insuficiente do aprovador.", "danger")
        return redirect(url_for("ordens"))
    centro = CentroCusto.query.filter_by(nome=ordem.centro_custo).first()
    if not centro or (centro.saldo or 0) < valor:
        flash("Centro de custo sem saldo.", "danger")
        return redirect(url_for("ordens"))

    saldo_ap.saldo -= valor
    centro.saldo   -= valor
    ordem.aprovado_por = current_user.nome
    ordem.aprovado_em  = datetime.now()

    if (ordem.centro_custo or "").strip().lower() == CENTRO_DUPLA_APROVACAO.lower():
        ordem.status = "Aguardando 2a Aprovacao"
        admin = Usuario.query.filter_by(perfil="admin").first()
        ordem.aprovador_2 = admin.nome if admin else "admin"
        db.session.commit()
        flash(
            f"1a aprovacao registrada por {current_user.nome}. "
            f"Ordem aguarda 2a aprovacao de {ordem.aprovador_2}.",
            "info"
        )
    else:
        ordem.status = "Aprovada"
        for item in ordem.itens:
            if item.produto:
                item.produto.estoque_atual = max(
                    0, (item.produto.estoque_atual or 0) - item.quantidade
                )
        db.session.commit()
        flash("Ordem aprovada com sucesso.", "success")

    return redirect(url_for("ordens"))

# ===============================
# 2a APROVACAO (FUNDOS_CQP)
# ===============================
@app.route("/ordens/segunda_aprovacao/<int:ordem_id>", methods=["POST"])
@login_required
def segunda_aprovacao(ordem_id):
    if current_user.perfil not in ["admin", "aprovador"]:
        abort(403)

    ordem = OrdemCompra.query.get_or_404(ordem_id)
    if ordem.status != "Aguardando 2a Aprovacao":
        flash("Esta ordem nao esta aguardando 2a aprovacao.", "warning")
        return redirect(url_for("ordens"))

    if ordem.aprovado_por == current_user.nome:
        flash("Voce ja realizou a 1a aprovacao. A 2a aprovacao deve ser feita por outro usuario.", "danger")
        return redirect(url_for("ordens"))

    ordem.status        = "Aprovada"
    ordem.aprovado_por_2 = current_user.nome
    ordem.aprovado_em_2  = datetime.now()

    for item in ordem.itens:
        if item.produto:
            item.produto.estoque_atual = max(
                0, (item.produto.estoque_atual or 0) - item.quantidade
            )

    db.session.commit()
    flash(f"2a aprovacao registrada por {current_user.nome}. Ordem finalizada.", "success")
    return redirect(url_for("ordens"))

# ===============================
# REPROVAR
# ===============================
@app.route("/ordens/reprovar/<int:ordem_id>", methods=["POST"])
@login_required
def reprovar_ordem(ordem_id):
    if current_user.perfil not in ["admin", "aprovador"]:
        abort(403)
    ordem = OrdemCompra.query.get_or_404(ordem_id)

    if ordem.aprovado_por and ordem.status == "Aguardando 2a Aprovacao":
        valor    = float(ordem.valor or 0)
        saldo_ap = SaldoAprovador.query.filter_by(nome_aprovador=ordem.aprovador).first()
        centro   = CentroCusto.query.filter_by(nome=ordem.centro_custo).first()
        if saldo_ap:
            saldo_ap.saldo = (saldo_ap.saldo or 0) + valor
        if centro:
            centro.saldo = (centro.saldo or 0) + valor

    ordem.status       = "Reprovada"
    ordem.aprovado_por = current_user.nome
    ordem.aprovado_em  = datetime.now()
    db.session.commit()
    flash("Ordem reprovada com sucesso.", "warning")
    return redirect(url_for("ordens"))

@app.route("/ordens/excluir/<int:ordem_id>", methods=["POST"])
@login_required
def excluir_ordem(ordem_id):
    if current_user.perfil != "admin":
        abort(403)
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    db.session.delete(ordem)
    db.session.commit()
    flash("Ordem excluida.", "success")
    return redirect(url_for("ordens"))

# ===============================
# RELATORIOS
# ===============================
@app.route("/relatorios")
@login_required
def relatorios():
    return render_template(
        "relatorios.html",
        ordens=OrdemCompra.query.order_by(OrdemCompra.id.desc()).all(),
        centros=CentroCusto.query.order_by(CentroCusto.nome).all(),
        aprovadores=Usuario.query.filter_by(perfil="aprovador").all()
    )

@app.route("/relatorios/anexar_nf/<int:ordem_id>", methods=["POST"])
@login_required
def anexar_nf(ordem_id):
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    file  = request.files.get("nota_fiscal")
    if not file:
        return redirect(url_for("relatorios"))
    os.makedirs(os.path.join("static", "notas_fiscais"), exist_ok=True)
    filename = secure_filename(file.filename)
    file.save(os.path.join("static", "notas_fiscais", filename))
    ordem.nota_fiscal = filename
    db.session.commit()
    return redirect(url_for("relatorios"))

@app.route("/relatorios/excluir/<int:ordem_id>", methods=["POST"])
@login_required
def excluir_ordem_relatorio(ordem_id):
    if current_user.perfil != "admin":
        abort(403)
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    db.session.delete(ordem)
    db.session.commit()
    return redirect(url_for("relatorios"))

# ===============================
# HELPERS PDF — cabecalho e rodape
# ===============================
def _path_static(filename):
    """Retorna caminho absoluto para arquivo dentro de static/."""
    base = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base, "static", filename)

def _draw_cabecalho_rodape(c, doc):
    largura, altura = A4

    logo_path = _path_static("logo_escola.png")
    logo_x    = 1.8 * cm
    logo_y    = altura - 3.5 * cm
    logo_w    = 3.5 * cm
    logo_h    = 3.5 * cm
    if os.path.exists(logo_path):
        c.drawImage(logo_path, logo_x, logo_y,
                    width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask="auto")

    texto_x = logo_x + logo_w + 0.5 * cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(texto_x, altura - 1.5 * cm, "CENTRO DE QUALIFICAÇÃO PROFISSIONAL CQP")
    c.setFont("Helvetica", 9)
    c.drawString(texto_x, altura - 2.1 * cm, "CNPJ: 39.368.679/0001-01")
    c.drawString(texto_x, altura - 2.6 * cm, "Rua: Prata Mancebo nº 148 - Centro  |  Carapebús - RJ  |  CEP 27998-000")
    c.drawString(texto_x, altura - 3.1 * cm, "Tel.: (22) 99868-4334  |  centrodequalificacao@cqpcursos.com.br")

    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.5)
    c.line(1.8 * cm, altura - 3.8 * cm, largura - 1.8 * cm, altura - 3.8 * cm)

    rodape_y = 3.5 * cm
    c.line(1.8 * cm, rodape_y + 0.3 * cm, largura - 1.8 * cm, rodape_y + 0.3 * cm)

    assinatura_path = _path_static("assinatura.png")
    ass_w = 4.0 * cm
    ass_h = 1.8 * cm
    ass_x = (largura - ass_w) / 2
    ass_y = rodape_y + 0.5 * cm
    if os.path.exists(assinatura_path):
        c.drawImage(assinatura_path, ass_x, ass_y,
                    width=ass_w, height=ass_h,
                    preserveAspectRatio=True, mask="auto")

    linha_y = rodape_y - 0.1 * cm
    c.line(ass_x - 0.5 * cm, linha_y,
           ass_x + ass_w + 0.5 * cm, linha_y)

    c.setFont("Helvetica", 8)
    c.drawCentredString(largura / 2, linha_y - 0.4 * cm,
                        "Centro de Qualificação Profissional")

    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawRightString(largura - 1.8 * cm, 1.5 * cm,
                      f"Página {doc.page}")
    c.setFillColorRGB(0, 0, 0)


# ===============================
# EXPORTAR EXCEL
# ===============================
@app.route("/relatorios/excel")
@login_required
def relatorios_excel():
    ordens = OrdemCompra.query.order_by(OrdemCompra.id.desc()).all()
    dados  = [{
        "ID": o.id, "Fornecedor": o.fornecedor,
        "Centro de Custo": o.centro_custo,
        "Valor (R$)": float(o.valor or 0),
        "Aprovador": o.aprovado_por or "",
        "Data de Compra": o.data_compra.strftime("%d/%m/%Y") if o.data_compra else "",
        "Status": o.status
    } for o in ordens]
    df     = pd.DataFrame(dados)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Ordens")
    output.seek(0)
    return send_file(
        output, as_attachment=True,
        download_name="relatorio_ordens.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ===============================
# EXPORTAR PDF
# ===============================
@app.route("/relatorios/pdf")
@login_required
def relatorios_pdf():
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    ordens = OrdemCompra.query.order_by(OrdemCompra.id.desc()).all()

    output = io.BytesIO()

    margem_topo    = 4.5 * cm
    margem_base    = 4.5 * cm
    margem_lateral = 1.8 * cm

    doc = BaseDocTemplate(
        output,
        pagesize=A4,
        topMargin=margem_topo,
        bottomMargin=margem_base,
        leftMargin=margem_lateral,
        rightMargin=margem_lateral,
    )

    frame = Frame(
        margem_lateral, margem_base,
        A4[0] - 2 * margem_lateral,
        A4[1] - margem_topo - margem_base,
        id="conteudo"
    )

    template = PageTemplate(
        id="cqp",
        frames=[frame],
        onPage=_draw_cabecalho_rodape
    )
    doc.addPageTemplates([template])

    styles = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=styles["Heading1"],
                            alignment=TA_CENTER, fontSize=13, spaceAfter=12)
    gerado = ParagraphStyle("gerado", parent=styles["Normal"],
                            alignment=TA_CENTER, fontSize=8,
                            textColor=colors.grey, spaceAfter=16)

    story = [
        Paragraph("Relatório de Ordens de Compra", titulo),
        Paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}  |  "
            f"Por: {current_user.nome}",
            gerado
        ),
    ]

    cabecalho = [["ID", "Fornecedor", "Centro de Custo",
                  "Valor (R$)", "Aprovador", "Data de Compra", "Status"]]
    dados = []
    for o in ordens:
        dados.append([
            str(o.id),
            o.fornecedor or "",
            o.centro_custo or "",
            f"R$ {float(o.valor or 0):.2f}",
            o.aprovado_por or "",
            o.data_compra.strftime("%d/%m/%Y") if o.data_compra else "",
            o.status or ""
        ])

    tabela_dados = cabecalho + dados
    largura_util = A4[0] - 2 * margem_lateral
    col_widths = [
        0.08 * largura_util,  # ID
        0.18 * largura_util,  # Fornecedor
        0.18 * largura_util,  # Centro de Custo
        0.13 * largura_util,  # Valor (R$)
        0.15 * largura_util,  # Aprovador
        0.15 * largura_util,  # Data de Compra
        0.13 * largura_util,  # Status
    ]

    tbl = Table(tabela_dados, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#005f63")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  8),
        ("FONTSIZE",      (0, 1), (-1, -1), 7.5),
        ("WORDWRAP",      (0, 0), (-1, 0),  True),
        ("ALIGN",         (3, 1), (3, -1),  "RIGHT"),
        ("ALIGN",         (5, 0), (5, -1),  "CENTER"),
        ("ALIGN",         (6, 1), (6, -1),  "CENTER"),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#aaaaaa")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f2f9f9")]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]))

    story.append(tbl)
    doc.build(story)

    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="relatorio_ordens.pdf",
        mimetype="application/pdf"
    )

@app.route("/relatorios/data_compra/<int:ordem_id>", methods=["POST"])
@login_required
def salvar_data_compra(ordem_id):
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    data  = request.form.get("data_compra")
    if data:
        try:
            ordem.data_compra = datetime.strptime(data, "%Y-%m-%d").date()
            db.session.commit()
        except ValueError:
            pass
    return redirect(url_for("relatorios"))

# ===============================
# PRODUTOS (ESTOQUE)
# ===============================
@app.route("/produtos", methods=["GET", "POST"])
@login_required
def produtos():
    if request.method == "POST":
        if request.form.get("produto_id") and request.form.get("ajuste"):
            try:
                produto = Produto.query.get(int(request.form.get("produto_id")))
                ajuste  = int(request.form.get("ajuste"))
                if produto:
                    produto.estoque_atual = max(0, (produto.estoque_atual or 0) + ajuste)
                    db.session.commit()
                    flash("Estoque atualizado com sucesso.", "success")
            except Exception:
                flash("Erro ao atualizar estoque.", "danger")
            return redirect(url_for("produtos"))

        nome           = request.form.get("nome")
        estoque_atual  = int(request.form.get("estoque_atual",  0))
        estoque_minimo = int(request.form.get("estoque_minimo", 0))
        if not nome:
            flash("Nome do produto e obrigatorio.", "warning")
            return redirect(url_for("produtos"))
        if Produto.query.filter_by(nome=nome).first():
            flash("Produto ja cadastrado.", "warning")
            return redirect(url_for("produtos"))
        db.session.add(Produto(
            nome=nome, estoque_atual=estoque_atual, estoque_minimo=estoque_minimo
        ))
        db.session.commit()
        flash("Produto cadastrado com sucesso.", "success")
        return redirect(url_for("produtos"))

    return render_template("produtos.html", produtos=Produto.query.order_by(Produto.nome).all())

# ===============================
# EDITAR PRODUTO
# ===============================
@app.route("/produtos/editar/<int:produto_id>", methods=["POST"])
@login_required
def editar_produto(produto_id):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    produto        = Produto.query.get_or_404(produto_id)
    nome           = request.form.get("nome", "").strip()
    estoque_atual  = request.form.get("estoque_atual", "")
    estoque_minimo = request.form.get("estoque_minimo", "")
    if not nome:
        flash("Nome do produto e obrigatorio.", "warning")
        return redirect(url_for("produtos"))
    outro = Produto.query.filter_by(nome=nome).first()
    if outro and outro.id != produto_id:
        flash("Ja existe outro produto com esse nome.", "warning")
        return redirect(url_for("produtos"))
    try:
        produto.nome           = nome
        produto.estoque_atual  = int(estoque_atual)
        produto.estoque_minimo = int(estoque_minimo)
        db.session.commit()
        flash("Produto atualizado com sucesso.", "success")
    except (ValueError, TypeError):
        flash("Valores de estoque invalidos.", "danger")
    return redirect(url_for("produtos"))

# ===============================
# EXCLUIR PRODUTO
# ===============================
@app.route("/produtos/excluir/<int:produto_id>", methods=["POST"])
@login_required
def excluir_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    if ItemOrdem.query.filter_by(produto_id=produto_id).first():
        flash("Produto vinculado a uma ordem, nao pode ser excluido.", "warning")
        return redirect(url_for("produtos"))
    db.session.delete(produto)
    db.session.commit()
    flash("Produto excluido com sucesso.", "success")
    return redirect(url_for("produtos"))

# ===============================
# START
# ===============================
with app.app_context():
    db.create_all()
    migrations = [
        "ALTER TABLE usuarios ADD COLUMN limite_aprovacao REAL",
        "ALTER TABLE ordens_compra ADD COLUMN aprovador_2 TEXT",
        "ALTER TABLE ordens_compra ADD COLUMN aprovado_por_2 TEXT",
        "ALTER TABLE ordens_compra ADD COLUMN aprovado_em_2 DATETIME",
        "ALTER TABLE ordens_compra ADD COLUMN data_compra DATE",
    ]
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
