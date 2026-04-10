from app_resgate import app, db
from models import CentroCusto

with app.app_context():
    db.create_all()
    print("Tabelas criadas com sucesso.")
