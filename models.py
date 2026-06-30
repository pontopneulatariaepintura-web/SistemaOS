from datetime import datetime

from extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user", nullable=False)
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
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    ultima_atualizacao = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EstoquePeca(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    codigo = db.Column(db.String(50))
    fornecedor = db.Column(db.String(120))
    quantidade = db.Column(db.Integer, default=0)
    estoque_minimo = db.Column(db.Integer, default=0)
    valor_unitario = db.Column(db.Float, default=0)
    localizacao = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def valor_total(self):
        return (self.quantidade or 0) * (self.valor_unitario or 0)

    @property
    def estoque_baixo(self):
        return (self.quantidade or 0) <= (self.estoque_minimo or 0)



class EstoqueParaBrisa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    veiculo = db.Column(db.String(120), nullable=False)
    modelo = db.Column(db.String(120))
    ano_inicial = db.Column(db.Integer)
    ano_final = db.Column(db.Integer)
    lado = db.Column(db.String(40), default="Dianteiro")
    codigo = db.Column(db.String(50))
    fornecedor = db.Column(db.String(120))
    quantidade = db.Column(db.Integer, default=0)
    estoque_minimo = db.Column(db.Integer, default=0)
    valor_unitario = db.Column(db.Float, default=0)
    localizacao = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def descricao(self):
        partes = [self.veiculo]
        if self.modelo:
            partes.append(self.modelo)
        if self.ano_inicial and self.ano_final:
            partes.append(f"{self.ano_inicial}/{self.ano_final}")
        elif self.ano_inicial:
            partes.append(f"a partir de {self.ano_inicial}")
        elif self.ano_final:
            partes.append(f"at? {self.ano_final}")
        return " - ".join(partes)

    @property
    def valor_total(self):
        return (self.quantidade or 0) * (self.valor_unitario or 0)

    @property
    def estoque_baixo(self):
        return (self.quantidade or 0) <= (self.estoque_minimo or 0)
