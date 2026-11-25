# Este arquivo tem três partes, nesta ordem:
#   1. Configuração   -> limite da fila, número de trechos, status válidos
#   2. Dados e regras -> a lista de postos e as regras de negócio
#   3. Rotas (Flask)  -> recebem os pedidos do navegador e devolvem JSON
#
#   Navegador  ->  rotas  ->  regras + dados
#
# Regras de negócio
#   1. A fila nunca fica negativa
#   2. Só os status aberto, lotado e fechado são aceitos
#   3. Posto fechado nunca é recomendado (lotado também não)
#   4. Fila acima de LIMITE_FILA -> posto vira "lotado" sozinho
#   5. Não dá para reabrir posto com a fila acima do limite
#   6. Posto fechado não recebe +1 na fila
#   7. A recomendação pesa distância E fila: custo = distância + fila ÷ PESSOAS_POR_TRECHO
#
# Privacidade: nenhum dado pessoal ou clínico é guardado.
# Só contamos quantas pessoas estão na fila.

# ------------------------------------------------------------
# Importações
# ------------------------------------------------------------
import os                          # lê variáveis de ambiente (LIMITE_FILA, PORTA...)
import threading                   # cria a "trava" contra cliques ao mesmo tempo
from copy import deepcopy          # faz cópias independentes das listas/dicionários
from datetime import datetime      # pega a data e hora atual
from pathlib import Path           # monta caminhos de pastas sem se preocupar com / ou \

# Flask: cria o servidor
# jsonify: transforma dicionário Python em resposta JSON
# request: dá acesso ao pedido que chegou (URL, corpo, cabeçalhos)
# send_from_directory: entrega um arquivo de uma pasta (usado para as páginas HTML)
from flask import Flask, jsonify, request, send_from_directory

# O arquivo backend/.env é OPCIONAL: serve para mudar o limite da fila
# sem mexer no código. Se o python-dotenv não estiver instalado,
# o "except" ignora e seguimos com os valores padrão.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


# ############################################################
# PARTE 1 · CONFIGURAÇÃO
# ############################################################

def inteiro_do_ambiente(nome, padrao):
    """
    Lê um número da configuração (variável de ambiente ou .env).
    Se não existir, vier com letra ou for zero/negativo, usa o valor padrão.
    Ex.: inteiro_do_ambiente("LIMITE_FILA", 20) -> 20 se ninguém configurou.
    """
    try:
        valor = int(os.environ.get(nome, padrao))
    except ValueError:             # ex.: LIMITE_FILA=abc
        return padrao
    return valor if valor > 0 else padrao


# Limite configurável: com MAIS pessoas que isso na fila, o posto vira "lotado" sozinho
LIMITE_FILA = inteiro_do_ambiente("LIMITE_FILA", 20)

# Quantos trechos tem o circuito (o trio só pode estar do trecho 1 até este número)
TOTAL_TRECHOS = inteiro_do_ambiente("TOTAL_TRECHOS", 10)

# Usado na recomendação (regra 7): andar 1 trecho "vale" o mesmo que esperar
# esta quantidade de pessoas na fila. Com 5, um posto vazio a 1 trecho de distância
# ganha de um posto no trecho do trio que já tem mais de 5 pessoas esperando.
PESSOAS_POR_TRECHO = inteiro_do_ambiente("PESSOAS_POR_TRECHO", 5)

# Porta onde o site vai rodar (padrão 5000 -> http://127.0.0.1:5000)
PORTA = inteiro_do_ambiente("PORTA", 5000)

# Os únicos status aceitos (regra 2)
STATUS_VALIDOS = ("aberto", "lotado", "fechado")

# Pasta onde estão o HTML, o CSS e o JS (sobe uma pasta a partir de backend/ e entra em frontend/)
PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# Lista dos ÚNICOS arquivos que o servidor aceita entregar.
# Assim ninguém consegue pedir, por exemplo, o código do app.py pelo navegador.
ARQUIVOS_FRONTEND = ("index.html", "voluntario.html", "coordenacao.html", "style.css", "script.js")


