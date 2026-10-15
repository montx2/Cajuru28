"""Diagnóstico independente Jettax, Python 3.11+, sem instalar bibliotecas.
Somente GET. Não grava token, respostas, CNPJ, XML ou URLs no disco.
Execute: python diagnostico_jettax.py
"""
from __future__ import annotations

import getpass
import hashlib
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://morfeu.jettax360.com.br"
LIMITE_JSON = 8 * 1024 * 1024
LIMITE_XML = 2 * 1024 * 1024
RELATORIO = "relatorio_jettax_seguro.json"


class SemRedirecionamento(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def estrutura(valor, nivel=0):
    """Somente nomes de campos estáticos e tipos; nunca valores."""
    if nivel >= 14:
        return "profundidade_limitada"
    if isinstance(valor, dict):
        resultado = {}
        for chave, item in list(valor.items())[:150]:
            # IDs, documentos, URLs e chaves dinâmicas ficam ocultos.
            nome = chave if re.fullmatch(r"[A-Za-z_]{1,80}", chave) else "chave_dinamica_oculta"
            resultado[nome] = estrutura(item, nivel + 1)
        return resultado
    if isinstance(valor, list):
        formas = []
        for item in valor[:20]:
            forma = estrutura(item, nivel + 1)
            if forma not in formas:
                formas.append(forma)
        return {"tipo": "array", "amostras_de_estrutura": formas, "vazia": not valor}
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "boolean"
    if isinstance(valor, str):
        return "string"
    if isinstance(valor, int):
        return "integer"
    if isinstance(valor, float):
        return "number"
    return "outro_tipo"


def link_publico(url):
    try:
        partes = urllib.parse.urlsplit(url)
        if (partes.scheme != "https" or not partes.hostname or partes.username
                or partes.password or partes.port not in (None, 443)):
            return False
        enderecos = socket.getaddrinfo(partes.hostname, 443, type=socket.SOCK_STREAM)
        return bool(enderecos) and all(ipaddress.ip_address(item[4][0]).is_global for item in enderecos)
    except (ValueError, OSError):
        return False


class Diagnostico:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # não envia segredo a proxy do ambiente
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            SemRedirecionamento(),
        )
        self.resultados = []
        self.parar = False
        self.ultima_chamada = 0.0

    def consultar(self, nome, url, *, autenticado=False, json_esperado=True, limite=LIMITE_JSON):
        if self.parar:
            return None
        time.sleep(max(0, 2 - (time.monotonic() - self.ultima_chamada)))
        self.ultima_chamada = time.monotonic()
        registro = {"teste": nome}
        self.resultados.append(registro)
        headers = {"Accept": "application/json" if json_esperado else "application/xml, text/xml, */*"}
        if autenticado:
            if not url.startswith(BASE + "/api/"):
                raise ValueError("Token restrito à API oficial")
            headers["Authorization"] = self.token
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with self.opener.open(req, timeout=30) as resposta:
                registro["http"] = resposta.status
                corpo = resposta.read(limite + 1)
                if len(corpo) > limite:
                    registro["resultado"] = "resposta_excede_limite_de_seguranca"
                    return None
            if json_esperado:
                try:
                    dados = json.loads(corpo)
                except (ValueError, UnicodeError):
                    registro["resultado"] = "nao_e_json_valido"
                    return None
                registro["estrutura"] = estrutura(dados)
                return dados
            return corpo
        except urllib.error.HTTPError as exc:
            registro["http"] = exc.code
            registro["resultado"] = "corpo_e_cabecalhos_omitidos"
            if exc.code == 429:
                registro["resultado"] = "limite_atingido_diagnostico_interrompido_sem_retry"
                self.parar = True
            elif exc.code in (401, 403) and autenticado:
                self.parar = True
            exc.close()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            registro["resultado"] = "falha_de_rede_tls_ou_formato_detalhes_omitidos"
        return None


def paginacao(dados):
    if not isinstance(dados, dict):
        return {}
    meta = dados.get("meta")
    pag = meta.get("pagination") if isinstance(meta, dict) else None
    return pag if isinstance(pag, dict) else {}


def itens(dados):
    return dados.get("data", []) if isinstance(dados, dict) and isinstance(dados.get("data"), list) else []


def comparar_paginas(primeira, segunda):
    # Hash somente em memória: nada identificável é incluído no relatório.
    def assinaturas(dados):
        return {hashlib.sha256(json.dumps(item, sort_keys=True).encode()).digest() for item in itens(dados)}
    a, b = assinaturas(primeira), assinaturas(segunda)
    return bool(a and b and a.isdisjoint(b))


