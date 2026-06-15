from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

from extensions import db
from models import User, OS

app = Flask(__name__)
app.secret_key = "SISTEMA-OS-2026"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# ---------------- INIT ----------------
with app.app_context():
    db.create_all()

    if not User.query.filter_by(username="admin").first():
        db.session.add(User(
            username="admin",
            password=generate_password_hash("1234"),
            role="admin"
        ))
        db.session.commit()


# ---------------- HELPERS ----------------
def login_required():
    return session.get("user") is not None


def is_admin():
    return session.get("role") == "admin"


def parse_date(v):
    try:
        return datetime.strptime(v, "%Y-%m-%d").date() if v else None
    except:
        return None


STATUS_FLOW = ["CRIADA", "VISTORIA", "LIBERADA", "REPARO", "FINALIZADA"]


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        user = User.query.filter_by(username=request.form["username"]).first()

        if user and check_password_hash(user.password, request.form["password"]):
            session["user"] = user.username
            session["role"] = user.role
            return redirect("/")

        return "Login inválido"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------- DASHBOARD ----------------
@app.route("/")
def dashboard():
    if not login_required():
        return redirect("/login")

    total = OS.query.count()

    return render_template("dashboard.html", total=total)


# ---------------- USUÁRIOS ----------------
@app.route("/usuarios")
def usuarios():
    if not login_required() or not is_admin():
        return "Acesso negado"

    return render_template("usuarios.html", usuarios=User.query.all())


@app.route("/usuarios/novo", methods=["GET", "POST"])
def novo_usuario():
    if not login_required() or not is_admin():
        return "Acesso negado"

    if request.method == "POST":

        if User.query.filter_by(username=request.form["username"]).first():
            return "Usuário já existe"

        db.session.add(User(
            username=request.form["username"],
            password=generate_password_hash(request.form["password"]),
            role=request.form.get("role", "user")
        ))

        db.session.commit()

        return redirect("/usuarios")

    return render_template("novo_usuario.html")


# ---------------- NOVA OS ----------------
@app.route("/nova_os", methods=["GET", "POST"])
def nova_os():
    if not login_required():
        return redirect("/login")

    if request.method == "POST":

        os_item = OS(
            numero_os=request.form["numero_os"],
            cliente=request.form["cliente"],
            placa=request.form["placa"],
            seguradora=request.form["seguradora"],

            data_entrada=parse_date(request.form.get("data_entrada")),
            data_vistoria=parse_date(request.form.get("data_vistoria")),
            data_liberacao_vistoria=parse_date(request.form.get("data_liberacao_vistoria")),
            data_inicio_reparo=parse_date(request.form.get("data_inicio_reparo")),
            previsao_entrega=parse_date(request.form.get("previsao_entrega")),
            data_pagamento=parse_date(request.form.get("data_pagamento")),

            valor_pecas=float(request.form.get("valor_pecas") or 0),
            valor_mao_obra=float(request.form.get("valor_mao_obra") or 0),

            status="CRIADA",
            criado_por=session["user"]
        )

        db.session.add(os_item)
        db.session.commit()

        return redirect("/listar_os")

    return render_template("nova_os.html")


# ---------------- LISTAR OS ----------------
@app.route("/listar_os")
def listar_os():
    if not login_required():
        return redirect("/login")

    return render_template("listar_os.html", os_list=OS.query.all())


# ---------------- AVANÇAR STATUS (CORRIGIDO) ----------------
@app.route("/avancar/<int:id>")
def avancar(id):

    if not login_required():
        return redirect("/login")

    os_item = OS.query.get_or_404(id)

    STATUS_FLOW = ["CRIADA", "VISTORIA", "LIBERADA", "REPARO", "FINALIZADA"]

    if os_item.status not in STATUS_FLOW:
        os_item.status = "CRIADA"
    else:
        i = STATUS_FLOW.index(os_item.status)
        if i < len(STATUS_FLOW) - 1:
            os_item.status = STATUS_FLOW[i + 1]

    db.session.commit()

    return redirect("/listar_os")


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)