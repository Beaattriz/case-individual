# Painel Folia · Bloco Saúde

Painel para acompanhar, em tempo real, a fila dos postos de saúde no circuito do carnaval.

- **Voluntário no posto** (`voluntario.html`): botões grandes de +1 / −1 pessoa na fila e troca de status (aberto, lotado, fechado).
- **Coordenação** (`coordenacao.html`): postos ordenados pela distância do trio, com fila, status e cor conforme a lotação; botão **Atualizar** com o horário da última atualização; destaque do posto recomendado.

## Como rodar

### Jeito rápido (Windows)

Dê duplo clique em **`iniciar.bat`**. Ele cria um ambiente virtual (`.venv`), instala o Flask e liga o servidor.
Depois abra **http://127.0.0.1:5000** no navegador.

### Jeito manual (qualquer sistema)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r backend/requirements.txt
python backend/app.py
```

Abra **http://127.0.0.1:5000**.

## Estrutura

```
backend/
  app.py             API Flask + regras de negócio + dados em memória
  requirements.txt   dependências (Flask)
  .env.example       configuração opcional
frontend/
  index.html         tela inicial
  voluntario.html    tela do voluntário no posto
  coordenacao.html   tela da coordenação
  style.css          estilos das três telas
  script.js          chamadas à API e montagem das telas
iniciar.bat          instala e liga tudo (Windows)
```

## API

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/postos` | lista os postos com fila, status e horário da última atualização (`?trecho=<n>` ordena pela distância do trio) |
| PATCH | `/api/postos/<id>/fila` | `{"variacao": 1}` ou `{"variacao": -1}` |
| PATCH | `/api/postos/<id>/status` | `{"status": "aberto" \| "lotado" \| "fechado"}` |
| GET | `/api/recomendacao?trecho=<n>` | posto recomendado para aquele trecho do circuito |
| POST | `/api/postos` | cadastra um posto: `{"nome": "...", "trecho": n}` |

Erros sempre voltam como `{"erro": "mensagem"}`.

## Regras de negócio (no backend)

1. A fila nunca fica negativa (`409`).
2. Só os status `aberto`, `lotado` e `fechado` são aceitos (`422`).
3. Posto fechado nunca é recomendado (e lotado também não).
4. Posto com fila acima do limite (`LIMITE_FILA`, padrão 30) passa automaticamente para `lotado`.
5. Não dá para reabrir um posto com a fila acima do limite (`409`).
6. Posto fechado não recebe +1 na fila (`409`).

A recomendação é o posto **aberto** mais próximo do trio; no empate, o de fila menor.

## Cores na coordenação

| Cor | Quando |
|---|---|
| Verde | aberto, fila abaixo de 70% do limite |
| Amarelo | aberto, fila a partir de 70% do limite |
| Vermelho | lotado |
| Cinza | fechado |

## Configuração (opcional)

Copie `backend/.env.example` para `backend/.env` e ajuste `LIMITE_FILA`, `TOTAL_TRECHOS` e `PORTA`.

## Privacidade

O painel não recebe nem guarda dados pessoais ou clínicos: só a contagem da fila e o status de cada posto.
Os dados ficam em memória; ao reiniciar o servidor, tudo volta ao estado inicial.
