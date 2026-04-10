from app import app
from models import db, OrdemCompra
from datetime import date, timedelta

with app.app_context():
    ordem1 = OrdemCompra(
        centro_custo="Administração",
        fornecedor="Fornecedor A",
        data_inicio=date.today(),
        prazo=10,
        fim_prazo=date.today() + timedelta(days=10),
        dias_a_vencer=10,
        quantidade=1,
        valor=5000.00,
        aprovador="Diretor",
        status="Verde"
    )

    ordem2 = OrdemCompra(
        centro_custo="Obras",
        fornecedor="Fornecedor B",
        data_inicio=date.today(),
        prazo=2,
        fim_prazo=date.today() + timedelta(days=2),
        dias_a_vencer=2,
        quantidade=3,
        valor=12000.00,
        aprovador="Secretário",
        status="Amarelo"
    )

    db.session.add_all([ordem1, ordem2])
    db.session.commit()

    print("Ordens inseridas com sucesso!")
