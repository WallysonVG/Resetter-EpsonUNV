# Resetter - EpsonUNV

**Baixar:** [`release/ResetEpson.exe`](release/ResetEpson.exe) — roda em qualquer Windows, sem Python.

Lê e zera os contadores de tinta descartada de impressoras Epson ligadas na USB.
Reconhece o modelo sozinho e traz um banco com 1.589 modelos, cerca de 1.000 deles
com reset completo conhecido (L3250, L3150, L4260, L1800, ET-2810, XP, WF e outros).

## Gerar o executável (uma vez só)

1. Num Windows com Python 3.10+ instalado (marque "Add Python to PATH" na instalação).
2. Dê dois cliques em `gerar_exe.bat`.
3. O programa fica em `dist\ResetEpson.exe`. Esse arquivo roda em qualquer Windows,
   sem Python. É só copiar.

## Usar

1. Ligue a impressora na USB e feche o **Epson Status Monitor** (ícone perto do relógio).
2. Abra o `ResetEpson.exe` (ou `python reset.py`).
3. Escolha no menu:
   - **1 - Ler contadores**: só mostra, não altera nada. Faça isso primeiro.
   - **2 - Zerar**: salva um backup em `backups\` e pede confirmação (S/N) antes de gravar.
   - **3 - Restaurar**: volta os valores de um backup.
4. Depois de zerar, desligue a impressora, espere 10 segundos e ligue de novo.

O reset fica gravado na impressora: rodando uma vez, ela volta a funcionar
em qualquer computador.

## Observações

- A porcentagem só aparece para a família L3250, que tem os limites conhecidos.
  Nos outros modelos o programa mostra os valores brutos.
- Alguns modelos do banco ainda não têm a chave de gravação conhecida. Para esses,
  o programa só lê e avisa que não consegue zerar.
- O antivírus pode estranhar o .exe (falso positivo comum do PyInstaller).
- Para ver os bytes trocados com a impressora: `python reset.py --debug ler`.

## Cuidado

Zerar o contador não esvazia a esponja de descarte. Se ela estiver encharcada,
a tinta pode vazar por baixo da impressora. O ideal é instalar uma mangueira
para um pote externo (tanque de tinta residual) ou trocar as esponjas.

## Arquivos

| Arquivo            | O que faz                                                     |
|--------------------|---------------------------------------------------------------|
| `reset.py`         | O programa (menu e linha de comando)                          |
| `usb_windows.py`   | Acha a impressora e abre a USB pelo driver do Windows         |
| `d4.py`            | Protocolo IEEE 1284.4 ("D4"), canal de controle da Epson      |
| `epson.py`         | Comandos Epson: identificar, ler e gravar a EEPROM            |
| `modelos.py`       | Escolhe a ficha do modelo detectado                           |
| `banco_modelos.py` | Chaves e endereços de 227 famílias / 1.589 modelos            |
| `gerar_exe.bat`    | Gera o `ResetEpson.exe`                                       |

## Créditos e licença

O banco de modelos e o protocolo vêm do projeto open-source **reinkpy**
(codeberg.org/atufi/reinkpy), licenciado sob AGPL-3.0. Se você distribuir
este programa, mantenha o código aberto e os créditos.
