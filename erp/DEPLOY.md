# Colocar o ERP Moveleiro no ar

O ERP é uma aplicação Python (FastAPI) com PostgreSQL. Escolha um dos caminhos.

## Opção A: servidor próprio (VPS) com Docker — recomendada

### Do que você precisa

- **VPS Ubuntu 24.04 (ou 22.04)** com acesso root por SSH. Para começar: 2 vCPU, 4 GB de RAM e 50 GB de disco (Hostinger KVM 2, Hetzner CPX21, Contabo VPS S, DigitalOcean 4 GB). Com 2 GB de RAM funciona: o script cria swap.
- **Um domínio** (ex.: `erp.suaempresa.com.br`) com um registro **A** apontando para o IP da VPS.
- **Um e-mail** para os avisos do certificado HTTPS.
- Se o repositório for privado, um **token de leitura** do GitHub (fine-grained, só `Contents: read` neste repositório). Ele é usado só no clone e não fica gravado no servidor.

### Instalação em um comando

No servidor, como root:

```bash
curl -fsSL https://raw.githubusercontent.com/designeredjales/Configurador/claude/adoring-heisenberg-kzz1c6/erp/scripts/provisionar.sh -o provisionar.sh
DOMINIO=erp.suaempresa.com.br EMAIL=ti@suaempresa.com.br RAMO=claude/adoring-heisenberg-kzz1c6 bash provisionar.sh
# repositório privado: acrescente GIT_TOKEN=github_pat_... antes do bash (e baixe o script com o mesmo token)
```

Depois que o PR for mesclado, use `RAMO=main` (o padrão). O script, em 7 etapas:

