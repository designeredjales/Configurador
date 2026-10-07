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

**Backup diário do banco** (agende no cron do servidor e copie para fora dele):
```bash
docker compose exec -T banco pg_dump -U erp erp | gzip > backup_$(date +%F).sql.gz
```

**Atualizar a versão:** `git pull && docker compose up -d --build`. As migrações novas rodam sozinhas na subida.

## Opção B: plataforma gerenciada (Render, Railway, Fly.io)

1. Crie um PostgreSQL gerenciado e anote a URL de conexão.
2. Crie um serviço web a partir do repositório, com raiz em `erp/` e o `Dockerfile`.
3. Variáveis de ambiente: `DATABASE_URL` (no formato `postgresql+psycopg://usuario:senha@host:5432/banco`), `ERP_SECRET`, `ERP_URL_PUBLICA` e, se quiser e-mail, as `SMTP_*`.
4. Verificação de saúde: `GET /api/saude`. A plataforma fornece o HTTPS.

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

## Limites conhecidos desta versão

- **Um processo por instalação.** O limite de tentativas de login fica em memória. Para rodar várias instâncias atrás de um balanceador, troque `app/services/limite.py` por Redis.
- **NF-e:** emita primeiro em homologação e valide NCM, CFOP e CSOSN com o contador antes de mudar para produção.
