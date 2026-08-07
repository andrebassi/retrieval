// Os três pedaços que toda aba usa: carregar dados, dizer que está carregando,
// dizer que quebrou.
//
// Moram aqui — e não no `App.jsx` — porque o escolhedor virou arquivo próprio e
// precisa dos três. Deixá-los no `App.jsx` faria `App → Advice → App`, e ciclo
// de import no Vite não dá erro de build: dá `undefined` em runtime, que é a
// armadilha 19 de novo.

import { useEffect, useState } from "react";
import { Warning } from "@phosphor-icons/react";

export function useAsync(loader, deps) {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    let alive = true;
    setState({ status: "loading" });
    loader()
      .then((data) => alive && setState({ status: "ok", data }))
      .catch((error) => alive && setState({ status: "error", error }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function Loading({ what }) {
  return <p className="poc-muted">carregando {what}…</p>;
}

export function Failed({ error }) {
  return (
    <div className="poc-alert">
      <Warning size={18} weight="bold" /> {String(error.message || error)}
    </div>
  );
}
