#!/usr/bin/env python3
"""
Gera o ícone do programa (`icone.ico`, `icone.png`) — sem depender de designer.

Por que um script e não um arquivo binário solto no repositório: ícone é
identidade visual, e identidade visual muda. Aqui a marca é **gerada**, então
ajustar o azul/verde, o raio do canto ou o desenho é uma linha de código — e o
`.ico` com todos os tamanhos que o Windows usa (16px na barra de tarefas, 256px
no explorador) sai sempre completo. Um `.ico` montado à mão costuma vir só com
256×256 e ficar borrado no menu Iniciar.

Uso:
    python scripts/gerar_icone.py

Saída:
    installer/notasflow.ico   (16, 24, 32, 48, 64, 128, 256)
    frontend/public/icone.png (favicon do painel)
    backend/icone.png         (ícone do pacote: bandeja do sistema)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
VERDE = (31, 111, 84, 255)  # #1F6F54 — o mesmo `accent` do painel
VERDE_ESCURO = (22, 82, 62, 255)
PAPEL = (255, 255, 255, 255)
PAPEL_SUAVE = (228, 239, 233, 255)  # #E4EFE9
TAMANHO_BASE = 1024
CANTOS = (16, 24, 32, 48, 64, 128, 256)

FONTES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _fonte(tamanho: int) -> ImageFont.FreeTypeFont:
    for caminho in FONTES:
        if Path(caminho).is_file():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default(tamanho)


def desenhar(tamanho: int = TAMANHO_BASE) -> Image.Image:
    """
    A marca: um quadrado arredondado verde com uma **nota fiscal** (folha com
    linhas) e as iniciais NF.

    A ideia é que reconhecer o programa na bandeja seja instantâneo a 16px —
    por isso o contraste alto entre papel e fundo e poucos elementos. Ícone
    detalhado a 16px vira mancha cinza.
    """
    escala = tamanho / TAMANHO_BASE
    imagem = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)

    # Fundo: quadrado arredondado com um leve degradê (topo mais claro).
    raio = int(180 * escala)
    desenho.rounded_rectangle([(0, 0), (tamanho - 1, tamanho - 1)], radius=raio, fill=VERDE)
    desenho.rounded_rectangle(
        [(0, 0), (tamanho - 1, int(tamanho * 0.52))], radius=raio, fill=VERDE_ESCURO
    )
    desenho.rounded_rectangle([(0, 0), (tamanho - 1, tamanho - 1)], radius=raio, fill=VERDE)

    # A folha da nota, com o canto dobrado — o desenho universal de documento.
    margem_x = int(tamanho * 0.235)
    margem_y = int(tamanho * 0.185)
    largura = tamanho - 2 * margem_x
    altura = tamanho - 2 * margem_y
    dobra = int(min(largura, altura) * 0.30)
    x0, y0 = margem_x, margem_y
    x1, y1 = margem_x + largura, margem_y + altura

    desenho.polygon(
        [
            (x0, y0),
            (x1 - dobra, y0),
            (x1, y0 + dobra),
            (x1, y1),
            (x0, y1),
        ],
        fill=PAPEL,
    )
    # A dobra, em tom suave, para o canto parecer virado.
    desenho.polygon([(x1 - dobra, y0), (x1, y0 + dobra), (x1 - dobra, y0 + dobra)], fill=PAPEL_SUAVE)

    # Linhas de texto da nota: a primeira mais forte (é o cabeçalho).
    espessura = max(1, int(14 * escala))
    linha_x0 = x0 + int(largura * 0.14)
    linha_x1 = x1 - int(largura * 0.14)
    primeira_y = y0 + int(altura * 0.40)
    passo = int(altura * 0.145)

    for indice in range(3):
        y = primeira_y + indice * passo
        largura_linha = linha_x1 if indice < 2 else linha_x1 - int(largura * 0.28)
        desenho.rounded_rectangle(
            [(linha_x0, y), (largura_linha, y + espessura)],
            radius=espessura // 2,
            fill=VERDE if indice == 0 else (150, 175, 166, 255),
        )

    # Assinatura: as iniciais, na faixa de baixo do documento.
    texto = "NF"
    fonte = _fonte(int(altura * 0.26))
    caixa = desenho.textbbox((0, 0), texto, font=fonte)
    largura_texto = caixa[2] - caixa[0]
    altura_texto = caixa[3] - caixa[1]
    desenho.text(
        (
            x1 - int(largura * 0.14) - largura_texto,
            y1 - int(altura * 0.13) - altura_texto - caixa[1],
        ),
        texto,
        font=fonte,
        fill=VERDE,
    )

    return imagem


def main() -> int:
    base = desenhar()

    pasta_instalador = RAIZ / "installer"
    pasta_instalador.mkdir(exist_ok=True)
    ico = pasta_instalador / "notasflow.ico"
    base.save(ico, format="ICO", sizes=[(t, t) for t in CANTOS])

    # PNGs avulsos: o pacote usa na bandeja, o painel usa como favicon.
    for destino in (RAIZ / "backend" / "icone.png", RAIZ / "frontend" / "public" / "icone.png"):
        destino.parent.mkdir(parents=True, exist_ok=True)
        base.resize((256, 256), Image.LANCZOS).save(destino, format="PNG", optimize=True)

    print(f"[icone] {ico} ({', '.join(f'{t}x{t}' for t in CANTOS)})")
    print("[icone] backend/icone.png, frontend/public/icone.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
