from datetime import timedelta, datetime
from functools import wraps
from html import escape
from io import BytesIO
import os
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Flask, Response, abort, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import EstoqueParaBrisa, EstoquePeca, FechamentoFinanceiro, FechamentoFinanceiroItem, OS, OSFoto, User

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
OPERACOES_OS = ["Venda", "Fornecimento"]
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


def valor_total_os(item):
    valor_os = item.valor_os or 0
    if valor_os > 0:
        return valor_os
    valor_negociado = item.valor_negociado or 0
    if valor_negociado > 0:
        return valor_negociado
    return (item.valor_pecas or 0) + (item.valor_mao_obra or 0)


def is_maxpar(item):
    seguradora = (item.seguradora or "").lower().replace(" ", "")
    return "maxpar" in seguradora


def valor_faturado_maxpar(item):
    if not is_maxpar(item):
        return 0
    return item.faturado_maxpar or 0


def format_brl(valor):
    return f"R$ {(valor or 0):.2f}"


def docx_text(valor):
    return escape(str(valor if valor not in (None, "") else "-"))


def docx_paragraph(texto, bold=False):
    texto = docx_text(texto)
    if bold:
        return f"<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{texto}</w:t></w:r></w:p>"
    return f"<w:p><w:r><w:t>{texto}</w:t></w:r></w:p>"


def docx_cell(texto, bold=False):
    return f"<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>{docx_paragraph(texto, bold)}</w:tc>"


def docx_row(valores, header=False):
    return "<w:tr>" + "".join(docx_cell(valor, header) for valor in valores) + "</w:tr>"


def docx_table(rows):
    table_props = (
        "<w:tblPr><w:tblStyle w:val=\"TableGrid\"/>"
        "<w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders><w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "</w:tblBorders></w:tblPr>"
    )
    return "<w:tbl>" + table_props + "".join(rows) + "</w:tbl>"



def excel_col(numero):
    nome = ""
    while numero:
        numero, resto = divmod(numero - 1, 26)
        nome = chr(65 + resto) + nome
    return nome


def xlsx_cell(row, col, value, style=None):
    ref = f"{excel_col(col)}{row}"
    style_attr = f' s="{style}"' if style is not None else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style_attr}><v>{value:.2f}</v></c>'
    safe = escape(str(value if value not in (None, "") else "-"))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{safe}</t></is></c>'


def xlsx_row(row_num, values, header=False):
    style = 1 if header else None
    return f'<row r="{row_num}">' + "".join(
        xlsx_cell(row_num, index + 1, value, style) for index, value in enumerate(values)
    ) + "</row>"


def xlsx_sheet(rows, widths=None):
    cols = ""
    if widths:
        cols = "<cols>" + "".join(
            f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
            for index, width in enumerate(widths, start=1)
        ) + "</cols>"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + cols
        + "<sheetData>"
        + "".join(rows)
        + "</sheetData></worksheet>"
    )


def gerar_xlsx_fechamento(fechamento, itens):
    criado_em = fechamento.criado_em.strftime("%d/%m/%Y %H:%M") if fechamento.criado_em else "-"
    resumo_rows = [
        xlsx_row(1, ["Ponto Do Pneu Auto Center"], True),
        xlsx_row(2, [f"Relatorio de fechamento financeiro #{fechamento.id}"], True),
        xlsx_row(3, [f"Gerado em {criado_em} por {fechamento.criado_por or '-'}"]),
        xlsx_row(5, ["Campo", "Valor"], True),
    ]
    resumo = [
        ("Qtd. OS", fechamento.quantidade_os or 0),
        ("Valor total das OS", fechamento.total_os or 0),
        ("Total da franquia", fechamento.total_franquia or 0),
        ("Total faturado MaxPar", fechamento.total_faturado_maxpar or 0),
        ("Contrapartida financeira", fechamento.total_contrapartida_financeira or 0),
        ("Pecas", fechamento.total_pecas or 0),
        ("Mao de obra", fechamento.total_mao_obra or 0),
        ("Custo pecas", fechamento.total_custo_pecas or 0),
        ("Orcamento", fechamento.total_orcamento or 0),
    ]
    for offset, row in enumerate(resumo, start=6):
        resumo_rows.append(xlsx_row(offset, list(row)))

    ordens_rows = [
        xlsx_row(
            1,
            [
                "OS",
                "Cliente",
                "Placa",
                "Veiculo",
                "Seguradora",
                "Status",
                "Valor da OS",
                "Valor da franquia",
                "Valor a faturar MaxPar",
                "Contrapartida financeira",
            ],
            True,
        )
    ]
    for row_num, item in enumerate(itens, start=2):
        ordens_rows.append(
            xlsx_row(
                row_num,
                [
                    f"#{item.numero_os}",
                    item.cliente or "-",
                    item.placa or "-",
                    getattr(item, "veiculo", None) or buscar_veiculo_item_fechamento(item),
                    item.seguradora or "-",
                    item.status or "-",
                    valor_total_os(item),
                    item.franquia or 0,
                    item.faturado_maxpar or 0,
                    item.contrapartida_financeira or 0,
                ],
            )
        )

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as xlsx:
        xlsx.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>",
        )
        xlsx.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        xlsx.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Resumo" sheetId="1" r:id="rId1"/>'
            '<sheet name="Ordens" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        xlsx.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        xlsx.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            "</styleSheet>",
        )
        xlsx.writestr("xl/worksheets/sheet1.xml", xlsx_sheet(resumo_rows, [32, 18]))
        xlsx.writestr("xl/worksheets/sheet2.xml", xlsx_sheet(ordens_rows, [12, 28, 14, 24, 20, 15, 16, 18, 22, 24]))

    buffer.seek(0)
    return buffer


