"""
Implementação mínima do IEEE 1284.4 ("D4"), o protocolo que as impressoras
Epson usam por cima da USB para separar canais (impressão, controle etc.).

Fluxo:
  1. Mandar o comando EJL que coloca a impressora no modo D4
  2. Init           -> negociar a revisão do protocolo
  3. GetSocketID    -> descobrir o número do canal "EPSON-CTRL"
  4. OpenChannel    -> abrir o canal
  5. trocar mensagens (cada envio gasta 1 "crédito"; créditos vêm da impressora)
  6. CloseChannel + Exit

Referência: projeto reinkpy (https://codeberg.org/atufi/reinkpy).
"""
import struct
import time

ENTRAR_D4 = b"\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL\n@EJL\n"
RESPOSTA_ENTRAR_D4 = b"\x00\x00\x00\x08\x01\x00\xc5\x00"

CABECALHO = struct.Struct(">BBHBB")  # psid, ssid, tamanho total, crédito, controle

ERROS = {
    0x80: "pacote malformado",
    0x81: "pacote enviado sem crédito",
    0x82: "resposta sem comando correspondente",
    0x83: "pacote maior que o permitido",
    0x84: "canal não está aberto",
    0x85: "resultado desconhecido",
    0x86: "estouro de crédito",
    0x87: "comando reservado/obsoleto",
}


class ErroD4(Exception):
    pass


