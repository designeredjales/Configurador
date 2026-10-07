# ERP Moveleiro: núcleo Engenharia + PCP

ERP SaaS para fábricas de móveis sob medida. O MVP cobre o caminho crítico da operação:

```
Projeto (Promob) → Engenharia (BOM + consumo + gate) → Ordem de Produção → Roteiro por peça → Baixa por código de barras → Painel PCP
```

## O que já funciona

| Módulo | Entrega |
|---|---|
| **Cadastros** | Empresa (multiempresa desde o dia 1), clientes, materiais (chapa, fita, ferragem, acessório) e centros de trabalho |
| **Engenharia** | Importação da lista de peças e itens (CSV) em uma árvore Projeto → Ambiente → Módulo → Peça/Item |
| **Consumo** | Chapas em m² e em nº de chapas (com % de perda), fita de borda em metros por lado, ferragens, custo de material |
| **Gate de liberação** | O projeto só vai para a fábrica sem pendências: material sem cadastro, medida inválida, projeto vazio. Depois de liberado, a engenharia fica travada |
| **PCP** | Geração de OP com uma etiqueta (código de barras) por peça física e um roteiro automático por regra do centro: CORTE → BORDA (se tem fita) → USINAGEM (se tem programa) → EMBALAGEM |
| **Apontamento** | Baixa por leitor de código de barras: bloqueia etapa fora de ordem, centro fora do roteiro e baixa duplicada. Fecha a OP e o projeto sozinho |
| **Painel** | OPs abertas, em produção e atrasadas, fila de peças por centro, baixas do dia, progresso por OP |

## Rodar

```bash
cd erp
pip install -r requirements.txt
python seed_demo.py                 # opcional: empresa demo com a cozinha de exemplo
uvicorn app.main:app --reload
```

Abra `http://localhost:8000/?empresa=1`. A API documentada fica em `http://localhost:8000/docs`.

O banco padrão é SQLite (`marcenaria_erp.db`). Em produção, use `DATABASE_URL=postgresql+psycopg://...`.

## Testes

```bash
cd erp && python -m pytest -q
```

## Layout do CSV de importação

Separador `;` (ou `,`), com cabeçalho. O decimal pode vir com vírgula. Exemplo completo em `exemplos/cozinha_silva.csv`.

| Coluna | Obrigatória | Uso |
|---|---|---|
| AMBIENTE | sim | Cozinha, Dormitório... |
| MODULO_CODIGO / MODULO_DESCRICAO / MODULO_QTD | código sim | O módulo multiplica a quantidade das peças |
| TIPO | sim | `PECA` (chapa cortada) ou `ITEM` (ferragem/acessório) |
| CODIGO / DESCRICAO | código sim | Identificação da peça/item |
| MATERIAL | sim | Código do material cadastrado |
| COMPRIMENTO / LARGURA / ESPESSURA | PECA | mm, medida acabada |
| QUANTIDADE | sim | Por módulo |
| VEIO | não | S/N |
| FITA_C1 / FITA_C2 / FITA_L1 / FITA_L2 | não | Código da fita em cada lado (C = comprimento, L = largura) |
| USINAGEM | não | Nome do programa CNC/furadeira. Se vier preenchido, a peça passa pela USINAGEM |
| UNIDADE | não | Para ITEM |

## Estrutura

```
erp/
  app/
    models.py          # modelo de dados (multiempresa)
    services/
      importacao.py    # CSV → árvore do projeto
      engenharia.py    # consumo, pendências, liberação
      pcp.py           # OP, roteiro, apontamento, filas
    routers/           # API REST (cadastros, projetos, produção)
    static/index.html  # interface web (painel, projetos, OPs, apontamento, materiais)
  tests/               # fluxo completo, gate, isolamento entre empresas
  exemplos/            # CSV e materiais de demonstração
```

## Próximas camadas (roadmap)

1. **Autenticação e perfis** (JWT, usuário por empresa, papéis: engenharia, PCP, operador, gestor). Hoje o tenant vem no header `X-Empresa-Id`, e isso **não serve para produção**.
2. **Adaptador XML nativo do Promob**, a ser validado com exportações reais.
3. **Etiquetas** (PDF/ZPL) e **plano de corte** com integração à otimizadora.
4. **Compras e estoque**: MRP a partir do consumo dos projetos liberados, reserva de chapas e almoxarifado.
5. **Comercial e financeiro**: orçamento → pedido → contrato, contas a pagar e a receber, DRE por obra.
6. **Alembic** para migrações e PostgreSQL como padrão.
