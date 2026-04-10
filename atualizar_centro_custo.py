import sqlite3

conn = sqlite3.connect("instance/ordem_compra.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE centros_custo ADD COLUMN saldo REAL DEFAULT 0")
    print("Coluna saldo adicionada com sucesso.")
except Exception as e:
    print("Aviso:", e)

conn.commit()
conn.close()
