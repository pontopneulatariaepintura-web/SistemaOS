python
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

from extensions import db
from models import User, OS

app = Flask(__name__)

# CONFIG
app.secret_key = "SISTEMA-OS-2026"

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///database.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# CRIA BANCO
with app.app_context():
    db.create_all()

    admin = User.query.filter_by(username="admin").first()

    if not admin:
        db.session.add(
            User(
                username="admin",
                password=generate_password_hash("1234"),
                role="admin"
            )
        )
        db.session.commit()


# HELPERS
def logado():
    return "user" in session


def admin():
    return session.get("role") == "admin"


def parse_date(valor):
    if not valor:
        return None

    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except:
        return None


STATUS_FLOW = [
    "CRIADA",
    "VISTORIA",
    "LIBERADA",
    "REPARO",
    "FINALIZADA"
]


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        usuario = User.query.filter_by(
            username=request.form["username"]
        ).first()

        if usuario and check_password_hash(
            usuario.password,
            request.form["password"]
        ):

            session["user"] = usuario.username
            session["role"] = usuario.role

            return redirect("/")

        return "Usuário ou senha inválidos"

    return render_template("login.html")


# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# DASHBOARD
@app.route("/")
def dashboard():

    if not logado():
        return redirect("/login")

    total_os = OS.query.count()

    criadas = OS.query.filter_by(
        status="CRIADA"
    ).count()

    vistoria = OS.query.filter_by(
        status="VISTORIA"
    ).count()

    liberadas = OS.query.filter_by(
        status="LIBERADA"
    ).count()

    reparo = OS.query.filter_by(
        status="REPARO"
    ).count()

    finalizadas = OS.query.filter_by(
        status="FINALIZADA"
    ).count()

    valor_pecas = sum(
        os.valor_pecas or 0
        for os in OS.query.all()
    )

    valor_mao_obra = sum(
        os.valor_mao_obra or 0
        for os in OS.query.all()
    )

    return render_template(
        "dashboard.html",
        total_os=total_os,
        criadas=criadas,
        vistoria=vistoria,
        liberadas=liberadas,
        reparo=reparo,
        finalizadas=finalizadas,
        valor_pecas=valor_pecas,
        valor_mao_obra=valor_mao_obra
    )


# USUÁRIOS
@app.route("/usuarios")
def usuarios():

    if not logado() or not admin():
        return "Acesso negado"

    return render_template(
        "usuarios.html",
        usuarios=User.query.all()
    )


@app.route("/usuarios/novo", methods=["GET", "POST"])
def novo_usuario():

    if not logado() or not admin():
        return "Acesso negado"

    if request.method == "POST":

        existe = User.query.filter_by(
            username=request.form["username"]
        ).first()

        if existe:
            return "Usuário já existe"

        novo = User(
            username=request.form["username"],
            password=generate_password_hash(
                request.form["password"]
            ),
            role=request.form.get("role", "user")
        )

        db.session.add(novo)
        db.session.commit()

        return redirect("/usuarios")

    return render_template("novo_usuario.html")


@app.route("/usuarios/excluir/<int:id>")
def excluir_usuario(id):

    if not logado() or not admin():
        return "Acesso negado"

    usuario = User.query.get_or_404(id)

    if usuario.username == "admin":
        return "Não é permitido excluir o admin"

    db.session.delete(usuario)
    db.session.commit()

    return redirect("/usuarios")


# NOVA OS
@app.route("/nova_os", methods=["GET", "POST"])
def nova_os():

    if not logado():
        return redirect("/login")

    if request.method == "POST":

        nova = OS(
            numero_os=request.form["numero_os"],
            cliente=request.form["cliente"],
            placa=request.form["placa"],
            seguradora=request.form["seguradora"],

            data_entrada=parse_date(
                request.form.get("data_entrada")
            ),

            data_vistoria=parse_date(
                request.form.get("data_vistoria")
            ),

            data_liberacao_vistoria=parse_date(
                request.form.get(
                    "data_liberacao_vistoria"
                )
            ),

            data_inicio_reparo=parse_date(
                request.form.get(
                    "data_inicio_reparo"
                )
            ),

            previsao_entrega=parse_date(
                request.form.get(
                    "previsao_entrega"
                )
            ),

            data_pagamento=parse_date(
                request.form.get(
                    "data_pagamento"
                )
            ),

            valor_pecas=float(
                request.form.get(
                    "valor_pecas"
                ) or 0
            ),

            valor_mao_obra=float(
                request.form.get(
                    "valor_mao_obra"
                ) or 0
            ),

            status="CRIADA",
            criado_por=session["user"]
        )

        db.session.add(nova)
        db.session.commit()

        return redirect("/listar_os")

    return render_template("nova_os.html")


# LISTAR OS
@app.route("/listar_os")
def listar_os():

    if not logado():
        return redirect("/login")

    lista = OS.query.order_by(
        OS.id.desc()
    ).all()

    return render_template(
        "listar_os.html",
        os_list=lista
    )


# EDITAR OS
@app.route("/editar_os/<int:id>", methods=["GET", "POST"])
def editar_os(id):

    if not logado():
        return redirect("/login")

    os_item = OS.query.get_or_404(id)

    if request.method == "POST":

        os_item.cliente = request.form["cliente"]
        os_item.placa = request.form["placa"]
        os_item.seguradora = request.form["seguradora"]

        os_item.valor_pecas = float(
            request.form.get(
                "valor_pecas"
            ) or 0
        )

        os_item.valor_mao_obra = float(
            request.form.get(
                "valor_mao_obra"
            ) or 0
        )

        os_item.status = request.form["status"]

        db.session.commit()

        return redirect("/listar_os")

    return render_template(
        "editar_os.html",
        os=os_item
    )


# EXCLUIR OS
@app.route("/excluir_os/<int:id>")
def excluir_os(id):

    if not logado():
        return redirect("/login")

    if not admin():
        return "Acesso negado"

    os_item = OS.query.get_or_404(id)

    db.session.delete(os_item)
    db.session.commit()

    return redirect("/listar_os")


# AVANÇAR ETAPA
@app.route("/avancar/<int:id>")
def avancar(id):

    if not logado():
        return redirect("/login")

    os_item = OS.query.get_or_404(id)

    if os_item.status not in STATUS_FLOW:
        os_item.status = "CRIADA"
    else:

        indice = STATUS_FLOW.index(
            os_item.status
        )

        if indice < len(
            STATUS_FLOW
        ) - 1:

            os_item.status = STATUS_FLOW[
                indice + 1
            ]

    db.session.commit()

    return redirect("/listar_os")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )

