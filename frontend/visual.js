// parte so visual da tela de chamada. nao muda nada da logica da chamada:
// so LE o que o app.js ja tem (estadoAtual, analisador, dadosNivel) e enfeita a tela.
//  1. relogio da barra do celular
//  2. orbe: a esfera "liquida" que reage a voz
//  3. legenda: as palavras entram uma a uma
//  4. total da comanda virando igual painel de aeroporto

(() => {
  const semMovimento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- 1. relogio ----------
  const relogio = document.getElementById("relogio");
  function atualizarRelogio() {
    const agora = new Date();
    relogio.textContent = agora.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  atualizarRelogio();
  setInterval(atualizarRelogio, 15000);

  // ---------- 2. orbe ----------
  const canvas = document.getElementById("orbe-canvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const centro = W / 2;
  const raioBase = W * 0.3;

  // quanto o contorno "balanca" em cada estado e a velocidade do movimento
  const JEITO = {
    ocioso:      { mexe: 0.012, rapidez: 0.4 },
    conectando:  { mexe: 0.03,  rapidez: 1.2 },
    ouvindo:     { mexe: 0.02,  rapidez: 0.9 },
    processando: { mexe: 0.045, rapidez: 1.8 },
    falando:     { mexe: 0.05,  rapidez: 1.3 },
    encerrada:   { mexe: 0.008, rapidez: 0.3 },
    erro:        { mexe: 0.006, rapidez: 0.2 }
  };

  let volume = 0;        // volume alisado da voz do cliente
  let mexeAtual = 0.012; // vai mudando aos poucos pro valor do estado novo
  let rapidezAtual = 0.4;
  let tempo = 0;
  let ultimo = performance.now();

  function lerVolume() {
    // usa o mesmo medidor que o app.js ja criou pro microfone
    if (typeof analisador === "undefined" || !analisador || !dadosNivel) return 0;
    analisador.getByteTimeDomainData(dadosNivel);
    let soma = 0;
    for (let i = 0; i < dadosNivel.length; i++) {
      const v = (dadosNivel[i] - 128) / 128;
      soma += v * v;
    }
    return Math.sqrt(soma / dadosNivel.length);
  }

  function estado() {
    return typeof estadoAtual === "string" ? estadoAtual : "ocioso";
  }

  // contorno da bolha: um circulo com algumas ondas somadas
  function contorno(raio, amplitude, fase) {
    ctx.beginPath();
    const passos = 120;
    for (let p = 0; p <= passos; p++) {
      const a = (p / passos) * Math.PI * 2;
      const onda =
        Math.sin(a * 3 + fase) * 0.5 +
        Math.sin(a * 5 - fase * 1.3) * 0.3 +
        Math.sin(a * 2 + fase * 0.7) * 0.2;
      const r = raio * (1 + amplitude * onda);
      const x = centro + Math.cos(a) * r;
      const y = centro + Math.sin(a) * r;
      if (p === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  function desenhar(agora) {
    const dt = Math.min((agora - ultimo) / 1000, 0.05);
    ultimo = agora;
    const nome = estado();
    const jeito = JEITO[nome] || JEITO.ocioso;

    // a voz do cliente so conta quando o microfone esta aberto
    const alvoVolume = nome === "ouvindo" ? Math.min(lerVolume() * 6, 1) : 0;
    volume += (alvoVolume - volume) * 0.18;

    // o atendente falando: pulso "de fala", ja que o audio dele nao passa pelo medidor
    let fala = 0;
    if (nome === "falando") {
      fala = (Math.sin(tempo * 9) * 0.5 + 0.5) * (Math.sin(tempo * 2.3) * 0.5 + 0.5);
    }

    mexeAtual += (jeito.mexe - mexeAtual) * 0.05;
    rapidezAtual += (jeito.rapidez - rapidezAtual) * 0.05;
    tempo += dt * rapidezAtual;

    const amplitude = mexeAtual + volume * 0.22 + fala * 0.08;
    const raio = raioBase * (1 + volume * 0.12 + fala * 0.05);

    ctx.clearRect(0, 0, W, W);

    // brilho em volta
    const brilho = ctx.createRadialGradient(centro, centro, raio * 0.6, centro, centro, raio * 1.7);
    brilho.addColorStop(0, `rgba(255, 255, 255, ${0.18 + volume * 0.25})`);
    brilho.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = brilho;
    ctx.fillRect(0, 0, W, W);

    // duas camadas de "liquido" atras, meio transparentes
    ctx.fillStyle = "rgba(255, 255, 255, 0.12)";
    contorno(raio * 1.12, amplitude * 1.4, tempo * 1.3 + 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 255, 255, 0.18)";
    contorno(raio * 1.05, amplitude * 1.2, -tempo * 1.1 + 4);
    ctx.fill();

    // a bolha principal, com reflexo de metal no canto de cima
    const corpo = ctx.createRadialGradient(centro - raio * 0.35, centro - raio * 0.4, raio * 0.1, centro, centro, raio * 1.1);
    corpo.addColorStop(0, "rgba(255, 255, 255, 0.98)");
    corpo.addColorStop(0.45, "rgba(255, 244, 238, 0.85)");
    corpo.addColorStop(1, "rgba(255, 220, 205, 0.35)");
    ctx.fillStyle = corpo;
    contorno(raio, amplitude, tempo);
    ctx.fill();

    if (!semMovimento) requestAnimationFrame(desenhar);
  }
  requestAnimationFrame(desenhar);

  // ---------- 3. legenda com palavras entrando ----------
  const conversa = document.getElementById("conversa");
  const NOMES = { "VOCÊ": "Você", "ATENDENTE": "Atendente" };

  function enfeitarFala(fala) {
    const quem = fala.querySelector(".quem");
    if (quem && NOMES[quem.textContent]) quem.textContent = NOMES[quem.textContent];

    const texto = fala.querySelector(".texto");
    // fala parcial muda o tempo todo (streaming): fica sem animacao ate fechar
    if (!texto || fala.classList.contains("parcial") || semMovimento) return;
    const conteudo = texto.textContent;
    if (!conteudo || texto.dataset.enfeitado === conteudo) return;

    texto.dataset.enfeitado = conteudo;
    texto.textContent = "";
    conteudo.split(/(\s+)/).forEach((pedaco, i) => {
      if (/^\s+$/.test(pedaco)) {
        texto.appendChild(document.createTextNode(pedaco));
        return;
      }
      const palavra = document.createElement("span");
      palavra.className = "palavra";
      palavra.style.setProperty("--i", Math.min(i / 2, 40));
      palavra.textContent = pedaco;
      texto.appendChild(palavra);
    });
  }

  new MutationObserver(() => {
    conversa.querySelectorAll(".fala").forEach(enfeitarFala);
    // separar as palavras muda a altura do texto: rola de novo pra ultima fala aparecer inteira
    conversa.scrollTop = conversa.scrollHeight;
  }).observe(conversa, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class"] });

  // ---------- 4. total da comanda virando ----------
  const total = document.getElementById("comanda-total");
  let totalAnterior = total.textContent;

  new MutationObserver(() => {
    if (total.dataset.virando === "1") return;
    const novo = total.textContent;
    if (novo === totalAnterior || semMovimento) {
      totalAnterior = novo;
      return;
    }
    totalAnterior = novo;
    total.dataset.virando = "1";
    total.textContent = "";
    [...novo].forEach((letra, i) => {
      const span = document.createElement("span");
      span.className = "letra-virando";
      span.style.setProperty("--i", i);
      span.textContent = letra === " " ? " " : letra;
      total.appendChild(span);
    });
    // libera na proxima volta, depois que o observador ja viu a nossa propria mudanca
    setTimeout(() => { total.dataset.virando = ""; }, 0);
  }).observe(total, { childList: true, characterData: true, subtree: true });
})();
