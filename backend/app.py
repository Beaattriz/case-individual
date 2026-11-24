"""
Painel Folia · Backend (Flask)
------------------------------------------------------------
API do Bloco Saúde. Toda regra de negócio fica AQUI; o
frontend só mostra os dados e chama as rotas abaixo.

    Navegador (HTML/CSS/JS)  ->  app.py (Flask)  ->  lista em memória

Rotas
    GET   /api/postos[?trecho=<n>]       lista os postos (ordenados pela
                                         distância do trio se vier o trecho)
    PATCH /api/postos/<id>/fila          {"variacao": 1} ou {"variacao": -1}
    PATCH /api/postos/<id>/status        {"status": "aberto" | "lotado" | "fechado"}
    GET   /api/recomendacao?trecho=<n>   posto recomendado para o trecho
    POST  /api/postos                    {"nome": "...", "trecho": n} (cadastro)

Regras de negócio
    1. A fila nunca fica negativa                               -> 409
    2. Só os status aberto, lotado e fechado são aceitos        -> 422
    3. Posto fechado nunca é recomendado (lotado também não)
    4. Fila acima de LIMITE_FILA -> posto vira "lotado" sozinho
    5. Não dá para reabrir um posto com a fila acima do limite  -> 409
    6. Posto fechado não recebe +1 na fila                      -> 409

Configuração (variáveis de ambiente ou backend/.env)
    LIMITE_FILA    padrão 30   (fila acima disso = lotado)
    TOTAL_TRECHOS  padrão 10   (quantos trechos tem o circuito)
    PORTA          padrão 5000

Privacidade: nenhum dado pessoal ou clínico é recebido ou
guardado. Só contamos quantas pessoas estão na fila.
"""

import os
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

PASTA_BACKEND = Path(__file__).resolve().parent
PASTA_FRONTEND = PASTA_BACKEND.parent / "frontend"

# .env é opcional: só é lido se o python-dotenv estiver instalado
try:
    from dotenv import load_dotenv
    load_dotenv(PASTA_BACKEND / ".env")
except ImportError:
    pass


# ============================================================
# Configuração
# ============================================================

def inteiro_do_ambiente(nome, padrao):
    """Lê um número inteiro positivo do ambiente; se vier errado, usa o padrão."""
    try:
        valor = int(os.environ.get(nome, padrao))
    except ValueError:
        return padrao
    return valor if valor > 0 else padrao


LIMITE_FILA = inteiro_do_ambiente("LIMITE_FILA", 30)
TOTAL_TRECHOS = inteiro_do_ambiente("TOTAL_TRECHOS", 10)
PORTA = inteiro_do_ambiente("PORTA", 5000)

STATUS_VALIDOS = ("aberto", "lotado", "fechado")
ARQUIVOS_FRONTEND = ("index.html", "voluntario.html", "coordenacao.html", "style.css", "script.js")

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False  # acentos legíveis nas respostas


# ============================================================
# Dados (em memória: reiniciar o servidor volta ao estado inicial)
# ============================================================

# "trecho" = posição do posto no circuito Barra–Ondina (1 a TOTAL_TRECHOS)
POSTOS_INICIAIS = [
    {"id": 1, "nome": "Posto Farol da Barra",   "trecho": 1,  "fila": 0, "status": "aberto"},
    {"id": 2, "nome": "Posto Porto da Barra",   "trecho": 3,  "fila": 0, "status": "aberto"},
    {"id": 3, "nome": "Posto Morro do Cristo",  "trecho": 5,  "fila": 0, "status": "aberto"},
    {"id": 4, "nome": "Posto Calabar",          "trecho": 6,  "fila": 0, "status": "aberto"},
    {"id": 5, "nome": "Posto Ondina",           "trecho": 8,  "fila": 0, "status": "aberto"},
    {"id": 6, "nome": "Posto Rio Vermelho",     "trecho": 10, "fila": 0, "status": "fechado"},
]

