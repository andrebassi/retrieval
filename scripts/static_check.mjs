/**
 * Valida a versão publicável rodando a página de verdade num Chrome headless.
 *
 * Existe porque conferir que os arquivos respondem 200 não prova nada sobre a
 * tela: o snapshot pode estar completo e a busca ainda cair, se o nome de
 * arquivo que o JS monta não for o que o exportador gravou — as duas
 * implementações de `slugify` vivem em linguagens diferentes e nada as obriga a
 * concordar. Aqui a página é carregada, as cinco abas são percorridas clicando
 * pelo TEXTO que a pessoa vê, e o que se afirma é o que ficou renderizado.
 *
 * É o par do `tools/web_check.py`: aquele confere o payload do servidor vivo,
 * este confere a tela sem servidor nenhum. Um não substitui o outro.
 *
 * Sobe o Chrome antes (o 19-web-static-check.sh faz isso):
 *   Google\ Chrome --headless=new --remote-debugging-port=9222 \
 *     --user-data-dir=/tmp/poc-chrome-profile about:blank
 *
 * Uso: node scripts/static_check.mjs [url-base] [url-cdp]
 */

const BASE = process.argv[2] || "http://127.0.0.1:8098";
const CDP = process.argv[3] || "http://127.0.0.1:9222";

let nextId = 1;
const pending = new Map();
const consoleErrors = [];
const failedRequests = [];

const targets = await (await fetch(`${CDP}/json/list`)).json();
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("nenhuma aba no Chrome de depuração");

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Runtime.exceptionThrown") {
    consoleErrors.push(message.params.exceptionDetails?.exception?.description?.split("\n")[0]);
    return;
  }
  // Arquivo do snapshot que falta responde 404 e o React mostra o erro numa aba
  // só — as outras quatro seguem verdes. Ouvir a rede pega o buraco mesmo quando
  // a tela em que ele aparece não é a que está sendo conferida.
  if (message.method === "Network.responseReceived") {
    const { status, url } = message.params.response;
    if (status >= 400) failedRequests.push(`${status} ${url.replace(BASE, "")}`);
    return;
  }
  const waiting = pending.get(message.id);
  if (!waiting) return;
  pending.delete(message.id);
  message.error ? waiting.reject(new Error(message.error.message)) : waiting.resolve(message.result);
});

function send(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
    setTimeout(() => {
      if (pending.delete(id)) reject(new Error(`sem resposta de ${method}`));
    }, 30000);
  });
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description?.split("\n")[0] || "erro");
  }
  return result.result.value;
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const text = () => evaluate(`document.body.innerText.replace(/\\s+/g, " ").trim()`);

// Clicar pelo texto visível, não por classe: seletor de classe passa verde numa
// tela que renderizou sem o rótulo certo, que é justamente o defeito procurado.
const click = (label) =>
  evaluate(`
    (() => {
      const wanted = ${JSON.stringify(label)};
      const nodes = [...document.querySelectorAll("button, [role=button], a")];
      const hit = nodes.find((node) => node.textContent.replace(/\\s+/g, " ").includes(wanted));
      if (!hit) return false;
      hit.click();
      return true;
    })()
  `);

