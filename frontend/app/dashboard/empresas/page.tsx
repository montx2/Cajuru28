"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { Empresa } from "@/lib/types";

const UFS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
  "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
  "SP", "SE", "TO",
];

export default function EmpresasPage() {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [mostrarFormulario, setMostrarFormulario] = useState(false);
  const [razaoSocial, setRazaoSocial] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [uf, setUf] = useState("SP");
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  function carregar() {
    setCarregando(true);
    api
      .listarEmpresas()
      .then(setEmpresas)
      .finally(() => setCarregando(false));
  }

  useEffect(carregar, []);

  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSalvando(true);
    try {
      await api.criarEmpresa(razaoSocial, cnpj.replace(/\D/g, ""), uf);
      setRazaoSocial("");
      setCnpj("");
      setMostrarFormulario(false);
      carregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível cadastrar a empresa.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <p className="font-serif text-2xl text-ink">Empresas</p>
        <button
          onClick={() => setMostrarFormulario((v) => !v)}
          className="border border-accent px-4 py-2 text-sm font-medium text-accent hover:bg-accent-soft"
        >
          {mostrarFormulario ? "Cancelar" : "Nova empresa"}
        </button>
      </div>

      {mostrarFormulario && (
        <form onSubmit={criar} className="mb-6 border border-line bg-surface p-5">
          <div className="mb-3 flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-sm text-ink-muted">Razão social</label>
              <input
                required
                value={razaoSocial}
                onChange={(e) => setRazaoSocial(e.target.value)}
                className="w-full border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
            </div>
            <div className="w-56">
              <label className="mb-1 block text-sm text-ink-muted">CNPJ / CPF</label>
              <input
                required
                value={cnpj}
                onChange={(e) => setCnpj(e.target.value)}
                placeholder="Somente números"
                className="w-full border border-line bg-bg px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent"
              />
            </div>
            <div className="w-24">
              <label className="mb-1 block text-sm text-ink-muted">UF</label>
              <select
                value={uf}
                onChange={(e) => setUf(e.target.value)}
                className="w-full border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              >
                {UFS.map((sigla) => (
                  <option key={sigla} value={sigla}>
                    {sigla}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {erro && <p className="mb-3 text-sm text-danger">{erro}</p>}
          <button
            type="submit"
            disabled={salvando}
            className="bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {salvando ? "Salvando…" : "Cadastrar empresa"}
          </button>
        </form>
      )}

      {carregando ? (
        <p className="text-sm text-ink-muted">Carregando…</p>
      ) : empresas.length === 0 ? (
        <div className="border border-line bg-surface p-8 text-center">
          <p className="text-sm text-ink-muted">
            Nenhuma empresa cadastrada ainda. Cadastre a primeira para começar a importar notas.
          </p>
        </div>
      ) : (
        <table className="w-full border-t border-line text-sm">
          <thead>
            <tr className="border-b border-line text-left text-ink-muted">
              <th className="py-2 font-normal">Razão social</th>
              <th className="py-2 font-normal">CNPJ / CPF</th>
              <th className="py-2 font-normal">UF</th>
              <th className="py-2 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {empresas.map((empresa) => (
              <tr key={empresa.id} className="border-b border-line last:border-0">
                <td className="py-3 text-ink">{empresa.razao_social}</td>
                <td className="py-3 font-mono text-ink-muted">{empresa.cnpj_cpf}</td>
                <td className="py-3 font-mono text-ink-muted">{empresa.uf}</td>
                <td className="py-3 text-right">
                  <Link href={`/dashboard/empresas/${empresa.id}`} className="text-accent hover:underline">
                    abrir
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
