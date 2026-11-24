"""
Painel Folia · Rotas (Flask)
------------------------------------------------------------
Este arquivo só cuida do HTTP: recebe a requisição, chama a
função certa do backend.py e devolve a resposta em JSON.
As regras de negócio e os dados ficam no backend.py.

    Navegador  ->  app.py (rotas)  ->  backend.py (regras + dados)

Rotas da API
    GET   /api/postos                  lista os postos (?trecho=<n> ordena pela distância do trio)
    PATCH /api/postos/<id>/fila        {"variacao": 1} ou {"variacao": -1}
    PATCH /api/postos/<id>/status      {"status": "aberto" | "lotado" | "fechado"}
    GET   /api/recomendacao?trecho=<n> posto recomendado para o trecho
    POST  /api/postos                  {"nome": "...", "trecho": n}  (cadastro)

Para rodar:  python backend/app.py   ->   http://127.0.0.1:5000
"""

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import backend
from backend import ErroDeRegra

PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
ARQUIVOS_FRONTEND = ("index.html", "voluntario.html", "coordenacao.html", "style.css", "script.js")
PORTA = backend.inteiro_do_ambiente("PORTA", 5000)

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False  # acentos legíveis nas respostas


# ============================================================
# Funções de apoio
# ============================================================

def erro(mensagem, codigo):
    return jsonify({"erro": mensagem}), codigo


def ler_json():
    """Devolve o corpo JSON da requisição (dict) ou None se não for um objeto JSON."""
    corpo = request.get_json(silent=True)
    return corpo if isinstance(corpo, dict) else None


@app.errorhandler(ErroDeRegra)
def tratar_erro_de_regra(e):
    """Qualquer ErroDeRegra levantado no backend.py vira {"erro": ...} com o código certo."""
    return erro(e.mensagem, e.codigo)


@app.after_request
def cabecalhos_api(resposta):
    if request.path.startswith("/api/"):
        # Dado de fila envelhece rápido: o navegador não deve guardar cópia
        resposta.headers["Cache-Control"] = "no-store"

        # Libera a página aberta pelo Live Server (127.0.0.1/localhost)
        # ou direto do arquivo (origem "null"). Só para uso local.
        origem = request.headers.get("Origin", "")
        if origem == "null" or origem.startswith(("http://127.0.0.1:", "http://localhost:")):
            resposta.headers["Access-Control-Allow-Origin"] = origem
            resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            resposta.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resposta.headers["Vary"] = "Origin"
    return resposta


# ============================================================
# Rotas GET
# ============================================================

@app.route("/api/postos", methods=["GET"])
def get_postos():
    trecho = None
    if "trecho" in request.args:
        trecho = backend.validar_trecho(request.args["trecho"])
    return jsonify(backend.listar_postos(trecho)), 200


@app.route("/api/recomendacao", methods=["GET"])
def get_recomendacao():
    trecho = backend.validar_trecho(request.args.get("trecho"))
    return jsonify(backend.recomendar_posto(trecho)), 200


# ============================================================
# Rotas PATCH
# ============================================================

@app.route("/api/postos/<int:id_posto>/fila", methods=["PATCH"])
def patch_fila(id_posto):
    corpo = ler_json()
    if corpo is None:
        return erro('Envie um JSON, ex.: {"variacao": 1}.', 400)
    posto = backend.alterar_fila(id_posto, corpo.get("variacao"))
    return jsonify(posto), 200


@app.route("/api/postos/<int:id_posto>/status", methods=["PATCH"])
def patch_status(id_posto):
    corpo = ler_json()
    if corpo is None:
        return erro('Envie um JSON, ex.: {"status": "aberto"}.', 400)
    posto = backend.alterar_status(id_posto, corpo.get("status"))
    return jsonify(posto), 200


# ============================================================
# Rota POST (usada pelo "Cadastrar novo posto" da coordenação)
# ============================================================

@app.route("/api/postos", methods=["POST"])
def post_posto():
    corpo = ler_json()
    if corpo is None:
        return erro("Envie um JSON com nome e trecho.", 400)
    novo = backend.cadastrar_posto(corpo.get("nome"), corpo.get("trecho"))
    return jsonify(novo), 201


# ============================================================
# Páginas do site (o Flask entrega o frontend também)
# ============================================================

@app.route("/", methods=["GET"])
def pagina_inicial():
    return send_from_directory(PASTA_FRONTEND, "index.html")


@app.route("/<path:arquivo>", methods=["GET"])
def arquivos_frontend(arquivo):
    # Aceita também /frontend/arquivo.html (caminho usado pelo Live Server)
    arquivo = arquivo.removeprefix("frontend/")
    if arquivo not in ARQUIVOS_FRONTEND:
        return erro("Página não encontrada.", 404)
    return send_from_directory(PASTA_FRONTEND, arquivo)


# ============================================================
# Erros genéricos sempre em JSON
# ============================================================

@app.errorhandler(404)
def nao_encontrado(_e):
    return erro("Recurso não encontrado.", 404)


@app.errorhandler(405)
def metodo_nao_permitido(_e):
    return erro("Método não permitido para esta rota.", 405)


@app.errorhandler(500)
def erro_interno(_e):
    return erro("Erro interno no servidor.", 500)


if __name__ == "__main__":
    print(f"Painel Folia no ar: http://127.0.0.1:{PORTA}  (limite da fila: {backend.LIMITE_FILA})")
    app.run(host="127.0.0.1", port=PORTA, debug=os.environ.get("FLASK_DEBUG") == "1")
