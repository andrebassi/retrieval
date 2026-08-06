{
  # Stack local 100% via Nix — NUNCA Docker para recurso local (rule 23).
  # `nix run .#services` sobe Postgres 17 + pgvector.
  # `nix develop` entrega o toolchain (Python, uv, psql, ollama).
  description = "retrieval-poc — léxico, denso, fusão e reranking sobre o mesmo corpus";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    process-compose-flake.url = "github:Platonic-Systems/process-compose-flake";
    services-flake.url = "github:juspay/services-flake";
  };

  outputs = inputs @ { flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      imports = [ inputs.process-compose-flake.flakeModule ];

      perSystem = { pkgs, ... }: {
        # `nix run .#services` — Postgres 17 com pgvector.
        #
        # O índice léxico NÃO precisa de extensão: `tsvector` e `ts_rank_cd` são
        # nativos, e o BM25 desta PoC é calculado em SQL a partir deles. É de
        # propósito — a pergunta que o projeto responde é o que dá para fazer
        # com o Postgres que já está lá.
        process-compose."services" = {
          imports = [ inputs.services-flake.processComposeModules.default ];

          services.postgres."pg" = {
            enable = true;
            package = pkgs.postgresql_17;
            extensions = exts: [ exts.pgvector ];
            # A extensão vai em `schemas`, e não em `initialScript.before`:
            # `before` roda ANTES de os bancos de `initialDatabases` existirem,
            # então a extensão nasce no banco `postgres` e o `retrieval` fica
            # sem ela — com a mensagem enganosa `type "vector" does not exist`
            # só na hora do CREATE TABLE. Medido aqui, não suposto.
            initialDatabases = [{
              name = "retrieval";
              schemas = [
                (pkgs.writeText "00-extensions.sql" ''
                  CREATE EXTENSION IF NOT EXISTS vector;
                '')
              ];
            }];
            listen_addresses = "127.0.0.1";
            # 5432 é do sistema, 5433 é do image-embedding-poc: as duas PoCs
            # rodam juntas sem se atrapalhar.
            port = 5434;
            superuser = "postgres";
          };
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python312
            uv # torch e sentence-transformers vêm de wheel, não de nixpkgs
            postgresql_17 # psql para inspecionar o índice à mão
            go-task
            jq
            curl
            ollama # embedding de texto local (bge-m3), nada sai da máquina
          ];
          shellHook = ''
            export PGHOST=127.0.0.1 PGPORT=5434 PGUSER=postgres PGDATABASE=retrieval
            echo "retrieval-poc — shell Nix (sem Docker)"
            echo "  nix run .#services   → Postgres 17 + pgvector na porta 5434"
            echo "  task setup           → venv + modelos locais"
            echo "  task all             → corpus → index → eval → experiments → report"
          '';
        };
      };
    };
}
