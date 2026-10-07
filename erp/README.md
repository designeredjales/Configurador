# ERP Moveleiro: núcleo Engenharia + PCP

ERP SaaS para fábricas de móveis sob medida. O MVP cobre o caminho crítico da operação:

```
Projeto (Promob) → Engenharia (BOM + consumo + gate) → Ordem de Produção → Roteiro por peça → Baixa por código de barras → Painel PCP
```

## O que já funciona

| Módulo | Entrega |
|---|---|
| **Acesso e segurança** | Cadastro da empresa com o primeiro administrador, login por e-mail e senha, perfis com permissão checada no servidor, gestão da equipe. A empresa (tenant) vem sempre do login |
| **Cadastros** | Clientes, materiais (chapa, fita, ferragem, acessório) e centros de trabalho, isolados por empresa |
| **Entrada pelo Promob (XML)** | O projeto inteiro nasce do XML do Promob: cliente, ambientes, módulos, conjuntos (gavetas), peças com medida acabada, chapa, fita (metros), ferragens e o roteiro produtivo de cada peça. Materiais novos entram no cadastro automaticamente com o preço de tabela |
| **Consumo** | Chapas em m² e em nº de chapas (com % de perda), fita de borda em metros por lado, ferragens, custo de material |
| **Gate de liberação** | O projeto só vai para a fábrica sem pendências: material sem cadastro, medida inválida, projeto vazio. Depois de liberado, a engenharia fica travada |
| **PCP** | Geração de OP com uma etiqueta (código de barras) por peça física e roteiro pelas operações do Promob: CORTE → BORDA (se a peça tem borda) → USINAGEM (se tem FURAR/RASGO) → EMBALAGEM |
| **Apontamento** | Baixa por leitor de código de barras, registrada em nome do usuário logado: bloqueia etapa fora de ordem, centro fora do roteiro e baixa duplicada. Fecha a OP e o projeto sozinho |
| **Painel** | OPs abertas, em produção e atrasadas, fila de peças por centro, baixas do dia, progresso por OP |
| **Chão de fábrica** | Plano de corte guilhotinado por material (serra, refilo, veio) com desenho de cada chapa; etiquetas 100 × 50 mm com código de barras para imprimir no navegador ou em ZPL (Zebra); apontamento pela câmera do celular |
| **Estoque** | Saldo por movimentação, reserva automática na liberação do projeto, baixa automática na conclusão, inventário com ajuste pela diferença, custo médio ponderado |
| **Comercial** | Valor de tabela, pedido à fábrica, venda ao cliente, frete, montagem e condição de pagamento lidos do XML; contrato gera as parcelas a receber |
| **Financeiro** | Contas a receber e a pagar (a compra recebida vira conta a pagar no prazo do fornecedor), baixas, fluxo de caixa de 6 meses, **DRE por obra** (receita − impostos − material − custos diretos = margem de contribuição) |
| **Montagem e pós-obra** | Agenda de montagem (só inicia com a produção concluída), checklist de entrega com quem conferiu, entrega com nome de quem recebeu; assistência técnica com garantia, causa raiz e custo lançado no DRE da obra |
| **Compras (MRP)** | Sugestão de compra = reservado + mínimo − saldo − em pedido; pedido ao fornecedor, envio, recebimento parcial ou total, cancelamento |

## Rodar

```bash
cd erp
pip install -r requirements.txt
export ERP_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python seed_demo.py                 # opcional: empresa demo com a cozinha de exemplo
uvicorn app.main:app --reload
```

Abra `http://localhost:8000` e cadastre sua empresa, ou entre na demonstração com `admin@demo.com` / `demo12345` (operador: `operador@demo.com` / `demo12345`). A API documentada fica em `http://localhost:8000/docs`.

## Acesso e perfis

