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
  it("mostra a mensagem do servidor sem presumir filtro nem período", () => {
    // Nem toda tela que recebe 422 é uma consulta: "Nova empresa" recebia
    // "confira o período e os filtros destacados abaixo", texto que não existe
    // no formulário. A mensagem do servidor é a única verdade disponível.
    const descrito = descreverErro(new ApiError(422, "Não foi possível identificar a UF automaticamente."));
    expect(descrito.titulo).toBe("A API recusou o envio");
    expect(descrito.causa).toBe("Não foi possível identificar a UF automaticamente.");
    expect(descrito.proximoPasso).not.toMatch(/filtro|período/i);
  });

  it("não inventa causa quando o servidor não manda mensagem", () => {
    const descrito = descreverErro(new ApiError(422, ""));
    expect(descrito.causa).toContain("não informou qual campo");
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

  it("preserva a explicação real do servidor em erros 400, 409 e 422 textuais", () => {
    expect(mensagemDoErro(new ApiError(409, "Já existe uma empresa com esse CNPJ/CPF"))).toContain(
      "Já existe uma empresa com esse CNPJ/CPF"
    );
    expect(
      mensagemDoErro(
        new ApiError(422, "Não foi possível identificar a UF automaticamente. Informe a UF manualmente.")
      )
    ).toContain("Informe a UF manualmente");
    expect(mensagemDoErro(new ApiError(400, "Planilha empresas.csv ilegível"))).toContain(
      "Planilha empresas.csv ilegível"
    );
  });
});