let failures = 0;
function check(label, ok, detail = "") {
  console.log(`${ok ? "  ✅" : "  🛑"} ${label}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures++;
}

await send("Runtime.enable");
await send("Page.enable");
await send("Network.enable");

console.log(`==> abrindo ${BASE}`);
await send("Page.navigate", { url: BASE });
await wait(4000);

const home = await text();
check("página carregou", home.includes("Seis formas de achar um documento"));
check(
  "aviso da versão publicada aparece",
  home.includes("versão publicada") && home.includes("congeladas"),
  "sem ele a tela promete uma busca ao vivo que este host não faz",
);
check("ficha do corpus na tela", /114 documentos/.test(home), home.slice(0, 90));

/**
 * O link do código, conferido pelo `href` real e não pelo rótulo: rótulo certo
 * apontando para o repositório antigo é exatamente o defeito que passa
 * despercebido numa leitura de tela.
 */
const repoLink = await evaluate(`
  (() => {
    const hit = [...document.querySelectorAll("a")].find((node) =>
      node.href.includes("github.com/andrebassi/retrieval"));
    return hit ? { texto: hit.textContent.replace(/\\s+/g, " ").trim(), alvo: hit.target } : null;
  })()
`);
check("cabeçalho leva ao repositório", Boolean(repoLink), repoLink ? `“${repoLink.texto}”` : "nenhum link para o GitHub");
check("abre em outra aba", repoLink?.alvo === "_blank", "sair da PoC no meio perderia o lugar");

console.log("==> aba de entrada: a recomendação");
const advice = await text();
check("a campeã tem nome e nota", /acerta \d+,\d%/.test(advice), advice.slice(0, 120));
check(
  "a lista traz as outras cinco",
  await evaluate(`document.querySelectorAll(".poc-ans-row").length`).then((n) => n === 5),
  `${await evaluate(`document.querySelectorAll(".poc-ans-row").length`)} linhas`,
);
// A armadilha 44 em forma de asserção de TELA: o `web_check.py` varre o payload,
// mas o front também formata (format.js), e nenhuma asserção de payload alcança
// o que sai do `toFixed`. Ponto decimal em pt-BR lê como separador de milhar.
const dotDecimal = await evaluate(`
  (() => {
    const body = document.body.innerText;
    // O rodapé cita os parâmetros como estão no config.py (k1=1.2, b=0.75) — é
    // cópia literal de configuração, não medida para o visitante.
    const foot = document.querySelector(".poc-footer")?.innerText || "";
    const scan = body.replace(foot, "");
    return (scan.match(/\\d+\\.\\d/g) || []).slice(0, 5);
  })()
`);
check("nenhum decimal com ponto na tela", dotDecimal.length === 0, dotDecimal.join(", "));

console.log("==> aba da busca");
check("abrir “Fazer uma pergunta”", await click("Fazer uma pergunta"));
await wait(1200);

// A primeira pergunta pronta da primeira família. Clicar pelo texto do chip é o
// que a pessoa faz, e é o caminho que exercita o `slugify` do front contra o
// nome que o exportador gravou.
const firstQuery = await evaluate(`
  document.querySelector(".poc-chips button")?.textContent.replace(/\\s+/g, " ").trim() || null
`);
check("há perguntas prontas", Boolean(firstQuery), firstQuery ? `“${firstQuery}”` : "");
if (firstQuery) {
  check("clicar na pergunta pronta", await click(firstQuery));
  await wait(2500);
  const result = await text();
  const broke = result.includes("A busca falhou") || result.includes("não está entre as");
  check("resultado veio do snapshot", !broke, broke ? result.slice(0, 160) : "");
  const lists = await evaluate(`document.querySelectorAll(".poc-grid .poc-card").length`);
  check("as seis listas renderizaram", lists === 6, `${lists} listas`);
}

// Trocar o `k` prova que os três valores congelaram. É o defeito que o snapshot
// tem de sobra para produzir: o `<select>` oferece 3, 5 e 10 e o exportador podia
// ter gravado um só — e a falha só aparece quando alguém mexe no seletor.
check(
  "trocar para 10 por lista",
  await evaluate(`
    (() => {
      const select = document.querySelector(".poc-search select");
      if (!select) return false;
      select.value = "10";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `),
);
await wait(2500);
const withTen = await text();
check("k=10 também está congelado", !withTen.includes("o snapshot não tem k="), withTen.slice(0, 120));

// Pergunta que nunca foi medida: tem que virar aviso explicado, nunca lista
// vazia. Vazio numa tela que compara motores de busca lê como "nenhum achou
// nada", que é a conclusão errada — é a razão de o modo snapshot existir assim.
check(
  "digitar uma pergunta fora do conjunto",
  await evaluate(`
    (() => {
      const input = document.querySelector(".poc-search input");
      const form = document.querySelector("form.poc-search");
      if (!input || !form) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      setter.call(input, "pergunta que ninguem mediu jamais");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      form.requestSubmit();
      return true;
    })()
  `),
);
await wait(1800);
const missing = await text();
check(
  "a ausência vira aviso, não lista vazia",
  missing.includes("não está entre as"),
  missing.includes("perguntas medidas") ? "" : missing.slice(0, 160),
);

console.log("==> as outras três abas");
// A palavra-âncora tem que sair do conteúdo que só existe DEPOIS do `fetch`,
// nunca do cabeçalho da aba — senão a asserção passa com o painel vazio. Por
// isso “cópia 2”: é o título do segundo painel do documento, e ele só é
// renderizado quando `fetchDocument` resolveu. (A primeira versão procurava
// “vetor”, palavra que aparece só em comentário de código, em nenhum texto de
// tela: a asserção falhava com a página certa na frente.)
for (const [label, needle] of [
  ["Como isso fica guardado", "cópia 2"],
  ["Quem acerta mais", "acerta"],
  ["Onde elas discordam", "discord"],
]) {
  check(`abrir “${label}”`, await click(label));
  await wait(2200);
  const screen = await text();
  const ok = screen.toLowerCase().includes(needle) && !screen.includes("Falhou");
  check(`“${label}” renderizou`, ok, ok ? "" : screen.slice(0, 160));
}

console.log("==> fechamento");
check("nenhuma requisição com erro", failedRequests.length === 0, failedRequests.slice(0, 4).join(" | "));
check("nenhuma exceção no console", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" | "));

socket.close();
console.log(`\nerros: ${failures}`);
process.exit(failures === 0 ? 0 : 1);
