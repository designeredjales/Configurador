# Configurador Externo: Gerenciador de Setups Promob

> Este repositório também abriga o **ERP Moveleiro** (Engenharia + PCP), na pasta [`erp/`](erp/README.md).

Código-fonte do `ConfiguradorExterno.exe` ("Gerenciador de Setups Promob - ProTech (Filtro Avançado)").
Ele foi reconstruído a partir do executável original, um app Python 3.14 + Tkinter empacotado com PyInstaller.
Compilado com Python 3.14, este `editor_promob.py` gera um bytecode **idêntico** ao do executável, instrução por instrução, nos 83 blocos de código.

## O que o app faz

Ele edita os setups (engenharias) de atributos do Promob direto nos arquivos XML da pasta `System`:

| Arquivo | Uso |
|---|---|
| `System/Atributos/sugestaoctrl.attributes` | Definição das variáveis (ID, nome, descrição, default, valores propostos, categoria) |
| `System/Atributos/property.category` (ou `property.xml`) | Árvore de categorias, com imagens |
| `System/Config/Attributes/index.definitions` | Lista de setups (ID, descrição, arquivo) |
| `System/Config/Attributes/<ID>.attributes` | Valores de cada setup |

Funções:
- **Selecionar a pasta `System`**: carrega as variáveis, as categorias e os setups.
- **Setup ativo**: troca o setup pelo combobox. Editar o texto do combobox e apertar Enter renomeia o setup.
- **Novo / Renomear / Deletar setup**: o novo setup pode copiar os dados do setup ativo, e o `index.definitions` é atualizado.
- **Árvore de categorias**: mostra as variáveis da categoria escolhida e das subcategorias. O botão abre a imagem da categoria.
- **Filtros combinados** (ID, Nome, Categoria, Valor, Descrição): use `+` para exigir vários termos (ex.: `porta+folga`).
- **Agente Global**: busca em linguagem natural, com relevância (categoria vale 3, nome 2, descrição 1) e sem considerar acentos.
- **Edição inline**: duplo clique na célula Valor. Tab e Shift+Tab passam para a próxima ou a anterior. Variáveis com `ONLYPROPOSEDVALUES="Y"` abrem um combobox.
- **Edição em lote**: aplica um valor às linhas selecionadas.
- **Aplicar em múltiplos setups**: grava só as variáveis selecionadas nos `.attributes` dos setups marcados, sem tocar no resto.
- **Salvar**: reescreve o `.attributes` do setup ativo.
- **Ctrl+C**: copia o nome do setup ou `ID<TAB>Nome<TAB>Descrição` da variável.

## Executar

```bash
pip install -r requirements.txt   # opcional (imagens JPG)
python editor_promob.py
```

## Gerar o .exe (Windows)

```bat
build_exe.bat
```

O executável sai em `dist\ConfiguradorExterno.exe`.

> Faça backup da pasta `System` antes de usar: o app grava direto nos arquivos do Promob.
