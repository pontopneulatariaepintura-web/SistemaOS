from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from extensions import db
from models import User, OS

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


# -------------------
# INIT DB
# -------------------
with app.app_context():
    db.create_all()

    admin = User.query.filter_by(username="admin").first()
    if not admin:
        db.session.add(User(
            username="admin",
            password=generate_password_hash("Ponto2026"),
            role="admin"
        ))
        db.session.commit()


# -------------------
# HELPERS
# -------------------
def login_ok():
    return "user" in session


STATUS_FLOW = ["CRIADA", "VISTORIA", "LIBERADA", "REPARO", "FINALIZADA"]


# -------------------
# LOGIN
# -------------------
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


# -------------------
# LOGOUT
# -------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# -------------------
# DASHBOARD
# -------------------
@app.route("/")
def dashboard():
    if not login_ok():
        return redirect("/login")

    return render_template("dashboard.html", total=OS.query.count())


# -------------------
# NOVA OS
# -------------------
@app.route("/nova_os", methods=["GET", "POST"])
def nova_os():
    if not login_ok():
        return redirect("/login")

    if request.method == "POST":

        os_item = OS(
            numero_os=request.form["numero_os"],
            cliente=request.form["cliente"],
            placa=request.form["placa"],
            seguradora=request.form["seguradora"],
            criado_por=session["user"],
            status="CRIADA"
        )

        db.session.add(os_item)
        db.session.commit()

        return redirect("/listar_os")

    return render_template("nova_os.html")


# -------------------
# LISTAR OS
# -------------------
@app.route("/listar_os")
def listar_os():
    if not login_ok():
        return redirect("/login")

    os_list = OS.query.order_by(OS.id.desc()).all()
    return render_template("listar_os.html", os_list=os_list)


# -------------------
# EDITAR OS
# -------------------
@app.route("/editar_os/<int:id>", methods=["GET", "POST"])
def editar_os(id):
    if not login_ok():
        return redirect("/login")

    os_item = OS.query.get_or_404(id)

    if request.method == "POST":
        os_item.numero_os = request.form["numero_os"]
        os_item.cliente = request.form["cliente"]
        os_item.placa = request.form["placa"]
        os_item.seguradora = request.form["seguradora"]

        db.session.commit()
        return redirect("/listar_os")

    return render_template("editar_os.html", os=os_item)


# -------------------
# EXCLUIR OS
# -------------------
@app.route("/excluir_os/<int:id>")
def excluir_os(id):
    if not login_ok():
        return redirect("/login")

    os_item = OS.query.get_or_404(id)
    db.session.delete(os_item)
    db.session.commit()

    return redirect("/listar_os")


# -------------------
# STATUS FLOW
# -------------------
@app.route("/avancar_status/<int:id>")
def avancar_status(id):
    if not login_ok():
        return redirect("/login")

    os_item = OS.query.get_or_404(id)

    if os_item.status in STATUS_FLOW:
        i = STATUS_FLOW.index(os_item.status)
        if i < len(STATUS_FLOW) - 1:
            os_item.status = STATUS_FLOW[i + 1]

    db.session.commit()
    return redirect("/listar_os")


# -------------------
# RUN
# -------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)