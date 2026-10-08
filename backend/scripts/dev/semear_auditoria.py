"""Semeia um banco Fluxa com volume realista para reproduzir a auditoria.

Ferramenta de desenvolvimento, não artefato do produto: os DADOS ficam fora do
repositório (`~/_fluxa_dev/fluxa.db`), o script fica aqui para não se perder
quando o ambiente é recriado do zero.

Volume (o que faz bug de lista/contagem aparecer):
  - 42 empresas (3 inativas), certificados com validades variadas (vencidos,
    3/7/30/300 dias, ausentes), 1.127 documentos (NFS-e/NF-e/CT-e, tomada e
    prestada, canceladas, leiaute resumo), sincronizações bloqueadas, execuções
    vivas e histórico de 30 dias, eventos pendentes, auditoria e um backup.

Decisões que evitam "banco de teste bonito demais":
  - `importado_em` acompanha a emissão em até 36 h — sem isso o acervo inteiro
    entra em "documentos de hoje" e o painel mente sobre o dia;
  - poucas execuções vivas ao mesmo tempo (3), como no uso real, mas com
    histórico concluído hoje para as contagens diárias não zerarem;
  - CNPJ gerado com dígito verificador válido, porque a API agora recusa o
    contrário;
  - certificado A1 AUTOASSINADO de verdade em disco (senha `SenhaCert#123`),
    no mesmo caminho que o upload grava, para "Validar certificado" e a
    captura exercitarem o caminho real em vez de parar no arquivo ausente;
  - XML de verdade em disco no formato do worker (procNFe/procCTe/NFSe com
    grupo identificador, e resNFe nos resumos) — o exportador classifica por
    CONTEÚDO, então o ZIP precisa de arquivo real para contar nota;
  - `agora` é o instante da semeadura: para reproduzir cota da SEFAZ e janelas,
    semeie perto da hora do teste.

Uso:
    cd backend
    DATABASE_URL=sqlite:////caminho/fluxa.db \\
    VAULT_MASTER_KEY=... SECRET_KEY=... \\
    .venv/bin/python scripts/dev/semear_auditoria.py
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import settings  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.core.vault import cifrar_segredo  # noqa: E402
from app.services.certificados import guardar_pfx_protegido  # noqa: E402
from app.db.base import criar_tabelas  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    BackupRegistro,
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Escritorio,
    ExecucaoImportacao,
    Empresa,
    EventoFiscalPendente,
    RegistroAuditoria,
    SincronizacaoDFe,
    StatusBackup,
    StatusDocumentoFiscal,
    StatusExecucao,
    TipoDocumentoFiscal,
    Usuario,
)

random.seed(20261008)
AGORA = datetime.now(timezone.utc)

PRESIDENTES = [
    "Alvorada", "Bandeirantes", "Caxias", "Dom Pedro", "Estrela do Sul", "Farroupilha",
    "Guarani", "Horizonte", "Ipiranga", "Jequitibá", "Klabin", "Litoral", "Monte Verde",
    "Nova Aurora", "Ouro Preto", "Paineira", "Quatro Irmãos", "Rio Claro", "Serra Azul",
    "Tupinambá", "União", "Vera Cruz", "Xanxerê", "Ypê", "Zebu",
]
SEGMENTOS = [
    "Comércio de Alimentos", "Transportes", "Serviços Contábeis", "Metalurgia",
    "Confecções", "Materiais de Construção", "Farmacêutica", "Tecnologia",
    "Agropecuária", "Moveleira", "Auto Peças", "Gráfica",
]
UFS = ["SP", "MG", "PR", "SC", "RS", "RJ", "BA", "PE", "GO", "MT", "ES", "CE"]
SUFIXOS = ["LTDA", "ME", "EPP", "S/A", "EIRELI"]


def cnpj_valido(indice: int) -> str:
    """CNPJ de 14 dígitos com dígitos verificadores corretos."""
    base = f"{11222333 + indice:08d}" + f"{4455 + (indice * 7) % 5000:04d}"
    base = base[:12]

    def dv(parcial: str) -> str:
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if len(parcial) == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(c) * p for c, p in zip(parcial, pesos))
        resto = soma % 11
        return str(0 if resto < 2 else 11 - resto)

    return base + dv(base) + dv(base + dv(base))


def chave_acesso(uf_idx: int, numero: int, emitente: str, tipo: str) -> str:
    """44 dígitos: cUF AAMM CNPJ mod serie nNF tpEmis cNF cDV."""
    prefixo = f"{35 + uf_idx:02d}{AGORA:%y%m}{emitente[-8:]}{'55' if tipo == 'nfe' else '57'}001{numero:09d}1{numero % 100000000:08d}"
    prefixo = prefixo[:43].ljust(43, "0")
    soma = sum(int(c) * [2, 3, 4, 5, 6, 7, 8, 9][i % 8] for i, c in enumerate(reversed(prefixo)))
    resto = soma % 11
    return prefixo + str(0 if resto in (0, 1) else 11 - resto)


def nome_empresa(i: int) -> str:
    return f"{PRESIDENTES[i % len(PRESIDENTES)]} {SEGMENTOS[(i * 5) % len(SEGMENTOS)]} {SUFIXOS[i % len(SUFIXOS)]}"


# ---------------------------------------------------------------------------
# Certificado A1 de verdade (autoassinado) e XML de verdade em disco
#
# O seed antigo gravava só a LINHA do certificado e o caminho do XML: qualquer
# verificação que exigisse o arquivo (validar A1, exportar ZIP, abrir o XML no
# detalhe) parava no primeiro passo, e a auditoria de captura de ponta a ponta
# não tinha como rodar neste ambiente. Aqui o arquivo existe e é classificável
# pelo próprio produto: o .pfx abre com a senha semeada e o XML é "completo"
# (procNFe/procCTe/NFSe com infNFSe) ou "resumo" (resNFe), como a SEFAZ entrega.
# ---------------------------------------------------------------------------

SENHA_CERTIFICADO = "SenhaCert#123"


def gerar_pfx_autoassinado(razao_social: str, cnpj: str, validade: datetime, inicio: datetime) -> bytes:
    """A1 de desenvolvimento: chave RSA + X.509 autoassinado, empacotado em PKCS#12.

    O CNPJ aparece no CN (depois dos dois-pontos, como nos A1 reais) porque é
    dele que `services.certificados` extrai a identidade — o mesmo caminho que
    valida o upload do operador.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, razao_social[:60]),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Fluxa Desenvolvimento"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{razao_social[:38]}:{cnpj}"),
        ]
    )
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(validade)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=razao_social[:60].encode(),
        key=chave,
        cert=certificado,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(SENHA_CERTIFICADO.encode()),
    )


