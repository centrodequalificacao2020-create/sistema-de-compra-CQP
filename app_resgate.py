print("### ESTE APP_RESAGATE ESTA SENDO EXECUTADO ###")

import io
import pandas as pd
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

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
from sqlalchemy import func
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

# ===============================
# CONFIGURAÇÃO DE E-MAIL (ZOHO)
# ===============================
EMAIL_REMETENTE = "sistema@cqpcursos.com.br"
EMAIL_DESTINO = "compras@cqpcursos.com.br"
EMAIL_SMTP = "smtp.zoho.com"
EMAIL_PORTA = 587
EMAIL_SENHA = os.environ.get("EMAIL_SENHA", "")

def enviar_email_nova_ordem(ordem):
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_REMETENTE
        msg["To"] = EMAIL_DESTINO
        msg["Subject"] = "Nova ordem de compra criada"

        corpo = f"""
Olá,

Uma nova ordem de compra foi criada e aguarda aprovação.

Fornecedor: {ordem.fornecedor}
Centro de Custo: {ordem.centro_custo}
Valor: R$ {float(ordem.valor or 0):.2f}
Aprovador: {ordem.aprovador}

Sistema de Ordem de Compra - CQP
        """

        msg.set_content(corpo)

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
    DB_PATH = os.path.join(BASE_DIR, "instance", "ordem_compra.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
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
        flash("Email ou senha inválidos", "danger")
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

    ordens_pendentes = OrdemCompra.query.filter_by(status="Pendente").all()
    total_pendentes = len(ordens_pendentes)
    valor_pendente = sum(float(o.valor or 0) for o in ordens_pendentes)

    total_ordens = OrdemCompra.query.count()

    aprovadores = (
        db.session.query(OrdemCompra.aprovador)
        .filter(OrdemCompra.aprovador.isnot(None))
        .distinct()
        .all()
    )

    saldos_aprovadores = (
        db.session.query(SaldoAprovador)
        .join(Usuario, Usuario.nome == SaldoAprovador.nome_aprovador)
        .filter(Usuario.perfil == "aprovador")
        .order_by(SaldoAprovador.nome_aprovador)
        .all()
    )

    centros_custo = [
        c[0] for c in db.session.query(OrdemCompra.centro_custo)
        .distinct().all() if c[0]
    ]

    fornecedores = [
        f[0] for f in db.session.query(OrdemCompra.fornecedor)
        .distinct().all() if f[0]
    ]

    from sqlalchemy import extract
    ano_atual = datetime.now().year

    gastos_por_centro = (
        db.session.query(
            OrdemCompra.centro_custo,
            func.sum(OrdemCompra.valor)
        )
        .filter(OrdemCompra.status == "Aprovada")
        .filter(OrdemCompra.centro_custo.isnot(None))
        .filter(OrdemCompra.centro_custo != "")
        .filter(extract("year", OrdemCompra.aprovado_em) == ano_atual)
        .group_by(OrdemCompra.centro_custo)
        .all()
    )

    labels_centros = [g[0] for g in gastos_por_centro]
    valores_centros = [float(g[1] or 0) for g in gastos_por_centro]

    aprovadores_pendentes = (
        db.session.query(OrdemCompra.aprovador)
        .filter(OrdemCompra.status == "Pendente")
        .filter(OrdemCompra.aprovador.isnot(None))
        .distinct()
        .all()
    )

    nomes_aprovadores_pendentes = [a[0] for a in aprovadores_pendentes]

    page = request.args.get("page", 1, type=int)

    paginacao = Produto.query.order_by(Produto.nome).paginate(
        page=page,
        per_page=10,
        error_out=False
    )

    produtos = paginacao.items
    produtos_classificados = []

    for p in produtos:
        minimo = p.estoque_minimo or 0
        atual = p.estoque_atual or 0

        if atual <= minimo:
            status = "critico"
        elif atual <= minimo * 1.3:
            status = "atencao"
        else:
            status = "normal"

        produtos_classificados.append({
            "nome": p.nome,
            "estoque_atual": atual,
            "estoque_minimo": minimo,
            "status": status
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
# FUNCIONÁRIOS
# ===============================
@app.route("/funcionarios", methods=["GET", "POST"])
@login_required
def funcionarios():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")
        perfil = request.form.get("perfil")

        if not nome or not email or not senha or not perfil:
            flash("Preencha todos os campos.", "warning")
            return redirect(url_for("funcionarios"))

        if Usuario.query.filter_by(email=email).first():
            flash("Email já cadastrado.", "warning")
            return redirect(url_for("funcionarios"))

        usuario = Usuario(
            nome=nome,
            email=email,
            senha=generate_password_hash(senha),
            perfil=perfil
        )
        db.session.add(usuario)
        db.session.commit()

        flash("Funcionário cadastrado com sucesso.", "success")
        return redirect(url_for("funcionarios"))

    usuarios = Usuario.query.order_by(Usuario.id.desc()).all()
    return render_template("funcionarios.html", funcionarios=usuarios)

@app.route("/funcionarios/editar/<int:usuario_id>")
@login_required
def editar_funcionario(usuario_id):
    flash("Edição de funcionário será habilitada futuramente.", "info")
    return redirect(url_for("funcionarios"))

@app.route("/funcionarios/excluir/<int:usuario_id>", methods=["POST"])
@login_required
def excluir_funcionario(usuario_id):
    usuario = Usuario.query.get_or_404(usuario_id)
    if usuario.id == current_user.id:
        flash("Você não pode excluir seu próprio usuário.", "danger")
        return redirect(url_for("funcionarios"))

    db.session.delete(usuario)
    db.session.commit()
    flash("Funcionário excluído com sucesso.", "success")
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

    centros_custo = CentroCusto.query.order_by(CentroCusto.nome).all()
    aprovadores = Usuario.query.filter_by(perfil="aprovador").order_by(Usuario.nome).all()
    saldos_aprovadores = {
        s.nome_aprovador: s for s in SaldoAprovador.query.all()
    }

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
    valor = float(request.form.get("saldo", 0))
    registro = SaldoAprovador.query.filter_by(nome_aprovador=nome_aprovador).first()
    if not registro:
        registro = SaldoAprovador(nome_aprovador=nome_aprovador, saldo=0)
        db.session.add(registro)
    registro.saldo = valor
    db.session.commit()
    return redirect(url_for("financeiro"))

@app.route("/financeiro/centro_custo/editar/<int:centro_id>", methods=["POST"])
@login_required
def editar_saldo_centro_custo(centro_id):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    centro = CentroCusto.query.get_or_404(centro_id)
    centro.saldo = float(request.form.get("saldo", 0))
    db.session.commit()
    flash("Saldo do centro de custo atualizado.", "success")
    return redirect(url_for("financeiro"))

# ===============================
# EXCLUIR CENTRO DE CUSTO (ADMIN)
# ===============================
@app.route("/centro_custo/excluir/<int:centro_id>", methods=["POST"])
@login_required
def excluir_centro_custo_fin(centro_id):
    if current_user.perfil != "admin":
        abort(403)

    centro = CentroCusto.query.get_or_404(centro_id)
    ordem_vinculada = OrdemCompra.query.filter_by(centro_custo=centro.nome).first()
    if ordem_vinculada:
        flash("Este centro de custo não pode ser excluído porque está vinculado a ordens.", "warning")
        return redirect(url_for("fornecedores"))

    db.session.delete(centro)
    db.session.commit()
    flash("Centro de custo excluído com sucesso.", "success")
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
        flash("Fornecedor já existe.", "warning")
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
    flash("Fornecedor excluído com sucesso", "success")
    return redirect(url_for("fornecedores"))

# ===============================
# NOVO CENTRO DE CUSTO
# ===============================
@app.route("/financeiro/centro_custo/novo", methods=["POST"])
@login_required
def novo_centro_custo():
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)
    nome = request.form.get("nome")
    saldo = float(request.form.get("saldo", 0))

    if not nome:
        flash("Nome do centro de custo é obrigatório.", "warning")
        return redirect(url_for("financeiro"))

    if CentroCusto.query.filter_by(nome=nome).first():
        flash("Centro de custo já existe.", "warning")
        return redirect(url_for("financeiro"))

    centro = CentroCusto(nome=nome, saldo=saldo)
    db.session.add(centro)
    db.session.commit()
    flash("Centro de custo criado com sucesso.", "success")
    return redirect(url_for("financeiro"))

# ===============================
# ORDENS
# ===============================
@app.route("/ordens")
@login_required
def ordens():
    return render_template(
        "ordens.html",
        ordens=OrdemCompra.query.order_by(OrdemCompra.id.desc()).all()
    )

@app.route("/nova_ordem", methods=["GET", "POST"])
@login_required
def nova_ordem():

    fornecedores = Fornecedor.query.order_by(Fornecedor.nome).all()
    centros_custo = CentroCusto.query.order_by(CentroCusto.nome).all()
    todos_produtos = Produto.query.order_by(Produto.nome).all()

    if request.method == "POST":

        fornecedor = request.form.get("fornecedor")
        centro_custo = request.form.get("centro_custo")
        aprovador = request.form.get("aprovador")

        produtos_ids = request.form.getlist("produto_id[]")
        quantidades = request.form.getlist("quantidade[]")
        valores_unitarios = request.form.getlist("valor_unitario[]")

        if not fornecedor or not centro_custo:
            flash("Fornecedor e Centro de Custo são obrigatórios.", "warning")
            return redirect(url_for("nova_ordem"))

        if not produtos_ids:
            flash("Adicione pelo menos um produto.", "warning")
            return redirect(url_for("nova_ordem"))

        nova_ordem = OrdemCompra(
            fornecedor=fornecedor,
            centro_custo=centro_custo,
            aprovador=aprovador,
            descricao_itens="",
            valor=0
        )

        db.session.add(nova_ordem)
        db.session.flush()

        total = 0
        descricao_auto = []

        for i in range(len(produtos_ids)):
            try:
                produto_id = int(produtos_ids[i])
                quantidade = int(quantidades[i])
                valor_unitario = float(valores_unitarios[i])
            except (ValueError, IndexError):
                continue

            if quantidade <= 0 or valor_unitario < 0:
                continue

            produto = Produto.query.get(produto_id)
            if not produto:
                continue

            subtotal = quantidade * valor_unitario
            total += subtotal
            descricao_auto.append(f"{produto.nome} ({quantidade} un)")

            item = ItemOrdem(
                ordem_id=nova_ordem.id,
                produto_id=produto_id,
                quantidade=quantidade,
                valor_unitario=valor_unitario
            )
            db.session.add(item)

        if total == 0:
            flash("Valores inválidos na ordem.", "warning")
            db.session.rollback()
            return redirect(url_for("nova_ordem"))

        nova_ordem.valor = total
        nova_ordem.descricao_itens = "\n".join(descricao_auto)
        db.session.commit()

        flash("Ordem criada com sucesso.", "success")
        return redirect(url_for("ordens"))

    produtos_json = [
        {"id": p.id, "nome": p.nome}
        for p in todos_produtos
    ]

    return render_template(
        "nova_ordem.html",
        fornecedores=fornecedores,
        centros_custo=centros_custo,
        produtos=produtos_json
    )

# ===============================
# APROVAR / REPROVAR
# ===============================
@app.route("/aprovar/<int:ordem_id>", methods=["POST"])
@login_required
def aprovar(ordem_id):
    if current_user.perfil not in ["admin", "aprovador"]:
        abort(403)

    ordem = OrdemCompra.query.get_or_404(ordem_id)
    valor = float(ordem.valor or 0)

    saldo_aprovador = SaldoAprovador.query.filter_by(nome_aprovador=ordem.aprovador).first()
    if not saldo_aprovador or saldo_aprovador.saldo < valor:
        flash("Saldo insuficiente do aprovador.", "danger")
        return redirect(url_for("ordens"))

    centro = CentroCusto.query.filter_by(nome=ordem.centro_custo).first()
    if not centro or (centro.saldo or 0) < valor:
        flash("Centro de custo sem saldo.", "danger")
        return redirect(url_for("ordens"))

    saldo_aprovador.saldo -= valor
    centro.saldo -= valor

    ordem.status = "Aprovada"
    ordem.aprovado_por = current_user.nome
    ordem.aprovado_em = datetime.now()

    for item in ordem.itens:
        produto = item.produto
        if produto:
            produto.estoque_atual -= item.quantidade
            if produto.estoque_atual < 0:
                produto.estoque_atual = 0

    db.session.commit()
    flash("Ordem aprovada com sucesso.", "success")
    return redirect(url_for("ordens"))

@app.route("/ordens/reprovar/<int:ordem_id>", methods=["POST"])
@login_required
def reprovar_ordem(ordem_id):
    if current_user.perfil not in ["admin", "aprovador"]:
        abort(403)

    ordem = OrdemCompra.query.get_or_404(ordem_id)
    ordem.status = "Reprovada"
    ordem.aprovado_por = current_user.nome
    ordem.aprovado_em = datetime.now()
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
    flash("Ordem excluída.", "success")
    return redirect(url_for("ordens"))

# ===============================
# RELATÓRIOS
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
    file = request.files.get("nota_fiscal")

    if not file:
        flash("Nenhum arquivo enviado.", "warning")
        return redirect(url_for("relatorios"))

    os.makedirs(os.path.join("static", "notas_fiscais"), exist_ok=True)
    filename = secure_filename(file.filename)
    file.save(os.path.join("static", "notas_fiscais", filename))

    ordem.nota_fiscal = filename
    db.session.commit()
    flash("Nota fiscal anexada com sucesso.", "success")
    return redirect(url_for("relatorios"))

@app.route("/relatorios/excluir/<int:ordem_id>", methods=["POST"])
@login_required
def excluir_ordem_relatorio(ordem_id):
    if current_user.perfil != "admin":
        abort(403)
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    db.session.delete(ordem)
    db.session.commit()
    flash("Ordem excluída.", "success")
    return redirect(url_for("relatorios"))

# ===============================
# EXPORTAR EXCEL
# ===============================
@app.route("/relatorios/excel")
@login_required
def relatorios_excel():

    ordens = OrdemCompra.query.order_by(OrdemCompra.id.desc()).all()

    dados = []
    for o in ordens:
        dados.append({
            "ID": o.id,
            "Fornecedor": o.fornecedor,
            "Centro de Custo": o.centro_custo,
            "Valor (R$)": float(o.valor or 0),
            "Aprovador": o.aprovado_por or "",
            "Data da Compra": o.data_compra.strftime("%d/%m/%Y") if o.data_compra else "",
            "Status": o.status
        })

    df = pd.DataFrame(dados)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Ordens")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="relatorio_ordens.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ===============================
# EXPORTAR PDF
# ===============================
@app.route("/relatorios/pdf")
@login_required
def relatorios_pdf():

    ordens = OrdemCompra.query.order_by(OrdemCompra.id.desc()).all()
    caminho = os.path.join(os.getcwd(), "relatorio_ordens.pdf")

    doc = SimpleDocTemplate(caminho, pagesize=A4)
    elementos = []

    tabela = [
        ["ID", "Fornecedor", "Centro", "Valor",
         "Aprovador", "Data da Compra", "Status"]
    ]

    for o in ordens:
        tabela.append([
            str(o.id),
            o.fornecedor,
            o.centro_custo,
            f"R$ {float(o.valor or 0):.2f}",
            o.aprovado_por or "",
            o.data_compra.strftime("%d/%m/%Y") if o.data_compra else "",
            o.status
        ])

    estilo = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
    ])

    tbl = Table(tabela)
    tbl.setStyle(estilo)
    elementos.append(tbl)
    doc.build(elementos)

    return send_file(
        caminho,
        as_attachment=True,
        download_name="relatorio_ordens.pdf"
    )

