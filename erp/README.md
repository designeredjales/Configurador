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
| **Lotes de produção** | Vários projetos liberados entram juntos na fábrica: um plano de corte para o lote inteiro, etiquetas com lote, cliente e ambiente, progresso por projeto e consulta das peças do lote |
| **Expedição (caixa master)** | Estação de embalagem por leitor: cada caixa é de um único cliente, obra e ambiente; peça de outro cliente é recusada, ambiente ou módulos demais sugerem outra caixa ou separar para depois; etiqueta de volume, carregamento por leitor e romaneio de carga |
| **Painel** | OPs abertas, em produção e atrasadas, fila de peças por centro, baixas do dia, progresso por OP |
| **Chão de fábrica** | Plano de corte guilhotinado por material (serra, refilo, veio) com desenho de cada chapa; etiquetas 100 × 50 mm com código de barras para imprimir no navegador ou em ZPL (Zebra); apontamento pela câmera do celular |
| **Estoque** | Saldo por movimentação, reserva automática na liberação do projeto, baixa automática na conclusão, inventário com ajuste pela diferença, custo médio ponderado |
| **Comercial** | Valor de tabela, pedido à fábrica, venda ao cliente, frete, montagem e condição de pagamento lidos do XML; contrato gera as parcelas a receber |
| **Financeiro** | Contas a receber e a pagar (a compra recebida vira conta a pagar no prazo do fornecedor), baixas, fluxo de caixa de 6 meses, **DRE por obra** (receita − impostos − material − custos diretos = margem de contribuição) |
| **Fiscal e banco** | NF-e de venda por emissor integrado (Focus NFe) com validação prévia e CFOP automático; conciliação bancária por extrato OFX com sugestão de pareamento |
| **Indicadores do dono** | Painel único: vendas contratadas, margem de contribuição ponderada, pontualidade, prazo contrato→entrega, gargalo da fábrica, retrabalho, caixa vencido e alertas |
| **Montagem e pós-obra** | Agenda de montagem (só inicia com a produção concluída), checklist de entrega com quem conferiu, entrega com nome de quem recebeu; assistência técnica com garantia, causa raiz e custo lançado no DRE da obra |
| **Compras (MRP)** | Sugestão de compra = reservado + mínimo − saldo − em pedido; pedido ao fornecedor, envio, recebimento parcial ou total, cancelamento |

## Pronto para produção

- **Auditoria:** quem alterou o quê, com ação em português, registro afetado, resultado (ok, recusado, erro) e resumo do que foi enviado, sem senhas ou tokens. Fica em Configurações → Registro de alterações, com filtro por período, usuário e ação.
- **Erros com código:** erro inesperado mostra ao usuário um código de 8 caracteres e fica registrado com rota e rastreio. O Sentry é opcional (`SENTRY_DSN`).
- **Backup diário:** serviço `backup` no docker-compose, com retenção, cópia opcional na nuvem (rclone) e script de restauração. O último backup aparece em Configurações → Saúde do sistema, com alerta depois de 26 horas.
- **Logs JSON** por requisição e `/api/saude` para monitor externo. Detalhes no [DEPLOY.md](DEPLOY.md).

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
| Comercial | Cadastro de clientes · Funil e negociação · Aprovar descontos e auditoria | Engenharia, Financeiro (clientes) · Vendedor (funil e clientes) |
| Produção | Ordens de produção (inclui lotes) · Apontamento · Estornar apontamento · Refugo e reposição | PCP (todas) · Operador (só apontamento) |
| Expedição | Caixa master e expedição | PCP |
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

## Lotes de produção

Na aba **Projetos → Lotes de produção**, marque os projetos liberados e forme o lote (`POST /api/lotes`). Cada projeto ganha a sua OP (o rastreio continua por cliente), mas a fábrica trabalha o lote inteiro:

