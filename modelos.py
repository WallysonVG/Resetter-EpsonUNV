"""
Monta a "ficha" de cada modelo a partir do banco (banco_modelos.py).

Uma ficha tem:
  chave_leitura   2 bytes que liberam a leitura da EEPROM
  chave_gravacao  8 bytes que liberam a gravação (alguns modelos não têm)
  rlen / wlen     quantos bytes tem o endereço na leitura / gravação
  contadores      lista de (descrição, [endereços])
  reset           {endereço: valor} usado para zerar os contadores de tinta
  limites         % só para modelos em que o limite é conhecido
"""
import re

from banco_modelos import FAMILIAS

# Limites conhecidos (valor que corresponde a 100%) por endereço do byte baixo.
# Vêm do script público da L3250; para outros modelos mostramos só o valor.
LIMITES_L3250 = {0x30: 6345, 0x32: 3416, 0xFC: 1300}


def _normalizar(nome: str) -> str:
    return re.sub(r"\s+SERIES$", "", nome.strip().upper())


def _ficha(familia: dict, nome: str) -> dict:
    reset = {}
    for m in familia["mem"]:
        if re.search("waste counter", m["desc"], re.I):
            valores = m.get("reset") or [0] * len(m["addr"])
            reset.update(zip(m["addr"], valores))
    wkey = familia.get("wkey")
    return {
        "nome": nome,
        "chave_leitura": familia.get("rkey"),
        "chave_gravacao": wkey.encode("latin-1") if wkey else None,
        "rlen": familia["rlen"],
        "wlen": familia["wlen"],
        "contadores": [(m["desc"], m["addr"]) for m in familia["mem"]],
        "reset": reset,
        "limites": LIMITES_L3250 if "L3250" in familia["modelos"] else {},
    }


def achar_modelo(nome_impressora: str):
    nome = _normalizar(nome_impressora)
    for fam in FAMILIAS:
        if nome in fam["modelos"]:
            return _ficha(fam, nome)
    return None


def pode_ler(ficha: dict) -> bool:
    return ficha["chave_leitura"] is not None


def pode_zerar(ficha: dict) -> tuple[bool, str]:
    if not ficha["chave_gravacao"]:
        return False, "a chave de gravação deste modelo ainda não é conhecida"
    if ficha["chave_leitura"] is None:
        return False, "a chave de leitura deste modelo ainda não é conhecida"
    if not ficha["reset"]:
        return False, "os endereços dos contadores deste modelo não são conhecidos"
    return True, ""


def total_modelos() -> int:
    return sum(len(f["modelos"]) for f in FAMILIAS)