def buscar_veiculo_item_fechamento(item):
    if not getattr(item, "os_id", None):
        return "-"
    os_item = db.session.get(OS, item.os_id)
    if not os_item:
        return "-"
    return os_item.carro_modelo or "-"


def gerar_docx_fechamento(fechamento, itens):
    criado_em = fechamento.criado_em.strftime("%d/%m/%Y %H:%M") if fechamento.criado_em else "-"
    partes = [
        docx_paragraph("Ponto Do Pneu Auto Center", True),
        docx_paragraph(f"Relatorio de fechamento financeiro #{fechamento.id}", True),
        docx_paragraph(f"Gerado em {criado_em} por {fechamento.criado_por or '-'}"),
        docx_paragraph("Resumo", True),
        docx_table(
            [
                docx_row(["Campo", "Valor"], True),
                docx_row(["Qtd. OS", fechamento.quantidade_os or 0]),
                docx_row(["Pecas", format_brl(fechamento.total_pecas)]),
                docx_row(["Mao de obra", format_brl(fechamento.total_mao_obra)]),
                docx_row(["Valor total das OS", format_brl(fechamento.total_os)]),
                docx_row(["Custo pecas", format_brl(fechamento.total_custo_pecas)]),
                docx_row(["Orcamento", format_brl(fechamento.total_orcamento)]),
                docx_row(["Valor da franquia", format_brl(fechamento.total_franquia)]),
                docx_row(["Contrapartida financeira", format_brl(fechamento.total_contrapartida_financeira)]),
                docx_row(["Valor a faturar para MaxPar", format_brl(fechamento.total_faturado_maxpar)]),
            ]
        ),
        docx_paragraph("Ordens incluidas", True),
    ]

    rows = [
        docx_row(
            [
                "OS",
                "Cliente",
                "Placa",
                "Veiculo",
                "Seguradora",
                "Status",
                "Valor OS",
                "Valor da franquia",
                "Valor a faturar MaxPar",
            ],
            True,
        )
    ]
    for item in itens:
        rows.append(
            docx_row(
                [
                    f"#{item.numero_os}",
                    item.cliente or "-",
                    item.placa or "-",
                    getattr(item, "veiculo", None) or buscar_veiculo_item_fechamento(item),
                    item.seguradora or "-",
                    item.status or "-",
                    format_brl(valor_total_os(item)),
                    format_brl(item.franquia),
                    format_brl(item.faturado_maxpar),
                ]
            )
        )
    partes.append(docx_table(rows))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(partes)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="850"/></w:sectPr>'
        "</w:body></w:document>"
    )

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as docx:
        docx.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        docx.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        docx.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        docx.writestr("word/document.xml", document_xml)

    buffer.seek(0)
    return buffer


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
        "valor_negociado": "FLOAT",
        "contrapartida_financeira": "FLOAT",
        "faturado_maxpar": "FLOAT",
        "valor_os": "FLOAT",
        "tipo_operacao": "VARCHAR(30)",
        "descricao_servico": "TEXT",
        "data_criacao": "TIMESTAMP" if dialect == "postgresql" else "DATETIME",
        "ultima_atualizacao": "TIMESTAMP" if dialect == "postgresql" else "DATETIME",
        "fechamento_id": "INTEGER",
    }

    for column_name, column_type in column_sql.items():
        if column_name not in existing:
            db.session.execute(text(f"ALTER TABLE os ADD COLUMN {column_name} {column_type}"))

    for table_name, columns in {
        "fechamento_financeiro": {
            "total_valor_negociado": "FLOAT",
            "total_contrapartida_financeira": "FLOAT",
            "total_faturado_maxpar": "FLOAT",
        },
        "fechamento_financeiro_item": {
            "veiculo": "VARCHAR(120)",
            "valor_negociado": "FLOAT",
            "contrapartida_financeira": "FLOAT",
            "faturado_maxpar": "FLOAT",
            "valor_os": "FLOAT",
        },
    }.items():
        existing_table_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type in columns.items():
            if column_name not in existing_table_columns:
                db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))

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

    ordens_financeiro = OS.query.filter(OS.fechamento_id.is_(None)).all()
    financeiro_aberto = sum((item.valor_pecas or 0) + (item.valor_mao_obra or 0) for item in ordens_financeiro)

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
        financeiro_aberto=financeiro_aberto,
        total_itens_estoque=total_itens_estoque,
        valor_estoque=valor_estoque,
        estoque_baixo=estoque_baixo,
        total_para_brisas=total_para_brisas,
        para_brisas_baixo=para_brisas_baixo,
        prazo_alertas=prazo_alertas,
    )