XML_NAMESPACE_NFE = 'xmlns="http://www.portalfiscal.inf.br/nfe"'


def xml_do_documento(tipo: str, chave: str, numero: str, emitente: str, valor: float,
                     emissao: datetime, leiaute: str) -> bytes:
    """XML no formato que `classificar_documento_dfe` reconhece.

    `completo` → procNFe/procCTe/NFSe com o grupo identificador (é a NOTA);
    `resumo` → resNFe (é o que a distribuição entrega antes da manifestação).
    Nada de XML simbólico: o exportador classifica por CONTEÚDO, então o
    arquivo precisa ser lido como nota de verdade para o ZIP contar.
    """
    data = emissao.strftime("%Y-%m-%dT%H:%M:%S-03:00")
    if leiaute == "resumo":
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<resNFe versao="1.01" {XML_NAMESPACE_NFE}>'
            f"<chNFe>{chave}</chNFe><CNPJ>{emitente}</CNPJ><xNome>Emitente {emitente}</xNome>"
            f"<dhEmi>{data}</dhEmi><vNF>{valor:.2f}</vNF><situacao>Autorizada</situacao></resNFe>\n"
        ).encode()
    if tipo == "cte":
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<procCTe versao="4.00" xmlns="http://www.portalfiscal.inf.br/cte">'
            f'<CTe><infCte versao="4.00" Id="CTe{chave}"><ide><cCT>{numero}</cCT><nCT>{numero}</nCT>'
            f"<dhEmi>{data}</dhEmi><CNPJ>{emitente}</CNPJ></ide>"
            f"<vPrest><vTPrest>{valor:.2f}</vTPrest></vPrest></infCte></CTe></procCTe>\n"
        ).encode()
    if tipo == "nfse":
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<NFSe versao="1.00" xmlns="http://www.sped.fazenda.gov.br/nfse">'
            f'<infNFSe Id="NFSe{chave}"><nNFSe>{numero}</nNFSe><dhEmi>{data}</dhEmi>'
            f"<emit><CNPJ>{emitente}</CNPJ></emit><valores><vLiq>{valor:.2f}</vLiq></valores></infNFSe></NFSe>\n"
        ).encode()
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<procNFe versao="4.00" {XML_NAMESPACE_NFE}>'
        f'<NFe><infNFe versao="4.00" Id="NFe{chave}"><ide><nNF>{numero}</nNF><dhEmi>{data}</dhEmi>'
        f"</ide><emit><CNPJ>{emitente}</CNPJ></emit><total><ICMSTot><vNF>{valor:.2f}</vNF></ICMSTot></total>"
        f"</infNFe></NFe></procNFe>\n"
    ).encode()