- **Plano de corte do lote** (`GET /api/lotes/{id}/plano-corte`): junta as peças de todos os clientes por material, o que reduz chapas em relação a cortar cada obra separada. Cada peça no desenho mostra a obra a que pertence.
- **Etiquetas do lote** (`/etiquetas.html` e `/etiquetas.zpl`): a primeira linha de toda etiqueta diz de quem é a peça: `L<lote> <obra> · <cliente> · <ambiente>`. É ela que separa a expedição depois.
- Enquanto nenhuma peça foi apontada, dá para incluir projetos no lote; depois que a produção começa, o lote fecha.
- Progresso por projeto e "onde estão as peças" do lote na consulta de produção (`?lote_id=`).
- **Voltar para programação**, do lote inteiro (`POST /api/lotes/{id}/voltar-programacao`) ou projeto a projeto (`POST /api/ops/{id}/voltar-programacao`): a OP sai da fábrica e o projeto volta a LIBERADO, pronto para outro lote. Só vale para OP que a fábrica não tocou (sem baixa, refugo ou peça em caixa); no lote é tudo ou nada. A OP fica cancelada com o motivo e o número nunca é reaproveitado, então etiqueta velha impressa é recusada no leitor. Cancelar uma OP também devolve o projeto a LIBERADO.

## Carrinhos, conferência por setor e separação de peças

Tudo fica na aba **Configurações** (função "Usuários e configurações"), junto com os dados da empresa.

- **Carrinho no apontamento.** No modo *Carrinho*, cada peça bipada recebe a baixa do setor e entra no carrinho escolhido. Peça que já tinha a baixa só muda de carrinho. O carrinho mistura obras, como sai do corte de um lote, e por isso agrupa as peças por **lote, obra/cliente e separação**. Cada grupo imprime um **marcador** (HTML ou ZPL) que vai entre as peças.
- **Conferência do carrinho.** O setor seguinte bipa a etiqueta do carrinho (`98…`) e todas as peças que esperam por ele recebem a baixa de uma vez. O retorno mostra quantas peças foram baixadas, quantas já tinham baixa, quantas não passam pelo setor e quais ficaram bloqueadas, com o motivo.
- **Pular conferência.** Cada setor tem a opção *Conferência obrigatória*. Desmarcada, o setor não é bipado e some da fila do painel. A etapa fecha sozinha, com o operador "Sem conferência", quando a peça passa pelo setor seguinte. Se o setor sem conferência for o último da peça, ela termina junto com a última baixa.
- **Separação de peças (tupia, tamburato, peça que vira outra).** A classe da peça vem de **palavras-chave**, procuradas na descrição e no código da peça, no módulo e nas operações do Promob, ou é marcada à mão pelo PCP no detalhe da OP. Ela aparece na etiqueta (`SEPARAR TUPIA`), dispara o aviso **SEPARAR** no apontamento e separa os grupos do carrinho. A classe pode ainda:
  - colocar um setor próprio no roteiro, com um setor de regra *Só peças separadas*;
  - impedir a caixa master (*Vai para caixa master* desmarcado), porque a peça vira outra peça.
- *Reaplicar regras* reclassifica os projetos que ainda não foram para a fábrica. A marcação manual nunca é sobrescrita.

## Expedição por caixa master

A aba **Expedição** é a estação de embalagem: o operador só bipa.

| Situação ao bipar | O que o sistema faz |
|---|---|
| Primeira peça (sem caixa ativa) | Abre uma caixa master daquela obra e ambiente; se faltava só a EMBALAGEM, dá essa baixa sozinho |
| Peça da mesma obra, mesmo ambiente | Entra na caixa |
| **Peça de outro cliente** | **Recusa** (alerta vermelho e bipe grave). A peça não recebe baixa |
| Peça de outra obra do mesmo cliente | Recusa: entregas diferentes, caixas diferentes |
| Mesmo cliente, outro ambiente, ou módulo além do limite da caixa (padrão 3, configurável) | Alerta laranja com duas saídas: **abrir nova caixa master com esta peça** ou **separar para bipar depois** |
| Peça que ainda não passou pela fábrica, refugada ou já embalada | Recusa, dizendo o que falta ou em que caixa ela está |
| Etiqueta de uma caixa | Volta para aquela caixa (se aberta) |

