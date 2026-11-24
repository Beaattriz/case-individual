"""
Painel Folia · Regras de negócio e dados
------------------------------------------------------------
Este arquivo NÃO sabe nada de Flask nem de HTTP. Ele só:
  - guarda os postos (numa lista em memória);
  - aplica as regras de negócio;
  - devolve os dados ou levanta ErroDeRegra quando algo não pode.

Quem recebe as requisições e transforma tudo em JSON é o app.py.

    Navegador  ->  app.py (rotas)  ->  backend.py (regras + dados)

Regras de negócio
    1. A fila nunca fica negativa
    2. Só os status aberto, lotado e fechado são aceitos
    3. Posto fechado nunca é recomendado (lotado também não)
    4. Fila acima de LIMITE_FILA -> posto vira "lotado" sozinho
    5. Não dá para reabrir posto com a fila acima do limite
    6. Posto fechado não recebe +1 na fila

Privacidade: nenhum dado pessoal ou clínico é guardado.
Só contamos quantas pessoas estão na fila.
"""

import os
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

# .env é opcional: só é lido se o python-dotenv estiver instalado
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
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


LIMITE_FILA = inteiro_do_ambiente("LIMITE_FILA", 30)      # fila acima disso = lotado
TOTAL_TRECHOS = inteiro_do_ambiente("TOTAL_TRECHOS", 10)  # trechos do circuito
STATUS_VALIDOS = ("aberto", "lotado", "fechado")


class ErroDeRegra(Exception):
    """Algo que a regra de negócio não permite. Leva a mensagem e o código HTTP."""

    def __init__(self, mensagem, codigo):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


# ============================================================
# Dados (em memória: reiniciar o servidor volta ao estado inicial)
# ============================================================