def gravar_xml(dados_dir: Path, empresa_id: int, tipo: str, chave: str, conteudo: bytes) -> str:
    """Mesmo caminho absoluto que o worker grava (`<dados>/xml/<empresa>/<tipo>/<chave>.xml`)."""
    pasta = dados_dir / "xml" / str(empresa_id) / tipo
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{chave}.xml"
    caminho.write_bytes(conteudo)
    return str(caminho)


def main() -> None:
    criar_tabelas()
    db = SessionLocal()
    try:
        if db.query(Empresa).count() > 0:
            print("Banco já semeado — abortando para não duplicar.")
            return

        escritorio = Escritorio(nome="Escritório Contábil Cajuru")
        db.add(escritorio)
        db.flush()

        for email, papel in [
            ("admin@escritorio.com", "admin"),
            ("operador@escritorio.com", "operador"),
            ("leitura@escritorio.com", "leitura"),
        ]:
            db.add(
                Usuario(
                    escritorio_id=escritorio.id,
                    nome=email.split("@")[0].capitalize() + " Teste",
                    email=email,
                    senha_hash=gerar_hash_senha("SenhaForte#2026ab"),
                    ativo=True,
                    papel=papel,
                )
            )
        db.flush()

        empresas: list[Empresa] = []
        for i in range(42):
            empresa = Empresa(
                escritorio_id=escritorio.id,
                razao_social=nome_empresa(i),
                cnpj_cpf=cnpj_valido(i),
                uf=UFS[i % len(UFS)],
                ativa=i % 14 != 13,
                sincronizar_automaticamente=i % 6 != 5,
                quais_tipos_sincronizar=["nfse,nfe,cte", "nfse,nfe", "nfe,cte", "nfse"][i % 4],
                manifestar_automaticamente=i % 3 == 0,
                codigo_ibge=f"{3100000 + i:07d}",
            )
            db.add(empresa)
            empresas.append(empresa)
        db.flush()

        for i, empresa in enumerate(empresas[:34]):
            dias = [300, 120, 45, 30, 7, 3, -2, -40][i % 8]
            validade = AGORA + timedelta(days=dias)
            # O arquivo existe de verdade: sem ele qualquer verificação que
            # abra o A1 ("Validar certificado", captura) para no primeiro passo.
            pasta_certificado = Path(settings.dados_dir) / "certificados" / str(empresa.id)
            pasta_certificado.mkdir(parents=True, exist_ok=True)
            caminho_certificado = pasta_certificado / f"{empresa.cnpj_cpf}.pfx.enc"
            pfx = gerar_pfx_autoassinado(
                empresa.razao_social, empresa.cnpj_cpf, validade, AGORA - timedelta(days=365)
            )
            guardar_pfx_protegido(caminho_certificado, pfx)
            cert = Certificado(
                empresa_id=empresa.id,
                arquivo_path=str(caminho_certificado),
                senha_cifrada=cifrar_segredo(SENHA_CERTIFICADO),
                validade=validade,
                ativo=True,
                ultima_utilizacao_em=AGORA - timedelta(hours=i % 30),
                ultima_validacao_em=AGORA - timedelta(days=i % 5),
                ultimo_erro="Não foi possível autenticar no ADN (cStat 280)." if i % 11 == 3 else None,
            )
            db.add(cert)
        db.flush()

        for i, empresa in enumerate(empresas):
            for j, tipo_nome in enumerate(empresa.quais_tipos_sincronizar.split(",")):
                tipo = TipoDocumentoFiscal(tipo_nome)
                ultimo = 1000 * (i + 1) + j * 137
                bloqueado = i % 7 == 2
                db.add(
                    SincronizacaoDFe(
                        empresa_id=empresa.id,
                        tipo=tipo,
                        ultimo_nsu=str(ultimo),
                        max_nsu=str(ultimo + (240 if i % 5 == 0 else 0)),
                        proxima_consulta_em=AGORA + timedelta(minutes=random.randint(1, 55)),
                        bloqueado_ate=AGORA + timedelta(minutes=random.randint(5, 50)) if bloqueado else None,
                        motivo_bloqueio="Consumo indevido (cStat 656): aguardando a janela oficial de 1 hora." if bloqueado else None,
                        bloqueios_seguidos=2 if bloqueado else 0,
                        consultas_pontuais=random.randint(0, 14),
                        ultima_consulta_em=AGORA - timedelta(minutes=random.randint(10, 600)),
                        tarefas_pendentes=1 if i % 9 == 4 else 0,
                    )
                )
        db.flush()

        total_documentos = 1127
        base, resto = divmod(total_documentos, len(empresas))
        por_empresa = {empresa.id: base + (1 if i < resto else 0) for i, empresa in enumerate(empresas)}

        for i, empresa in enumerate(empresas):
            tipo_uf = UFS.index(empresa.uf)
            emitente = cnpj_valido(i)
            for n in range(por_empresa[empresa.id]):
                tipo = [TipoDocumentoFiscal.NFSE, TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE][n % 3]
                direcao = DirecaoDocumento.TOMADA if n % 5 < 3 else DirecaoDocumento.PRESTADA
                emissao = AGORA - timedelta(days=(n * 3) % 95, hours=n % 24, minutes=(n * 7) % 60)
                if i == 0 and n < 6:
                    emissao = AGORA - timedelta(hours=n)  # "hoje" para a primeira empresa
                importado_em = min(emissao + timedelta(hours=random.randint(1, 36)), AGORA - timedelta(minutes=5))
                cancelada = n % 23 == 7
                leiaute = "resumo" if n % 9 == 4 else "completo"
                chave = chave_acesso(tipo_uf, n + 1, emitente, tipo.value)
                valor = round(random.uniform(80, 24000), 2)
                # XML gravado no MESMO lugar e formato do worker. Sem isso o ZIP
                # sai sem notas, o detalhe não abre o XML e o LEIA-ME acusa
                # "arquivo ausente no disco" — verdade para o seed antigo, mas
                # não para o ambiente que precisa exercitar a captura de ponta.
                conteudo_xml = xml_do_documento(
                    tipo.value, chave, str(n + 1), emitente, valor, emissao, leiaute
                )
                documento = DocumentoFiscal(
                    empresa_id=empresa.id,
                    tipo=tipo,
                    direcao=direcao,
                    chave_acesso=chave,
                    nsu=str(1000 * (i + 1) + n),
                    data_emissao=emissao,
                    competencia=date(emissao.year, emissao.month, 1),
                    valor_total=valor,
                    xml_path=gravar_xml(Path(settings.dados_dir), empresa.id, tipo.value, chave, conteudo_xml),
                    leiaute=leiaute,
                    numero=str(n + 1),
                    serie="1",
                    emitente_documento=emitente if direcao == DirecaoDocumento.PRESTADA else cnpj_valido((i + 30) % 42),
                    emitente_nome=empresa.razao_social if direcao == DirecaoDocumento.PRESTADA else "Fornecedor Municipal Ltda",
                    destinatario_documento=empresa.cnpj_cpf,
                    destinatario_nome=empresa.razao_social,
                    situacao="Autorizada",
                    origem=["adn", "sefaz"][n % 2],
                    status=StatusDocumentoFiscal.CANCELADA if cancelada else StatusDocumentoFiscal.NORMAL,
                    motivo_cancelamento="Erro na emissão" if cancelada else None,
                    cancelado_em=emissao + timedelta(days=1) if cancelada else None,
                    manifestado_em=emissao + timedelta(hours=2) if tipo == TipoDocumentoFiscal.NFE and direcao == DirecaoDocumento.TOMADA and n % 4 == 0 else None,
                    tentativas_completar=0 if n % 9 != 4 else 2,
                    importado_em=importado_em,
                )
                db.add(documento)
                if n % 17 == 0:
                    db.flush()
                    db.add(
                        DocumentoFiscalFonte(
                            documento_id=documento.id,
                            origem="adn" if tipo == TipoDocumentoFiscal.NFSE else "sefaz",
                            identificador_externo=str(1000 * (i + 1) + n),
                        )
                    )
        db.flush()

        vivas = [(0, StatusExecucao.EM_ANDAMENTO), (1, StatusExecucao.EM_ANDAMENTO), (2, StatusExecucao.AGUARDANDO)]
        for i, empresa in enumerate(empresas[:30]):
            for j in range(3):
                if j == 0 and i < len(vivas):
                    estado = vivas[i][1]
                    inicio = AGORA - timedelta(minutes=random.randint(2, 9))
                    finalizado = None
                elif j == 0 and i < 8:
                    estado = StatusExecucao.CONCLUIDA
                    finalizado = AGORA - timedelta(minutes=random.randint(20, 8 * 60))
                    inicio = finalizado - timedelta(minutes=random.randint(1, 12))
                else:
                    estado = StatusExecucao.ERRO if (i + j) % 7 == 0 else StatusExecucao.CONCLUIDA
                    inicio = AGORA - timedelta(days=(i + j) % 30, hours=(i * 3 + j) % 24, minutes=(i * 11 + j * 7) % 60)
                    finalizado = None if estado == StatusExecucao.ERRO else inicio + timedelta(minutes=random.randint(1, 12))
                db.add(
                    ExecucaoImportacao(
                        empresa_id=empresa.id,
                        tipo=[TipoDocumentoFiscal.NFSE, TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE][j % 3],
                        status=estado,
                        documentos_importados=random.randint(0, 60) if estado == StatusExecucao.CONCLUIDA else 0,
                        documentos_cancelados=random.randint(0, 3) if estado == StatusExecucao.CONCLUIDA else 0,
                        ultimo_nsu=str(1000 * (i + 1) + j),
                        documentos_no_periodo=random.randint(0, 40),
                        documentos_fora_do_periodo=random.randint(0, 8),
                        tentativas=1 if estado == StatusExecucao.AGUARDANDO else 0,
                        bloqueado_ate=AGORA + timedelta(minutes=42) if estado == StatusExecucao.AGUARDANDO else None,
                        origem=["manual", "lote", "agendador"][(i + j) % 3],
                        mensagem_erro="Timeout de conexão com o ADN após 30s." if estado == StatusExecucao.ERRO else None,
                        aviso="Agenda atingida: a captura continua na próxima janela." if estado == StatusExecucao.AGUARDANDO else None,
                        iniciado_em=inicio,
                        finalizado_em=finalizado,
                    )
                )

        for i, empresa in enumerate(empresas[:9]):
            db.add(
                EventoFiscalPendente(
                    empresa_id=empresa.id,
                    tipo=TipoDocumentoFiscal.NFE,
                    chave_acesso=chave_acesso(0, 9000 + i, cnpj_valido(i), "nfe"),
                    tipo_evento="cancelamento",
                    nsu=str(9000 + i),
                    motivo="Cancelamento por substituição de NF-e",
                    data_evento=AGORA - timedelta(days=i),
                    processado=False,
                )
            )

        acoes = [
            "empresa_criada", "empresa_atualizada", "certificado_enviado", "importacao_disparada",
            "login", "documento_baixado", "usuario_criado", "backup_manual",
        ]
        for i in range(80):
            db.add(
                RegistroAuditoria(
                    escritorio_id=escritorio.id,
                    quando=AGORA - timedelta(hours=i * 3, minutes=(i * 7) % 60),
                    usuario_email=["admin@escritorio.com", "operador@escritorio.com"][i % 2],
                    acao=acoes[i % len(acoes)],
                    entidade=["empresa", "documento", "certificado", "usuario"][i % 4],
                    entidade_id=(i % 40) + 1,
                    detalhe=f"Registro de auditoria de teste #{i + 1}",
                )
            )

        db.add(
            BackupRegistro(
                tipo="agendado",
                status=StatusBackup.OK,
                iniciado_em=AGORA - timedelta(hours=9),
                finalizado_em=AGORA - timedelta(hours=9) + timedelta(minutes=3),
                tamanho_bytes=54_300_000,
                caminho="backups/fluxa-2026-10-08.zip",
                checksum_sha256="a" * 64,
                arquivos_incluidos=1127,
                empresas=42,
                documentos=1127,
                execucoes=90,
                restauracao_testada_em=AGORA - timedelta(days=3),
                restauracao_ok=True,
            )
        )

        db.commit()
        print("Semeadura concluída:")
        print(f"  empresas: {db.query(Empresa).count()}")
        print(f"  certificados: {db.query(Certificado).count()}")
        print(f"  documentos: {db.query(DocumentoFiscal).count()}")
        print(f"  execuções: {db.query(ExecucaoImportacao).count()}")
        print(f"  sincronizações: {db.query(SincronizacaoDFe).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
