"""
Comandos da Epson enviados pelo canal EPSON-CTRL.

Formato de uma mensagem:  2 letras  +  tamanho (2 bytes, little-endian)  +  dados
  ex.: b"di" + b"\x01\x00" + b"\x01"   -> pede a identificação da impressora

Leitura/gravação da EEPROM usa o comando "||" (de fábrica):
  dados = chave_do_modelo (2 bytes) + letra + ~letra + letra rotacionada + parâmetros
    letra "A" = ler    -> parâmetros: endereço (2 bytes)
    letra "B" = gravar -> parâmetros: endereço (2 bytes) + valor (1 byte) + chave de gravação (8 bytes)
"""
import re
import struct

from d4 import LinkD4

CANAL_CTRL_PADRAO = (0x02, 0x02)


class ErroEpson(Exception):
    pass


def montar(cmd: bytes, dados: bytes = b"") -> bytes:
    return cmd + struct.pack("<H", len(dados)) + dados


def montar_fabrica(chave_leitura: int, letra: str, parametros: bytes) -> bytes:
    c = ord(letra)
    cabecalho = struct.pack("<HBBB", chave_leitura, c, ~c & 0xFF,
                            ((c >> 1) & 0x7F) | ((c << 7) & 0x80))
    return montar(b"||", cabecalho + parametros)


class ImpressoraEpson:
    def __init__(self, io, modelo=None, log=None):
        self.io = io
        self.modelo = modelo
        self.log = log or (lambda *a: None)
        self.d4 = LinkD4(io, log=self.log)
        self.ctrl = None

    def __enter__(self):
        self.io.__enter__()
        try:
            self.d4.iniciar()
            self.ctrl = self.d4.id_do_canal("EPSON-CTRL", CANAL_CTRL_PADRAO)
            self.d4.abrir_canal(self.ctrl)
        except Exception:
            self.io.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        try:
            self.d4.fechar_canal(self.ctrl)
            self.d4.sair()
        finally:
            self.io.__exit__(*exc)

    def _cmd(self, mensagem: bytes) -> bytes:
        return self.d4.conversar(self.ctrl, mensagem)

    # ------------------------------------------------------------------
    def identificacao(self) -> dict:
        """Pergunta à impressora quem ela é (fabricante, modelo, série...)."""
        r = self._cmd(montar(b"di", b"\x01")).decode("ascii", "replace")
        texto = r.split("@EJL ID", 1)[-1].strip()
        campos = {}
        for parte in texto.split(";"):
            chave, _, valor = parte.partition(":")
            if chave.strip():
                campos[chave.strip()] = valor.strip()
        return campos

    def ler(self, endereco: int) -> int:
        fmt = "<B" if self.modelo["rlen"] == 1 else "<H"
        msg = montar_fabrica(self.modelo["chave_leitura"], "A", struct.pack(fmt, endereco))
        r = self._cmd(msg).decode("ascii", "replace")
        # resposta típica: "@BDC PS\r\nEE:0030C9;"  -> endereço 0x0030, valor 0xC9
        m = re.search(r"EE:([0-9A-Fa-f]{4,6});", r)
        if not m:
            raise ErroEpson(f"Resposta inválida lendo 0x{endereco:03X}: {r!r}")
        dados = bytes.fromhex(m.group(1))
        end_resp, valor = int.from_bytes(dados[:-1], "big"), dados[-1]
        if end_resp != endereco:
            raise ErroEpson(f"Pedi 0x{endereco:03X} e veio 0x{end_resp:03X}")
        return valor

    def gravar(self, endereco: int, valor: int) -> None:
        fmt = "<BB" if self.modelo["wlen"] == 1 else "<HB"
        params = struct.pack(fmt, endereco, valor) + self.modelo["chave_gravacao"]
        r = self._cmd(montar_fabrica(self.modelo["chave_leitura"], "B", params))
        if b":OK;" not in r:
            raise ErroEpson(f"Impressora recusou gravar 0x{endereco:03X}: {r!r}")
        lido = self.ler(endereco)
        if lido != valor:
            raise ErroEpson(f"Gravei 0x{valor:02X} em 0x{endereco:03X} mas li 0x{lido:02X}")
