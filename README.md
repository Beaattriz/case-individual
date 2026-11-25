# Painel Folia · Bloco Saúde

Painel para acompanhar, em tempo real, a fila dos postos de saúde no circuito do carnaval.

- **Voluntário no posto** (`voluntario.html`): botões grandes de +1 / −1 pessoa na fila e troca de status (aberto, lotado, fechado).
- **Coordenação** (`coordenacao.html`): postos ordenados pela distância do trio, com fila, status e cor conforme a lotação; botão **Atualizar** com o horário da última atualização; destaque do posto recomendado.

## Como rodar

No terminal, dentro da pasta do projeto:

```bash
pip install -r backend/requirements.txt   # instala o Flask (só na primeira vez)
python backend/app.py                     # liga o servidor
```

Depois abra **http://127.0.0.1:5000** no navegador. Para desligar o servidor: `Ctrl+C` no terminal.

## Estrutura

```
backend/
  app.py             backend inteiro: configuração, dados + regras de negócio e rotas Flask
  requirements.txt   dependências (Flask)
frontend/
  index.html         tela inicial
  voluntario.html    tela do voluntário no posto
  coordenacao.html   tela da coordenação
  style.css          estilos das três telas
  script.js          chamadas à API e montagem das telas
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
4. Posto com fila acima do limite (`LIMITE_FILA`, padrão 20) passa automaticamente para `lotado`.
5. Não dá para reabrir um posto com a fila acima do limite (`409`).
6. Posto fechado não recebe +1 na fila (`409`).

A recomendação considera **distância e fila** juntas. Para cada posto **aberto** calculamos:

```
custo = distância até o trio (em trechos) + fila ÷ PESSOAS_POR_TRECHO   (padrão 5)
```

e recomendamos o de menor custo (empate: fila menor). Assim, um posto quase lotado no trecho do trio
(0 + 20÷5 = 4) perde para um posto vazio no trecho ao lado (1 + 0÷5 = 1).

## Cores na coordenação

| Cor | Quando |
|---|---|
| Verde | aberto, fila abaixo de 70% do limite |
| Amarelo | aberto, fila a partir de 70% do limite |
| Vermelho | lotado |
| Cinza | fechado |

## Configuração (opcional)

Crie um arquivo `backend/.env` (opcional) para mudar `LIMITE_FILA` (padrão 20), `PESSOAS_POR_TRECHO` (padrão 5), `TOTAL_TRECHOS` (padrão 10) e `PORTA` (padrão 5000). Ex.: `LIMITE_FILA=25`.

## Privacidade

O painel não recebe nem guarda dados pessoais ou clínicos: só a contagem da fila e o status de cada posto.
Os dados ficam em memória; ao reiniciar o servidor, tudo volta ao estado inicial.
