from extensions import db
from datetime import datetime


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(20), default="user")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OS(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    numero_os = db.Column(db.String(20), unique=True, nullable=False)

    cliente = db.Column(db.String(120))
    placa = db.Column(db.String(20))
    seguradora = db.Column(db.String(120))

    status = db.Column(db.String(30), default="CRIADA")

    data_entrada = db.Column(db.Date)
    data_vistoria = db.Column(db.Date)
    data_liberacao_vistoria = db.Column(db.Date)
    data_inicio_reparo = db.Column(db.Date)
    previsao_entrega = db.Column(db.Date)
    data_pagamento = db.Column(db.Date)

    valor_pecas = db.Column(db.Float, default=0)
    valor_mao_obra = db.Column(db.Float, default=0)

    criado_por = db.Column(db.String(80))