Ao fechar, sai a **etiqueta de volume** (caixa, volume X de Y, cliente, obra, ambiente, módulos e código de barras). No modo **Carregar caminhão** o leitor aceita só etiquetas de caixa fechada, uma vez cada. O **romaneio de carga** lista cada volume com as peças dentro e avisa o que ficou fora. Peça embalada não pode ser estornada; peça refugada sai da caixa e a reposição entra quando ficar pronta.

## Compras e estoque

O estoque é a soma das movimentações de cada material, na unidade do cadastro (chapa por chapa `CH` ou por `M2`, fita em `M`, ferragem em `UN`).

1. **Liberar o projeto** reserva o consumo calculado do XML, com a perda da empresa. Chapa cadastrada por chapa (com medidas) é reservada em fração de chapa.
2. **Sugestão de compra** (`GET /api/estoque`): `reservado + estoque mínimo − saldo − em pedido`, arredondada para cima nos itens contáveis.
3. **Pedido** (`POST /api/pedidos`) → **enviar** → **receber** (parcial ou total). O recebimento gera a entrada e recalcula o custo médio ponderado do material.
4. **Projeto concluído** (última baixa da última OP): a reserva vira saída de estoque, ao custo médio, referenciada ao projeto.
5. **Inventário** (`POST /api/estoque/inventario`): informa a quantidade contada e o ERP lança o ajuste pela diferença, com usuário e observação.

Saldo negativo é permitido e aparece em vermelho: indica consumo sem entrada registrada, ou seja, recebimento que não foi lançado.

## Comercial: funil, negociação e auditoria da venda

O orçamento continua no Promob. O ERP recebe o resultado e conduz a negociação dentro da política definida pelo administrador.

- **Funil (CRM):** oportunidades em colunas por etapa (configuráveis), com cliente, parceiro, vendedor, valor, próxima ação e data. O vendedor (perfil **VENDEDOR**) vê só as suas e as sem dono; quem tem a função *Aprovar descontos e auditoria* vê todas.
- **Versões da proposta:** cada XML do Promob enviado vira uma versão (ambientes, módulos, m² de chapa, tabela, pedido à fábrica, frete e montagem). Renders (JPG/PNG/WebP) e os links do 3D/VR (`galeria3d.promob.com`) e do 2020 Manager ficam na oportunidade.
- **Negociação com alçadas:** desconto e condição de pagamento (à vista, entrada + parcelas, com ajuste de preço). O ERP calcula preço final, impostos, RT do parceiro, comissão do vendedor, custo e margem. Acima do limite do vendedor ou abaixo da margem mínima vai para o gerente; acima do limite do gerente, para o administrador. A aprovação pendente bloqueia a proposta.
- **Proposta ao cliente:** link público (`/p/{token}`) com renders, ambientes, valor e condição, sem custos nem margens, com validade e aceite eletrônico (nome, data e IP).
- **Fechar a venda exige o XML:** o fechamento cria o projeto a partir do XML da versão aceita, registra o contrato e as parcelas e lança RT e comissão a pagar junto com cada parcela.
- **Auditoria vendido × produção:** quando a engenharia importa o XML executivo, o ERP compara com o que foi vendido: valor negociado, módulos (incluindo repetidos), peças, m² de chapa e pedido à fábrica. Divergência acima do limite da política trava a liberação até alguém com a função de aprovação dar ciência.
- **Promob Prices:** com o token da conta (gravado só pela tela, nunca exibido), o ERP baixa a tabela ativa (`prices-api.promob.com`) e confere os itens do orçamento.
- **Configurações do comercial** (administrador): limites de desconto, margem mínima, comissão, limite de divergência, validade da proposta, etapas do funil, condições de pagamento, parceiros com % de RT e o token do Prices.

## Setup da base

Cada fábrica é uma base com a sua parametrização. Em **Configurações → Setup da base** o administrador:

- **exporta** toda a parametrização num arquivo JSON: parâmetros de produção, padrões fiscais, setores e regras do roteiro, separação de peças, política comercial, integração Promob Prices (endereço, tabela e colunas), parceiros e metas da gestão à vista. **Tokens e senhas nunca entram no arquivo**;
- **aplica** um arquivo personalizado ou um **modelo pronto** (`app/setups/*.json`: "Marcenaria sob medida" e "Indústria com tupia e tamburato"). Antes de gravar, o ERP mostra a prévia do que muda, seção por seção, e só aplica as seções marcadas. Setores, separações e parceiros são casados pelo código ou nome; nada é apagado.