@app.route("/relatorios/data_compra/<int:ordem_id>", methods=["POST"])
@login_required
def salvar_data_compra(ordem_id):
    ordem = OrdemCompra.query.get_or_404(ordem_id)
    data = request.form.get("data_compra")
    if data:
        ordem.data_compra = datetime.strptime(data, "%Y-%m-%d").date()
        db.session.commit()
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
                ajuste = int(request.form.get("ajuste"))
                if produto:
                    produto.estoque_atual += ajuste
                    if produto.estoque_atual < 0:
                        produto.estoque_atual = 0
                    db.session.commit()
                    flash("Estoque atualizado com sucesso.", "success")
            except:
                flash("Erro ao atualizar estoque.", "danger")
            return redirect(url_for("produtos"))

        nome = request.form.get("nome")
        estoque_atual = int(request.form.get("estoque_atual", 0))
        estoque_minimo = int(request.form.get("estoque_minimo", 0))

        if not nome:
            flash("Nome do produto é obrigatório.", "warning")
            return redirect(url_for("produtos"))

        if Produto.query.filter_by(nome=nome).first():
            flash("Produto já cadastrado.", "warning")
            return redirect(url_for("produtos"))

        novo_produto = Produto(
            nome=nome,
            estoque_atual=estoque_atual,
            estoque_minimo=estoque_minimo
        )
        db.session.add(novo_produto)
        db.session.commit()
        flash("Produto cadastrado com sucesso.", "success")
        return redirect(url_for("produtos"))

    lista_produtos = Produto.query.order_by(Produto.nome).all()
    return render_template("produtos.html", produtos=lista_produtos)

