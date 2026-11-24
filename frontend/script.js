'use strict';

/* =========================================================
   Painel Folia · Frontend
   ---------------------------------------------------------
   Um só arquivo para as duas telas. A classe do <body> diz
   qual tela está aberta:
     body.tela-voluntario   -> voluntario.html
     body.tela-coordenacao  -> coordenacao.html

   Aqui NÃO tem regra de negócio: quem decide se a fila pode
   diminuir, se o posto vira "lotado" e qual posto é
   recomendado é o backend (Flask). Este arquivo só mostra os
   dados, confere o que o usuário digitou e chama a API.
   ========================================================= */

/* ---------- Configuração ---------- */

// Se a página veio do Flask (porta 5000), usa o mesmo endereço.
// Se foi aberta direto do arquivo ou pelo Live Server, aponta para o Flask local.
const PORTA_FLASK = '5000';
const ABERTO_FORA_DO_FLASK = location.protocol === 'file:' || location.port !== PORTA_FLASK;

const CONFIG = {
  API: ABERTO_FORA_DO_FLASK ? `http://127.0.0.1:${PORTA_FLASK}` : '',
  TEMPO_LIMITE_MS: 8000,   // rede do circuito é instável: não esperar para sempre
  AMARELO_A_PARTIR: 0.7,   // fila >= 70% do limite = cartão amarelo
  DADO_ANTIGO_S: 60,       // depois de 60 s, avisamos que o dado é antigo
};

const NOMES_STATUS = { aberto: 'Aberto', lotado: 'Lotado', fechado: 'Fechado' };
const CHAVE_POSTO_SALVO = 'painelFolia.posto';

const $ = (id) => document.getElementById(id);

/* =========================================================
   Comunicação com a API
   ========================================================= */

/**
 * Faz a requisição e SEMPRE devolve um objeto no mesmo formato:
 * { ok, status, dados, semConexao }. Assim a tela nunca quebra
 * quando a rede cai no meio do circuito.
 */
async function chamarApi(caminho, metodo = 'GET', corpo) {
  const controle = new AbortController();
  const timer = setTimeout(() => controle.abort(), CONFIG.TEMPO_LIMITE_MS);

  const opcoes = { method: metodo, signal: controle.signal };
  if (corpo !== undefined) {
    opcoes.headers = { 'Content-Type': 'application/json' };
    opcoes.body = JSON.stringify(corpo);
  }

  try {
    const resposta = await fetch(CONFIG.API + caminho, opcoes);
    let dados = null;
    try { dados = await resposta.json(); } catch { dados = null; }
    mostrarAvisoConexao(false);
    return { ok: resposta.ok, status: resposta.status, dados, semConexao: false };
  } catch {
    mostrarAvisoConexao(true);
    return { ok: false, status: 0, dados: null, semConexao: true };
  } finally {
    clearTimeout(timer);
  }
}

function textoDoErro(resp, padrao) {
  if (resp.semConexao) return 'Sem conexão com o servidor.';
  if (resp.dados && typeof resp.dados.erro === 'string') return resp.dados.erro;
  return padrao;
}

/* =========================================================
   Utilidades de tela
   ========================================================= */

function mostrarAvisoConexao(semConexao) {
  const aviso = $('aviso-conexao');
  if (!aviso) return;
  aviso.textContent = 'Sem conexão com o servidor. Confira se o Flask está rodando (iniciar.bat) e tente de novo.';
  aviso.hidden = !semConexao;
}

function mostrarMensagem(elemento, texto, tipo = 'ok') {
  elemento.textContent = texto;
  elemento.classList.remove('mensagem--erro', 'mensagem--aviso');
  if (tipo === 'erro') elemento.classList.add('mensagem--erro');
  if (tipo === 'aviso') elemento.classList.add('mensagem--aviso');
  elemento.hidden = false;
}

function esconder(elemento) {
  elemento.hidden = true;
  elemento.textContent = '';
}

