"""Auditoria, registro de erros, log de acesso e Sentry (opcional).

Um único middleware observa cada requisição:
- toda alteração (POST/PUT/PATCH/DELETE em /api) vira uma linha de auditoria com
  quem fez, a ação em português, o registro afetado, o resultado e um resumo do que
  foi enviado (senhas e tokens nunca são gravados);
- todo erro inesperado vira um registro com código, que o usuário vê na tela e o
  suporte localiza no painel "Saúde do sistema" (e no Sentry, se SENTRY_DSN existir);
- cada requisição gera uma linha de log JSON (método, rota, status, tempo, empresa).
"""
import json
import logging
import os
import secrets
import time
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import engine
from .models import RegistroAuditoria, RegistroErro, Usuario
from .security import ler_token

log_acesso = logging.getLogger("erp.acesso")
log_erro = logging.getLogger("erp.erro")
SENTRY_ATIVO = False

ALTERA = {"POST", "PUT", "PATCH", "DELETE"}
SENSIVEIS = ("senha", "token", "secret", "segredo")
NAO_AUDITAR = {"/api/auth/esqueci", "/api/auth/redefinir"}  # o pedido em si não diz quem é; o efeito aparece no login

ACOES = {
    ("POST", "/api/auth/registrar"): "Cadastrou a empresa",
    ("POST", "/api/auth/login"): "Entrou no sistema",
    ("POST", "/api/auth/senha"): "Trocou a própria senha",
    ("POST", "/api/usuarios"): "Criou usuário",
    ("PATCH", "/api/usuarios/{usuario_id}"): "Alterou usuário (perfil, funções, situação ou senha)",
    ("PUT", "/api/empresas/atual"): "Alterou configurações da empresa",
    ("POST", "/api/clientes"): "Cadastrou cliente",
    ("PUT", "/api/clientes/{cliente_id}"): "Alterou cliente",
    ("POST", "/api/materiais"): "Cadastrou material",
    ("PUT", "/api/materiais/{material_id}"): "Alterou material (custo, medidas ou mínimo)",
    ("POST", "/api/centros"): "Criou setor da fábrica",
    ("PATCH", "/api/centros/{centro_id}"): "Alterou setor da fábrica",
    ("POST", "/api/projetos"): "Criou projeto",
    ("POST", "/api/projetos/importar-xml"): "Importou projeto do Promob (XML)",
    ("PATCH", "/api/projetos/{projeto_id}"): "Alterou projeto",
    ("POST", "/api/projetos/{projeto_id}/importar"): "Reimportou projeto",
    ("POST", "/api/projetos/{projeto_id}/liberar"): "Liberou projeto para a fábrica",
    ("POST", "/api/projetos/{projeto_id}/ops"): "Gerou OP",
    ("POST", "/api/projetos/{projeto_id}/contrato"): "Registrou contrato",
    ("POST", "/api/projetos/{projeto_id}/nfe"): "Emitiu NF-e",
    ("POST", "/api/ops/{op_id}/cancelar"): "Cancelou OP",
    ("POST", "/api/ops/{op_id}/voltar-programacao"): "Voltou OP para programação",
    ("POST", "/api/apontamentos"): "Deu baixa em peça",
    ("POST", "/api/apontamentos/estorno"): "Estornou baixa",
    ("POST", "/api/apontamentos/refugo"): "Refugou peça",
    ("POST", "/api/fornecedores"): "Cadastrou fornecedor",
    ("POST", "/api/estoque/inventario"): "Ajustou estoque (inventário)",
    ("POST", "/api/pedidos"): "Criou pedido de compra",
    ("POST", "/api/pedidos/{pedido_id}/enviar"): "Enviou pedido de compra",
    ("POST", "/api/pedidos/{pedido_id}/cancelar"): "Cancelou pedido de compra",
    ("POST", "/api/pedidos/{pedido_id}/receber"): "Recebeu pedido de compra",
    ("POST", "/api/lancamentos"): "Criou lançamento financeiro",
    ("POST", "/api/lancamentos/{lanc_id}/baixar"): "Baixou conta (pagamento/recebimento)",
    ("DELETE", "/api/lancamentos/{lanc_id}"): "Excluiu lançamento financeiro",
    ("POST", "/api/conciliacao/importar"): "Importou extrato bancário",
    ("POST", "/api/conciliacao/{mov_id}/conciliar"): "Conciliou movimento bancário",
    ("POST", "/api/conciliacao/{mov_id}/lancar"): "Lançou movimento bancário",
    ("POST", "/api/conciliacao/{mov_id}/ignorar"): "Ignorou movimento bancário",
    ("POST", "/api/notas/{nota_id}/consultar"): "Consultou NF-e no emissor",
    ("POST", "/api/montagens"): "Agendou montagem",
    ("POST", "/api/montagens/{montagem_id}/iniciar"): "Iniciou montagem",
    ("POST", "/api/montagens/{montagem_id}/checklist/{item_id}"): "Conferiu item do checklist",
    ("POST", "/api/montagens/{montagem_id}/concluir"): "Entregou a obra",
    ("POST", "/api/montagens/{montagem_id}/cancelar"): "Cancelou montagem",
    ("POST", "/api/chamados"): "Abriu chamado de assistência",
    ("PATCH", "/api/chamados/{chamado_id}"): "Alterou chamado",
    ("POST", "/api/chamados/{chamado_id}/resolver"): "Resolveu chamado",
    ("POST", "/api/lotes"): "Formou lote de produção",
    ("POST", "/api/lotes/{lote_id}/projetos"): "Incluiu projetos no lote",
    ("POST", "/api/lotes/{lote_id}/voltar-programacao"): "Voltou lote para programação",
    ("POST", "/api/expedicao/bipar"): "Embalou peça em caixa master",
    ("POST", "/api/expedicao/carregar"): "Carregou caixa no caminhão",
    ("POST", "/api/caixas/{caixa_id}/fechar"): "Fechou caixa master",
    ("POST", "/api/caixas/{caixa_id}/reabrir"): "Reabriu caixa master",
    ("POST", "/api/caixas/{caixa_id}/remover"): "Tirou peça da caixa master",
    ("POST", "/api/carrinhos"): "Cadastrou carrinhos",
    ("POST", "/api/carrinhos/conferir"): "Conferiu carrinho",
    ("POST", "/api/carrinhos/{carrinho_id}/bipar"): "Colocou peça no carrinho",
    ("POST", "/api/carrinhos/{carrinho_id}/remover"): "Tirou peça do carrinho",
    ("POST", "/api/carrinhos/{carrinho_id}/esvaziar"): "Esvaziou carrinho",
    ("POST", "/api/separacoes"): "Criou separação de peças",
    ("PATCH", "/api/separacoes/{classe_id}"): "Alterou separação de peças",
    ("POST", "/api/separacoes/reaplicar"): "Reaplicou regras de separação",
    ("PUT", "/api/pecas/{peca_id}/separacao"): "Marcou separação da peça",
}