Para criar um modelo próprio da consultoria, exporte de uma base bem configurada, ajuste `nome` e `descricao` e salve em `app/setups/`. API: `GET /api/setup/exportar`, `GET /api/setup/modelos`, `POST /api/setup/aplicar` (`{"setup" | "modelo", "secoes", "simular"}`).

### Integração Promob Prices por base

Endereço da API, tabela a usar (vazio = a ativa) e nome das colunas do CSV (vazio = detecção automática) fazem parte do setup. O botão **Ver formatos da conta** (`POST /api/comercial/prices/diagnostico`) lista as tabelas da conta e mostra o cabeçalho e as primeiras linhas do CSV, sem gravar nada: é como se acerta o mapeamento de cada base. O token só viaja para endereços `https` em domínios `promob.com`.

## Gestão à vista

Aba **Gestão à vista** (função *Indicadores do dono*), feita para a reunião diária e para a TV da fábrica (**Modo TV**: tela cheia, sem menus, atualiza a cada minuto).

- **KPIs do mês em m² e em valor** contra as metas da base: vendido, m² vendidos, m² produzidos, preço e custo por m², margem prevista, entregas no prazo, refugo e conversão comercial. Metas acumuladas são cobradas na proporção dos dias úteis já passados.
- **Ritmo × takt (Toyota):** m² produzidos por dia nos últimos 14 dias contra o takt da meta, projeção do mês e quanto é preciso produzir por dia útil para fechar.
- **Restrição (Teoria das Restrições):** fila e vazão de cada setor; o setor com mais dias de fila é a restrição que dita o ritmo da fábrica.
- **Pulmão das obras:** prazo consumido × trabalho apontado, em verde, amarelo, vermelho e preto (vencida).
- **Kanban do fluxo da obra** (negociação, engenharia, liberado, produção, expedição, entregue) com **limite de WIP** por coluna.
- **Andon:** obras vencidas ou no vermelho, restrição com fila longa, WIP estourado, refugos e estornos por setor, chamados abertos, descontos aguardando aprovação e auditorias de venda travando a liberação.

Metas, limites de WIP, dias úteis e horas do turno ficam no setup da base (`GET/PUT /api/gestao/config`); o painel é `GET /api/gestao/painel`.

## De-para Promob → estoque

Em **Materiais → De-para**, cada código da biblioteca do Promob aponta para o material que a fábrica compra e estoca, com **fator de conversão** quando a unidade de compra é outra (dobradiça por unidade no Promob, caixa com 100 no estoque: fator 0,01). A importação do XML já troca o código e a quantidade; **Reaplicar** troca nos projetos que ainda estão na engenharia. A tela lista os códigos em uso nos projetos abertos (sem cadastro, mesmo código ou vinculado) com **sugestões** por semelhança de código e descrição. Com **criar materiais automaticamente** desligado (setup da base), código sem de-para vira pendência de engenharia em vez de material novo. O de-para viaja no setup, casado pelo código do material na base de destino.

## Custo-hora e mão de obra padrão

Em **Configurações → Capacidade, tempos padrão e custo-hora**, cada setor recebe pessoas, horas por dia, eficiência, custo mensal (folha, encargos e rateio) e tempo padrão (minutos por peça + minutos por m²). **Custo-hora** = custo mensal ÷ (pessoas × horas × eficiência × dias úteis). A **mão de obra padrão** de cada obra soma o roteiro de cada peça (as mesmas regras da OP) × o custo-hora: entra no **DRE da obra** e no **custo da proposta comercial**, por setor.

## Sequenciamento pela restrição (tambor-pulmão-corda)

No **Painel PCP**, a sequência mostra o **tambor** (setor com mais dias de carga em horas, ou fixado no setup), encaixa as obras pela data de entrega na capacidade dele, calcula a **saída prevista** (tambor + pulmão), a **folga** e a **corda** (até quando liberar cada obra). **Aplicar prioridades** ajusta as OPs; **Formar lote** junta as próximas obras liberadas que cabem em N dias de tambor. Sem tempos cadastrados, a carga é em m² e a capacidade vem da vazão dos últimos 7 dias. Pulmão e tambor ficam no setup (gestão à vista).

