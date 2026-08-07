#!/usr/bin/env bash
# Cria o ambiente Python e confere o que a PoC precisa fora dele.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "── ambiente Python"
uv sync
echo

echo "── Ollama"
# `rtk proxy` obrigatório: o wrapper reescreve `curl` e devolve resumo de
# schema em vez do JSON, o que quebra o parse silenciosamente.
if ! rtk proxy curl -s --max-time 5 "${OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null; then
    echo "🛑 Ollama não responde em ${OLLAMA_URL:-http://127.0.0.1:11434}"
    echo "   suba com: ollama serve"
    exit 1
fi

MODEL="${DENSE_MODEL:-bge-m3}"
# `grep -c` num pipe, e não `grep -q` nem herestring: `-q` fecha o pipe ao casar e
# mata o curl com SIGPIPE, e a herestring trava acima de ~100 B — a lista de
# modelos do Ollama passa disso com folga.
if [ "$(rtk proxy curl -s --max-time 5 "${OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" | grep -c "\"${MODEL}" || true)" != "0" ]; then
    echo "✅ modelo ${MODEL} já disponível"
else
    echo "baixando ${MODEL}…"
    ollama pull "${MODEL}"
fi

echo
echo "── reranker"
echo "o cross-encoder baixa do HuggingFace na primeira execução de \`task eval\`"
echo "modelo: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 (~470 MB)"