function lerData(texto) {
  const data = new Date(texto);
  return Number.isNaN(data.getTime()) ? null : data;
}

function hora(data) {
  return data.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** "há 12 s", "há 3 min", "há 1 h" */
function haQuantoTempo(data) {
  const s = Math.max(0, Math.round((Date.now() - data.getTime()) / 1000));
  if (s < 60) return `há ${s} s`;
  const min = Math.floor(s / 60);
  return min < 60 ? `há ${min} min` : `há ${Math.floor(min / 60)} h`;
}

function aplicarSelo(elemento, status) {
  elemento.textContent = NOMES_STATUS[status] || '—';
  elemento.classList.remove('status-aberto', 'status-lotado', 'status-fechado');
  if (NOMES_STATUS[status]) elemento.classList.add(`status-${status}`);
}

/** Cor do cartão (só apresentação; o "lotado" já vem decidido do backend). */
function corDoPosto(posto, limite) {
  if (posto.status === 'fechado') return 'cor-cinza';
  if (posto.status === 'lotado') return 'cor-vermelho';
  if (posto.fila >= limite * CONFIG.AMARELO_A_PARTIR) return 'cor-amarelo';
  return 'cor-verde';
}

function travar(botoes, travado) {
  botoes.forEach((b) => {
    b.disabled = travado;
    b.classList.toggle('carregando', travado);
  });
}

/* =========================================================
   TELA DO VOLUNTÁRIO
   ========================================================= */

function iniciarVoluntario() {
  const el = {
    select: $('select-posto'),
    area: $('area-posto'),
    status: $('vol-status'),
    fila: $('vol-fila'),
    atualizado: $('vol-atualizado'),
    mensagem: $('vol-mensagem'),
    botoesFila: document.querySelectorAll('.btn-fila'),
    botoesStatus: document.querySelectorAll('.btn-status'),
  };

  let postoAtual = null;   // posto escolhido (última versão vinda do servidor)

  async function carregarPostos() {
    const resp = await chamarApi('/api/postos');
    el.select.replaceChildren();

    if (!resp.ok || !resp.dados) {
      el.select.append(new Option('Não foi possível carregar os postos', ''));
      return;
    }

    el.select.append(new Option('Selecione o seu posto', ''));
    resp.dados.postos.forEach((p) => {
      el.select.append(new Option(`${p.nome} (trecho ${p.trecho})`, String(p.id)));
    });

    // Se o voluntário recarregar a página, volta direto para o posto dele
    let salvo = null;
    try { salvo = localStorage.getItem(CHAVE_POSTO_SALVO); } catch { /* sem storage */ }
    const posto = resp.dados.postos.find((p) => String(p.id) === salvo);
    if (posto) {
      el.select.value = String(posto.id);
      mostrarPosto(posto);
    }
  }

  function mostrarPosto(posto) {
    postoAtual = posto;
    el.area.hidden = false;
    el.fila.textContent = String(posto.fila);
    aplicarSelo(el.status, posto.status);

    const data = lerData(posto.atualizado_em);
    el.atualizado.textContent = data ? hora(data) : '—';

    el.botoesStatus.forEach((b) => b.classList.toggle('selecionado', b.dataset.status === posto.status));
  }

  el.select.addEventListener('change', async () => {
    esconder(el.mensagem);
    const id = el.select.value;
    if (!id) {
      postoAtual = null;
      el.area.hidden = true;
      try { localStorage.removeItem(CHAVE_POSTO_SALVO); } catch { /* ignora */ }
      return;
    }
    try { localStorage.setItem(CHAVE_POSTO_SALVO, id); } catch { /* ignora */ }

    // Busca de novo para mostrar o número mais recente da fila
    const resp = await chamarApi('/api/postos');
    const posto = resp.ok && resp.dados ? resp.dados.postos.find((p) => String(p.id) === id) : null;
    if (posto) {
      mostrarPosto(posto);
    } else {
      mostrarMensagem(el.mensagem, textoDoErro(resp, 'Posto não encontrado.'), 'erro');
    }
  });

  /* --- +1 / −1 --- */
  el.botoesFila.forEach((botao) => {
    botao.addEventListener('click', async () => {
      if (!postoAtual) return;
      const variacao = Number(botao.dataset.variacao);
      const statusAntes = postoAtual.status;

      travar(el.botoesFila, true);
      const resp = await chamarApi(`/api/postos/${postoAtual.id}/fila`, 'PATCH', { variacao });
      travar(el.botoesFila, false);

      if (resp.ok && resp.dados) {
        mostrarPosto(resp.dados);
        if (statusAntes !== 'lotado' && resp.dados.status === 'lotado') {
          mostrarMensagem(el.mensagem, 'A fila passou do limite: o posto foi marcado como LOTADO automaticamente.', 'aviso');
        } else {
          mostrarMensagem(el.mensagem, variacao > 0 ? '+1 registrado.' : '−1 registrado.');
        }
      } else if (resp.semConexao) {
        // Nunca guardamos o clique para reenviar depois: poderia contar a mesma pessoa duas vezes
        mostrarMensagem(el.mensagem, 'Sem conexão: o clique NÃO foi registrado. Tente de novo.', 'erro');
      } else {
        mostrarMensagem(el.mensagem, textoDoErro(resp, 'Não foi possível alterar a fila.'), resp.status === 409 ? 'aviso' : 'erro');
      }
    });
  });

  /* --- Aberto / Lotado / Fechado --- */
  el.botoesStatus.forEach((botao) => {
    botao.addEventListener('click', async () => {
      if (!postoAtual) return;
      const status = botao.dataset.status;

      travar(el.botoesStatus, true);
      const resp = await chamarApi(`/api/postos/${postoAtual.id}/status`, 'PATCH', { status });
      travar(el.botoesStatus, false);

      if (resp.ok && resp.dados) {
        mostrarPosto(resp.dados);
        mostrarMensagem(el.mensagem, `Status alterado para ${NOMES_STATUS[resp.dados.status].toUpperCase()}.`);
      } else if (resp.semConexao) {
        mostrarMensagem(el.mensagem, 'Sem conexão: o status NÃO foi alterado. Tente de novo.', 'erro');
      } else {
        mostrarMensagem(el.mensagem, textoDoErro(resp, 'Não foi possível alterar o status.'), resp.status === 409 ? 'aviso' : 'erro');
      }
    });
  });

  carregarPostos();
}

/* =========================================================
   TELA DA COORDENAÇÃO
   ========================================================= */

function iniciarCoordenacao() {
  const el = {
    formTrecho: $('form-trecho'),
    campoTrecho: $('campo-trecho'),
    trechoTotal: $('trecho-total'),
    erroTrecho: $('erro-trecho'),
    botaoAtualizar: $('botao-atualizar'),
    frescor: $('frescor'),
    frescorTexto: $('frescor-texto'),
    recomendado: $('recomendado'),
    recNome: $('recomendado-nome'),
    recDetalhe: $('recomendado-detalhe'),
    lista: $('lista-postos'),
    formCadastro: $('form-cadastro'),
    campoNome: $('campo-nome'),
    campoTrechoNovo: $('campo-trecho-novo'),
    msgCadastro: $('msg-cadastro'),
  };

  let ultimaAtualizacao = null;   // horário da última resposta OK
  let semConexao = false;

  /** Lê o trecho digitado; devolve o número ou null (e mostra o erro). */
  function trechoDigitado() {
    const texto = el.campoTrecho.value.trim();
    const n = Number(texto);
    const max = Number(el.campoTrecho.max) || Infinity;
    if (texto === '' || !Number.isInteger(n) || n < 1 || n > max) {
      el.campoTrecho.classList.add('invalido');
      mostrarMensagem(el.erroTrecho, `Informe o trecho do trio (número de 1 a ${max}).`, 'erro');
      return null;
    }
    el.campoTrecho.classList.remove('invalido');
    esconder(el.erroTrecho);
    return n;
  }

  async function atualizar() {
    const trecho = trechoDigitado();
    if (trecho === null) return;

    el.botaoAtualizar.disabled = true;
    el.botaoAtualizar.textContent = 'Atualizando…';

    // As duas buscas ao mesmo tempo
    const [respPostos, respRec] = await Promise.all([
      chamarApi(`/api/postos?trecho=${trecho}`),
      chamarApi(`/api/recomendacao?trecho=${trecho}`),
    ]);

    el.botaoAtualizar.disabled = false;
    el.botaoAtualizar.textContent = 'Atualizar';
    semConexao = respPostos.semConexao;

    if (!respPostos.ok || !respPostos.dados) {
      // Mantém a lista antiga na tela, mas deixa claro que ela está velha
      el.lista.classList.add('desatualizada');
      if (!respPostos.semConexao) {
        mostrarMensagem(el.erroTrecho, textoDoErro(respPostos, 'Erro ao buscar os postos.'), 'erro');
      }
      atualizarFrescor();
      return;
    }

    const { postos, limite_fila: limite, total_trechos: total } = respPostos.dados;
    ultimaAtualizacao = new Date();
    el.lista.classList.remove('desatualizada');

    // O backend diz quantos trechos o circuito tem
    el.campoTrecho.max = total;
    el.campoTrechoNovo.max = total;
    el.trechoTotal.textContent = `de ${total}`;

    const recomendado = mostrarRecomendacao(respRec);
    mostrarLista(postos, limite, recomendado ? recomendado.id : null);
    atualizarFrescor();
  }

  function mostrarRecomendacao(resp) {
    el.recomendado.classList.remove('recomendado--vazio', 'sem-opcao');

    if (resp.ok && resp.dados) {
      const p = resp.dados;
      el.recNome.textContent = p.nome;
      const onde = p.distancia === 0 ? 'no trecho do trio' : `a ${p.distancia} trecho(s) do trio`;
      el.recDetalhe.textContent = `Trecho ${p.trecho} (${onde}) · ${p.fila} pessoa(s) na fila`;
      return p;
    }

    el.recomendado.classList.add('sem-opcao');
    if (resp.status === 404) {
      el.recNome.textContent = 'Nenhum posto disponível';
      el.recDetalhe.textContent = 'Todos os postos estão lotados ou fechados. Acione a central.';
    } else {
      el.recNome.textContent = 'Recomendação indisponível';
      el.recDetalhe.textContent = textoDoErro(resp, 'Não foi possível calcular a recomendação.');
    }
    return null;
  }

  /** Os postos já chegam ordenados por distância (o backend ordena). */
  function mostrarLista(postos, limite, idRecomendado) {
    el.lista.replaceChildren();

    if (postos.length === 0) {
      const vazio = document.createElement('li');
      vazio.className = 'lista-vazia';
      vazio.textContent = 'Nenhum posto cadastrado.';
      el.lista.append(vazio);
      return;
    }

    postos.forEach((p) => el.lista.append(criarCartao(p, limite, p.id === idRecomendado)));
  }

  function criarCartao(posto, limite, ehRecomendado) {
    const item = document.createElement('li');
    item.classList.add(corDoPosto(posto, limite));
    if (ehRecomendado) item.classList.add('recomendado');

    // Esquerda: nome, trecho, distância e horário
    const info = document.createElement('div');

    const nome = document.createElement('p');
    nome.className = 'posto__nome';
    nome.textContent = posto.nome;
    if (ehRecomendado) {
      const tag = document.createElement('span');
      tag.className = 'posto__tag-recomendado';
      tag.textContent = 'RECOMENDADO';
      nome.append(tag);
    }

    const meta = document.createElement('p');
    meta.className = 'posto__meta';
    meta.textContent = posto.distancia === 0
      ? `Trecho ${posto.trecho} · no trecho do trio`
      : `Trecho ${posto.trecho} · ${posto.distancia} trecho(s) de distância`;

    const data = lerData(posto.atualizado_em);
    if (data) {
      const quando = document.createElement('span');
      quando.textContent = ` · atualizado às ${hora(data)}`;
      // Ninguém mexe nesse posto há mais de 5 min: vale confirmar por rádio
      if (Date.now() - data.getTime() > 5 * 60 * 1000) {
        quando.classList.add('antigo');
        quando.title = 'Este posto não envia atualização há algum tempo.';
      }
      meta.append(quando);
    }

    info.append(nome, meta);

    // Direita: fila + selo de status
    const direita = document.createElement('div');
    direita.className = 'posto__direita';

    const fila = document.createElement('p');
    fila.className = 'posto__fila';
    fila.textContent = String(posto.fila);
    const sufixo = document.createElement('small');
    sufixo.textContent = ' na fila';
    fila.append(sufixo);

    const selo = document.createElement('span');
    selo.className = 'selo';
    aplicarSelo(selo, posto.status);

    direita.append(fila, selo);
    item.append(info, direita);
    return item;
  }

  /** Mostra há quanto tempo o dado na tela foi buscado. */
  function atualizarFrescor() {
    el.frescor.classList.remove('recente', 'antigo', 'offline');

    if (!ultimaAtualizacao) {
      if (semConexao) {
        el.frescor.classList.add('offline');
        el.frescorTexto.textContent = 'Sem conexão. Nenhum dado carregado ainda.';
      }
      return;
    }

    const quando = `${hora(ultimaAtualizacao)} (${haQuantoTempo(ultimaAtualizacao)})`;
    const segundos = (Date.now() - ultimaAtualizacao.getTime()) / 1000;

    if (semConexao) {
      el.frescor.classList.add('offline');
      el.frescorTexto.textContent = `Sem conexão. Mostrando dados de ${quando}.`;
    } else if (segundos > CONFIG.DADO_ANTIGO_S) {
      el.frescor.classList.add('antigo');
      el.frescorTexto.textContent = `Dado antigo: última atualização às ${quando}. Clique em Atualizar.`;
    } else {
      el.frescor.classList.add('recente');
      el.frescorTexto.textContent = `Última atualização às ${quando}.`;
    }
  }

  el.formTrecho.addEventListener('submit', (e) => {
    e.preventDefault();
    atualizar();
  });

  el.campoTrecho.addEventListener('input', () => {
    el.campoTrecho.classList.remove('invalido');
    esconder(el.erroTrecho);
  });

  /* --- Cadastro de posto --- */
  el.formCadastro.addEventListener('submit', async (e) => {
    e.preventDefault();
    const nome = el.campoNome.value.trim();
    const trecho = Number(el.campoTrechoNovo.value);
    const max = Number(el.campoTrechoNovo.max) || Infinity;

    if (nome.length < 3) {
      mostrarMensagem(el.msgCadastro, 'O nome precisa ter pelo menos 3 letras.', 'erro');
      return;
    }
    if (!Number.isInteger(trecho) || trecho < 1 || trecho > max) {
      mostrarMensagem(el.msgCadastro, `Informe um trecho de 1 a ${max}.`, 'erro');
      return;
    }

    const resp = await chamarApi('/api/postos', 'POST', { nome, trecho });
    if (resp.ok && resp.dados) {
      mostrarMensagem(el.msgCadastro, `${resp.dados.nome} cadastrado no trecho ${resp.dados.trecho}.`);
      el.formCadastro.reset();
      atualizar();
    } else {
      mostrarMensagem(el.msgCadastro, textoDoErro(resp, 'Não foi possível cadastrar.'), 'erro');
    }
  });

  // O "há X s" envelhece sozinho, mesmo sem nova busca
  setInterval(atualizarFrescor, 1000);
  atualizar();
}

/* =========================================================
   Início: roda só o código da tela aberta
   ========================================================= */

if (document.body.classList.contains('tela-voluntario')) iniciarVoluntario();
if (document.body.classList.contains('tela-coordenacao')) iniciarCoordenacao();
