import sqlite3

conn = sqlite3.connect("instance/ordem_compra.db")
cursor = conn.cursor()

def coluna_existe(nome_coluna):
    cursor.execute("PRAGMA table_info(usuario)")
    colunas = [c[1] for c in cursor.fetchall()]
    return nome_coluna in colunas

colunas_para_adicionar = [
    ("nome", "TEXT"),
    ("cpf", "TEXT"),
    ("data_nascimento", "TEXT"),
    ("perfil", "TEXT DEFAULT 'usuario'")
]

for coluna, tipo in colunas_para_adicionar:
    if not coluna_existe(coluna):
        print(f"Adicionando coluna: {coluna}")
        cursor.execute(f"ALTER TABLE usuario ADD COLUMN {coluna} {tipo};")
    else:
        print(f"Coluna já existe: {coluna}")

conn.commit()
conn.close()

print("Migração concluída com sucesso.")
