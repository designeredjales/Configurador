# ERP Moveleiro: núcleo Engenharia + PCP

ERP SaaS para fábricas de móveis sob medida. O MVP cobre o caminho crítico da operação:

```
Projeto (Promob) → Engenharia (BOM + consumo + gate) → Ordem de Produção → Roteiro por peça → Baixa por código de barras → Painel PCP
```

## O que já funciona

| Módulo | Entrega |
|---|---|
| **Acesso e segurança** | Cadastro da empresa com o primeiro administrador, login por e-mail e senha, **configurador de funções por login** (o perfil é o modelo; o administrador libera ou retira cada função), permissão checada no servidor a cada requisição. A empresa (tenant) vem sempre do login |
| **Cadastros** | Clientes, materiais (chapa, fita, ferragem, acessório) e centros de trabalho, isolados por empresa |
| **Entrada pelo Promob (XML)** | O projeto inteiro nasce do XML do Promob: cliente, ambientes, módulos, conjuntos (gavetas), peças com medida acabada, chapa, fita (metros), ferragens e o roteiro produtivo de cada peça. Materiais novos entram no cadastro automaticamente com o preço de tabela |
| **Consumo** | Chapas em m² e em nº de chapas (com % de perda), fita de borda em metros por lado, ferragens, custo de material |
| **Gate de liberação** | O projeto só vai para a fábrica sem pendências: material sem cadastro, medida inválida, projeto vazio. Depois de liberado, a engenharia fica travada |
| **PCP** | Geração de OP com uma etiqueta (código de barras) por peça física e roteiro pelas operações do Promob: CORTE → BORDA (se a peça tem borda) → USINAGEM (se tem FURAR/RASGO) → EMBALAGEM |
| **Apontamento** | Baixa por leitor de código de barras, registrada em nome do usuário logado: bloqueia etapa fora de ordem, centro fora do roteiro e baixa duplicada. Fecha a OP e o projeto sozinho |
| **Controle de produção** | Consulta de peças (onde cada peça está parada, quem deu a última baixa), estorno da última baixa com motivo, refugo com etiqueta de reposição, baixa do material perdido e custo no DRE da obra; baixas por operador e setor; histórico de ocorrências |
| **Painel** | OPs abertas, em produção e atrasadas, fila de peças por centro, baixas do dia, progresso por OP |
| **Chão de fábrica** | Plano de corte guilhotinado por material (serra, refilo, veio) com desenho de cada chapa; etiquetas 100 × 50 mm com código de barras para imprimir no navegador ou em ZPL (Zebra); apontamento pela câmera do celular |
| **Estoque** | Saldo por movimentação, reserva automática na liberação do projeto, baixa automática na conclusão, inventário com ajuste pela diferença, custo médio ponderado |
| **Comercial** | Valor de tabela, pedido à fábrica, venda ao cliente, frete, montagem e condição de pagamento lidos do XML; contrato gera as parcelas a receber |
| **Financeiro** | Contas a receber e a pagar (a compra recebida vira conta a pagar no prazo do fornecedor), baixas, fluxo de caixa de 6 meses, **DRE por obra** (receita − impostos − material − custos diretos = margem de contribuição) |
| **Fiscal e banco** | NF-e de venda por emissor integrado (Focus NFe) com validação prévia e CFOP automático; conciliação bancária por extrato OFX com sugestão de pareamento |
| **Indicadores do dono** | Painel único: vendas contratadas, margem de contribuição ponderada, pontualidade, prazo contrato→entrega, gargalo da fábrica, retrabalho, caixa vencido e alertas |
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

## Acesso, perfis e funções

Cada tela e cada ação do sistema é uma **função**. O perfil define o modelo inicial; na aba **Usuários → Funções**, o administrador marca exatamente o que cada login opera. Exemplos: o operador líder do corte que também estorna baixas; o PCP que não registra refugo; o financeiro que concilia o banco mas não emite NF-e. A mudança vale na próxima ação da pessoa, sem novo login; "Voltar ao modelo do perfil" desfaz a personalização e trocar o perfil reaplica o modelo novo.

| Módulo | Função | Modelo por perfil |
|---|---|---|
| Gestão | Indicadores do dono | Administrador, Gestor |
| Engenharia | Projetos e engenharia · Cadastro de materiais | Engenharia (+ Compras: materiais) |
| Comercial | Cadastro de clientes | Engenharia, Financeiro |
| Produção | Ordens de produção · Apontamento · Estornar apontamento · Refugo e reposição | PCP (todas) · Operador (só apontamento) |
| Obra | Montagem · Assistência técnica | Montagem, PCP |
| Suprimentos | Estoque e inventário · Compras | Compras |
| Financeiro | Financeiro · NF-e · Conciliação bancária | Financeiro |
| Administração | Usuários e configurações | só Administrador |