def configurar_sentry() -> bool:
    """Ativa o Sentry só com SENTRY_DSN definido (e o pacote instalado). Nada de dado pessoal é enviado."""
    global SENTRY_ATIVO
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log_erro.warning("SENTRY_DSN definido, mas o pacote sentry-sdk não está instalado")
        return False
    sentry_sdk.init(dsn=dsn, environment=os.getenv("ERP_AMBIENTE", "producao"), release=os.getenv("APP_VERSAO"),
                    send_default_pii=False, traces_sample_rate=float(os.getenv("SENTRY_TRACES", "0")))
    SENTRY_ATIVO = True
    return True


def limpar(valor, profundidade: int = 0):
    """Tira senhas/tokens e corta textos longos antes de gravar na auditoria."""
    if profundidade > 4:
        return "…"
    if isinstance(valor, dict):
        return {k: ("***" if any(s in k.lower() for s in SENSIVEIS) else limpar(v, profundidade + 1))
                for k, v in list(valor.items())[:40]}
    if isinstance(valor, list):
        return [limpar(v, profundidade + 1) for v in valor[:30]] + (["…"] if len(valor) > 30 else [])
    if isinstance(valor, str) and len(valor) > 300:
        return valor[:300] + "…"
    return valor


def _quem(request: Request, corpo: dict | None, rota: str) -> tuple[int | None, int | None, str | None]:
    """Empresa, id e nome do usuário: do token; no login, do e-mail informado."""
    auth = request.headers.get("authorization", "")
    with Session(engine) as db:
        if auth.lower().startswith("bearer "):
            try:
                dados = ler_token(auth.split(" ", 1)[1])
                usuario = db.get(Usuario, int(dados["sub"]))
                return dados.get("emp"), int(dados["sub"]), usuario.nome if usuario else None
            except Exception:
                return None, None, None
        if rota in ("/api/auth/login", "/api/auth/registrar") and isinstance(corpo, dict) and corpo.get("email"):
            usuario = db.scalar(select(Usuario).where(Usuario.email == str(corpo["email"]).strip().lower()))
            if usuario is not None:
                return usuario.empresa_id, usuario.id, usuario.nome
    return None, None, None


