# PingMonitorPy


# Monitor de Conexão — Manual de Uso

Aplicativo desktop para monitorar continuamente a conexão com um host/IP (ping), com
interface gráfica, ícone na bandeja do sistema, alerta sonoro e registro automático
de quedas de conexão.

---

## 1. Visão geral

O programa executa pings periódicos (padrão: 1 por segundo) contra um endereço definido
pelo usuário (IP ou host, ex: `8.8.8.8` ou `google.com` ou `123.123.123.2`). Enquanto a conexão estiver
normal, nada é gravado — o programa só registra um evento quando a conexão **cai** e
quando ela **volta**, evitando arquivos de log gigantes.

---

## 2. Funcionalidades

| Recurso | Descrição |
|---|---|
| Ping contínuo configurável | Endereço e intervalo (segundos) definidos na tela principal |
| Status em tempo real | Indicador colorido (verde/vermelho/cinza) + horário da última checagem |
| Log automático de quedas | Grava em CSV: **Data, Hora, Endereço, Causa** — apenas nas quedas |
| Registro de reconexão | Ao voltar a conexão, grava também **quanto tempo ficou fora do ar** |
| Detecção da causa | Diferencia: erro de DNS, host/rede inacessível, timeout, falha desconhecida |
| Histórico visual | Tabela na própria janela com os últimos eventos, carregada do CSV ao abrir |
| Minimizar para bandeja | Botão dedicado + fechar a janela (X) também manda para a bandeja |
| Ícone dinâmico na bandeja | Muda de cor conforme o status da conexão (verde/vermelho/cinza) |
| Alerta sonoro | "Ping de sonar" sintetizado, toca automaticamente quando a conexão cai |
| Volume ajustável | Slider de 0% a 100% (padrão: 10%), com botão "Testar som" |
| Configurações persistentes | Host, intervalo, caminho do log, volume e preferência de som são salvos entre execuções |
| Sem janelas de console piscando | Chamadas ao `ping` são executadas de forma totalmente oculta no Windows |

---

## 3. O que é necessário para rodar o `.exe`

Se você (ou quem for usar o programa) vai rodar o **executável já compilado**
(`MonitorConexao.exe`), gerado via PyInstaller:

- **Não precisa instalar Python.** O `.exe` já inclui tudo empacotado.
- **Sistema operacional:** Windows 10 ou 11 (64-bit recomendado).
- **Comando `ping` do sistema:** já vem por padrão em qualquer instalação do Windows —
  nada a instalar.
