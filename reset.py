"""
Resetter Epson pela USB (Windows) — contadores de tinta descartada.

Dois jeitos de usar:
  - Dando dois cliques (ou "python reset.py"): abre um menu.
  - Pela linha de comando:
        python reset.py ler
        python reset.py zerar
        python reset.py restaurar ARQUIVO.json
    acrescente --debug para ver os bytes trocados com a impressora.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

from d4 import ErroD4
from epson import ErroEpson, ImpressoraEpson
from modelos import achar_modelo, pode_ler, pode_zerar, total_modelos

VERSAO = "1.1"


class Cancelado(Exception):
    pass


def pasta_do_programa() -> Path:
    # No .exe do PyInstaller, __file__ aponta para uma pasta temporária;
    # o lugar certo é onde o .exe está.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


PASTA_BACKUP = pasta_do_programa() / "backups"


# --------------------------------------------------------------- conexão
def conectar(debug):
    try:
        from usb_windows import UsbPrintIO, listar_impressoras_usb
    except ImportError:
        raise Cancelado("Este programa usa o acesso USB do Windows. Rode no Windows.")

    epsons = [c for c in listar_impressoras_usb() if "vid_04b8" in c.lower()]
    if not epsons:
        raise Cancelado("Nenhuma impressora Epson encontrada na USB. "
                        "Ela está ligada e conectada neste computador?")
    if len(epsons) > 1:
        print("Mais de uma Epson encontrada; usando a primeira.")

    return ImpressoraEpson(UsbPrintIO(epsons[0]), log=print if debug else None)


def identificar(imp, precisa_gravar=False):
    info = imp.identificacao()
    nome = info.get("MDL", "?")
    print(f"Impressora encontrada: {info.get('MFG', 'EPSON')} {nome}")
    ficha = achar_modelo(nome)
    if ficha is None:
        raise Cancelado(f"O modelo '{nome}' ainda não está no banco de modelos.")
    if not pode_ler(ficha):
        raise Cancelado(f"Ainda não sabemos como ler a memória da {ficha['nome']}.")
    if precisa_gravar:
        ok, motivo = pode_zerar(ficha)
        if not ok:
            raise Cancelado(f"Não dá para zerar a {ficha['nome']}: {motivo}.")
    imp.modelo = ficha
    return ficha


# --------------------------------------------------------------- exibição
TRADUCAO = {
    "waste counters (?)": "Contadores de descarte (?)",
    "waste counter (main pad)": "Descarte (esponja principal)",
    "waste counter (platen pad)": "Descarte (esponja da bandeja)",
    "waste counter": "Contador de descarte",
    "platen pad counters": "Esponja da bandeja",
}


def mostrar_contadores(imp, ficha):
    print("\nContadores:")
    for desc, enderecos in ficha["contadores"]:
        valores = [imp.ler(e) for e in enderecos]
        bytes_txt = " ".join(f"{v:02X}" for v in valores)
        linha = f"  {TRADUCAO.get(desc.lower(), desc):<30} [{bytes_txt}]"
        if len(valores) == 2:
            total = valores[1] * 256 + valores[0]
            linha += f" = {total}"
            limite = ficha["limites"].get(enderecos[0])
            if limite:
                linha += f"  ->  ~{total / limite * 100:.1f}%"
        print(linha)


def confirmar(pergunta):
    return input(f"\n{pergunta} Digite SIM para continuar: ").strip().upper() == "SIM"


# --------------------------------------------------------------- ações
def acao_ler(imp):
    ficha = identificar(imp)
    mostrar_contadores(imp, ficha)
    ok, motivo = pode_zerar(ficha)
    if not ok:
        print(f"\nObs.: este modelo não pode ser zerado por aqui ({motivo}).")


def acao_zerar(imp):
    ficha = identificar(imp, precisa_gravar=True)
    mostrar_contadores(imp, ficha)

    PASTA_BACKUP.mkdir(exist_ok=True)
    valores = {f"0x{e:03X}": imp.ler(e) for e in sorted(ficha["reset"])}
    agora = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    arq = PASTA_BACKUP / f"backup-{ficha['nome']}-{agora}.json"
    arq.write_text(json.dumps({"modelo": ficha["nome"], "valores": valores}, indent=2))
    print(f"\nBackup salvo em: {arq}")

    print("\nATENÇÃO: zerar o contador não esvazia a esponja interna. Se ela estiver")
    print("cheia, a tinta pode vazar. O ideal é instalar um tanque externo de descarte.")
    if not confirmar("Os contadores serão zerados."):
        print("Cancelado. Nada foi alterado.")
        return

    for end, val in sorted(ficha["reset"].items()):
        imp.gravar(end, val)
        print(f"  0x{end:03X} <- 0x{val:02X}  ok")

    mostrar_contadores(imp, ficha)
    print("\nPronto! Desligue a impressora, espere uns 10 segundos e ligue de novo.")


def acao_restaurar(imp, arquivo):
    dados = json.loads(Path(arquivo).read_text())
    ficha = identificar(imp, precisa_gravar=True)
    if dados.get("modelo") != ficha["nome"]:
        raise Cancelado(f"Esse backup é da {dados.get('modelo')}, "
                        f"mas a impressora conectada é a {ficha['nome']}.")
    print(f"Restaurando {len(dados['valores'])} endereços de {arquivo}")
    if not confirmar("Os valores do backup serão gravados."):
        print("Cancelado.")
        return
    for end, val in dados["valores"].items():
        imp.gravar(int(end, 16), val)
        print(f"  {end} <- 0x{val:02X}  ok")
    print("Restaurado. Reinicie a impressora.")


def executar(acao, debug=False, *extra):
    try:
        with conectar(debug) as imp:
            acao(imp, *extra)
    except Cancelado as e:
        print(f"\n{e}")
    except (ErroD4, ErroEpson, OSError) as e:
        print(f"\nERRO: {e}")
        print("Dica: feche o Epson Status Monitor, confira o cabo e tente de novo.")


# --------------------------------------------------------------- menu
def escolher_backup():
    backups = sorted(PASTA_BACKUP.glob("backup-*.json"), reverse=True)
    if not backups:
        print("\nNenhum backup encontrado na pasta 'backups'.")
        return None
    print("\nBackups disponíveis:")
    for i, b in enumerate(backups[:10], 1):
        print(f"  {i} - {b.name}")
    esc = input("Número do backup (Enter para voltar): ").strip()
    if esc.isdigit() and 1 <= int(esc) <= len(backups[:10]):
        return backups[int(esc) - 1]
    return None


def menu(debug=False):
    print("=" * 56)
    print(f"  Resetter Epson USB  v{VERSAO}  ({total_modelos()} modelos no banco)")
    print("=" * 56)
    while True:
        print("\n  1 - Ler contadores (não altera nada)")
        print("  2 - Zerar contadores de tinta descartada")
        print("  3 - Restaurar um backup")
        print("  0 - Sair")
        op = input("\nEscolha: ").strip()
        if op == "1":
            executar(acao_ler, debug)
        elif op == "2":
            executar(acao_zerar, debug)
        elif op == "3":
            arq = escolher_backup()
            if arq:
                executar(acao_restaurar, debug, arq)
        elif op == "0":
            return
        else:
            print("Opção inválida.")


def main():
    p = argparse.ArgumentParser(description="Resetter Epson via USB")
    p.add_argument("--debug", action="store_true", help="mostra os bytes trocados")
    sub = p.add_subparsers(dest="comando")
    sub.add_parser("ler")
    sub.add_parser("zerar")
    sub.add_parser("restaurar").add_argument("arquivo")
    args = p.parse_args()

    if args.comando is None:
        menu(args.debug)
    elif args.comando == "ler":
        executar(acao_ler, args.debug)
    elif args.comando == "zerar":
        executar(acao_zerar, args.debug)
    else:
        executar(acao_restaurar, args.debug, args.arquivo)


if __name__ == "__main__":
    main()
