from app_resgate import app
from models import db, Usuario
from werkzeug.security import generate_password_hash

with app.app_context():
    admin = Usuario(
        nome="Administrador",
        email="admin@cqp.com.br",
        senha=generate_password_hash("123456"),
        perfil="admin"
    )
    db.session.add(admin)
    db.session.commit()
    print("✅ Admin criado com sucesso")