# "trecho" = posição do posto no circuito Barra–Ondina (1 a TOTAL_TRECHOS)
POSTOS_INICIAIS = [
    {"id": 1, "nome": "Posto Farol da Barra",  "trecho": 1,  "fila": 0, "status": "aberto"},
    {"id": 2, "nome": "Posto Porto da Barra",  "trecho": 3,  "fila": 0, "status": "aberto"},
    {"id": 3, "nome": "Posto Morro do Cristo", "trecho": 5,  "fila": 0, "status": "aberto"},
    {"id": 4, "nome": "Posto Calabar",         "trecho": 6,  "fila": 0, "status": "aberto"},
    {"id": 5, "nome": "Posto Ondina",          "trecho": 8,  "fila": 0, "status": "aberto"},
    {"id": 6, "nome": "Posto Rio Vermelho",    "trecho": 10, "fila": 0, "status": "fechado"},
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


def _buscar(id_posto):
    posto = next((p for p in postos if p["id"] == id_posto), None)
    if posto is None:
        raise ErroDeRegra("Posto não encontrado.", 404)
    return posto


reiniciar_dados()


# ============================================================
# Validações
# ============================================================

def _eh_inteiro(valor):
    # Em Python, True/False também contam como int; aqui não aceitamos
    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_trecho(texto):
    """Converte o trecho que veio da URL (texto) em número, ou levanta erro."""
    texto = (texto or "").strip()
    if not texto:
        raise ErroDeRegra("Informe o trecho do trio.", 400)
    try:
        trecho = int(texto)
    except ValueError:
        raise ErroDeRegra("O trecho precisa ser um número inteiro.", 400)
    if not 1 <= trecho <= TOTAL_TRECHOS:
        raise ErroDeRegra(f"O trecho precisa estar entre 1 e {TOTAL_TRECHOS}.", 422)
    return trecho


def _distancia(posto, trecho):
    return abs(posto["trecho"] - trecho)


def _aplicar_limite(posto):
    """Regra 4: posto aberto com fila acima do limite vira lotado sozinho."""
    if posto["status"] == "aberto" and posto["fila"] > LIMITE_FILA:
        posto["status"] = "lotado"


# ============================================================
# Operações (chamadas pelas rotas do app.py)
# ============================================================

def listar_postos(trecho=None):
    """
    Devolve todos os postos. Se vier o trecho do trio, ordena do mais
    perto para o mais longe (empate: fila menor) e inclui a "distancia".
    """
    with trava:
        lista = deepcopy(postos)

    if trecho is not None:
        lista.sort(key=lambda p: (_distancia(p, trecho), p["fila"], p["id"]))
        for p in lista:
            p["distancia"] = _distancia(p, trecho)

    return {
        "limite_fila": LIMITE_FILA,
        "total_trechos": TOTAL_TRECHOS,
        "gerado_em": agora(),
        "postos": lista,
    }


def alterar_fila(id_posto, variacao):
    """Soma +1 ou -1 na fila do posto."""
    if not _eh_inteiro(variacao) or variacao not in (1, -1):
        raise ErroDeRegra("A variação deve ser 1 ou -1.", 422)

    with trava:
        posto = _buscar(id_posto)

        # Regra 6
        if variacao == 1 and posto["status"] == "fechado":
            raise ErroDeRegra("O posto está fechado e não pode receber pessoas na fila.", 409)

        # Regra 1
        if posto["fila"] + variacao < 0:
            raise ErroDeRegra("A fila já está em zero.", 409)

        posto["fila"] += variacao
        _aplicar_limite(posto)
        posto["atualizado_em"] = agora()
        return dict(posto)


def alterar_status(id_posto, status):
    """Muda o status do posto para aberto, lotado ou fechado."""
    status = status.strip().lower() if isinstance(status, str) else None

    # Regra 2
    if status not in STATUS_VALIDOS:
        raise ErroDeRegra("Status inválido. Use: aberto, lotado ou fechado.", 422)

    with trava:
        posto = _buscar(id_posto)

        # Regra 5
        if status == "aberto" and posto["fila"] > LIMITE_FILA:
            raise ErroDeRegra(
                f"A fila ({posto['fila']}) está acima do limite ({LIMITE_FILA}). "
                "Diminua a fila antes de reabrir o posto.",
                409,
            )

        posto["status"] = status
        posto["atualizado_em"] = agora()
        return dict(posto)


def recomendar_posto(trecho):
    """O posto ABERTO mais perto do trio; empate -> fila menor; empate -> menor id."""
    with trava:
        # Regra 3: fechado e lotado ficam de fora
        candidatos = [p for p in postos if p["status"] == "aberto"]
        if not candidatos:
            raise ErroDeRegra("Nenhum posto disponível no momento.", 404)

        melhor = min(candidatos, key=lambda p: (_distancia(p, trecho), p["fila"], p["id"]))
        return {**melhor, "distancia": _distancia(melhor, trecho)}


def cadastrar_posto(nome, trecho):
    """Cria um posto novo (começa aberto e com fila zero)."""
    if not isinstance(nome, str) or len(nome.strip()) < 3:
        raise ErroDeRegra("O nome precisa ter pelo menos 3 letras.", 422)
    nome = nome.strip()
    if len(nome) > 60:
        raise ErroDeRegra("O nome pode ter no máximo 60 caracteres.", 422)
    if not _eh_inteiro(trecho) or not 1 <= trecho <= TOTAL_TRECHOS:
        raise ErroDeRegra(f"O trecho precisa ser um número de 1 a {TOTAL_TRECHOS}.", 422)

    with trava:
        if any(p["nome"].lower() == nome.lower() for p in postos):
            raise ErroDeRegra("Já existe um posto com esse nome.", 409)
        novo = {
            "id": max((p["id"] for p in postos), default=0) + 1,
            "nome": nome,
            "trecho": trecho,
            "fila": 0,
            "status": "aberto",
            "atualizado_em": agora(),
        }
        postos.append(novo)
        return dict(novo)