- **Permissões:** não precisa rodar como administrador.
- **Smart App Control / SmartScreen:** como o `.exe` não tem certificado de editor
  (assinatura digital), o Windows pode alertar na primeira execução ("Editor
  desconhecido" ou bloqueio do Controle de Aplicativo Inteligente). Nesses casos:
  - No aviso do SmartScreen, clique em **"Mais informações" → "Executar assim mesmo"**.
  - Se o **Controle de Aplicativo Inteligente** estiver ativo e bloqueando, prefira
    rodar o `.exe` a partir de um terminal (PowerShell) em vez de duplo-clique direto
    no atalho — costuma ser menos restritivo.
- **Antivírus:** alguns antivírus podem marcar executáveis Python empacotados como
  suspeitos por padrão (falso positivo comum do PyInstaller). Se acontecer, adicione
  uma exceção para o arquivo.

Resumindo: **para rodar o `.exe`, não é necessário instalar nada** — é só copiar o
arquivo para o computador e executar.

---

## 4. O que é necessário para rodar o código-fonte (`ping_monitor.py`)

Se em vez do `.exe` você for rodar o script Python diretamente:

1. **Python 3.9 ou superior** instalado
   - Baixe em [python.org/downloads](https://www.python.org/downloads/)
   - No instalador do Windows, marque **"Add python.exe to PATH"**
   - O componente **Tkinter** (interface gráfica) já vem incluso por padrão nesse
     instalador — nada extra a fazer no Windows
2. **Duas bibliotecas Python extras**, para a bandeja do sistema:
   ```
   pip install pystray pillow
   ```
   ou, usando o arquivo fornecido:
   ```
   pip install -r requirements.txt
   ```
3. Rodar o programa:
   ```
   python ping_monitor.py
   ```

> No Linux, o Tkinter pode não vir por padrão: `sudo apt install python3-tk`.
> O alerta sonoro usa o módulo `winsound`, disponível **apenas no Windows**; em
> outros sistemas a aplicação funciona normalmente, mas os controles de som ficam
> desativados automaticamente.

---

## 5. Como gerar o `.exe` (para quem for distribuir o programa)

```
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "MonitorConexao" ping_monitor.py
```

O executável final fica em `dist\MonitorConexao.exe`. As pastas `build\` e o arquivo
`.spec` gerados podem ser apagados — são temporários do processo de build.

---

## 6. Como usar

1. Abra o programa (`.exe` ou `python ping_monitor.py`).
2. No campo **Host / IP**, informe o endereço a monitorar (ex: `8.8.8.8`, `google.com`,
   IP do roteador, etc.).
3. Ajuste o **Intervalo (s)** entre pings, se quiser diferente de 1 segundo.
4. (Opcional) Marque/desmarque **"Tocar som ao cair a conexão"** e ajuste o **Volume**.
5. Clique em **Iniciar monitoramento**.
6. O indicador colorido mostra o status atual; a tabela abaixo lista o histórico de
   quedas e reconexões.
7. Para deixar rodando em segundo plano, clique em **Minimizar para bandeja** (ou
   simplesmente feche a janela pelo X — ela vai para a bandeja em vez de encerrar).
8. Para encerrar de fato, clique com o botão direito no ícone da bandeja e escolha
   **Sair**.

---

## 7. Arquivos gerados pelo programa

Todos criados na mesma pasta do `.exe` ou do `ping_monitor.py`:

| Arquivo | Conteúdo |
|---|---|
| `quedas_conexao.csv` | Histórico de quedas/reconexões (Data, Hora, Endereço, Evento), separado por `;` |
| `config_ping_monitor.json` | Preferências salvas: host, intervalo, caminho do log, volume, som ativo/inativo |

O som sintetizado também gera um arquivo temporário (`ping_monitor_sonar.wav`) na
pasta temporária do Windows — não precisa se preocupar com ele, é recriado
automaticamente a cada abertura do programa.

---

## 8. Especificações técnicas

- **Linguagem:** Python 3
- **Interface gráfica:** Tkinter (nativo do Python)
- **Bandeja do sistema:** biblioteca `pystray` + `Pillow` (geração dos ícones)
- **Ping:** módulo `subprocess`, chamando o `ping` nativo do sistema operacional
  (`-n`/`-w` no Windows, `-c`/`-W` no Linux/Mac)
- **Detecção de causa da queda:** análise da saída de texto do comando `ping`
  (DNS, host inacessível, timeout, etc.)
- **Log:** arquivo CSV (separador `;`), compatível com Excel/LibreOffice
- **Som de alerta:** sintetizado via `wave` + `math` (onda senoidal com decaimento
  exponencial e eco, sem depender de arquivos de áudio externos), reproduzido com
  `winsound` (Windows)
- **Threads:** o ping roda em uma thread separada da interface, para não travar a
  tela; a comunicação entre a thread de monitoramento e a interface usa uma fila
  (`queue.Queue`) processada a cada 200ms

---

## 9. Solução de problemas rápida

| Problema | Causa provável | Solução |
|---|---|---|
| `'pip' não é reconhecido` | Python não instalado ou fora do PATH | Reinstale marcando "Add to PATH", ou use `python -m pip install ...` |
| Console piscando a cada ping | Comportamento padrão do Windows ao chamar programas externos sem console pai | Já corrigido no código (flag `CREATE_NO_WINDOW`) |
| Aviso do Controle de Aplicativo Inteligente ao abrir o `.exe` | Executável sem assinatura digital reconhecida | Rodar via terminal, ou permitir a execução manualmente (ver seção 3) |
| Som não toca | Falha ao tocar som direto da memória (bug conhecido do Windows) | Já corrigido — som agora toca a partir de arquivo temporário |
| Log não aparece | Nenhuma queda ocorreu ainda, ou monitoramento não foi iniciado | Confirme que clicou em "Iniciar monitoramento" |

---
