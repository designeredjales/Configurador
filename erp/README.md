# ERP Moveleiro: núcleo Engenharia + PCP

ERP SaaS para fábricas de móveis sob medida. O MVP cobre o caminho crítico da operação:

```
Projeto (Promob) → Engenharia (BOM + consumo + gate) → Ordem de Produção → Roteiro por peça → Baixa por código de barras → Painel PCP
```

## O que já funciona

| Módulo | Entrega |
|---|---|
| **Cadastros** | Empresa (multiempresa desde o dia 1), clientes, materiais (chapa, fita, ferragem, acessório) e centros de trabalho |
| **Entrada pelo Promob (XML)** | O projeto inteiro nasce do XML do Promob: cliente, ambientes, módulos, conjuntos (gavetas), peças com medida acabada, chapa, fita (metros), ferragens e o roteiro produtivo de cada peça. Materiais novos entram no cadastro automaticamente com o preço de tabela |
| **Consumo** | Chapas em m² e em nº de chapas (com % de perda), fita de borda em metros por lado, ferragens, custo de material |
| **Gate de liberação** | O projeto só vai para a fábrica sem pendências: material sem cadastro, medida inválida, projeto vazio. Depois de liberado, a engenharia fica travada |
| **PCP** | Geração de OP com uma etiqueta (código de barras) por peça física e roteiro pelas operações do Promob: CORTE → BORDA (se a peça tem borda) → USINAGEM (se tem FURAR/RASGO) → EMBALAGEM |
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

## Entrada do projeto: XML do Promob

No Promob, exporte o relatório **Orçamento-Explodido c/ Operação** em XML. Na tela **Projetos → Novo projeto a partir do Promob**, ou pela API:

```bash
curl -H "X-Empresa-Id: 1" -F arquivo=@Cozinha.xml -F codigo=P-0001 http://localhost:8000/api/projetos/importar-xml
```

| No XML (`LISTING/AMBIENTS/AMBIENT/CATEGORIES/CATEGORY/ITEMS/ITEM`) | No ERP |
|---|---|
| `ITEM` de nível 0 | Módulo (balcão, gaveteiro, porta, frente) |
| `ITEM` sem `COMPONENT`/`STRUCTURE` e com filhos | Conjunto intermediário (ex.: gaveta): é percorrido e as quantidades são multiplicadas em cadeia |
| `ITEM COMPONENT="Y"` | Peça: `WIDTH` × `DEPTH`, espessura em `HEIGHT` |
| `STRUCTURE="Y"`, `STRUCTUREKEY="CHAPA"` / `CHAPA_*` | Material da peça (`REFERENCE`, m², `PRICE TABLE` = custo/m²) |
| `STRUCTURE="Y"`, `STRUCTUREKEY="FITA_BORDA"` | Fita da peça e metragem total |
| `STRUCTURE="Y"`, `STRUCTUREKEY` CORTE, BORDA, FURAR, RASGO... | Operações do roteiro da peça |
| `FAMILY="Ferragens"` | Ferragem, consolidada por código no módulo |
| `CUSTOMERSDATA/DATA[@ID="nomecliente"]` | Cliente do projeto |
| `ITEMSWITHOUTPRICE` | Não é importado (repete itens da árvore); vira aviso de "sem preço" |

Limitações conhecidas desse relatório: ele não traz os lados da fita (C1/C2/L1/L2) nem as coordenadas de furação, só a metragem total de fita e as operações.

O exemplo anonimizado fica em `exemplos/promob_cozinha.xml`. Os testes conferem que a área de chapa e a metragem de fita calculadas pelo ERP batem com os valores gravados pelo Promob.

## Alternativa: CSV (somente pela API)

Para projetos que não vêm do Promob, `POST /api/projetos/{id}/importar` aceita o CSV abaixo (e também o XML). Separador `;` (ou `,`), com cabeçalho. O decimal pode vir com vírgula. Exemplo completo em `exemplos/cozinha_silva.csv`.

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
      promob_xml.py    # leitor do XML do Promob
      importacao.py    # XML/CSV → árvore do projeto, cadastro automático de materiais
      engenharia.py    # consumo, pendências, liberação
      pcp.py           # OP, roteiro, apontamento, filas
    routers/           # API REST (cadastros, projetos, produção)
    static/index.html  # interface web (painel, projetos, OPs, apontamento, materiais)
  tests/               # fluxo completo, gate, isolamento entre empresas
  exemplos/            # XML do Promob (anonimizado), CSV e materiais de demonstração
```

## Próximas camadas (roadmap)

1. **Autenticação e perfis** (JWT, usuário por empresa, papéis: engenharia, PCP, operador, gestor). Hoje o tenant vem no header `X-Empresa-Id`, e isso **não serve para produção**.
2. **Lados da fita e furação**: ler o XML de máquina do Promob (ou o relatório com bordas) para etiquetas com C1/C2/L1/L2 e programas CNC.
3. **Etiquetas** (PDF/ZPL) e **plano de corte** com integração à otimizadora.
4. **Compras e estoque**: MRP a partir do consumo dos projetos liberados, reserva de chapas e almoxarifado.
5. **Comercial e financeiro**: orçamento → pedido → contrato, contas a pagar e a receber, DRE por obra.
6. **Alembic** para migrações e PostgreSQL como padrão.