class ErroDeRegra(Exception):
    """
    Erro "nosso", usado quando alguma regra de negócio não permite a ação.
    Carrega a mensagem para o usuário e o código HTTP, por exemplo:
        raise ErroDeRegra("Não é permitido deixar a fila negativa: ela já está em zero.", 409)

    Códigos usados:
        400 = pedido mal feito (faltou informação)
        404 = não encontrado
        409 = conflito (a ação vai contra uma regra, ex.: fila negativa)
        422 = valor inválido (ex.: status "cheio")

    A função tratar_erro_de_regra (lá na parte 3) captura esse erro
    e devolve {"erro": mensagem} para o navegador.
    """

    def __init__(self, mensagem, codigo):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


# ############################################################
# PARTE 2 · DADOS E REGRAS DE NEGÓCIO
# ############################################################

# ============================================================
# Dados (em memória: reiniciar o servidor volta ao estado inicial)
# ============================================================

# Postos com que o sistema começa.
# "trecho" = posição do posto no circuito Barra–Ondina (1 a TOTAL_TRECHOS).
# Usamos o trecho para medir a distância até o trio.
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
# Todo trecho de código que lê ou altera a lista fica dentro de "with trava:".
trava = threading.Lock()

# A lista "de verdade", que muda enquanto o site é usado.
# Ela é preenchida pela função reiniciar_dados() logo abaixo.
postos = []