class LinkD4:
    def __init__(self, io, log=None):
        self.io = io
        self.log = log or (lambda *a: None)
        self.revisao = 0x20
        self.creditos = {}       # (psid, ssid) -> créditos que temos para enviar
        self.buffer = b""
        self.pendentes = {}      # (psid, ssid) -> lista de payloads recebidos

    # ------------------------------------------------------------ baixo nível
    def _enviar_pacote(self, sid, payload, credito=1):
        pacote = CABECALHO.pack(sid[0], sid[1], CABECALHO.size + len(payload), credito, 0) + payload
        self.log(f"  >> {pacote.hex(' ')}")
        self.io.write(pacote)

    def _receber_pacote(self, tentativas=8):
        """Lê da USB até ter um pacote D4 completo. Retorna (sid, payload)."""
        for _ in range(tentativas):
            if len(self.buffer) >= CABECALHO.size:
                psid, ssid, tam, cred, _ctl = CABECALHO.unpack(self.buffer[:CABECALHO.size])
                if tam < CABECALHO.size:
                    # lixo no buffer (ex.: resto da resposta EJL); descarta 1 byte
                    self.buffer = self.buffer[1:]
                    continue
                if len(self.buffer) >= tam:
                    payload = self.buffer[CABECALHO.size:tam]
                    self.buffer = self.buffer[tam:]
                    sid = (psid, ssid)
                    self.creditos[sid] = self.creditos.get(sid, 0) + cred  # crédito "de carona"
                    self.log(f"  << [{psid},{ssid}] {payload.hex(' ')}")
                    return sid, payload
            dados = self.io.read()
            if dados:
                self.buffer += bytes(dados)
        return None, None

    # ------------------------------------------------- canal de transação (0,0)
    def _txn(self, codigo, corpo=b"", gasta_credito=True):
        sid = (0, 0)
        if gasta_credito:
            if self.creditos.get(sid, 0) < 1:
                raise ErroD4("sem crédito no canal de transação")
            self.creditos[sid] -= 1
        self._enviar_pacote(sid, bytes([codigo]) + corpo)
        esperado = codigo | 0x80
        for _ in range(8):
            rsid, payload = self._receber_pacote()
            if rsid is None:
                break
            if rsid != sid:
                if payload:
                    self.pendentes.setdefault(rsid, []).append(payload)
                continue
            if not payload:  # pacote só com crédito
                continue
            if payload[0] == 0x7F:
                cod = payload[3] if len(payload) > 3 else 0
                raise ErroD4(f"impressora respondeu erro 0x{cod:02X}: {ERROS.get(cod, '?')}")
            if payload[0] == esperado:
                return payload[1:]
        raise ErroD4(f"sem resposta para o comando 0x{codigo:02X}")

    # ----------------------------------------------------------- comandos D4
    def iniciar(self):
        """Entra no modo D4. Se a impressora estiver presa numa sessão anterior
        (nossa ou do driver da Epson), faz um soft reset da USB — o mesmo efeito
        de tirar e colocar o cabo — e tenta de novo."""
        try:
            self._entrar()
        except (OSError, ErroD4) as e:
            resetar = getattr(self.io, "soft_reset", None)
            if resetar is None:
                raise
            self.log(f"  a impressora não respondeu ({e}); reiniciando a conexão USB...")
            resetar()
            time.sleep(1.5)
            self.buffer = b""
            self.creditos = {}
            self.pendentes = {}
            self.revisao = 0x20
            self._entrar()

    def _entrar(self):
        self.log("Entrando no modo IEEE 1284.4...")
        self.io.write(ENTRAR_D4)
        resp = b""
        for _ in range(5):
            dados = self.io.read()
            if dados:
                resp += bytes(dados)
            if RESPOSTA_ENTRAR_D4 in resp:
                break
        else:
            self.log(f"  aviso: resposta inesperada ao entrar no D4: {resp.hex(' ')}")
        self.buffer = b""
        self._init(0x20)

    def _init(self, revisao):
        r = self._txn(0x00, bytes([revisao]), gasta_credito=False)
        resultado, rev = r[0], (r[1] if len(r) > 1 else revisao)
        if resultado == 0x00:
            self.revisao = revisao
            self.log(f"  Init OK (revisão 0x{revisao:02X})")
            return
        if resultado == 0x02 and rev != revisao and rev in (0x10, 0x20):
            self.log(f"  impressora pediu a revisão 0x{rev:02X}")
            return self._init(rev)
        raise ErroD4(f"Init falhou (resultado 0x{resultado:02X})")

    def id_do_canal(self, nome, padrao):
        try:
            r = self._txn(0x09, nome.encode("ascii"))
            if r[0] == 0x00:
                return (r[1], r[1])
        except ErroD4 as e:
            self.log(f"  GetSocketID falhou ({e}); usando canal padrão")
        return padrao

    def abrir_canal(self, sid):
        if self.revisao == 0x10:
            corpo = struct.pack(">BBHHHH", sid[0], sid[1], 0x100, 0x100, 0, 0)
        else:
            corpo = struct.pack(">BBHHH", sid[0], sid[1], 0x100, 0x100, 0)
        r = self._txn(0x01, corpo)
        if r[0] != 0x00:
            raise ErroD4(f"não abriu o canal {sid} (resultado 0x{r[0]:02X})")
        if len(r) >= 11:  # crédito concedido na abertura
            self.creditos[sid] = self.creditos.get(sid, 0) + struct.unpack(">H", r[9:11])[0]
        self.creditos.setdefault(sid, 0)

    def pedir_credito(self, sid):
        if self.revisao == 0x10:
            corpo = struct.pack(">BBHH", sid[0], sid[1], 0x0080, 0xFFFF)
        else:
            corpo = struct.pack(">BBH", sid[0], sid[1], 0)
        r = self._txn(0x04, corpo)
        if r[0] == 0x00 and len(r) >= 5:
            self.creditos[sid] = self.creditos.get(sid, 0) + struct.unpack(">H", r[3:5])[0]

    def fechar_canal(self, sid):
        corpo = bytes([sid[0], sid[1]]) + (b"\x00" if self.revisao == 0x10 else b"")
        try:
            self._txn(0x02, corpo)
        except ErroD4 as e:
            self.log(f"  aviso ao fechar canal: {e}")

    def sair(self):
        try:
            self._txn(0x08)
        except ErroD4 as e:
            self.log(f"  aviso ao sair do D4: {e}")

    # ------------------------------------------------------- troca de dados
    def conversar(self, sid, mensagem):
        """Envia uma mensagem no canal e devolve a resposta (bytes)."""
        for _ in range(3):
            if self.creditos.get(sid, 0) >= 1:
                break
            self.pedir_credito(sid)
        else:
            raise ErroD4(f"impressora não liberou crédito no canal {sid}")
        self.creditos[sid] -= 1
        self._enviar_pacote(sid, mensagem)

        fila = self.pendentes.get(sid)
        if fila:
            return fila.pop(0)
        for _ in range(8):
            rsid, payload = self._receber_pacote()
            if rsid is None:
                break
            if rsid == sid and payload:
                return payload
            if rsid != sid and payload:
                self.pendentes.setdefault(rsid, []).append(payload)
        raise ErroD4("a impressora não respondeu no canal de controle")

    def aguardar(self, segundos=0.05):
        time.sleep(segundos)