1. atualiza o sistema, liga as **atualizações de segurança automáticas**, o **fail2ban** e o **firewall** (só SSH, 80 e 443), cria swap em máquina pequena e ajusta o fuso;
2. instala o **Docker**;
3. baixa o ERP em `/opt/erp-moveleiro`;
4. cria o `.env` com **senha do banco e segredo gerados** (permissão 600; o `.env` nunca é sobrescrito numa segunda execução);
5. confere se o DNS do domínio aponta para a VPS;
6. sobe **banco, ERP, backup e Caddy** (HTTPS automático com Let's Encrypt, HTTP→HTTPS, HSTS, compressão). O ERP fica só em `127.0.0.1` e é alcançado pelo proxy;
7. confere se o ERP e o HTTPS responderam.

Ao final, acesse `https://seu-dominio` e cadastre a empresa: o primeiro usuário vira administrador. Em seguida aplique o **setup da base** (Configurações) e informe os tokens pela tela.

### Operação do dia a dia (na pasta `/opt/erp-moveleiro/erp`)

| Tarefa | Comando |
|---|---|
| Conferir tudo (contêineres, ERP, HTTPS e validade do certificado, último backup, disco, memória) | `bash scripts/verificar.sh` |
| **Atualizar a versão** | `bash scripts/atualizar.sh` |
| Backup agora (banco + renders) | `docker compose exec backup bash /scripts/backup.sh agora` |
| Logs | `docker compose logs -f erp` (ou `caddy`, `backup`) |
| Reiniciar | `docker compose restart erp` |

`atualizar.sh` faz **backup antes**, baixa e constrói a versão nova e confere se ela respondeu. **Se o build falhar, nada muda**; **se a versão nova não subir em 3 minutos, o código e a imagem anteriores voltam sozinhos**. As 3 imagens mais recentes ficam guardadas para voltar sem rebuild. Migrações de banco não são desfeitas automaticamente: se a volta acontecer depois de uma migração nova, restaure o backup do passo 1 (o nome aparece na tela). Durante a troca, o Caddy segura as requisições por até 60 s em vez de devolver erro.

### Segurança recomendada depois da instalação

- Entre por **chave SSH** e desligue o login por senha (`PasswordAuthentication no` em `/etc/ssh/sshd_config`, depois `systemctl restart ssh`). Só faça isso depois de testar a chave numa segunda janela.
- Guarde o `.env` num cofre de senhas: sem ele, os backups não sobem em outra máquina.
- Ligue a **cópia do backup na nuvem** (`RCLONE_DESTINO`) e um **monitor externo** em `https://seu-dominio/api/saude` (UptimeRobot, Better Stack).
- Libere no provedor só as portas 22, 80 e 443 (o firewall da VPS já faz isso).

### Instalação manual (sem o script)

1. Instale o Docker e clone o repositório.
2. Em `erp/`, copie `.env.exemplo` para `.env` e preencha `POSTGRES_PASSWORD`, `ERP_SECRET` (`openssl rand -base64 48`), `ERP_URL_PUBLICA`, `ERP_DOMINIO`, `ACME_EMAIL`, `ERP_BIND=127.0.0.1`, `COMPOSE_FILE=docker-compose.yml:docker-compose.vps.yml` e `COMPOSE_PROJECT_NAME=erp`.
3. `docker compose up -d --build`. Na subida, o contêiner aplica as migrações e só então inicia o servidor.

## Backup automático

O serviço `backup` do `docker-compose.yml` já vem ligado:

- faz um backup assim que sobe e depois **todo dia às `BACKUP_HORA`** (padrão 03h, no fuso `TZ`): o banco (`erp_*.dump`) e os renders das propostas (`erp_arquivos_*.tar.gz`);
- guarda **`BACKUP_DIAS` dias** (padrão 14) no volume `backups`, em arquivos `erp_AAAAMMDD_HHMM.dump`;
- com `RCLONE_DESTINO` preenchido, **envia cada backup para a nuvem** (S3, Backblaze B2, Google Drive, Dropbox... qualquer destino do rclone, configurado pelas variáveis `RCLONE_CONFIG_*` no `.env`). Backup que fica só no próprio servidor não protege contra a perda do servidor: ligue a nuvem.

O painel **Configurações → Saúde do sistema** mostra o último backup e acende alerta se ele tiver mais de 26 horas.

```bash
docker compose exec backup bash /scripts/backup.sh agora         # backup manual
docker compose exec backup ls -lh /backups                       # listar
docker compose stop erp                                          # restaurar (apaga os dados atuais!)
docker compose exec backup bash /scripts/restaurar.sh erp_20261007_0300.dump
docker compose start erp
# renders do mesmo horário (o restaurar.sh mostra o comando exato):
docker run --rm -v erp_arquivos:/arquivos -v erp_backups:/backups:ro postgres:16 tar -xzf /backups/erp_arquivos_20261007_0300.tar.gz -C /arquivos
```

Teste a restauração uma vez por mês num banco à parte: backup que nunca foi restaurado não é backup.

## Auditoria e monitoramento

- **Auditoria:** toda alteração (criar, alterar, liberar, cancelar, baixar, apontar, embalar, login...) fica registrada com quem fez, quando, a ação, o registro afetado, o resultado (ok, recusado ou erro) e um resumo do que foi enviado. Senhas e tokens nunca são gravados. O administrador consulta em **Configurações → Registro de alterações**.
- **Erros:** todo erro inesperado recebe um código (ex.: `7F3A9C21`), que o usuário vê na tela. O suporte localiza o código em **Saúde do sistema**, com rota, horário e tipo do erro. O rastreio completo fica no banco (tabela `erros_sistema`).
- **Sentry (opcional):** com `SENTRY_DSN` definido, cada erro também vai para o Sentry com o mesmo código, sem dados pessoais. O Sentry avisa por e-mail ou Slack.
- **Logs:** cada requisição gera uma linha JSON (método, rota, status, tempo em ms) no log do contêiner: `docker compose logs -f erp`.
- **Disponibilidade:** `GET /api/saude` responde só quando a aplicação e o banco estão de pé. Aponte para ela um monitor externo gratuito (UptimeRobot, Better Stack) para receber alerta se o ERP cair.

## Integração com o Promob Prices

O módulo Comercial puxa a tabela de preços ativa da conta Promob para conferir margens.

- O **token da conta** é informado pelo administrador em **Comercial → Configurações do comercial**. Ele fica só no banco, nunca volta para a tela nem aparece na auditoria. Não coloque o token em `.env`, código ou chamados.
- O servidor precisa de saída HTTPS para `prices-api.promob.com` e para o armazenamento de onde a Promob serve o `.zip` da tabela. Num VPS comum isso já é liberado; em rede corporativa com firewall, libere esses domínios.
- Token recusado (401/403) aparece como mensagem na tela; gere um novo na conta Promob e grave de novo.
- Antes da primeira sincronização de uma base nova, use **Ver formatos da conta** para conferir a tabela e as colunas do CSV e acerte o mapeamento no setup.

## Implantar uma base nova

1. Cadastre a empresa (primeiro acesso) e entre como administrador.
2. Em **Configurações → Setup da base**, aplique o modelo mais próximo ou o arquivo de setup preparado para o cliente; confira a prévia e aplique.
3. Informe os segredos pela tela, nunca no arquivo: token do Promob Prices (Comercial) e token fiscal (Configurações da empresa).
4. Cadastre os usuários e ajuste as funções de cada login.

Os renders enviados nas negociações ficam no volume `arquivos`. O backup do banco **não** inclui esse volume: inclua `arquivos` na sua cópia para a nuvem se quiser preservá-los.

## Consolidação financeira agendada

O próprio servidor consolida o DRE gerencial de cada empresa uma vez por dia, no horário definido em **Planejamento → Regras** (fuso `TZ`). Com mais de uma instância do ERP, a consolidação não roda em dobro (uma execução agendada por empresa e dia). Para desligar o agendador interno e usar cron no lugar: `ERP_AGENDADOR=0` e, no cron do servidor, `docker compose exec erp python -m app.consolidar` uma vez por hora.

## Opção B: plataforma gerenciada (Render, Railway, Fly.io)

1. Crie um PostgreSQL gerenciado e anote a URL de conexão.
2. Crie um serviço web a partir do repositório, com raiz em `erp/` e o `Dockerfile`.
3. Variáveis de ambiente: `DATABASE_URL` (no formato `postgresql+psycopg://usuario:senha@host:5432/banco`), `ERP_SECRET`, `ERP_URL_PUBLICA` e, se quiser e-mail, as `SMTP_*`.
4. Verificação de saúde: `GET /api/saude`. A plataforma fornece o HTTPS.
5. Backup: ative o backup automático do PostgreSQL gerenciado (todas essas plataformas oferecem) e, se quiser alertas de erro, defina `SENTRY_DSN`.

## Variáveis de ambiente

| Variável | Obrigatória | Uso |
|---|---|---|
| `DATABASE_URL` | sim | Banco PostgreSQL (`postgresql+psycopg://...`) |
| `ERP_SECRET` | sim (≥ 32 caracteres) | Assina os logins. Trocar derruba todas as sessões |
| `ERP_AMBIENTE` | já vem `producao` na imagem | Em produção, recusa subir sem `ERP_SECRET` forte |
| `ERP_CRIAR_TABELAS` | já vem `0` na imagem | `0` = schema só por migração |
| `ERP_URL_PUBLICA` | recomendada | Base do link de redefinição de senha |
| `ERP_SESSAO_HORAS` | não (12) | Validade do login |
| `SMTP_HOST`, `SMTP_PORTA`, `SMTP_USUARIO`, `SMTP_SENHA`, `SMTP_REMETENTE` | não | E-mail de redefinição de senha |
| `SENTRY_DSN` | não | Envia os erros para o Sentry |
| `APP_VERSAO` | não | Versão exibida no painel (ex.: commit) |
| `ERP_AGENDADOR` | não (1) | `0` desliga a consolidação diária interna (use cron com `python -m app.consolidar`) |
| `ERP_PASTA_ARQUIVOS` | já vem no compose (`/app/arquivos`) | Renders e imagens das propostas. Em plataforma gerenciada, use um disco persistente |
| `ERP_PASTA_BACKUP` | já vem no compose | Pasta lida pelo painel para mostrar o último backup |
| `BACKUP_HORA`, `BACKUP_DIAS`, `TZ` | não (03, 14, America/Sao_Paulo) | Agenda e retenção do backup |
| `RCLONE_DESTINO`, `RCLONE_CONFIG_*` | não | Cópia do backup na nuvem |

## Limites conhecidos desta versão

- **Um processo por instalação.** O limite de tentativas de login fica em memória. Para rodar várias instâncias atrás de um balanceador, troque `app/services/limite.py` por Redis.
- **NF-e:** emita primeiro em homologação e valide NCM, CFOP e CSOSN com o contador antes de mudar para produção.