@app.route("/financeiro")
@login_required
def financeiro():
    ordens = OS.query.filter(OS.fechamento_id.is_(None)).order_by(OS.id.desc()).all()
    totais = {
        "quantidade": len(ordens),
        "pecas": sum(item.valor_pecas or 0 for item in ordens),
        "mao_obra": sum(item.valor_mao_obra or 0 for item in ordens),
        "custo_pecas": sum(item.custo_pecas or 0 for item in ordens),
        "orcamento": sum(item.orcamento or 0 for item in ordens),
        "franquia": sum(item.franquia or 0 for item in ordens),
        "contrapartida": sum(item.contrapartida_financeira or 0 for item in ordens),
        "faturado_maxpar": sum(valor_faturado_maxpar(item) for item in ordens),
    }
    totais["total_os"] = sum(valor_total_os(item) for item in ordens)
    fechamentos = FechamentoFinanceiro.query.order_by(FechamentoFinanceiro.id.desc()).all()
    return render_template("financeiro.html", ordens=ordens, totais=totais, fechamentos=fechamentos)


def montar_fechamento_temporario(ordens):
    return FechamentoFinanceiro(
        id=0,
        criado_em=datetime.utcnow(),
        criado_por=session.get("username") if session else "-",
        quantidade_os=len(ordens),
        total_pecas=sum(item.valor_pecas or 0 for item in ordens),
        total_mao_obra=sum(item.valor_mao_obra or 0 for item in ordens),
        total_custo_pecas=sum(item.custo_pecas or 0 for item in ordens),
        total_orcamento=sum(item.orcamento or 0 for item in ordens),
        total_franquia=sum(item.franquia or 0 for item in ordens),
        total_receber=0,
        total_valor_negociado=sum(valor_total_os(item) for item in ordens),
        total_contrapartida_financeira=sum(item.contrapartida_financeira or 0 for item in ordens),
        total_faturado_maxpar=sum(valor_faturado_maxpar(item) for item in ordens),
    )


def montar_itens_temporarios(ordens):
    return [
        FechamentoFinanceiroItem(
            os_id=os_item.id,
            numero_os=os_item.numero_os,
            cliente=os_item.cliente,
            placa=os_item.placa,
            veiculo=os_item.carro_modelo,
            seguradora=os_item.seguradora,
            status=os_item.status,
            valor_pecas=os_item.valor_pecas or 0,
            valor_mao_obra=os_item.valor_mao_obra or 0,
            custo_pecas=os_item.custo_pecas or 0,
            orcamento=os_item.orcamento or 0,
            franquia=os_item.franquia or 0,
            total_receber=(os_item.total_receber or 0) + (os_item.franquia or 0),
            valor_negociado=os_item.valor_negociado or 0,
            contrapartida_financeira=os_item.contrapartida_financeira or 0,
            faturado_maxpar=os_item.faturado_maxpar or 0,
            valor_os=valor_total_os(os_item),
        )
        for os_item in ordens
    ]


