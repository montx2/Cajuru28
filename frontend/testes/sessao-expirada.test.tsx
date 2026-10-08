/**
 * Aviso de sessão expirada na tela de login (Bloco C, melhoria autorizada).
 *
 * A API redirecionava para `/login?destino=…` sem dizer o motivo: quem estava
 * trabalhando caía no formulário sem entender se tinha errado a senha, se
 * tinha sido desconectado ou se o sistema havia quebrado. O login agora
 * reconhece o marcador `sessao=expirada` e explica — em tom de espera, não de
 * erro: expirar por inatividade é o comportamento esperado da sessão.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

function fonte(caminho: string): string {
  return readFileSync(resolve(__dirname, "..", caminho), "utf-8");
}

describe("quem cai no login sabe por quê", () => {
  const api = fonte("lib/api.ts").replace(/\s+/g, " ");
  const login = fonte("app/login/FormularioLogin.tsx").replace(/\s+/g, " ");

  it("o redirecionamento por 401 marca a sessão como expirada", () => {
    expect(api).toContain("sessao=expirada");
    // O marcador convive com o destino, sem perder o caminho de volta.
    expect(api).toContain('${destino ? "&" : "?"}sessao=expirada');
  });

  it("o login mostra o aviso, e não o erro de credenciais", () => {
    expect(login).toContain('parametros.get("sessao") === "expirada"');
    expect(login).toContain("Sua sessão expirou por inatividade");
    // Tom de espera: expirar não é falha, e vermelho aqui assustaria à toa.
    expect(login).not.toMatch(/sessaoExpirada[\s\S]{0,400}bg-erro/);
  });

  it("o aviso é anunciado e oferece o caminho de volta", () => {
    // recorte até o formulário: o erro de credenciais (que é urgente) fica depois
    const trecho = login.slice(login.indexOf("sessaoExpirada ?"), login.indexOf('<Formulario aoEnviar={entrar}'));
    // O anúncio vem do primitivo: `Aviso` sem `urgente` sai como `role="status"`
    // (interromper o leitor de tela fica para o que é falha), e o tom é de espera.
    expect(trecho).toContain('<Aviso tom="espera"');
    expect(trecho).not.toContain("urgente");
    expect(trecho).toContain("você volta para a tela em que estava");
  });

  it("reaproveita o destino, sem virar redirecionador aberto", () => {
    const seguranca = fonte("app/login/FormularioLogin.tsx");
    expect(seguranca).toContain("function destinoSeguro");
    expect(seguranca).toContain("valor.startsWith(\"/\") && !valor.startsWith(\"//\")");
  });
});