def agora():
    """Data e hora atuais com fuso, ex.: 2027-02-12T20:15:03-03:00 (o JavaScript entende esse formato)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reiniciar_dados():
    """
    Copia os POSTOS_INICIAIS para a lista "postos" e marca o horário de agora.
    deepcopy garante que mexer em "postos" nunca altera POSTOS_INICIAIS.
    """
    global postos                  # "global": altera a variável postos lá de fora da função
    horario = agora()
    postos = [{**p, "atualizado_em": horario} for p in deepcopy(POSTOS_INICIAIS)]


def _buscar(id_posto):
    """
    Procura um posto pelo id. Se não achar, levanta erro 404.
    (O "_" no começo do nome indica que é uma função de uso interno.)
    """
    posto = next((p for p in postos if p["id"] == id_posto), None)
    if posto is None:
        raise ErroDeRegra("Posto não encontrado.", 404)
    return posto


# Carrega os postos assim que o servidor começa
reiniciar_dados()


# ============================================================
# Validações e cálculos auxiliares
# ============================================================

def _eh_inteiro(valor):
    """Confere se é um número inteiro de verdade."""
    # Em Python, True/False também contam como int (True == 1); aqui não aceitamos
    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_trecho(texto):
    """
    O trecho chega da URL como TEXTO (ex.: "4"). Esta função:
      - confere se veio alguma coisa  (senão: erro 400)
      - converte para número           (senão: erro 400)
      - confere se está entre 1 e TOTAL_TRECHOS (senão: erro 422)
    e devolve o número.
    """
    texto = (texto or "").strip()  # None vira "", e tira espaços das pontas
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
    """Quantos trechos separam o posto do trio. abs() tira o sinal: tanto faz se está antes ou depois."""
    return abs(posto["trecho"] - trecho)


def _aplicar_limite(posto):
    """Regra 4: posto aberto com fila acima do limite vira lotado sozinho."""
    if posto["status"] == "aberto" and posto["fila"] > LIMITE_FILA:
        posto["status"] = "lotado"


# ============================================================
# Operações (cada uma é chamada por uma rota da parte 3)
# ============================================================

def listar_postos(trecho=None):
    """
    Usada por: GET /api/postos

    Devolve todos os postos. Se vier o trecho do trio, ordena do mais
    perto para o mais longe (empate: fila menor) e inclui a "distancia".
    Também manda o limite da fila (o frontend usa para escolher a cor amarela)
    e o total de trechos (para o campo "O trio está no trecho").
    """
    with trava:
        lista = deepcopy(postos)   # cópia: ordenar aqui não bagunça a lista original

    if trecho is not None:
        # Ordena por (distância, fila, id): primeiro o mais perto; se empatar, o de fila menor
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
    """
    Usada por: PATCH /api/postos/<id>/fila

    Soma +1 ou -1 na fila do posto e devolve o posto atualizado.
    """
    # Só aceitamos exatamente 1 ou -1 (nada de +5 de uma vez)
    if not _eh_inteiro(variacao) or variacao not in (1, -1):
        raise ErroDeRegra("A variação deve ser 1 ou -1.", 422)

    with trava:
        posto = _buscar(id_posto)

        # Regra 6: posto fechado não recebe gente nova (mas pode esvaziar a fila com -1)
        if variacao == 1 and posto["status"] == "fechado":
            raise ErroDeRegra("O posto está fechado e não pode receber pessoas na fila.", 409)

        # Regra 1: a fila nunca fica negativa
        if posto["fila"] + variacao < 0:
            raise ErroDeRegra("Não é permitido deixar a fila negativa: ela já está em zero.", 409)

        posto["fila"] += variacao
        _aplicar_limite(posto)              # Regra 4: se passou do limite, vira lotado
        posto["atualizado_em"] = agora()    # guarda a hora para a coordenação saber se o dado é recente
        return dict(posto)                  # devolve uma cópia do posto


def alterar_status(id_posto, status):
    """
    Usada por: PATCH /api/postos/<id>/status

    Muda o status do posto para aberto, lotado ou fechado e devolve o posto atualizado.
    """
    # Aceita "ABERTO", " aberto " etc.: tira espaços e passa para minúsculo
    status = status.strip().lower() if isinstance(status, str) else None

    # Regra 2: só os três status existem
    if status not in STATUS_VALIDOS:
        raise ErroDeRegra("Status inválido. Use: aberto, lotado ou fechado.", 422)

    with trava:
        posto = _buscar(id_posto)

        # Regra 5: não faz sentido reabrir com a fila acima do limite
        # (ele viraria lotado de novo na hora)
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
    """
    Usada por: GET /api/recomendacao?trecho=<n>

    Escolhe para onde a coordenação deve mandar o paciente.
    Não basta ser o mais perto: um posto quase lotado no trecho do trio
    é pior do que um posto vazio logo ao lado. Por isso calculamos um "custo":

        custo = distância (em trechos) + fila ÷ PESSOAS_POR_TRECHO

    e recomendamos o posto ABERTO de menor custo.
    Exemplo com PESSOAS_POR_TRECHO = 5 e o trio no trecho 3:
        posto no trecho 3 com 20 pessoas -> 0 + 20/5 = 4,0
        posto no trecho 4 com  0 pessoas -> 1 +  0/5 = 1,0   <- recomendado
    Empate de custo -> fila menor; depois -> menor id.
    """
    with trava:
        # Regra 3: só postos abertos entram na disputa (fechado e lotado ficam de fora)
        candidatos = [p for p in postos if p["status"] == "aberto"]
        if not candidatos:
            raise ErroDeRegra("Nenhum posto disponível no momento.", 404)

        def custo(p):
            # Regra 7: junta "quanto o paciente anda" com "quanto ele espera"
            return _distancia(p, trecho) + p["fila"] / PESSOAS_POR_TRECHO

        # min() pega o candidato com a menor "nota" (custo, fila, id)
        melhor = min(candidatos, key=lambda p: (custo(p), p["fila"], p["id"]))
        return {**melhor, "distancia": _distancia(melhor, trecho)}


def cadastrar_posto(nome, trecho):
    """
    Usada por: POST /api/postos

    Cria um posto novo (começa aberto e com fila zero) e devolve o posto criado.
    """
    # Validações do nome: entre 3 e 60 letras
    if not isinstance(nome, str) or len(nome.strip()) < 3:
        raise ErroDeRegra("O nome precisa ter pelo menos 3 letras.", 422)
    nome = nome.strip()
    if len(nome) > 60:
        raise ErroDeRegra("O nome pode ter no máximo 60 caracteres.", 422)

    # Validação do trecho: número de 1 até TOTAL_TRECHOS
    if not _eh_inteiro(trecho) or not 1 <= trecho <= TOTAL_TRECHOS:
        raise ErroDeRegra(f"O trecho precisa ser um número de 1 a {TOTAL_TRECHOS}.", 422)

    with trava:
        # Não deixa ter dois postos com o mesmo nome (sem diferenciar maiúscula/minúscula)
        if any(p["nome"].lower() == nome.lower() for p in postos):
            raise ErroDeRegra("Já existe um posto com esse nome.", 409)

        novo = {
            "id": max((p["id"] for p in postos), default=0) + 1,  # próximo id livre
            "nome": nome,
            "trecho": trecho,
            "fila": 0,
            "status": "aberto",
            "atualizado_em": agora(),
        }
        postos.append(novo)
        return dict(novo)


# ############################################################
# PARTE 3 · ROTAS (FLASK)
# ############################################################

# Cria o servidor Flask. static_folder=None desliga a pasta "static" automática,
# porque nós mesmos entregamos os arquivos do frontend (rotas lá embaixo).
app = Flask(__name__, static_folder=None)

# Faz o JSON sair com acento normal ("não") em vez de código ("não")
app.json.ensure_ascii = False


# ============================================================
# Funções de apoio (usadas pelas rotas)
# ============================================================

def erro(mensagem, codigo):
    """Monta uma resposta de erro padrão: {"erro": "mensagem"} + código HTTP (400, 404, 409...)."""
    return jsonify({"erro": mensagem}), codigo


def ler_json():
    """
    Lê o corpo (body) do pedido como JSON.
    Devolve um dicionário, ou None se o corpo não for um JSON válido.
    silent=True: se o JSON vier quebrado, não dá erro, só devolve None.
    """
    corpo = request.get_json(silent=True)
    return corpo if isinstance(corpo, dict) else None


@app.errorhandler(ErroDeRegra)
def tratar_erro_de_regra(e):
    """
    Quando uma regra de negócio é quebrada, as funções da parte 2 levantam ErroDeRegra
    (ex.: "Não é permitido deixar a fila negativa", código 409).
    Esta função "pega" esse erro e transforma em resposta JSON para o navegador.
    Por isso as rotas abaixo não precisam de try/except.
    """
    return erro(e.mensagem, e.codigo)


@app.after_request
def cabecalhos_api(resposta):
    """
    Roda DEPOIS de toda rota, logo antes da resposta sair.
    Acrescenta alguns cabeçalhos nas respostas da API (/api/...).
    """
    if request.path.startswith("/api/"):
        # Não deixa o navegador guardar cópia: o número da fila muda o tempo todo,
        # então a resposta precisa vir sempre fresca do servidor.
        resposta.headers["Cache-Control"] = "no-store"

        # CORS: por segurança, o navegador bloqueia uma página de um endereço
        # (ex.: Live Server na porta 5500) de pedir dados a outro (Flask na 5000).
        # Aqui liberamos só endereços do próprio computador (127.0.0.1 / localhost)
        # e páginas abertas direto do arquivo (origem "null").
        origem = request.headers.get("Origin", "")
        if origem == "null" or origem.startswith(("http://127.0.0.1:", "http://localhost:")):
            resposta.headers["Access-Control-Allow-Origin"] = origem
            resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            resposta.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resposta.headers["Vary"] = "Origin"
    return resposta


# ============================================================
# Rotas GET (buscar dados, não alteram nada)
# ============================================================

@app.route("/api/postos", methods=["GET"])
def get_postos():
    """
    Lista todos os postos com fila, status e horário da última atualização.
    Usada pela tela do voluntário (para montar a lista de escolha)
    e pela coordenação (para mostrar os cartões).

    Exemplo: GET /api/postos?trecho=4
    Se vier ?trecho=, a lista volta ordenada do posto mais perto do trio ao mais longe.
    """
    trecho = None
    if "trecho" in request.args:                          # request.args = parâmetros depois do "?"
        trecho = validar_trecho(request.args["trecho"])
    return jsonify(listar_postos(trecho)), 200            # 200 = deu certo


@app.route("/api/recomendacao", methods=["GET"])
def get_recomendacao():
    """
    Devolve o posto recomendado para onde o trio está:
    o posto ABERTO com o menor custo (distância + fila ÷ PESSOAS_POR_TRECHO).
    Fechado e lotado nunca são recomendados.

    Exemplo: GET /api/recomendacao?trecho=4
    Se nenhum posto estiver aberto, devolve erro 404.
    """
    trecho = validar_trecho(request.args.get("trecho"))
    return jsonify(recomendar_posto(trecho)), 200


# ============================================================
# Rotas PATCH (alteram só uma parte de um posto)
# ============================================================

@app.route("/api/postos/<int:id_posto>/fila", methods=["PATCH"])
def patch_fila(id_posto):
    """
    Botões "+1" e "−1" da tela do voluntário.
    <int:id_posto> pega o número do posto que vem na URL (ex.: /api/postos/3/fila -> 3).

    Corpo esperado: {"variacao": 1} ou {"variacao": -1}
    Devolve o posto atualizado (o "lotado automático" já vem aplicado).
    """
    corpo = ler_json()
    if corpo is None:                                     # 400 = pedido mal feito
        return erro('Envie um JSON, ex.: {"variacao": 1}.', 400)
    posto = alterar_fila(id_posto, corpo.get("variacao"))
    return jsonify(posto), 200


@app.route("/api/postos/<int:id_posto>/status", methods=["PATCH"])
def patch_status(id_posto):
    """
    Botões ABERTO / LOTADO / FECHADO da tela do voluntário.

    Corpo esperado: {"status": "aberto"}, {"status": "lotado"} ou {"status": "fechado"}
    Qualquer outro status é recusado (erro 422).
    """
    corpo = ler_json()
    if corpo is None:
        return erro('Envie um JSON, ex.: {"status": "aberto"}.', 400)
    posto = alterar_status(id_posto, corpo.get("status"))
    return jsonify(posto), 200


# ============================================================
# Rota POST (cria algo novo)
# ============================================================

@app.route("/api/postos", methods=["POST"])
def post_posto():
    """
    Formulário "Cadastrar novo posto" da tela da coordenação.
    Corpo esperado: {"nome": "Posto Tal", "trecho": 4}
    Devolve o posto criado com o código 201 (= criado com sucesso).
    """
    corpo = ler_json()
    if corpo is None:
        return erro("Envie um JSON com nome e trecho.", 400)
    novo = cadastrar_posto(corpo.get("nome"), corpo.get("trecho"))
    return jsonify(novo), 201


# ============================================================
# Páginas do site (o Flask também entrega o HTML, CSS e JS)
# ============================================================

@app.route("/", methods=["GET"])
def pagina_inicial():
    """Quem abre http://127.0.0.1:5000 recebe a página inicial (index.html)."""
    return send_from_directory(PASTA_FRONTEND, "index.html")