def executar(diag, cnpj, competencia):
    diag.consultar("autenticacao_sem_token", BASE + "/api/clients")
    clientes = diag.consultar("clientes_token_puro", BASE + "/api/clients?" + urllib.parse.urlencode({"cnpj": cnpj}), autenticado=True)
    if clientes is None or diag.parar:
        return
    rota = BASE + "/api/nfse/invoices/" + cnpj
    def nfse(nome, **extras):
        params = {"simpleResponse": "true", "period": competencia, **extras}
        return diag.consultar(nome, rota + "?" + urllib.parse.urlencode(params), autenticado=True)
    dados = nfse("nfse_competencia_sem_paginacao")
    if dados is None:
        return
    primeira = nfse("sondagem_page1_limit1", page=1, limit=1)
    segunda = nfse("sondagem_page2_limit1", page=2, limit=1)
    conclusoes = {"teste": "verificacao_paginacao", "page_limit_sao_sondagens_nao_contrato": True}
    for nome, pagina, recebido in (("primeira", 1, primeira), ("segunda", 2, segunda)):
        pag = paginacao(recebido)
        conclusoes[nome] = {
            "meta_pagination_presente": bool(pag),
            "current_page_confirma_pedido": pag.get("current_page") == pagina,
            "per_page_confirma_limite": pag.get("per_page") == 1,
            "quantidade_compativel_com_limite": len(itens(recebido)) <= 1 if recebido is not None else None,
        }
    conclusoes["paginas_com_itens_distintos"] = comparar_paginas(primeira, segunda)
    conclusoes["aviso"] = "Se não houver ao menos duas notas, navegação completa permanece inconclusiva. Não varremos todo o acervo."
    diag.resultados.append(conclusoes)
    nfse("filtro_emitidas", tipoNota="enviada")
    nfse("filtro_recebidas", tipoNota="recebida")
    nfse("filtro_canceladas", notaSituacao="cancelada")
    # Amostra de no máximo 3 arquivos; nunca PDF, nunca token no storage.
    amostra = [item for item in itens(dados) if isinstance(item, dict)][:3]
    diag.resultados.append({"teste": "arquivos_amostra", "amostra_disponivel": bool(amostra), "urlPDF_vazio_presente": any(item.get("urlPDF") == "" for item in amostra)})
    for indice, item in enumerate(amostra, 1):
        url = item.get("url")
        if not isinstance(url, str) or not link_publico(url):
            diag.resultados.append({"teste": f"arquivo_{indice}", "resultado": "link_ausente_ou_nao_publico_https"})
            continue
        corpo = diag.consultar(f"download_arquivo_{indice}", url, json_esperado=False, limite=LIMITE_XML)
        if corpo is None:
            continue
        registro = {"teste": f"xml_{indice}"}
        try:
            if b"<!DOCTYPE" in corpo.upper() or b"<!ENTITY" in corpo.upper():
                raise ValueError("DTD não permitido")
            raiz = ET.fromstring(corpo)
            tags = {elemento.tag.rsplit("}", 1)[-1] for elemento in raiz.iter()}
            registro.update(xml_valido=True, leiaute_nacional_infNFSe="infNFSe" in tags,
                            tags_estruturais={tag: tag in tags for tag in ("NFSe", "CompNfse", "InfNfse", "infNFSe", "Cnpj", "CNPJ", "DataEmissao", "dhEmi", "dCompet", "CodigoVerificacao")})
            registro["aviso"] = "XML válido não confirma compatibilidade com o conversor local; valores não foram exportados."
        except (ET.ParseError, ValueError):
            registro.update(xml_valido=False, resultado="txt_ou_outro_formato_ou_xml_inseguro_invalido")
        diag.resultados.append(registro)


def main():
    print("DIAGNÓSTICO JETTAX — somente leitura, fase NFS-e")
    print("Não importa notas, não modifica cadastros e não consulta SEFAZ/ADN.")
    print("Faz até 11 GETs, incluindo no máximo 3 downloads de arquivos, com intervalo de 2 segundos.")
    print("Não tenta provocar erros 429/5xx nem testa gravação em banco.")
    token = getpass.getpass("Token Jettax (oculto, não fica salvo): ").strip()
    cnpj = re.sub(r"\D", "", getpass.getpass("CNPJ de UMA empresa cadastrada (oculto): "))
    competencia = input("Competência COM pelo menos duas notas, MM-AAAA: ").strip()
    if not token or len(cnpj) != 14 or not re.fullmatch(r"(0[1-9]|1[0-2])-\d{4}", competencia):
        print("Entrada inválida. Nada consultado.")
        return
    if input("Autoriza essas consultas somente leitura? Digite SIM: ").strip() != "SIM":
        print("Cancelado.")
        return
    diag = Diagnostico(token)
    try:
        executar(diag, cnpj, competencia)
    except KeyboardInterrupt:
        diag.resultados.append({"teste": "execucao", "resultado": "interrompida_pelo_operador"})
    except Exception:
        # Tracebacks podem conter o token ou a URL presigned: nunca imprimi-los.
        diag.resultados.append({"teste": "execucao", "resultado": "falha_inesperada_detalhes_omitidos"})
    relatorio = {"versao_diagnostico": 1, "escopo": "NFS-e somente leitura", "resultados": diag.resultados,
                 "nao_verificado": ["NFe e CTe (fase posterior)", "Completude do acervo e notas anteriores ao cadastro Jettax", "Troca exclusiva de coletor e fallback SEFAZ", "Idempotência e isolamento de escritórios no banco local (exigem testes simulados)", "Links expirados, 429, 5xx e falhas transitórias (testar com mocks, sem provocar na API)", "Paginação de todos os clientes e de todo o acervo", "Compatibilidade integral dos leiautes municipais e cancelamentos com o conversor local"]}
    try:
        Path(RELATORIO).write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Concluído. Envie somente o arquivo", RELATORIO)
    except OSError:
        print("Não foi possível salvar o relatório. Execute numa pasta com permissão de escrita.")


if __name__ == "__main__":
    main()
