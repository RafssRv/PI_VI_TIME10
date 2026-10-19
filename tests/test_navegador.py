"""Chrome real, MediaRecorder real e microfone sintético; servidor de voz controlado.

Executar: python -m pytest tests/test_navegador.py --navegador -v
O WebSocket é controlado aqui para testar a interface sem depender da IA.
O pipeline real, inclusive WebSocket, é coberto em test_integracao_voz.py.
"""

import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import wave

import pytest
import requests

pytestmark = pytest.mark.navegador
RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def servidor():
    with socket.socket() as reserva:
        reserva.bind(("127.0.0.1", 0))
        porta = reserva.getsockname()[1]
    with open(os.devnull, "w") as log:
        processo = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", "backend", "--port", str(porta), "--log-level", "warning"],
            cwd=RAIZ, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        url = "http://127.0.0.1:{}".format(porta)
        try:
            for _ in range(100):
                if processo.poll() is not None:
                    pytest.fail("Uvicorn terminou antes de abrir a porta")
                try:
                    if requests.get(url + "/health", timeout=0.3).status_code == 200:
                        break
                except requests.RequestException:
                    time.sleep(0.1)
            else:
                pytest.fail("Uvicorn não iniciou")
            yield url
        finally:
            processo.terminate()
            processo.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(
            channel=os.getenv("BROWSER_CHANNEL", "chrome"), headless=True,
            args=["--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
        )
        yield navegador
        navegador.close()


def resposta_wav():
    dados = io.BytesIO()
    with wave.open(dados, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 4000)
    return dados.getvalue()


@pytest.fixture
def pagina(browser, servidor):
    contexto = browser.new_context(permissions=["microphone"], viewport={"width": 1280, "height": 800})
    pagina = contexto.new_page()
    erros = []
    pagina.on("pageerror", lambda erro: erros.append(str(erro)))
    yield pagina, servidor, erros
    contexto.close()
    assert erros == []


def configurar_socket(pagina, mensagens, responder=True):
    def conexao(ws):
        ws.send(json.dumps({"tipo": "pronto", "versao_protocolo": 1, "capacidades": {"registro_pedidos": False}}))

        def receber(mensagem):
            if isinstance(mensagem, bytes):
                mensagens.append(mensagem)
                return
            controle = json.loads(mensagem)
            mensagens.append(controle)
            if controle["tipo"] == "fim_da_fala" and responder:
                ws.send(json.dumps({"tipo": "transcricao", "quem": "cliente", "texto": "Olá", "parcial": False}))
                ws.send(json.dumps({"tipo": "transcricao", "quem": "atendente", "texto": "Olá, como posso ajudar?", "parcial": False}))
                ws.send(json.dumps({"tipo": "audio_resposta", "formato": "audio/wav"}))
                ws.send(resposta_wav())
                ws.send(json.dumps({"tipo": "fim_audio"}))
        ws.on_message(receber)

    pagina.route_web_socket("**/ws/falar", conexao)


def test_grava_envia_final_do_turno_toca_resposta_e_libera_microfone(pagina):
    page, url, _ = pagina
    mensagens = []
    configurar_socket(page, mensagens)
    page.goto(url)
    page.locator("#botao-chamada").click()
    page.wait_for_function("estadoAtual === 'ouvindo' && protocoloNovo")
    page.wait_for_function("pedacosEnviados > 0")
    assert page.locator("#comanda-aviso").is_visible()

    # A requestData precisa ser chamada para entregar a cauda antes de fim_da_fala.
    page.evaluate("""() => {
        window.flushes = 0;
        window.tracksCapturadas = stream.getTracks();
        const original = gravador.requestData.bind(gravador);
        gravador.requestData = () => { window.flushes++; original(); };
        fimDaFala(1500);
    }""")
    page.wait_for_function("estadoAtual === 'falando' || document.querySelector('#conversa').textContent.includes('como posso ajudar')")
    page.wait_for_function("estadoAtual === 'ouvindo' && audioResposta.currentTime > 0")
    assert page.evaluate("window.flushes") == 1
    controles = [m for m in mensagens if isinstance(m, dict)]
    assert any(m["tipo"] == "resposta_tocada" for m in controles)
    indice_fim = next(i for i, m in enumerate(mensagens) if isinstance(m, dict) and m["tipo"] == "fim_da_fala")
    assert isinstance(mensagens[indice_fim - 1], bytes)
    assert page.evaluate("stream.getAudioTracks()[0].enabled")

    page.locator("#botao-chamada").click()
    page.wait_for_function("player.src.startsWith('blob:')")
    assert page.locator("#resumo-titulo").inner_text() == "Pedido não salvo"
    assert page.evaluate("window.tracksCapturadas.every(t => t.readyState === 'ended')")
    # Reproduz o próprio áudio capturado pelo MediaRecorder.
    page.evaluate("player.play()")
    page.wait_for_function("player.currentTime > 0")
    page.screenshot(path=str(RAIZ / ".local-test" / "navegador-resumo.png"))


def test_negacao_de_microfone_mostra_erro_e_permite_tentar_novamente(pagina):
    page, url, _ = pagina
    page.context.clear_permissions()
    page.goto(url)
    page.locator("#botao-chamada").click()
    page.wait_for_function("estadoAtual === 'erro'")
    assert "microfone" in page.locator("#tarja-erro-texto").inner_text().lower()
    assert page.locator("#tarja-erro-botao").inner_text() == "Tentar de novo"
    assert page.evaluate("stream === null")


def test_ligar_novamente_preserva_o_microfone_da_nova_chamada(pagina):
    page, url, _ = pagina
    configurar_socket(page, [], responder=False)
    page.goto(url)
    for _ in range(3):
        page.locator("#botao-chamada").click()
        page.wait_for_function("estadoAtual === 'ouvindo' && protocoloNovo")
        page.locator("#botao-chamada").click()
        page.locator("#resumo-fechar").click()
    page.locator("#botao-chamada").click()
    page.wait_for_function("estadoAtual === 'ouvindo' && protocoloNovo")
    page.wait_for_function("pedacosEnviados > 0")
    assert page.evaluate("stream.getAudioTracks()[0].readyState") == "live"


def test_layout_e_foco_do_resumo(pagina):
    page, url, _ = pagina
    configurar_socket(page, [], responder=False)
    page.goto(url)
    for largura, altura in ((1280, 800), (980, 800), (760, 800)):
        page.set_viewport_size({"width": largura, "height": altura})
        from playwright.sync_api import expect
        expect(page.locator("#botao-chamada")).to_be_in_viewport()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.evaluate("abrirResumo({duracao: '00:01'})")
    assert page.locator("#resumo-ligar").evaluate("el => el === document.activeElement")
    page.keyboard.press("Shift+Tab")
    assert page.locator("#resumo-fechar").evaluate("el => el === document.activeElement")
    page.keyboard.press("Escape")
    assert not page.locator("#resumo").is_visible()
