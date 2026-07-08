from datetime import timedelta, datetime
from functools import wraps
import os

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import EstoqueParaBrisa, EstoquePeca, OS, OSFoto, User

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///database.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace(
        "postgres://", "postgresql://", 1
    )

db.init_app(app)

STATUS_FLOW = ["CRIADA", "VISTORIA", "LIBERADA", "REPARO", "FINALIZADA"]
TIPOS_REPARO = ["Pequenos reparos", "Troca de pneu/roda", "Lataria e Pintura", "Parabrisa"]
SEGURADORAS = ["Porto Seguro", "Tokio", "HDI", "Yellum", "Mapfr", "Zurich", "MaxPar", "Car Glass", "Alura", "Allianz", "Youse", "Suhai", "Bradesco", "Itau", "Mithsui", "Santander", "Sura", "Loovi", "Conecta", "Pioneira", "Alfa", "Guara", "Potencia BR"]


def parse_date(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_float(valor):
    if valor in (None, ""):
        return 0
    return float(str(valor).replace(",", "."))


def save_os_fotos(os_id):
    fotos = request.files.getlist("fotos")
    for foto in fotos:
        if not foto or not foto.filename:
            continue
        if not (foto.content_type or "").startswith("image/"):
            flash("Somente arquivos de imagem foram aceitos nas fotos da OS.", "warning")
            continue
        data = foto.read()
        if not data:
            continue
        db.session.add(
            OSFoto(
                os_id=os_id,
                filename=foto.filename,
                content_type=foto.content_type or "image/jpeg",
                data=data,
            )
        )
    db.session.commit()


def montar_alertas_prazo():
    hoje = datetime.now().date()
    limite = hoje + timedelta(days=2)
    campos = [
        ("Vistoria", "data_vistoria", {"CRIADA", "VISTORIA"}),
        ("Reparo", "data_inicio_reparo", {"LIBERADA", "REPARO"}),
        ("Previs\u00e3o de entrega", "previsao_entrega", {"CRIADA", "VISTORIA", "LIBERADA", "REPARO"}),
    ]
    alertas = []

    ordens = OS.query.filter(OS.status != "FINALIZADA").all()
    for os_item in ordens:
        for titulo, campo, status_validos in campos:
            if os_item.status not in status_validos:
                continue

            prazo = getattr(os_item, campo)
            if not prazo or prazo > limite:
                continue

            dias = (prazo - hoje).days
            if dias < 0:
                situacao = f"vencido h\u00e1 {abs(dias)} dia(s)"
                classe = "danger"
            elif dias == 0:
                situacao = "vence hoje"
                classe = "danger"
            elif dias == 1:
                situacao = "vence amanh\u00e3"
                classe = "warning"
            else:
                situacao = f"vence em {dias} dias"
                classe = "warning"

            alertas.append(
                {
                    "os": os_item,
                    "tipo": titulo,
                    "prazo": prazo,
                    "dias": dias,
                    "situacao": situacao,
                    "classe": classe,
                }
            )

    return sorted(alertas, key=lambda item: (item["prazo"], item["os"].numero_os or ""))


def ensure_os_columns():
    inspector = inspect(db.engine)
    existing = {column["name"] for column in inspector.get_columns("os")}
    dialect = db.engine.dialect.name

    column_sql = {
        "tipo_reparo": "VARCHAR(60)",
        "carro_modelo": "VARCHAR(120)",
        "custo_pecas": "FLOAT",
        "orcamento": "FLOAT",
        "franquia": "FLOAT",
        "veiculo_terceiro": "BOOLEAN",
        "total_receber": "FLOAT",
        "data_criacao": "TIMESTAMP" if dialect == "postgresql" else "DATETIME",
        "ultima_atualizacao": "TIMESTAMP" if dialect == "postgresql" else "DATETIME",
    }

    for column_name, column_type in column_sql.items():
        if column_name not in existing:
            db.session.execute(text(f"ALTER TABLE os ADD COLUMN {column_name} {column_type}"))

    db.session.commit()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Fa\u00e7a login para acessar o sistema.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Fa\u00e7a login para acessar o sistema.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Acesso permitido apenas para administradores.", "danger")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped_view


@app.context_processor
def inject_user():
    return {"usuario_logado": session.get("username"), "perfil_logado": session.get("role")}


with app.app_context():
    db.create_all()
    ensure_os_columns()

    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(
            username="admin",
            password=generate_password_hash(os.getenv("ADMIN_PASSWORD", "1234")),
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        usuario = User.query.filter_by(username=username).first()
        if usuario and check_password_hash(usuario.password, password):
            session.clear()
            session.permanent = True
            session["user_id"] = usuario.id
            session["username"] = usuario.username
            session["role"] = usuario.role
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("dashboard"))

        flash("Usu\u00e1rio ou senha inv\u00e1lidos.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Voc\u00ea saiu do sistema.", "info")
    return redirect(url_for("login"))


@app.route("/alterar_senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    usuario = User.query.get_or_404(session["user_id"])

    if request.method == "POST":
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not check_password_hash(usuario.password, senha_atual):
            flash("Senha atual incorreta.", "danger")
            return render_template("alterar_senha.html")

        if len(nova_senha) < 4:
            flash("A nova senha deve ter pelo menos 4 caracteres.", "danger")
            return render_template("alterar_senha.html")

        if nova_senha != confirmar_senha:
            flash("A confirma\u00e7\u00e3o da senha n\u00e3o confere.", "danger")
            return render_template("alterar_senha.html")

        usuario.password = generate_password_hash(nova_senha)
        db.session.commit()
        flash("Senha alterada com sucesso.", "success")
        return redirect(url_for("dashboard"))

    return render_template("alterar_senha.html")


@app.route("/")
@login_required
def dashboard():
    total_os = OS.query.count()
    criadas = OS.query.filter_by(status="CRIADA").count()
    vistoria = OS.query.filter_by(status="VISTORIA").count()
    liberadas = OS.query.filter_by(status="LIBERADA").count()
    reparo = OS.query.filter_by(status="REPARO").count()
    finalizadas = OS.query.filter_by(status="FINALIZADA").count()

    ordens = OS.query.all()
    valor_pecas = sum(item.valor_pecas or 0 for item in ordens)
    valor_mao_obra = sum(item.valor_mao_obra or 0 for item in ordens)

    total_itens_estoque = EstoquePeca.query.count()
    valor_estoque = sum((peca.quantidade or 0) * (peca.valor_unitario or 0) for peca in EstoquePeca.query.all())
    estoque_baixo = EstoquePeca.query.filter(EstoquePeca.quantidade <= EstoquePeca.estoque_minimo).count()
    total_para_brisas = EstoqueParaBrisa.query.count()
    para_brisas_baixo = EstoqueParaBrisa.query.filter(
        EstoqueParaBrisa.quantidade <= EstoqueParaBrisa.estoque_minimo
    ).count()
    prazo_alertas = montar_alertas_prazo()

    return render_template(
        "dashboard.html",
        total_os=total_os,
        criadas=criadas,
        vistoria=vistoria,
        liberadas=liberadas,
        reparo=reparo,
        finalizadas=finalizadas,
        valor_pecas=valor_pecas,
        valor_mao_obra=valor_mao_obra,
        total_itens_estoque=total_itens_estoque,
        valor_estoque=valor_estoque,
        estoque_baixo=estoque_baixo,
        total_para_brisas=total_para_brisas,
        para_brisas_baixo=para_brisas_baixo,
        prazo_alertas=prazo_alertas,
    )


@app.route("/usuarios")
@admin_required
def usuarios():
    return render_template("usuarios.html", usuarios=User.query.order_by(User.username).all())


@app.route("/usuarios/novo", methods=["GET", "POST"])
@admin_required
def novo_usuario():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")

        if not username or not password:
            flash("Informe usu\u00e1rio e senha.", "danger")
            return render_template("novo_usuario.html")

        if User.query.filter_by(username=username).first():
            flash("J\u00e1 existe um usu\u00e1rio com esse login.", "danger")
            return render_template("novo_usuario.html")

        novo = User(username=username, password=generate_password_hash(password), role=role)
        db.session.add(novo)
        db.session.commit()
        flash("Usu\u00e1rio criado com sucesso.", "success")
        return redirect(url_for("usuarios"))

    return render_template("novo_usuario.html")


@app.route("/usuarios/excluir/<int:id>")
@admin_required
def excluir_usuario(id):
    usuario = User.query.get_or_404(id)

    if usuario.username == "admin":
        flash("N\u00e3o \u00e9 permitido excluir o usu\u00e1rio admin.", "danger")
        return redirect(url_for("usuarios"))

    if usuario.id == session.get("user_id"):
        flash("Voc\u00ea n\u00e3o pode excluir o pr\u00f3prio usu\u00e1rio logado.", "danger")
        return redirect(url_for("usuarios"))

    db.session.delete(usuario)
    db.session.commit()
    flash("Usu\u00e1rio exclu\u00eddo.", "success")
    return redirect(url_for("usuarios"))


@app.route("/nova_os", methods=["GET", "POST"])
@login_required
def nova_os():
    if request.method == "POST":
        numero_os = request.form.get("numero_os", "").strip()
        cliente = request.form.get("cliente", "").strip()
        placa = request.form.get("placa", "").strip().upper()
        seguradora = request.form.get("seguradora", "").strip()
        carro_modelo = request.form.get("carro_modelo", "").strip()
        tipo_reparo = request.form.get("tipo_reparo", "").strip()
        valor_pecas_raw = request.form.get("valor_pecas", "").strip()
        valor_mao_obra_raw = request.form.get("valor_mao_obra", "").strip()
        custo_pecas_raw = request.form.get("custo_pecas", "").strip()
        orcamento_raw = request.form.get("orcamento", "").strip()
        franquia_raw = request.form.get("franquia", "").strip()
        total_receber_raw = request.form.get("total_receber", "").strip()
        veiculo_terceiro = request.form.get("veiculo_terceiro") == "sim"
        form_data = request.form

        if not all([numero_os, cliente, placa, seguradora, tipo_reparo, valor_pecas_raw, valor_mao_obra_raw]):
            flash("Preencha todos os campos obrigat\u00f3rios da ordem de servi\u00e7o.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)

        if seguradora not in SEGURADORAS:
            flash("Selecione uma seguradora v\u00e1lida.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)

        if tipo_reparo not in TIPOS_REPARO:
            flash("Selecione um tipo de reparo v\u00e1lido.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)

        try:
            valor_pecas = parse_float(valor_pecas_raw)
            valor_mao_obra = parse_float(valor_mao_obra_raw)
            custo_pecas = parse_float(custo_pecas_raw)
            orcamento = parse_float(orcamento_raw)
            franquia = parse_float(franquia_raw)
            total_receber = parse_float(total_receber_raw)
        except ValueError:
            flash("Informe valores v\u00e1lidos para pe\u00e7as e m\u00e3o de obra.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)

        if min(valor_pecas, valor_mao_obra, custo_pecas, orcamento, franquia, total_receber) < 0:
            flash("Os valores de pe\u00e7as e m\u00e3o de obra n\u00e3o podem ser negativos.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)

        if OS.query.filter_by(numero_os=numero_os).first():
            flash("J\u00e1 existe uma OS com esse n\u00famero.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)

        nova = OS(
            numero_os=numero_os,
            cliente=cliente,
            placa=placa,
            seguradora=seguradora,
            carro_modelo=carro_modelo,
            custo_pecas=custo_pecas,
            orcamento=orcamento,
            franquia=franquia,
            veiculo_terceiro=veiculo_terceiro,
            total_receber=total_receber,
            tipo_reparo=tipo_reparo,
            data_entrada=parse_date(request.form.get("data_entrada")),
            data_vistoria=parse_date(request.form.get("data_vistoria")),
            data_liberacao_vistoria=parse_date(request.form.get("data_liberacao_vistoria")),
            data_inicio_reparo=parse_date(request.form.get("data_inicio_reparo")),
            previsao_entrega=parse_date(request.form.get("previsao_entrega")),
            data_pagamento=parse_date(request.form.get("data_pagamento")),
            valor_pecas=valor_pecas,
            valor_mao_obra=valor_mao_obra,
            status="CRIADA",
            criado_por=session["username"],
        )
        db.session.add(nova)
        db.session.commit()
        save_os_fotos(nova.id)
        flash("Ordem de servi\u00e7o criada.", "success")
        return redirect(url_for("listar_os"))

    return render_template("nova_os.html", form_data={}, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)


@app.route("/listar_os")
@login_required
def listar_os():
    status = request.args.get("status", "").strip().upper()
    query = OS.query
    titulo = "Ordens de serviço em andamento"
    empty_message = "Nenhuma ordem de serviço em andamento."

    if status:
        if status not in STATUS_FLOW:
            flash("Filtro de status inválido.", "danger")
            return redirect(url_for("listar_os"))
        query = query.filter_by(status=status)
        titulo = f"Ordens de serviço - {status}"
        empty_message = f"Nenhuma ordem de serviço com status {status}."
    else:
        query = query.filter(OS.status != "FINALIZADA")

    lista = query.order_by(OS.id.desc()).all()
    return render_template("listar_os.html", os_list=lista, titulo=titulo, empty_message=empty_message, status_atual=status)


@app.route("/os_finalizadas")
@login_required
def os_finalizadas():
    lista = OS.query.filter_by(status="FINALIZADA").order_by(OS.id.desc()).all()
    return render_template(
        "listar_os.html",
        os_list=lista,
        titulo="Ordens de serviço finalizadas",
        empty_message="Nenhuma ordem de serviço finalizada.",
        status_atual="FINALIZADA",
        finalizadas_view=True,
    )


@app.route("/editar_os/<int:id>", methods=["GET", "POST"])
@login_required
def editar_os(id):
    os_item = OS.query.get_or_404(id)

    if request.method == "POST":
        os_item.numero_os = request.form.get("numero_os", os_item.numero_os).strip()
        os_item.cliente = request.form.get("cliente", "").strip()
        os_item.placa = request.form.get("placa", "").strip().upper()
        os_item.seguradora = request.form.get("seguradora", "").strip()
        os_item.carro_modelo = request.form.get("carro_modelo", "").strip()
        os_item.custo_pecas = parse_float(request.form.get("custo_pecas"))
        os_item.orcamento = parse_float(request.form.get("orcamento"))
        os_item.franquia = parse_float(request.form.get("franquia"))
        os_item.veiculo_terceiro = request.form.get("veiculo_terceiro") == "sim"
        os_item.total_receber = parse_float(request.form.get("total_receber"))
        os_item.tipo_reparo = request.form.get("tipo_reparo", "").strip()
        os_item.data_entrada = parse_date(request.form.get("data_entrada"))
        os_item.data_vistoria = parse_date(request.form.get("data_vistoria"))
        os_item.data_liberacao_vistoria = parse_date(request.form.get("data_liberacao_vistoria"))
        os_item.data_inicio_reparo = parse_date(request.form.get("data_inicio_reparo"))
        os_item.previsao_entrega = parse_date(request.form.get("previsao_entrega"))
        os_item.data_pagamento = parse_date(request.form.get("data_pagamento"))
        os_item.valor_pecas = parse_float(request.form.get("valor_pecas"))
        os_item.valor_mao_obra = parse_float(request.form.get("valor_mao_obra"))
        os_item.status = request.form.get("status", os_item.status)
        db.session.commit()
        save_os_fotos(os_item.id)
        flash("Ordem de servi\u00e7o atualizada.", "success")
        return redirect(url_for("listar_os"))

    return render_template("editar_os.html", os=os_item, status_flow=STATUS_FLOW, tipos_reparo=TIPOS_REPARO, seguradoras=SEGURADORAS)


@app.route("/imprimir_os/<int:id>")
@login_required
def imprimir_os(id):
    os_item = OS.query.get_or_404(id)
    return render_template("imprimir_os.html", os=os_item)


@app.route("/excluir_os/<int:id>")
@admin_required
def excluir_os(id):
    os_item = OS.query.get_or_404(id)
    db.session.delete(os_item)
    db.session.commit()
    flash("Ordem de servi\u00e7o exclu\u00edda.", "success")
    return redirect(url_for("listar_os"))


@app.route("/avancar/<int:id>")
@login_required
def avancar(id):
    os_item = OS.query.get_or_404(id)

    if os_item.status not in STATUS_FLOW:
        os_item.status = "CRIADA"
    else:
        indice = STATUS_FLOW.index(os_item.status)
        if indice < len(STATUS_FLOW) - 1:
            os_item.status = STATUS_FLOW[indice + 1]

    db.session.commit()
    flash("Etapa atualizada.", "success")
    return redirect(url_for("listar_os"))


@app.route("/estoque")
@login_required
def estoque():
    pecas = EstoquePeca.query.order_by(EstoquePeca.nome).all()
    total_pecas = sum(peca.quantidade or 0 for peca in pecas)
    valor_total = sum((peca.quantidade or 0) * (peca.valor_unitario or 0) for peca in pecas)
    return render_template("estoque.html", pecas=pecas, total_pecas=total_pecas, valor_total=valor_total)


@app.route("/estoque/nova", methods=["GET", "POST"])
@login_required
def nova_peca():
    if request.method == "POST":
        peca = EstoquePeca(
            nome=request.form.get("nome", "").strip(),
            codigo=request.form.get("codigo", "").strip(),
            fornecedor=request.form.get("fornecedor", "").strip(),
            quantidade=int(request.form.get("quantidade") or 0),
            estoque_minimo=int(request.form.get("estoque_minimo") or 0),
            valor_unitario=float(request.form.get("valor_unitario") or 0),
            localizacao=request.form.get("localizacao", "").strip(),
        )
        if not peca.nome:
            flash("Informe o nome da pe\u00e7a.", "danger")
            return render_template("form_peca.html", peca=peca)

        db.session.add(peca)
        db.session.commit()
        flash("Pe\u00e7a adicionada ao estoque.", "success")
        return redirect(url_for("estoque"))

    return render_template("form_peca.html", peca=None)


@app.route("/estoque/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_peca(id):
    peca = EstoquePeca.query.get_or_404(id)

    if request.method == "POST":
        peca.nome = request.form.get("nome", "").strip()
        peca.codigo = request.form.get("codigo", "").strip()
        peca.fornecedor = request.form.get("fornecedor", "").strip()
        peca.quantidade = int(request.form.get("quantidade") or 0)
        peca.estoque_minimo = int(request.form.get("estoque_minimo") or 0)
        peca.valor_unitario = float(request.form.get("valor_unitario") or 0)
        peca.localizacao = request.form.get("localizacao", "").strip()
        db.session.commit()
        flash("Pe\u00e7a atualizada.", "success")
        return redirect(url_for("estoque"))

    return render_template("form_peca.html", peca=peca)


@app.route("/estoque/excluir/<int:id>")
@admin_required
def excluir_peca(id):
    peca = EstoquePeca.query.get_or_404(id)
    db.session.delete(peca)
    db.session.commit()
    flash("Pe\u00e7a removida do estoque.", "success")
    return redirect(url_for("estoque"))


@app.route("/para_brisas")
@login_required
def para_brisas():
    itens = EstoqueParaBrisa.query.order_by(EstoqueParaBrisa.veiculo, EstoqueParaBrisa.modelo).all()
    total_unidades = sum(item.quantidade or 0 for item in itens)
    valor_total = sum((item.quantidade or 0) * (item.valor_unitario or 0) for item in itens)
    return render_template(
        "para_brisas.html",
        itens=itens,
        total_unidades=total_unidades,
        valor_total=valor_total,
    )


@app.route("/para_brisas/novo", methods=["GET", "POST"])
@login_required
def novo_para_brisa():
    if request.method == "POST":
        item = EstoqueParaBrisa(
            veiculo=request.form.get("veiculo", "").strip(),
            modelo=request.form.get("modelo", "").strip(),
            ano_inicial=int(request.form.get("ano_inicial") or 0) or None,
            ano_final=int(request.form.get("ano_final") or 0) or None,
            lado=request.form.get("lado", "Dianteiro").strip(),
            codigo=request.form.get("codigo", "").strip(),
            fornecedor=request.form.get("fornecedor", "").strip(),
            quantidade=int(request.form.get("quantidade") or 0),
            estoque_minimo=int(request.form.get("estoque_minimo") or 0),
            valor_unitario=float(request.form.get("valor_unitario") or 0),
            localizacao=request.form.get("localizacao", "").strip(),
        )
        if not item.veiculo:
            flash("Informe o ve\u00edculo do para-brisa.", "danger")
            return render_template("form_para_brisa.html", item=item)

        db.session.add(item)
        db.session.commit()
        flash("Para-brisa adicionado ao estoque.", "success")
        return redirect(url_for("para_brisas"))

    return render_template("form_para_brisa.html", item=None)


@app.route("/para_brisas/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_para_brisa(id):
    item = EstoqueParaBrisa.query.get_or_404(id)

    if request.method == "POST":
        item.veiculo = request.form.get("veiculo", "").strip()
        item.modelo = request.form.get("modelo", "").strip()
        item.ano_inicial = int(request.form.get("ano_inicial") or 0) or None
        item.ano_final = int(request.form.get("ano_final") or 0) or None
        item.lado = request.form.get("lado", "Dianteiro").strip()
        item.codigo = request.form.get("codigo", "").strip()
        item.fornecedor = request.form.get("fornecedor", "").strip()
        item.quantidade = int(request.form.get("quantidade") or 0)
        item.estoque_minimo = int(request.form.get("estoque_minimo") or 0)
        item.valor_unitario = float(request.form.get("valor_unitario") or 0)
        item.localizacao = request.form.get("localizacao", "").strip()
        db.session.commit()
        flash("Para-brisa atualizado.", "success")
        return redirect(url_for("para_brisas"))

    return render_template("form_para_brisa.html", item=item)


@app.route("/para_brisas/excluir/<int:id>")
@admin_required
def excluir_para_brisa(id):
    item = EstoqueParaBrisa.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash("Para-brisa removido do estoque.", "success")
    return redirect(url_for("para_brisas"))


@app.route("/os_foto/<int:id>")
@login_required
def os_foto(id):
    foto = OSFoto.query.get_or_404(id)
    return Response(foto.data, mimetype=foto.content_type or "image/jpeg")


@app.route("/os_foto/excluir/<int:id>")
@admin_required
def excluir_os_foto(id):
    foto = OSFoto.query.get_or_404(id)
    os_id = foto.os_id
    db.session.delete(foto)
    db.session.commit()
    flash("Foto removida da OS.", "success")
    return redirect(url_for("editar_os", id=os_id))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