def _gravar(registro) -> None:
    try:
        with Session(engine) as db:
            db.add(registro)
            db.commit()
    except Exception:  # registrar nunca derruba a requisição
        log_erro.exception("Falha ao gravar registro de %s", type(registro).__name__)


async def observar(request: Request, call_next):
    inicio = time.perf_counter()
    caminho, metodo = request.url.path, request.method
    altera = metodo in ALTERA and caminho.startswith("/api/") and caminho not in NAO_AUDITAR
    corpo = None
    if altera and "json" in request.headers.get("content-type", ""):
        bruto = await request.body()
        if len(bruto) <= 64_000:
            try:
                corpo = json.loads(bruto or b"null")
            except ValueError:
                corpo = None
    try:
        resposta = await call_next(request)
    except Exception as exc:  # erro inesperado: registra com código e responde sem expor detalhes
        codigo = secrets.token_hex(4).upper()
        rota = getattr(request.scope.get("route"), "path", caminho)
        empresa_id, usuario_id, _ = _quem(request, corpo, rota)
        _gravar(RegistroErro(id=codigo, empresa_id=empresa_id, usuario_id=usuario_id, metodo=metodo, rota=rota[:200],
                             tipo=type(exc).__name__[:120], mensagem=str(exc)[:500],
                             rastreio="".join(traceback.format_exception(exc))[-8000:]))
        log_erro.error(json.dumps({"erro": codigo, "metodo": metodo, "rota": rota, "tipo": type(exc).__name__,
                                   "empresa": empresa_id}, ensure_ascii=False))
        if SENTRY_ATIVO:
            import sentry_sdk
            with sentry_sdk.new_scope() as escopo:
                escopo.set_tag("erro_codigo", codigo)
                escopo.set_tag("empresa_id", empresa_id)
                sentry_sdk.capture_exception(exc)
        return JSONResponse({"detail": f"Erro interno no servidor (código {codigo}). A equipe técnica já foi avisada; "
                                       f"se precisar, informe esse código ao suporte.", "erro_id": codigo}, status_code=500)

    rota = getattr(request.scope.get("route"), "path", None)
    duracao = round((time.perf_counter() - inicio) * 1000, 1)
    if altera and rota:
        empresa_id, usuario_id, nome = _quem(request, corpo, rota)
        params = request.scope.get("path_params") or {}
        entidade = next(iter(params.values()), None)
        detalhes = limpar(corpo) if corpo is not None else ({"arquivo": "enviado"} if "multipart" in request.headers.get("content-type", "") else None)
        if params:
            detalhes = {**(detalhes if isinstance(detalhes, dict) else {"corpo": detalhes} if detalhes is not None else {}), **{f"_{k}": v for k, v in params.items()}}
        _gravar(RegistroAuditoria(
            empresa_id=empresa_id, usuario_id=usuario_id, usuario_nome=nome, metodo=metodo, rota=rota[:200],
            acao=ACOES.get((metodo, rota), f"{metodo} {rota}")[:160], entidade_id=str(entidade)[:40] if entidade else None,
            status=resposta.status_code, ip=(request.client.host if request.client else None), detalhes=detalhes))
    if caminho.startswith("/api/"):
        log_acesso.info(json.dumps({"metodo": metodo, "rota": rota or caminho, "status": resposta.status_code, "ms": duracao},
                                   ensure_ascii=False))
    return resposta