| Perfil | Pode |
|---|---|
| **Administrador** | Tudo, inclusive criar, desativar e trocar o perfil dos usuários |
| **Gestor** | Engenharia, PCP, compras, estoque, apontamento e cadastros |
| **Engenharia** | Importar o XML, criar e liberar projetos, cadastrar materiais e clientes |
| **PCP** | Gerar e cancelar OPs, cadastrar centros de trabalho, apontar |
| **Compras** | Fornecedores, pedidos, recebimento, inventário e cadastro de materiais |
| **Financeiro** | Contrato, contas a pagar e receber, fluxo de caixa e DRE (valores financeiros só para Administrador, Gestor e Financeiro) |
| **Montagem** | Agenda de montagem, checklist de entrega e assistência técnica (Gestor e PCP também) |
| **Operador** | Apontar (dar baixa) e consultar OPs e painel |

Todos os perfis consultam os dados da própria empresa. Detalhes de segurança:

- Senhas guardadas só como hash `scrypt` com sal; mínimo de 8 caracteres.
- Sessão por token JWT (HS256) válido por 12 horas (`ERP_SESSAO_HORAS`). **Defina `ERP_SECRET` em produção**: sem ele, o servidor gera um segredo temporário e todos precisam entrar de novo a cada reinício.
- O perfil e a situação do usuário são lidos do banco a cada requisição: desativar alguém corta o acesso na hora, mesmo com token emitido.
- Login com erro não revela se o e-mail existe; a empresa nunca fica sem um administrador ativo.
- Ainda faltam: recuperação de senha por e-mail, limite de tentativas de login e HTTPS (fica a cargo do servidor de hospedagem).

O banco padrão é SQLite (`marcenaria_erp.db`). Em produção, use `DATABASE_URL=postgresql+psycopg://...`.

## Testes

```bash
cd erp && python -m pytest -q
```

## Entrada do projeto: XML do Promob

No Promob, exporte o relatório **Orçamento-Explodido c/ Operação** em XML. Na tela **Projetos → Novo projeto a partir do Promob**, ou pela API:

