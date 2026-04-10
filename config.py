import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Chave de segurança do sistema
    SECRET_KEY = 'chave-secreta-ordem-compra'

    # Banco de dados SQLite
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'ordem_compra.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuração de e-mail (ajustaremos depois)
    MAIL_SERVER = 'smtp.seuprovedor.com'
    MAIL_PORT = 587
    MAIL_USERNAME = 'seuemail@dominio.com'
    MAIL_PASSWORD = 'suasenha'
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