@app.route("/<path:arquivo>", methods=["GET"])
def arquivos_frontend(arquivo):
    """
    Entrega os outros arquivos do site (voluntario.html, style.css, script.js...).
    <path:arquivo> pega tudo o que vem depois da barra na URL.
    """
    # Aceita também /frontend/arquivo.html (caminho que o Live Server usa)
    arquivo = arquivo.removeprefix("frontend/")
    # Só entrega o que está na lista ARQUIVOS_FRONTEND; o resto é 404
    if arquivo not in ARQUIVOS_FRONTEND:
        return erro("Página não encontrada.", 404)
    return send_from_directory(PASTA_FRONTEND, arquivo)


# ============================================================
# Erros genéricos: sempre respondem em JSON (o script.js sabe ler)
# ============================================================

@app.errorhandler(404)
def nao_encontrado(_e):
    """Endereço que não existe."""
    return erro("Recurso não encontrado.", 404)


@app.errorhandler(405)
def metodo_nao_permitido(_e):
    """Rota existe, mas com outro método (ex.: DELETE em /api/postos)."""
    return erro("Método não permitido para esta rota.", 405)


@app.errorhandler(500)
def erro_interno(_e):
    """Algum erro inesperado no código do servidor."""
    return erro("Erro interno no servidor.", 500)


# ============================================================
# Liga o servidor
# ============================================================

# Este bloco só roda quando executamos "python backend/app.py"
# (não roda quando outro arquivo faz "import app", como nos testes).
if __name__ == "__main__":
    print(f"Painel Folia no ar: http://127.0.0.1:{PORTA}  (limite da fila: {LIMITE_FILA})")
    # host="127.0.0.1": o site só abre neste computador
    # debug: liga o modo de depuração se FLASK_DEBUG=1 (mostra erros detalhados)
    app.run(host="127.0.0.1", port=PORTA, debug=os.environ.get("FLASK_DEBUG") == "1")