## Planejamento e controladoria (DRE gerencial)

Aba **Planejamento** (funções *Planejamento e controladoria* e *Aprovar despesas*).

- **Centros de custo** (administrativo, produtivo, comercial, estrutura), com responsável e, nos produtivos, o setor da fábrica ligado. Lançamentos recebem centro e **conta gerencial** (receita, impostos, material, comissões, frete/montagem, pessoal, ocupação, administrativas, comercial, manutenção, financeiro, investimentos); sem conta, vale a da categoria.
- **Verbas**: teto de despesa por centro, conta e mês. Edição em grade, ou geração pela média realizada dos últimos meses com reajuste.
- **Fluxo de aprovação**: despesa que estoura a verba do centro vai para quem aprova despesas; despesa acima da alçada pode ser liberada pelo responsável do centro (nunca a própria). Pendente ou recusada não pode ser baixada. Regras por base: alçada, centro obrigatório, centro sem verba pede aprovação.
- **Consolidação agendada**: todo dia, no horário das regras, o ERP recalcula os meses recentes em dois regimes: **competência** (operacional: receita das obras concluídas, impostos pela alíquota, material consumido, custos da obra no mês da conclusão, despesas pelo vencimento) e **caixa** (bancário: recebido e pago, mais o extrato ainda não conciliado). Também sob demanda ("Consolidar agora"), com histórico de execuções.
- **Histórico mesclado**: importe o DRE de antes do ERP (`mes;conta;valor;regime;centro`). Meses sem dados do sistema usam o histórico, marcado com **H**.
- **DRE gerencial realizado × previsto** por mês, empresa inteira ou por centro, com margem de contribuição, EBITDA, resultado e geração de caixa; o previsto vem das verbas e do cenário principal. Exportação em CSV.
- **Relatório por centro**: verba, realizado, em aberto, saldo e consumo, por conta; CSV.
- **Cenários de planejamento** (modelo "Ponto de equilíbrio 2.0" da consultoria): imóvel locado ou próprio, investimentos, retorno esperado sobre o capital, pessoal com encargos, fixos (resumo ou detalhado), crescimento (marketing, reserva de caixa, reinvestimento, depreciação), despesa variável, RT, comissões, imposto e lucro desejado. Resultado: venda necessária, faturamento de equilíbrio (total e por funcionário), **meta**, composição da meta, **markup divisor**, markup final e o **markup a cadastrar no Promob**, custo-hora de máquina e custo da ociosidade, projeção mensal com sazonalidade. Simulação ao vivo, vários cenários, **comparação com o histórico real** (e "usar o histórico nas premissas"), cenário principal e **aplicar a meta na gestão à vista**.
- **Custo dos setores pelo realizado**: centros produtivos ligados a um setor atualizam o custo mensal do setor (e o custo-hora) com a média das despesas realizadas.
- Tudo entra no **setup da base** (centros, regras, agenda e cenário principal).

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
      lotes.py         # formação e controle de lotes de produção
      expedicao.py     # caixa master, carregamento e romaneio
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

1. **Escala**: limite de tentativas de login em Redis para rodar várias instâncias; retenção configurável da auditoria.
2. **Lados da fita e furação**: ler o XML de máquina do Promob (ou o relatório com bordas) para etiquetas com C1/C2/L1/L2 e programas CNC.
3. **Integração com a otimizadora** (Corte Certo, Optiplanning) e programas CNC por peça.
4. **Compras 2.0**: cotação entre fornecedores, envio do pedido por e-mail/WhatsApp, lotes e sobras de chapa reaproveitáveis.
5. **Pós-obra 2.0**: fotos da obra no checklist, assinatura do cliente na tela e reposição de peça com defeito na obra gerando OP.
6. **Fiscal 2.0**: cancelamento e carta de correção da NF-e, NFS-e da montagem, uma linha por ambiente na nota.
7. **Operação**: backup automático para nuvem, monitoramento de erros (Sentry) e domínio com e-mail transacional.