@app.route("/financeiro/excel_aberto")
@login_required
def baixar_financeiro_aberto_xlsx():
    ordens = OS.query.filter(OS.fechamento_id.is_(None)).order_by(OS.id.asc()).all()
    if not ordens:
        flash("NÃ£o hÃ¡ OS em aberto para gerar Excel.", "warning")
        return redirect(url_for("financeiro"))

    fechamento = montar_fechamento_temporario(ordens)
    arquivo = gerar_xlsx_fechamento(fechamento, montar_itens_temporarios(ordens))
    return send_file(
        arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="financeiro-aberto.xlsx",
    )


@app.route("/financeiro/fechar", methods=["POST"])
@admin_required
def fechar_financeiro():
    ordens = OS.query.filter(OS.fechamento_id.is_(None)).order_by(OS.id.asc()).all()
    if not ordens:
        flash("Não há valores em aberto para fechar.", "warning")
        return redirect(url_for("financeiro"))

    fechamento = FechamentoFinanceiro(
        criado_por=session.get("username"),
        quantidade_os=len(ordens),
        total_pecas=sum(item.valor_pecas or 0 for item in ordens),
        total_mao_obra=sum(item.valor_mao_obra or 0 for item in ordens),
        total_custo_pecas=sum(item.custo_pecas or 0 for item in ordens),
        total_orcamento=sum(item.orcamento or 0 for item in ordens),
        total_franquia=sum(item.franquia or 0 for item in ordens),
        total_receber=0,
        total_valor_negociado=sum(valor_total_os(item) for item in ordens),
        total_contrapartida_financeira=sum(item.contrapartida_financeira or 0 for item in ordens),
        total_faturado_maxpar=sum(valor_faturado_maxpar(item) for item in ordens),
    )
    fechamento.total_os = sum(valor_total_os(item) for item in ordens)
    db.session.add(fechamento)
    db.session.flush()

    for os_item in ordens:
        db.session.add(
            FechamentoFinanceiroItem(
                fechamento_id=fechamento.id,
                os_id=os_item.id,
                numero_os=os_item.numero_os,
                cliente=os_item.cliente,
                placa=os_item.placa,
                veiculo=os_item.carro_modelo,
                seguradora=os_item.seguradora,
                status=os_item.status,
                valor_pecas=os_item.valor_pecas or 0,
                valor_mao_obra=os_item.valor_mao_obra or 0,
                custo_pecas=os_item.custo_pecas or 0,
                orcamento=os_item.orcamento or 0,
                franquia=os_item.franquia or 0,
                total_receber=(os_item.total_receber or 0) + (os_item.franquia or 0),
                valor_negociado=os_item.valor_negociado or 0,
                contrapartida_financeira=os_item.contrapartida_financeira or 0,
                faturado_maxpar=os_item.faturado_maxpar or 0,
                valor_os=valor_total_os(os_item),
            )
        )
        os_item.fechamento_id = fechamento.id

    db.session.commit()
    itens = FechamentoFinanceiroItem.query.filter_by(fechamento_id=fechamento.id).order_by(
        FechamentoFinanceiroItem.id.asc()
    ).all()
    arquivo = gerar_xlsx_fechamento(fechamento, itens)
    return send_file(
        arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"fechamento-financeiro-{fechamento.id}.xlsx",
    )


@app.route("/financeiro/relatorio/<int:id>")
@login_required
def relatorio_financeiro(id):
    fechamento = FechamentoFinanceiro.query.get_or_404(id)
    itens = FechamentoFinanceiroItem.query.filter_by(fechamento_id=fechamento.id).order_by(
        FechamentoFinanceiroItem.id.asc()
    ).all()
    return render_template("relatorio_financeiro.html", fechamento=fechamento, itens=itens)


@app.route("/financeiro/relatorio/<int:id>/docx")
@login_required
def baixar_relatorio_financeiro_docx(id):
    fechamento = FechamentoFinanceiro.query.get_or_404(id)
    itens = FechamentoFinanceiroItem.query.filter_by(fechamento_id=fechamento.id).order_by(
        FechamentoFinanceiroItem.id.asc()
    ).all()
    arquivo = gerar_docx_fechamento(fechamento, itens)
    return send_file(
        arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"fechamento-financeiro-{fechamento.id}.docx",
    )


