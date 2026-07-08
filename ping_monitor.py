# -*- coding: utf-8 -*-
"""
Monitor de Conexão (Ping Monitor)
---------------------------------
- Interface gráfica em Tkinter
- Minimiza para a bandeja do sistema (pystray)
- Faz ping contínuo (padrão: a cada 1 segundo) para o host/IP informado
- Registra em arquivo (CSV) SOMENTE quando a conexão cai:
    Data, Hora, Endereço (host/IP), Causa do problema
- Registra também a reconexão, com a duração da queda (opcional, bônus)
- Toca um som de alerta ("ping" de sonar sintetizado) no momento da queda

Dependências (instalar antes de usar):
    pip install pystray pillow

Compatível com Windows e Linux.
"""

import os
import re
import csv
import io
import json
import time
import math
import wave
import queue
import tempfile
import platform
import threading
import subprocess
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import winsound
    SOM_DISPONIVEL = True
except ImportError:
    SOM_DISPONIVEL = False

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_DISPONIVEL = True
except ImportError:
    TRAY_DISPONIVEL = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config_ping_monitor.json")
LOG_PADRAO = os.path.join(BASE_DIR, "quedas_conexao.csv")


# --------------------------------------------------------------------------
# Lógica de ping (independente da GUI)
# --------------------------------------------------------------------------
def executar_ping(host, timeout_seg=1):
    """
    Executa um ping único para o host informado.
    Retorna (sucesso: bool, causa: str)
    """
    sistema = platform.system().lower()

    if sistema == "windows":
        timeout_ms = max(1, int(timeout_seg * 1000))
        comando = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        comando = ["ping", "-c", "1", "-W", str(max(1, int(timeout_seg))), host]

    # No Windows, evita que uma janela de console pisque a cada ping executado
    kwargs_extra = {}
    if sistema == "windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs_extra["startupinfo"] = startupinfo
        kwargs_extra["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        resultado = subprocess.run(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seg + 3,
            **kwargs_extra,
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout ao executar o comando ping"
    except FileNotFoundError:
        return False, "Comando 'ping' não encontrado no sistema"
    except Exception as exc:
        return False, f"Erro inesperado: {exc}"

    saida = (resultado.stdout or "") + (resultado.stderr or "")
    saida_lower = saida.lower()
    sucesso = resultado.returncode == 0

    if sucesso:
        return True, ""

    # Tenta identificar a causa provável do erro
    if any(t in saida_lower for t in [
        "could not find host", "unknown host", "name or service not known",
        "não é possível localizar", "temporary failure in name resolution",
    ]):
        causa = "Erro de DNS / host não encontrado"
    elif any(t in saida_lower for t in [
        "destination host unreachable", "host de destino inacessível",
        "network is unreachable", "rede inacessível",
    ]):
        causa = "Host/rede inacessível"
    elif any(t in saida_lower for t in [
        "request timed out", "esgotado o tempo", "100% packet loss",
        "100% de perda", "100% perda",
    ]):
        causa = "Timeout (sem resposta do host)"
    else:
        causa = "Falha desconhecida (ver detalhes no console)"

    return False, causa


# --------------------------------------------------------------------------
# Som de alerta ("ping" de sonar) sintetizado — sem precisar de arquivo externo
# --------------------------------------------------------------------------
def gerar_wav_sonar(frequencia=1500, duracao=0.9, taxa_amostragem=44100, ecos=2, volume=1.0):
    """
    Gera, em memória, um WAV de um 'ping' de sonar: tom puro com decaimento
    exponencial (fade-out) e um leve eco, para simular o som clássico de sonar.
    'volume' vai de 0.0 (mudo) a 1.0 (volume máximo).
    Retorna os bytes do arquivo WAV.
    """
    volume = max(0.0, min(1.0, volume))
    n_amostras = int(taxa_amostragem * duracao)
    amostras = [0.0] * n_amostras

    def somar_tom(inicio_seg, freq, amplitude, decaimento):
        inicio = int(inicio_seg * taxa_amostragem)
        for i in range(inicio, n_amostras):
            t = (i - inicio) / taxa_amostragem
            env = amplitude * math.exp(-decaimento * t)  # fade-out exponencial
            valor = env * math.sin(2 * math.pi * freq * t)
            amostras[i] += valor

    # Tom principal + ecos mais fracos (efeito "sonar" clássico)
    somar_tom(0.0, frequencia, amplitude=0.9, decaimento=4.0)
    for e in range(1, ecos + 1):
        somar_tom(0.18 * e, frequencia, amplitude=0.9 * (0.45 ** e), decaimento=4.0)

    # Normaliza (evita distorção) e aplica o volume desejado antes de converter para PCM 16-bit
    pico = max(1e-9, max(abs(a) for a in amostras))
    dados_pcm = bytearray()
    for a in amostras:
        valor = int(max(-1.0, min(1.0, a / pico)) * 32767 * volume)
        dados_pcm += valor.to_bytes(2, byteorder="little", signed=True)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(taxa_amostragem)
        wav_file.writeframes(bytes(dados_pcm))

    return buffer.getvalue()



class PingMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor de Conexão - Ping")
        self.root.geometry("620x480")
        self.root.minsize(560, 420)

        self.monitorando = False
        self.thread_monitor = None
        self.status_atual = None  # True = ok, False = caiu, None = ainda não testou
        self.momento_queda = None
        self.fila_eventos = queue.Queue()

        self.icone_bandeja = None
        self.thread_bandeja = None

        self._carregar_config()

        self._som_sonar_path = None
        if SOM_DISPONIVEL:
            try:
                dados_wav = gerar_wav_sonar(volume=self.config.get("volume", 0.1))
                caminho_temp = os.path.join(tempfile.gettempdir(), "ping_monitor_sonar.wav")
                with open(caminho_temp, "wb") as f:
                    f.write(dados_wav)
                self._som_sonar_path = caminho_temp
            except Exception:
                self._som_sonar_path = None

        self._montar_interface()
        self._carregar_historico_log()

        self.root.protocol("WM_DELETE_WINDOW", self.minimizar_para_bandeja)
        self.root.after(200, self._processar_fila_eventos)

    # ---------------------------- Configuração ---------------------------
    def _carregar_config(self):
        self.config = {
            "host": "8.8.8.8",
            "intervalo": 1,
            "log_path": LOG_PADRAO,
        }
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    self.config.update(dados)
            except Exception:
                pass

    def _salvar_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _salvar_config_e(self, **kwargs):
        self.config.update(kwargs)
        self._salvar_config()

    # ---------------------------- Interface --------------------------------
    def _montar_interface(self):
        estilo = ttk.Style()
        try:
            estilo.theme_use("clam")
        except Exception:
            pass

        # --- Frame de configuração do ping ---
        frame_topo = ttk.LabelFrame(self.root, text="Configuração do monitoramento")
        frame_topo.pack(fill="x", padx=10, pady=8)

        ttk.Label(frame_topo, text="Host / IP:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.entry_host = ttk.Entry(frame_topo, width=30)
        self.entry_host.insert(0, self.config.get("host", "8.8.8.8"))
        self.entry_host.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(frame_topo, text="Intervalo (s):").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        self.spin_intervalo = ttk.Spinbox(frame_topo, from_=1, to=60, width=5)
        self.spin_intervalo.set(self.config.get("intervalo", 1))
        self.spin_intervalo.grid(row=0, column=3, padx=6, pady=6, sticky="w")

        self.btn_iniciar = ttk.Button(frame_topo, text="Iniciar monitoramento", command=self.iniciar_monitoramento)
        self.btn_iniciar.grid(row=0, column=4, padx=6, pady=6)

        self.btn_parar = ttk.Button(frame_topo, text="Parar", command=self.parar_monitoramento, state="disabled")
        self.btn_parar.grid(row=0, column=5, padx=6, pady=6)

        self.var_som = tk.BooleanVar(value=self.config.get("som_ativo", True))
        chk_som = ttk.Checkbutton(
            frame_topo, text="Tocar som ao cair a conexão", variable=self.var_som,
            command=lambda: self._salvar_config_e(som_ativo=self.var_som.get()),
        )
        chk_som.grid(row=1, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="w")

        ttk.Label(frame_topo, text="Volume:").grid(row=1, column=2, padx=(6, 0), pady=(0, 6), sticky="e")
        self.var_volume = tk.DoubleVar(value=self.config.get("volume", 0.1) * 100)
        self.slider_volume = ttk.Scale(
            frame_topo, from_=0, to=100, orient="horizontal", variable=self.var_volume,
            length=110, command=self._on_alterar_volume,
        )
        self.slider_volume.grid(row=1, column=3, padx=6, pady=(0, 6), sticky="w")

        btn_testar_som = ttk.Button(frame_topo, text="Testar som", command=self._tocar_som_queda)
        btn_testar_som.grid(row=1, column=4, padx=6, pady=(0, 6), sticky="w")

        if not SOM_DISPONIVEL:
            chk_som.config(state="disabled")
            self.slider_volume.config(state="disabled")
            btn_testar_som.config(state="disabled")
            ttk.Label(
                frame_topo, text="(som indisponível neste sistema)", foreground="red"
            ).grid(row=1, column=5, sticky="w")

        # --- Frame de status ---
        frame_status = ttk.Frame(self.root)
        frame_status.pack(fill="x", padx=10, pady=4)

        self.canvas_led = tk.Canvas(frame_status, width=18, height=18, highlightthickness=0)
        self.led = self.canvas_led.create_oval(2, 2, 16, 16, fill="grey")
        self.canvas_led.pack(side="left", padx=(4, 8))

        self.label_status = ttk.Label(frame_status, text="Aguardando início...", font=("Segoe UI", 10, "bold"))
        self.label_status.pack(side="left")

        self.label_ultima_verificacao = ttk.Label(frame_status, text="")
        self.label_ultima_verificacao.pack(side="right", padx=6)

        # --- Frame do log de quedas ---
        frame_log = ttk.LabelFrame(self.root, text="Histórico de quedas de conexão")
        frame_log.pack(fill="both", expand=True, padx=10, pady=8)

        colunas = ("data_hora", "endereco", "evento")
        self.tree = ttk.Treeview(frame_log, columns=colunas, show="headings", height=12)
        self.tree.heading("data_hora", text="Data / Hora")
        self.tree.heading("endereco", text="Endereço")
        self.tree.heading("evento", text="Evento / Causa")
        self.tree.column("data_hora", width=150, anchor="center")
        self.tree.column("endereco", width=140, anchor="center")
        self.tree.column("evento", width=280, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)

        scroll = ttk.Scrollbar(frame_log, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", pady=6)

        # --- Frame inferior (log file + bandeja) ---
        frame_rodape = ttk.Frame(self.root)
        frame_rodape.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(frame_rodape, text="Arquivo de log:").pack(side="left")
        self.label_log_path = ttk.Label(frame_rodape, text=self.config.get("log_path", LOG_PADRAO), foreground="#555")
        self.label_log_path.pack(side="left", padx=6)

        ttk.Button(frame_rodape, text="Alterar...", command=self._alterar_log_path).pack(side="left", padx=4)

        ttk.Button(
            frame_rodape, text="Minimizar para bandeja", command=self.minimizar_para_bandeja
        ).pack(side="right")

        if not TRAY_DISPONIVEL:
            ttk.Label(
                frame_rodape,
                text="(instale 'pystray' e 'pillow' para habilitar a bandeja)",
                foreground="red",
            ).pack(side="right", padx=8)

    def _alterar_log_path(self):
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=os.path.basename(self.config.get("log_path", LOG_PADRAO)),
        )
        if caminho:
            self.config["log_path"] = caminho
            self.label_log_path.config(text=caminho)
            self._salvar_config()
            self._carregar_historico_log()

    # ---------------------------- Log em arquivo ---------------------------
    def _garantir_arquivo_log(self):
        caminho = self.config["log_path"]
        if not os.path.exists(caminho):
            with open(caminho, "w", newline="", encoding="utf-8") as f:
                escritor = csv.writer(f, delimiter=";")
                escritor.writerow(["Data", "Hora", "Endereco", "Evento"])

    def _gravar_evento_log(self, momento, endereco, evento):
        self._garantir_arquivo_log()
        with open(self.config["log_path"], "a", newline="", encoding="utf-8") as f:
            escritor = csv.writer(f, delimiter=";")
            escritor.writerow([
                momento.strftime("%d/%m/%Y"),
                momento.strftime("%H:%M:%S"),
                endereco,
                evento,
            ])

    def _carregar_historico_log(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        caminho = self.config.get("log_path", LOG_PADRAO)
        if not os.path.exists(caminho):
            return
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                leitor = csv.reader(f, delimiter=";")
                linhas = list(leitor)[1:]  # pula cabeçalho
                for linha in linhas[-200:]:
                    if len(linha) >= 4:
                        data_hora = f"{linha[0]} {linha[1]}"
                        self.tree.insert("", "end", values=(data_hora, linha[2], linha[3]))
                if linhas:
                    self.tree.see(self.tree.get_children()[-1])
        except Exception:
            pass

    # ---------------------------- Som de alerta -----------------------------
    def _on_alterar_volume(self, valor=None):
        # Debounce: só regrava o arquivo .wav quando o usuário parar de arrastar o slider
        if hasattr(self, "_job_volume") and self._job_volume:
            self.root.after_cancel(self._job_volume)
        self._job_volume = self.root.after(250, self._aplicar_volume)

    def _aplicar_volume(self):
        volume = self.var_volume.get() / 100.0
        self._salvar_config_e(volume=volume)
        if not SOM_DISPONIVEL:
            return
        try:
            dados_wav = gerar_wav_sonar(volume=volume)
            with open(self._som_sonar_path, "wb") as f:
                f.write(dados_wav)
        except Exception as exc:
            print(f"[aviso] Não foi possível atualizar o volume do som: {exc}")

    def _tocar_som_queda(self):
        if not SOM_DISPONIVEL or not self._som_sonar_path:
            return
        try:
            winsound.PlaySound(
                self._som_sonar_path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception as exc:
            print(f"[aviso] Não foi possível tocar o som de alerta: {exc}")

    # ---------------------------- Monitoramento -----------------------------
    def iniciar_monitoramento(self):
        host = self.entry_host.get().strip()
        if not host:
            messagebox.showwarning("Atenção", "Informe um host ou endereço IP para monitorar.")
            return

        try:
            intervalo = int(self.spin_intervalo.get())
            if intervalo < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Atenção", "Intervalo inválido, use um número inteiro >= 1.")
            return

        self.config["host"] = host
        self.config["intervalo"] = intervalo
        self._salvar_config()

        self.monitorando = True
        self.status_atual = None
        self.momento_queda = None

        self.btn_iniciar.config(state="disabled")
        self.btn_parar.config(state="normal")
        self.entry_host.config(state="disabled")
        self.spin_intervalo.config(state="disabled")

        self.thread_monitor = threading.Thread(
            target=self._loop_monitoramento, args=(host, intervalo), daemon=True
        )
        self.thread_monitor.start()

    def parar_monitoramento(self):
        self.monitorando = False
        self.btn_iniciar.config(state="normal")
        self.btn_parar.config(state="disabled")
        self.entry_host.config(state="normal")
        self.spin_intervalo.config(state="normal")
        self.fila_eventos.put(("status", None, "Monitoramento parado.", "grey"))

    def _loop_monitoramento(self, host, intervalo):
        while self.monitorando:
            ok, causa = executar_ping(host, timeout_seg=1)
            agora = datetime.now()

            if ok:
                if self.status_atual is False:
                    # reconectou
                    duracao = ""
                    if self.momento_queda:
                        segs = int((agora - self.momento_queda).total_seconds())
                        duracao = f" (fora do ar por {segs}s)"
                    evento = f"Conexão restabelecida{duracao}"
                    self._gravar_evento_log(agora, host, evento)
                    self.fila_eventos.put(("linha", agora, host, evento))
                self.status_atual = True
                self.fila_eventos.put((
                    "status", agora, f"Conectado — última checagem: {agora.strftime('%H:%M:%S')}", "green",
                ))
            else:
                if self.status_atual is not False:
                    self.momento_queda = agora
                    self._gravar_evento_log(agora, host, causa)
                    self.fila_eventos.put(("linha", agora, host, causa))
                    if self.var_som.get():
                        self._tocar_som_queda()
                self.status_atual = False
                self.fila_eventos.put((
                    "status", agora, f"SEM CONEXÃO — {causa}", "red",
                ))

            time.sleep(intervalo)

    def _processar_fila_eventos(self):
        try:
            while True:
                item = self.fila_eventos.get_nowait()
                tipo = item[0]
                if tipo == "status":
                    _, momento, texto, cor = item
                    self.label_status.config(text=texto)
                    self.canvas_led.itemconfig(self.led, fill=cor)
                    if momento:
                        self.label_ultima_verificacao.config(
                            text=f"Última verificação: {momento.strftime('%d/%m/%Y %H:%M:%S')}"
                        )
                    if self.icone_bandeja:
                        self._atualizar_icone_bandeja(cor)
                elif tipo == "linha":
                    _, momento, host, evento = item
                    data_hora = momento.strftime("%d/%m/%Y %H:%M:%S")
                    self.tree.insert("", "end", values=(data_hora, host, evento))
                    self.tree.see(self.tree.get_children()[-1])
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._processar_fila_eventos)

    # ---------------------------- Bandeja do sistema ------------------------
    def _criar_imagem_icone(self, cor="grey"):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        desenho = ImageDraw.Draw(img)
        cores = {"green": (46, 204, 113), "red": (231, 76, 60), "grey": (149, 165, 166)}
        rgb = cores.get(cor, cores["grey"])
        desenho.ellipse((8, 8, 56, 56), fill=rgb)
        return img

    def _atualizar_icone_bandeja(self, cor):
        if self.icone_bandeja:
            try:
                self.icone_bandeja.icon = self._criar_imagem_icone(cor)
            except Exception:
                pass

    def minimizar_para_bandeja(self):
        if not TRAY_DISPONIVEL:
            messagebox.showinfo(
                "Bandeja indisponível",
                "Para minimizar para a bandeja, instale as dependências:\n\n"
                "pip install pystray pillow",
            )
            return

        self.root.withdraw()

        if self.icone_bandeja is None:
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar janela", self._mostrar_janela, default=True),
                pystray.MenuItem("Sair", self._sair_aplicacao),
            )
            self.icone_bandeja = pystray.Icon(
                "ping_monitor", self._criar_imagem_icone("grey"), "Monitor de Conexão", menu
            )
            self.thread_bandeja = threading.Thread(target=self.icone_bandeja.run, daemon=True)
            self.thread_bandeja.start()

    def _mostrar_janela(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _sair_aplicacao(self, icon=None, item=None):
        self.monitorando = False
        if self.icone_bandeja:
            self.icone_bandeja.stop()
        self.root.after(0, self.root.destroy)


def main():
    root = tk.Tk()
    app = PingMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