# ===============================
# EDITAR PRODUTO (BUG 7)
# ===============================
@app.route("/produtos/editar/<int:produto_id>", methods=["POST"])
@login_required
def editar_produto(produto_id):
    if current_user.perfil not in ["admin", "financeiro"]:
        abort(403)

    produto = Produto.query.get_or_404(produto_id)

    nome = request.form.get("nome", "").strip()
    estoque_atual = request.form.get("estoque_atual", "")
    estoque_minimo = request.form.get("estoque_minimo", "")

    if not nome:
        flash("Nome do produto é obrigatório.", "warning")
        return redirect(url_for("produtos"))

    # Verifica duplicata de nome em outro produto
    outro = Produto.query.filter_by(nome=nome).first()
    if outro and outro.id != produto_id:
        flash("Já existe outro produto com esse nome.", "warning")
        return redirect(url_for("produtos"))

    try:
        produto.nome = nome
        produto.estoque_atual = int(estoque_atual)
        produto.estoque_minimo = int(estoque_minimo)
        db.session.commit()
        flash("Produto atualizado com sucesso.", "success")
    except (ValueError, TypeError):
        flash("Valores de estoque inválidos.", "danger")

    return redirect(url_for("produtos"))

# ===============================
# EXCLUIR PRODUTO
# ===============================
@app.route("/produtos/excluir/<int:produto_id>", methods=["POST"])
@login_required
def excluir_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    if ItemOrdem.query.filter_by(produto_id=produto_id).first():
        flash("Não é possível excluir este produto porque ele já foi utilizado em uma ordem de compra.", "warning")
        return redirect(url_for("produtos"))
    db.session.delete(produto)
    db.session.commit()
    flash("Produto excluído com sucesso.", "success")
    return redirect(url_for("produtos"))

# ===============================
# START
# ===============================
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
