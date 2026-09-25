/**
 * O 422 precisa dizer **qual campo** e **por quê**.
 *
 * O defeito que estes testes travam: a API respondia
 * `{"detail":[{"loc":["body","base_url"],"msg":"…HTTPS…"}]}`, o cliente HTTP
 * montava a frase certa — e `descreverErro` a descartava, devolvendo um texto
 * fixo sobre "período em AAAA-MM-DD" para uma tela que não tem período. O
 * operador via "confira os filtros" e tentava a mesma credencial de novo.
 */
import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { descreverErro, mensagemDoErro, problemasDeValidacao, rotuloDoCampo } from "@/lib/erros";

const erroDeUmCampo = () =>
  new ApiError(422, "base_url: A URL da integração precisa começar com 'https://'.", [
    { campo: "base_url", mensagem: "A URL da integração precisa começar com 'https://'." },
  ]);

const erroDeDoisCampos = () =>
  new ApiError(422, "base_url: use HTTPS; segredo: mínimo de 8 caracteres", [
    { campo: "base_url", mensagem: "Use HTTPS." },
    { campo: "segredo", mensagem: "O segredo precisa de pelo menos 8 caracteres." },
  ]);

describe("422 com um campo", () => {
  it("nomeia o campo no título, com o rótulo da tela e não o do banco", () => {
    expect(descreverErro(erroDeUmCampo()).titulo).toBe("Campo recusado: Base URL");
  });

  it("usa a mensagem real da API como causa", () => {
    expect(descreverErro(erroDeUmCampo()).causa).toContain("https://");
  });

  it("leva a causa para o aviso flutuante — era ela que se perdia", () => {
    const frase = mensagemDoErro(erroDeUmCampo());
    expect(frase).toContain("Base URL");
    expect(frase).toContain("https://");
    expect(frase).not.toContain("AAAA-MM-DD");
  });
});

describe("422 com vários campos", () => {
  it("conta os campos e lista cada motivo", () => {
    const descrito = descreverErro(erroDeDoisCampos());
    expect(descrito.titulo).toBe("2 campos recusados");
    expect(descrito.causa).toContain("Base URL");
    expect(descrito.causa).toContain("Credencial");
    expect(descrito.proximoPasso).toContain("Base URL, Credencial");
  });
});

describe("422 sem detalhe estruturado", () => {
  it("mantém a orientação genérica de filtros (é o caso das consultas)", () => {
    const descrito = descreverErro(new ApiError(422, "Período obrigatório"));
    expect(descrito.titulo).toBe("A API recusou os parâmetros");
    expect(descrito.causa).toBe("Período obrigatório");
  });
});

describe("apoio às telas", () => {
  it("expõe os campos recusados para destacar o formulário", () => {
    expect(problemasDeValidacao(erroDeDoisCampos()).map((item) => item.campo)).toEqual([
      "base_url",
      "segredo",
    ]);
    expect(problemasDeValidacao(new Error("qualquer coisa"))).toEqual([]);
  });

  it("traduz campo desconhecido sem deixar snake_case na tela", () => {
    expect(rotuloDoCampo("hora_sincronizacao")).toBe("Hora sincronizacao");
    expect(rotuloDoCampo("")).toBe("");
  });
});

describe("outros status continuam curtos", () => {
  it("não repete a causa no aviso quando não é validação", () => {
    const frase = mensagemDoErro(new ApiError(401, "Sessão expirada"));
    expect(frase).toBe("Sessão expirada. Entre novamente com as credenciais do escritório.");
  });
});