```bash
curl -H "Authorization: Bearer $TOKEN" -F arquivo=@Cozinha.xml -F codigo=P-0001 http://localhost:8000/api/projetos/importar-xml
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

## Chão de fábrica

- **Plano de corte** (`GET /api/ops/{id}/plano-corte`): agrupa as peças da OP por material e encaixa com corte guilhotina (melhor ajuste por área). Usa a medida de chapa do cadastro do material; sem ela, a medida padrão da empresa (2750 × 1850 mm). Serra (4 mm) e refilo (10 mm) também são da empresa. Peça com veio não gira. Num lote de 150 peças o aproveitamento fica em 86 a 87%, a 1 ou 2 chapas do mínimo teórico. Para chegar a 90% ou mais, integre a otimizadora da fábrica: o plano já sai por etiqueta.
- **Etiquetas**: `GET /api/ops/{id}/etiquetas.html` (100 × 50 mm, Code128, para impressora térmica ou folha de etiquetas) e `GET /api/ops/{id}/etiquetas.zpl` (Zebra, 203 dpi).
- **Câmera**: no Chrome do Android e no Safari recente, o apontamento ganha o botão "Ler pela câmera do celular" (API `BarcodeDetector`).

## Compras e estoque

O estoque é a soma das movimentações de cada material, na unidade do cadastro (chapa por chapa `CH` ou por `M2`, fita em `M`, ferragem em `UN`).

1. **Liberar o projeto** reserva o consumo calculado do XML, com a perda da empresa. Chapa cadastrada por chapa (com medidas) é reservada em fração de chapa.
2. **Sugestão de compra** (`GET /api/estoque`): `reservado + estoque mínimo − saldo − em pedido`, arredondada para cima nos itens contáveis.
3. **Pedido** (`POST /api/pedidos`) → **enviar** → **receber** (parcial ou total). O recebimento gera a entrada e recalcula o custo médio ponderado do material.
4. **Projeto concluído** (última baixa da última OP): a reserva vira saída de estoque, ao custo médio, referenciada ao projeto.
5. **Inventário** (`POST /api/estoque/inventario`): informa a quantidade contada e o ERP lança o ajuste pela diferença, com usuário e observação.

Saldo negativo é permitido e aparece em vermelho: indica consumo sem entrada registrada, ou seja, recebimento que não foi lançado.

## Comercial e financeiro

- **Do XML do Promob**: `TOTALPRICES/@TABLE` (valor de tabela), `MARGINS/ORDER/@VALUE` (pedido à fábrica com ICMS, IPI e descontos), `MARGINS/BUDGET/@VALUE` (venda ao cliente), frete e montagem do orçamento e a condição de pagamento selecionada.
- **Contrato** (`POST /api/projetos/{id}/contrato`): valor, parcelas e 1º vencimento; gera as parcelas mensais a receber. A última parcela absorve o arredondamento.
- **Contas a pagar**: cada recebimento de compra gera a conta do que entrou, com vencimento no prazo de pagamento do fornecedor. Custos da obra (frete, montador, comissão) são lançados com o projeto.
- **DRE por obra** (`GET /api/projetos/{id}/dre`): receita − impostos (alíquota da empresa) − material − custos diretos = margem de contribuição. Material é *previsto* (engenharia × custo médio) até o projeto concluir e *realizado* (baixa do estoque) depois.
- **Fluxo de caixa** (`GET /api/financeiro/fluxo`): previsto por vencimento (atrasado entra no mês atual) e realizado por data de baixa, com saldo acumulado.
- **Configurações** (`PUT /api/empresas/atual`, administrador): perdas, imposto sobre a venda, chapa padrão, serra e refilo.

## Montagem e pós-obra

- **Agenda** (`POST /api/montagens`): a partir da liberação, uma montagem ativa por projeto, com o checklist padrão de 7 itens.
- **Iniciar** exige o projeto com produção concluída. **Concluir** exige todos os itens conferidos e o nome de quem recebeu, e o projeto passa a `ENTREGUE`.
- **Assistência** (`POST /api/chamados`): aberta para projeto entregue, marca se está na garantia (`garantia_meses` da empresa, contada da entrega). Ao resolver, registra a causa raiz e o custo, que vira lançamento `ASSISTENCIA` no DRE da obra. Causas internas (produção, projeto, montagem, material) contam como retrabalho.
- **Marcos do projeto**: `liberado_em`, `producao_concluida_em` e `entregue_em` ficam gravados para os indicadores de prazo.

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
    security.py        # hash de senha e tokens de sessão
    deps.py            # usuário logado, empresa e permissões por perfil
    services/
      promob_xml.py    # leitor do XML do Promob
      importacao.py    # XML/CSV → árvore do projeto, cadastro automático de materiais
      engenharia.py    # consumo, pendências, liberação
      pcp.py           # OP, roteiro, apontamento, filas
      estoque.py       # reservas, MRP, recebimento, custo médio, inventário
      corte.py         # otimizador de plano de corte
      financeiro.py    # contrato, contas, DRE por obra, fluxo de caixa
      pos_obra.py      # montagem, checklist de entrega, assistência técnica
    routers/           # API REST (cadastros, projetos, produção)
    static/index.html  # interface web (painel, projetos, OPs, apontamento, materiais)
  tests/               # fluxo completo, XML do Promob, gate, perfis, isolamento entre empresas
  exemplos/            # XML do Promob (anonimizado), CSV e materiais de demonstração
```

## Próximas camadas (roadmap)

1. **Segurança 2.0**: recuperação de senha por e-mail, limite de tentativas de login, registro de auditoria.
2. **Lados da fita e furação**: ler o XML de máquina do Promob (ou o relatório com bordas) para etiquetas com C1/C2/L1/L2 e programas CNC.
3. **Integração com a otimizadora** (Corte Certo, Optiplanning) e programas CNC por peça.
4. **Compras 2.0**: cotação entre fornecedores, envio do pedido por e-mail/WhatsApp, lotes e sobras de chapa reaproveitáveis.
5. **Pós-obra 2.0**: fotos da obra no checklist, assinatura do cliente na tela e peça de reposição gerando OP.
6. **Fiscal**: NF-e via emissor integrado (Focus NFe, eNotas) e conciliação bancária.
7. **Alembic** para migrações e PostgreSQL como padrão.
