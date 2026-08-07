// Único ponto de acesso ao backend. Todo número exibido vem daqui — a tela não
// calcula hit@k, score nem latência por conta própria. É a mesma regra do
// `report.py`: existe um caminho de cálculo, e ele é o do Python.
//
// Diferente da PoC de imagens, aqui não há modo snapshot: publicar esta tela
// num host estático exigiria congelar 6 estratégias × N perguntas, e o valor da
// tela está justamente em digitar uma pergunta nova e ver o léxico voltar vazio
// ao vivo. Ela roda com `task web` e ponto.

async function get(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `${response.status} em ${path}`);
  }
  return response.json();
}

export const fetchState = () => get("/api/state");

export const fetchSearch = (text, k = 5) =>
  get(`/api/search?q=${encodeURIComponent(text)}&k=${k}`);

export const fetchDocument = (docId) =>
  get(`/api/document/${encodeURIComponent(docId)}`);

export const fetchCode = (strategy) =>
  get(`/api/code/${encodeURIComponent(strategy)}`);

export const fetchMeasured = () => get("/api/measured");

export const fetchDisagreements = () => get("/api/disagreements");

export const fetchAdvice = () => get("/api/advice");