O **Administrador** opera tudo, sempre (a empresa nunca fica sem quem administre); o **Gestor** tem tudo menos usuários. Consultas (painel, OPs, consulta de peças) ficam abertas a todos os logins da empresa. Catálogo e modelos: `GET /api/funcoes`; personalizar: `PATCH /api/usuarios/{id}` com `{"funcoes": [...]}` (`null` volta ao modelo).

Todos os perfis consultam os dados da própria empresa. Detalhes de segurança:

- Senhas guardadas só como hash `scrypt` com sal; mínimo de 8 caracteres.
- Sessão por token JWT (HS256) válido por 12 horas (`ERP_SESSAO_HORAS`). **Defina `ERP_SECRET` em produção**: sem ele, o servidor gera um segredo temporário e todos precisam entrar de novo a cada reinício.
- O perfil, as funções e a situação do usuário são lidos do banco a cada requisição: desativar alguém corta o acesso na hora, mesmo com token emitido.
- Login com erro não revela se o e-mail existe; a empresa nunca fica sem um administrador ativo.
- **Recuperação de senha** por e-mail: link de uso único, válido por 1 hora, guardado só como hash; a resposta não revela se o e-mail existe e há no máximo 3 pedidos por hora por endereço.
- **Trocar a senha** (no menu "Senha"), redefini-la ou o administrador mudar senha ou perfil derruba as outras sessões do usuário na hora (versão de sessão dentro do token).
- **Limite de tentativas**: 5 senhas erradas em 15 minutos bloqueiam aquele e-mail naquele IP.
- Cabeçalhos de segurança, `Cache-Control: no-store` na API e `GET /api/saude` para monitoramento. HTTPS fica com o proxy da hospedagem (ver [DEPLOY.md](DEPLOY.md)).

O banco padrão de desenvolvimento é SQLite (`marcenaria_erp.db`), com as tabelas criadas na subida. **Produção usa PostgreSQL com migrações**: veja o [guia de hospedagem](DEPLOY.md) (Docker + Postgres, HTTPS, backup).

### Migrações do banco (Alembic)

Mudou um modelo em `app/models.py`? Gere e aplique a migração:

```bash
alembic revision --autogenerate -m "descreva a mudança"
alembic upgrade head
```

O teste `tests/test_migracoes.py` falha se o modelo mudar sem migração.

## Testes

