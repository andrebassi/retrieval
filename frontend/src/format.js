// Número para LER, com vírgula decimal — a tela inteira é em pt-BR.
//
// `toFixed(1)` devolve `100.0`, que numa frase portuguesa lê como outra coisa:
// em pt-BR o ponto é separador de milhar. A tela dizia `acerta 100.0%` ao lado
// de um README que diz `100,0%`, e os dois números são o mesmo.
//
// A metade das frases já chega pronta do back-end, formatada pelo `fmt_number`
// do `app.py` — este arquivo é o par dele, para os campos que chegam como
// número cru (`value`, `p50`, `mrr`, `score`) e viram texto só aqui.
//
// NÃO vale para dois lugares, e os dois de propósito:
//
//   1. o rodapé técnico (`BM25 k1=1.2 b=0.75 · RRF k=60`) — ali o número é
//      **valor de parâmetro** copiado da configuração, e trocar o separador
//      faria a tela discordar do que está escrito no `config.py`;
//   2. as coordenadas do vetor (`vector_preview`) — mesma coisa: é o conteúdo
//      literal de uma linha do banco, não uma medida para o visitante ler.
//
// `toLocaleString("pt-BR")` faria isto sozinho, e foi descartado: ele também
// insere separador de milhar (`1.234,5`), e a única medida grande da tela é
// milissegundo, onde `1.234,5 ms` só atrapalha.

/** Número com vírgula decimal e casas fixas. */
export const num = (value, digits = 1) => value.toFixed(digits).replace(".", ",");

/** Fração 0–1 como porcentagem legível: `0.909` → `90,9%`. */
export const pct = (value) => `${num(value * 100)}%`;

/** Milissegundos com uma casa: `116.34` → `116,3 ms`. */
export const ms = (value) => `${num(value)} ms`;

/** Troca só o separador, sem mexer nas casas: `0.5234` → `0,5234`, `4` → `4`.
 *
 * Para número que já veio arredondado do back-end e cuja quantidade de casas é
 * informação: a nota do BM25 sai como `4,25` e a do denso como `0,52`, e forçar
 * `toFixed(4)` encheria as duas de zero à direita — inventando precisão que a
 * medição não tem. */
export const decimal = (value) => String(value).replace(".", ",");