@app.route("/financeiro/relatorio/<int:id>/xlsx")
@login_required
def baixar_relatorio_financeiro_xlsx(id):
    fechamento = FechamentoFinanceiro.query.get_or_404(id)
    itens = FechamentoFinanceiroItem.query.filter_by(fechamento_id=fechamento.id).order_by(
        FechamentoFinanceiroItem.id.asc()
    ).all()
    arquivo = gerar_xlsx_fechamento(fechamento, itens)
    return send_file(
        arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"fechamento-financeiro-{fechamento.id}.xlsx",
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
        tipo_operacao = request.form.get("tipo_operacao", "Venda").strip()
        descricao_servico = request.form.get("descricao_servico", "").strip()
        valor_pecas_raw = request.form.get("valor_pecas", "").strip()
        valor_mao_obra_raw = request.form.get("valor_mao_obra", "").strip()
        custo_pecas_raw = request.form.get("custo_pecas", "").strip()
        orcamento_raw = request.form.get("orcamento", "").strip()
        franquia_raw = request.form.get("franquia", "").strip()
        total_receber_raw = request.form.get("total_receber", "").strip()
        contrapartida_financeira_raw = request.form.get("contrapartida_financeira", "").strip()
        faturado_maxpar_raw = request.form.get("faturado_maxpar", "").strip()
        valor_os_raw = request.form.get("valor_os", "").strip()
        veiculo_terceiro = request.form.get("veiculo_terceiro") == "sim"
        form_data = request.form

        if not all([numero_os, cliente, placa, seguradora, tipo_reparo, valor_pecas_raw, valor_mao_obra_raw]):
            flash("Preencha todos os campos obrigat\u00f3rios da ordem de servi\u00e7o.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

        if seguradora not in SEGURADORAS:
            flash("Selecione uma seguradora v\u00e1lida.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

        if tipo_reparo not in TIPOS_REPARO:
            flash("Selecione um tipo de reparo v\u00e1lido.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

        if tipo_operacao not in OPERACOES_OS:
            flash("Selecione venda ou fornecimento.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

        try:
            valor_pecas = parse_float(valor_pecas_raw)
            valor_mao_obra = parse_float(valor_mao_obra_raw)
            custo_pecas = parse_float(custo_pecas_raw)
            orcamento = parse_float(orcamento_raw)
            franquia = parse_float(franquia_raw)
            total_receber = parse_float(total_receber_raw)
            contrapartida_financeira = parse_float(contrapartida_financeira_raw)
            faturado_maxpar = parse_float(faturado_maxpar_raw)
            valor_os = parse_float(valor_os_raw)
        except ValueError:
            flash("Informe valores v\u00e1lidos para pe\u00e7as e m\u00e3o de obra.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

        if min(valor_pecas, valor_mao_obra, custo_pecas, orcamento, franquia, total_receber, contrapartida_financeira, faturado_maxpar, valor_os) < 0:
            flash("Os valores de pe\u00e7as e m\u00e3o de obra n\u00e3o podem ser negativos.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

        if OS.query.filter_by(numero_os=numero_os).first():
            flash("J\u00e1 existe uma OS com esse n\u00famero.", "danger")
            return render_template("nova_os.html", form_data=form_data, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)

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
            valor_negociado=valor_os,
            contrapartida_financeira=contrapartida_financeira,
            faturado_maxpar=faturado_maxpar,
            valor_os=valor_os,
            tipo_operacao=tipo_operacao,
            descricao_servico=descricao_servico,
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

    return render_template("nova_os.html", form_data={}, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)


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
        os_item.tipo_operacao = request.form.get("tipo_operacao", os_item.tipo_operacao or "Venda").strip()
        os_item.descricao_servico = request.form.get("descricao_servico", "").strip()
        os_item.custo_pecas = parse_float(request.form.get("custo_pecas"))
        os_item.orcamento = parse_float(request.form.get("orcamento"))
        os_item.franquia = parse_float(request.form.get("franquia"))
        os_item.veiculo_terceiro = request.form.get("veiculo_terceiro") == "sim"
        os_item.total_receber = parse_float(request.form.get("total_receber"))
        os_item.contrapartida_financeira = parse_float(request.form.get("contrapartida_financeira"))
        os_item.faturado_maxpar = parse_float(request.form.get("faturado_maxpar"))
        os_item.valor_os = parse_float(request.form.get("valor_os"))
        os_item.valor_negociado = os_item.valor_os
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

    return render_template("editar_os.html", os=os_item, status_flow=STATUS_FLOW, tipos_reparo=TIPOS_REPARO, operacoes_os=OPERACOES_OS, seguradoras=SEGURADORAS)


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