# Trava: se dois voluntários clicam ao mesmo tempo, um pedido termina
# antes de o outro começar (assim a fila nunca vira -1 por acidente).
trava = threading.Lock()
postos = []


def agora():
    """Horário local com fuso, ex.: 2027-02-12T20:15:03-03:00"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reiniciar_dados():
    global postos
    horario = agora()
    postos = [{**p, "atualizado_em": horario} for p in deepcopy(POSTOS_INICIAIS)]


def buscar_posto(id_posto):
    return next((p for p in postos if p["id"] == id_posto), None)


reiniciar_dados()


# ============================================================
# Funções de apoio
# ============================================================

def erro(mensagem, codigo):
    return jsonify({"erro": mensagem}), codigo


def ler_json():
    """Devolve o corpo JSON (dict) ou None se ele não for um objeto JSON."""
    corpo = request.get_json(silent=True)
    return corpo if isinstance(corpo, dict) else None


def eh_inteiro(valor):
    # Em Python, True/False também contam como int; aqui não aceitamos
    return isinstance(valor, int) and not isinstance(valor, bool)


def ler_trecho(texto):
    """
    Converte o ?trecho= da URL.
    Devolve (trecho, None) ou (None, resposta_de_erro).
    """
    texto = (texto or "").strip()
    if not texto:
        return None, erro("Informe o trecho do trio.", 400)
    try:
        trecho = int(texto)
    except ValueError:
        return None, erro("O trecho precisa ser um número inteiro.", 400)
    if not 1 <= trecho <= TOTAL_TRECHOS:
        return None, erro(f"O trecho precisa estar entre 1 e {TOTAL_TRECHOS}.", 422)
    return trecho, None


def aplicar_limite(posto):
    """Regra 4: posto aberto com fila acima do limite vira lotado sozinho."""
    if posto["status"] == "aberto" and posto["fila"] > LIMITE_FILA:
        posto["status"] = "lotado"


def distancia(posto, trecho):
    return abs(posto["trecho"] - trecho)


@app.after_request
def cabecalhos_api(resposta):
    if request.path.startswith("/api/"):
        # Dado de fila envelhece rápido: o navegador não deve guardar cópia
        resposta.headers["Cache-Control"] = "no-store"

        # CORS só para desenvolvimento local: libera a página aberta direto
        # do arquivo (origem "null") ou pelo Live Server (127.0.0.1/localhost).
        origem = request.headers.get("Origin", "")
        if origem == "null" or origem.startswith(("http://127.0.0.1:", "http://localhost:")):
            resposta.headers["Access-Control-Allow-Origin"] = origem
            resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            resposta.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resposta.headers["Vary"] = "Origin"
    return resposta


# ============================================================
# Rotas da API
# ============================================================

@app.get("/api/postos")
def listar_postos():
    trecho = None
    if "trecho" in request.args:
        trecho, falha = ler_trecho(request.args["trecho"])
        if falha:
            return falha

    with trava:
        lista = deepcopy(postos)

    if trecho is not None:
        # Ordem: mais perto do trio primeiro; empate -> fila menor
        lista.sort(key=lambda p: (distancia(p, trecho), p["fila"], p["id"]))
        for p in lista:
            p["distancia"] = distancia(p, trecho)

    return jsonify({
        "limite_fila": LIMITE_FILA,
        "total_trechos": TOTAL_TRECHOS,
        "gerado_em": agora(),
        "postos": lista,
    }), 200


@app.patch("/api/postos/<int:id_posto>/fila")
def alterar_fila(id_posto):
    corpo = ler_json()
    if corpo is None:
        return erro("Envie um JSON, ex.: {\"variacao\": 1}.", 400)

    variacao = corpo.get("variacao")
    if not eh_inteiro(variacao) or variacao not in (1, -1):
        return erro("A variação deve ser 1 ou -1.", 422)

    with trava:
        posto = buscar_posto(id_posto)
        if posto is None:
            return erro("Posto não encontrado.", 404)

        # Regra 6
        if variacao == 1 and posto["status"] == "fechado":
            return erro("O posto está fechado e não pode receber pessoas na fila.", 409)

        # Regra 1
        if posto["fila"] + variacao < 0:
            return erro("A fila já está em zero.", 409)

        posto["fila"] += variacao
        aplicar_limite(posto)
        posto["atualizado_em"] = agora()
        resposta = dict(posto)

    return jsonify(resposta), 200


@app.patch("/api/postos/<int:id_posto>/status")
def alterar_status(id_posto):
    corpo = ler_json()
    if corpo is None:
        return erro("Envie um JSON, ex.: {\"status\": \"aberto\"}.", 400)

    status = corpo.get("status")
    status = status.strip().lower() if isinstance(status, str) else None

    # Regra 2
    if status not in STATUS_VALIDOS:
        return erro("Status inválido. Use: aberto, lotado ou fechado.", 422)

    with trava:
        posto = buscar_posto(id_posto)
        if posto is None:
            return erro("Posto não encontrado.", 404)

        # Regra 5
        if status == "aberto" and posto["fila"] > LIMITE_FILA:
            return erro(
                f"A fila ({posto['fila']}) está acima do limite ({LIMITE_FILA}). "
                "Diminua a fila antes de reabrir o posto.",
                409,
            )

        posto["status"] = status
        posto["atualizado_em"] = agora()
        resposta = dict(posto)

    return jsonify(resposta), 200


@app.get("/api/recomendacao")
def recomendar_posto():
    trecho, falha = ler_trecho(request.args.get("trecho"))
    if falha:
        return falha

    with trava:
        # Regra 3: só postos abertos (fechado e lotado ficam de fora)
        candidatos = [p for p in postos if p["status"] == "aberto"]
        if not candidatos:
            return erro("Nenhum posto disponível no momento.", 404)

        # Mais perto do trio; empate -> fila menor; empate -> menor id
        melhor = min(candidatos, key=lambda p: (distancia(p, trecho), p["fila"], p["id"]))
        resposta = {**melhor, "distancia": distancia(melhor, trecho)}

    return jsonify(resposta), 200


@app.post("/api/postos")
def cadastrar_posto():
    corpo = ler_json()
    if corpo is None:
        return erro("Envie um JSON com nome e trecho.", 400)

    nome = corpo.get("nome")
    trecho = corpo.get("trecho")

    if not isinstance(nome, str) or len(nome.strip()) < 3:
        return erro("O nome precisa ter pelo menos 3 letras.", 422)
    nome = nome.strip()
    if len(nome) > 60:
        return erro("O nome pode ter no máximo 60 caracteres.", 422)
    if not eh_inteiro(trecho) or not 1 <= trecho <= TOTAL_TRECHOS:
        return erro(f"O trecho precisa ser um número de 1 a {TOTAL_TRECHOS}.", 422)

    with trava:
        if any(p["nome"].lower() == nome.lower() for p in postos):
            return erro("Já existe um posto com esse nome.", 409)
        novo = {
            "id": max((p["id"] for p in postos), default=0) + 1,
            "nome": nome,
            "trecho": trecho,
            "fila": 0,
            "status": "aberto",
            "atualizado_em": agora(),
        }
        postos.append(novo)
        resposta = dict(novo)

    return jsonify(resposta), 201


# ============================================================
# Erros sempre em JSON
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


# ============================================================
# Páginas do frontend (servidas pelo próprio Flask)
# ============================================================

@app.get("/")
def pagina_inicial():
    return send_from_directory(PASTA_FRONTEND, "index.html")


@app.get("/<path:arquivo>")
def arquivos_frontend(arquivo):
    # Entrega só os arquivos do frontend, nada além
    if arquivo not in ARQUIVOS_FRONTEND:
        return erro("Recurso não encontrado.", 404)
    return send_from_directory(PASTA_FRONTEND, arquivo)


if __name__ == "__main__":
    print(f"Painel Folia no ar: http://127.0.0.1:{PORTA}  (limite da fila: {LIMITE_FILA})")
    app.run(host="127.0.0.1", port=PORTA, debug=False)