```bash
cd erp && python -m pytest -q
# a mesma suíte no PostgreSQL:
ERP_TEST_DATABASE_URL="postgresql+psycopg://usuario@/banco_teste?host=/tmp" python -m pytest -q
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

## Controle de produção

Inspirado nas consultas de controle de produção dos ERPs industriais, sem a complexidade deles: três ações e três consultas.

- **Consulta de peças** (`GET /api/producao/pecas`): filtra por OP, projeto, setor onde a peça está parada, material, situação (aguardando, em processo, concluída, refugada) e busca livre por etiqueta, peça ou módulo. Mostra a próxima etapa e a última baixa (setor, operador, horário).
- **Estorno** (`POST /api/apontamentos/estorno`, função *Estornar apontamento*): desfaz só a **última** baixa da peça, com motivo obrigatório. Sem baixas, a OP volta para ABERTA. OP concluída não estorna: o material já saiu do estoque e o caso vai para a Assistência.
- **Refugo e reposição** (`POST /api/apontamentos/refugo`, função *Refugo e reposição*): a peça vira REFUGADA e sai da contagem da OP; nasce uma peça de reposição com nova etiqueta e o mesmo roteiro desde o corte; o material perdido sai do estoque (fração de chapa ou m²) e o custo entra no **DRE da obra** e nos indicadores de qualidade. A etiqueta antiga é recusada no apontamento. `?apenas_reposicoes=true` nas etiquetas e no plano de corte imprime e corta só as reposições.
- **Baixas por operador e setor** (`GET /api/producao/baixas?de=&ate=`) e **ocorrências** (`GET /api/producao/ocorrencias`): quem produziu o quê, e cada estorno e refugo com motivo, custo e responsável.

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

## Fiscal e conciliação bancária

**NF-e (Focus NFe, API v2)**
1. Administrador: Usuários → Configurações da empresa: CNPJ, UF, NCM padrão (9403.40.00 para móveis de cozinha), CFOP no estado/fora (5101/6101), CSOSN (102 no Simples), ambiente e token. O token só é gravado; a API devolve apenas `fiscal_token_configurado`.
2. No projeto (Financeiro/Gestor): complete o cliente (CPF/CNPJ, endereço, CEP) e clique em **Emitir NF-e**. Faltando dado, o ERP lista as pendências e não chama o emissor.
3. A nota volta `PROCESSANDO`; **Consultar** atualiza para `AUTORIZADA` (número, chave, DANFE, XML) ou `ERRO` (mensagem da SEFAZ). Com erro, a próxima tentativa usa nova referência.

> A emissão foi testada contra um emissor simulado. Antes de usar em produção: emita em **homologação** com o seu token e peça ao contador que valide NCM, CFOP e CSOSN. Montagem é serviço (NFS-e municipal) e não entra nesta nota.

**Conciliação bancária (OFX)**
- `POST /api/conciliacao/importar`: lê o extrato OFX (1.x SGML ou 2.x XML); movimentos já importados (mesmo `FITID`) são ignorados.
- Para cada movimento pendente, sugere contas em aberto do mesmo sentido e valor, com vencimento em até 7 dias.
- Confirmar baixa a conta com a data e o valor do banco. Sem conta correspondente: **lançar** (cria a conta já baixada, ex.: tarifa) ou **ignorar** (ex.: transferência entre contas).

## Indicadores do dono

`GET /api/indicadores?dias=90` (Administrador e Gestor), também a tela inicial desses perfis:

| Indicador | Cálculo |
|---|---|
| Vendas contratadas | Soma dos contratos registrados no período, nº de contratos e ticket médio; série dos últimos 6 meses |
| Margem de contribuição | Σ margem ÷ Σ receita das obras com produção concluída no período (DRE de cada obra) |
| Entregas no prazo | Entregues até a data combinada ÷ entregues com data combinada |
| Prazo | Dias do contrato à entrega; dias da liberação ao fim da produção |
| Gargalo | Setor com maior tempo de passagem medido (≥ 6 min); sem medição, a maior fila |
| Retrabalho | Assistências com causa interna ÷ entregas; custo de assistência sobre as vendas |
| Caixa e estoque | A receber e a pagar vencidos, materiais reservados sem saldo |

A data de entrega combinada se informa no projeto (`PATCH /api/projetos/{id}`) ou na importação do XML (`data_entrega`).

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
    deps.py            # usuário logado, empresa e checagem de funções
    funcoes.py         # catálogo de funções e modelo por perfil
    services/
      promob_xml.py    # leitor do XML do Promob
      importacao.py    # XML/CSV → árvore do projeto, cadastro automático de materiais
      engenharia.py    # consumo, pendências, liberação
      pcp.py           # OP, roteiro, apontamento, filas
      producao.py      # estorno, refugo/reposição, consulta de peças e baixas
      estoque.py       # reservas, MRP, recebimento, custo médio, inventário
      corte.py         # otimizador de plano de corte
      financeiro.py    # contrato, contas, DRE por obra, fluxo de caixa
      pos_obra.py      # montagem, checklist de entrega, assistência técnica
      indicadores.py   # painel do dono
      fiscal.py        # NF-e via Focus NFe
      conciliacao.py   # extrato OFX e pareamento com contas
      code128.py       # código de barras das etiquetas
      limite.py        # limite de tentativas (login, redefinição)
      email.py         # envio SMTP
  migrations/          # migrações do banco (Alembic)
  Dockerfile, docker-compose.yml, DEPLOY.md
    routers/           # API REST (cadastros, projetos, produção)
    static/index.html  # interface web (painel, projetos, OPs, apontamento, materiais)
  tests/               # fluxo completo, XML do Promob, gate, perfis, isolamento entre empresas
  exemplos/            # XML do Promob (anonimizado), CSV e materiais de demonstração
```

## Próximas camadas (roadmap)

1. **Auditoria**: registro de quem alterou o quê (preços, contratos, baixas), limite de tentativas em Redis para várias instâncias.
2. **Lados da fita e furação**: ler o XML de máquina do Promob (ou o relatório com bordas) para etiquetas com C1/C2/L1/L2 e programas CNC.
3. **Integração com a otimizadora** (Corte Certo, Optiplanning) e programas CNC por peça.
4. **Compras 2.0**: cotação entre fornecedores, envio do pedido por e-mail/WhatsApp, lotes e sobras de chapa reaproveitáveis.
5. **Pós-obra 2.0**: fotos da obra no checklist, assinatura do cliente na tela e reposição de peça com defeito na obra gerando OP.
6. **Fiscal 2.0**: cancelamento e carta de correção da NF-e, NFS-e da montagem, uma linha por ambiente na nota.
7. **Operação**: backup automático para nuvem, monitoramento de erros (Sentry) e domínio com e-mail transacional.
