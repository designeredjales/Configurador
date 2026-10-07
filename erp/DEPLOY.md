# Colocar o ERP Moveleiro no ar

O ERP é uma aplicação Python (FastAPI) com PostgreSQL. Escolha um dos caminhos.

## Opção A: servidor próprio (VPS) com Docker — recomendada

Uma VPS de 2 GB de RAM (Hostinger, Contabo, DigitalOcean, AWS Lightsail) atende dezenas de usuários.

1. No servidor, instale o Docker e clone o repositório.
2. Na pasta `erp/`, copie `.env.exemplo` para `.env` e preencha:
   - `POSTGRES_PASSWORD`: senha forte do banco;
   - `ERP_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`;
   - `ERP_URL_PUBLICA`: o endereço com HTTPS (ex.: `https://erp.suaempresa.com.br`);
   - SMTP (opcional, para "Esqueci a senha"): servidor, porta, usuário e senha do seu e-mail transacional.
3. `docker compose up -d --build`. Na subida, o contêiner aplica as migrações (`alembic upgrade head`) e só então inicia o servidor.
4. **HTTPS é obrigatório** (senhas e tokens trafegam pela rede). Coloque na frente um proxy com certificado automático, por exemplo o Caddy:
   ```
   erp.suaempresa.com.br {
       reverse_proxy localhost:8000
   }
   ```
5. Acesse o endereço e cadastre a empresa. O primeiro usuário vira administrador.

**Atualizar a versão:** `APP_VERSAO=$(git rev-parse --short HEAD) docker compose up -d --build` depois do `git pull`. As migrações novas rodam sozinhas na subida.

## Backup automático

O serviço `backup` do `docker-compose.yml` já vem ligado:

- faz um backup assim que sobe e depois **todo dia às `BACKUP_HORA`** (padrão 03h, no fuso `TZ`);
- guarda **`BACKUP_DIAS` dias** (padrão 14) no volume `backups`, em arquivos `erp_AAAAMMDD_HHMM.dump`;
- com `RCLONE_DESTINO` preenchido, **envia cada backup para a nuvem** (S3, Backblaze B2, Google Drive, Dropbox... qualquer destino do rclone, configurado pelas variáveis `RCLONE_CONFIG_*` no `.env`). Backup que fica só no próprio servidor não protege contra a perda do servidor: ligue a nuvem.

O painel **Configurações → Saúde do sistema** mostra o último backup e acende alerta se ele tiver mais de 26 horas.

```bash
docker compose exec backup bash /scripts/backup.sh agora         # backup manual
docker compose exec backup ls -lh /backups                       # listar
docker compose stop erp                                          # restaurar (apaga os dados atuais!)
docker compose exec backup bash /scripts/restaurar.sh erp_20261007_0300.dump
docker compose start erp
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
| `ERP_PASTA_ARQUIVOS` | já vem no compose (`/app/arquivos`) | Renders e imagens das propostas. Em plataforma gerenciada, use um disco persistente |
| `ERP_PASTA_BACKUP` | já vem no compose | Pasta lida pelo painel para mostrar o último backup |
| `BACKUP_HORA`, `BACKUP_DIAS`, `TZ` | não (03, 14, America/Sao_Paulo) | Agenda e retenção do backup |
| `RCLONE_DESTINO`, `RCLONE_CONFIG_*` | não | Cópia do backup na nuvem |

## Limites conhecidos desta versão

- **Um processo por instalação.** O limite de tentativas de login fica em memória. Para rodar várias instâncias atrás de um balanceador, troque `app/services/limite.py` por Redis.
- **NF-e:** emita primeiro em homologação e valide NCM, CFOP e CSOSN com o contador antes de mudar para produção.
