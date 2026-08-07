// Único ponto de acesso ao backend. Todo número exibido vem daqui — a tela não
// calcula hit@k, score nem latência por conta própria. É a mesma regra do
// `report.py`: existe um caminho de cálculo, e ele é o do Python.
//
// Dois modos, mesma superfície:
//
// - **servidor** (`task web`): fala com o FastAPI, que consulta o Postgres e o
//   Ollama. É o modo em que a PoC realmente roda, e o único em que uma pergunta
//   nova é de fato executada contra as seis estratégias.
// - **snapshot** (`VITE_SNAPSHOT=1`): lê as MESMAS respostas, congeladas em
//   arquivo por `scripts/static_export.py`. Existe para publicar num host
//   estático, onde não há Python, banco nem modelo.
//
// O snapshot não inventa resposta: o que não foi medido não aparece. Pergunta
// fora do conjunto congelado vira erro explicado — nunca lista vazia, que a
// tela leria como "o motor não achou nada" e é justamente a conclusão errada.

import snapshot from "./snapshot.json";

const SNAPSHOT = import.meta.env.VITE_SNAPSHOT === "1";
const BASE = import.meta.env.BASE_URL;

// A tela precisa saber em que modo está para não prometer o que não pode
// cumprir: no snapshot, o campo de pergunta livre só responde o conjunto medido.
export const IS_SNAPSHOT = SNAPSHOT;
export const BAKED_QUERIES = snapshot.queries;
export const BAKED_K = snapshot.k;

async function get(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `${response.status} em ${path}`);
  }
  return response.json();
}

// Mesma regra do `slugify` em scripts/static_export.py — as duas têm que casar,
// senão o arquivo existe e ninguém acha. `normalize("NFD")` + corte dos
// combinantes é o equivalente do NFKD do Python para o que aparece aqui (acento
// de português); o resto vira hífen.
function slugify(text) {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Devolve o erro, NÃO o lança. `fetchSearch` é chamada dentro do `loader` do
// `useAsync`, e loader que lança de forma síncrona escapa do `.catch()` — a
// exceção sobe pelo `useEffect` e derruba a árvore inteira do React, não só a
// aba. Medido: a tela ficava em branco e as outras quatro abas paravam de
// responder ao clique. Rejeição de promessa vira o cartão de erro, que é o
// comportamento que este caminho existe para produzir.
function missingQuery(text) {
  return new Error(
    `Esta página é uma versão publicada: as respostas foram congeladas a partir ` +
      `de uma execução real, porque o Postgres e o Ollama rodam só na máquina. ` +
      `“${text}” não está entre as ${snapshot.queries.length} perguntas medidas — ` +
      `clique numa das prontas abaixo para ver o resultado de verdade.`,
  );
}

export const fetchState = () =>
  SNAPSHOT ? get(`${BASE}data/state.json`) : get("/api/state");

export const fetchSearch = (text, k = 5) => {
  if (!SNAPSHOT) return get(`/api/search?q=${encodeURIComponent(text)}&k=${k}`);
  const slug = slugify(text);
  // Duas ausências diferentes, e a distinção importa: `k` fora do congelado é
  // defeito do exportador (a tela oferece 3, 5 e 10 num `<select>`), enquanto
  // pergunta fora do conjunto é o limite honesto da publicação.
  if (!snapshot.k.includes(k)) {
    return Promise.reject(
      new Error(`o snapshot não tem k=${k} — congelados: ${snapshot.k.join(", ")}`),
    );
  }
  if (!snapshot.slugs.includes(slug)) return Promise.reject(missingQuery(text));
  return get(`${BASE}data/search/${slug}-k${k}.json`);
};

export const fetchDocument = (docId) =>
  SNAPSHOT
    ? get(`${BASE}data/document/${encodeURIComponent(docId)}.json`)
    : get(`/api/document/${encodeURIComponent(docId)}`);

export const fetchCode = (strategy) =>
  SNAPSHOT
    ? get(`${BASE}data/code/${encodeURIComponent(strategy)}.json`)
    : get(`/api/code/${encodeURIComponent(strategy)}`);

export const fetchMeasured = () =>
  SNAPSHOT ? get(`${BASE}data/measured.json`) : get("/api/measured");

export const fetchDisagreements = () =>
  SNAPSHOT ? get(`${BASE}data/disagreements.json`) : get("/api/disagreements");

export const fetchAdvice = () =>
  SNAPSHOT ? get(`${BASE}data/advice.json`) : get("/api/advice");
