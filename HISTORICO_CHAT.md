# Histórico Completo da Conversa (Chat Exportado)

**Projeto**: IARA - Atendente de voz para pizzaria (PI VI - Time 10)  
**Data**: 25 de Novembro de 2026  
**Assunto**: Diagnóstico do projeto, solução da voz robótica do Cadú e adição de vozes femininas no Piper TTS.

---

### Mensagem do Usuário 1:
> *da uma olhada no meu projeto ai pra tu entender*

### Resposta do Assistente:
O assistente analisou toda a estrutura de diretórios, `README.md`, `main.py`, `package.json`, `atendimento.py`, rotas de WebSocket (`rotas/voz.py`), banco de dados e testes. Apresentou um resumo detalhado:
- **IARA**: Atendente por voz 100% local (sem APIs externas pagas).
- **Frontend**: Captura do microfone com VAD (~1.2s de silêncio), WebSocket `/ws/falar`, legenda e comanda em tempo real.
- **Backend**: FastAPI, Whisper (STT), regras de negócio determinísticas em Python para cardápio e pagamentos, Ollama/Llama 3.2 para conversação residual sem escrita no banco, e Piper TTS para síntese de fala.
- **Persistência**: PostgreSQL com proteção de CPF via HMAC-SHA256 (`CPF_HMAC_SECRET`).
- **Painel Admin**: Em `/admin/` para métricas e acompanhamento de chamadas em tempo real.

---

### Mensagem do Usuário 2:
> *Entao, o problema que estamos tendo agora é que:*  
> *1- a voz do cadu ta muito robótica*  
> *2- queremos por uma voz de mulher*

### Investigação e Ações Realizadas:
1. **Diagnóstico da voz robótica**:
   - O modelo `cadu-medium` fala de forma muito arrastada (7,33s vs 5,6s das vozes novas na mesma frase de teste).
   - O modelo do Cadú tem pouca variação de pitch (frequência/tom), soando plano e metálico.
   - O código não passava parâmetros de expressividade (`SynthesisConfig`) ao Piper.
2. **Busca por vozes femininas em Português Brasileiro (pt_BR)**:
   - Identificou que o repositório oficial do Piper não possui vozes femininas em pt_BR, mas a comunidade (OpenVoiceOS / Phoonnx / Sherpa) desenvolveu modelos compatíveis.
   - Foram baixados dois modelos femininos para `backend/agente/models/piper/`:
     - **`pt_BR-dii-medium`**: Voz suave, fluida e natural (escolhida como padrão).
     - **`pt_BR-sage-medium`**: Voz firme, mais expressiva (alternativa).
3. **Ajustes de código**:
   - `backend/config.py`: Criada variável `VOZ_DO_PIPER` com suporte a `$env:PIPER_VOICE`.
   - `backend/agente/services/piper_service.py`: Resolução dinâmica de modelo e aplicação de `SynthesisConfig(length_scale=1.05, noise_scale=0.7, noise_w_scale=0.8)` para fala mais natural.
   - `README.md`: Documentação atualizada com a nova variável.
4. **Geração de áudios de teste**:
   - Foram gerados em `backend/agente/audio/`:
     - `teste_dii_ajustado.wav` (Nova voz padrão feminina)
     - `teste_dii_padrao.wav`
     - `teste_sage.wav` (Voz alternativa feminina)
     - `teste_cadu.wav` (Voz masculina original para comparação)
5. **Validação**:
   - Todos os 1191 testes do projeto continuaram passando com 100% de sucesso.

---

### Mensagem do Usuário 3:
> *Tem como eu exportar esse chat? Preciso que voce faça um arquivo com todas as mudanças que voce fez, explicando uma por uma pq jaja vou sair desse pc e esse chat vai sumir*

### Arquivos Criados no Repositório:
- [MUDANCAS_VOZ_IARA.md](file:///c:/Users/24007131/PI_VI_TIME10/MUDANCAS_VOZ_IARA.md): Relatório técnico completo de todas as alterações, explicações e comandos.
- [HISTORICO_CHAT.md](file:///c:/Users/24007131/PI_VI_TIME10/HISTORICO_CHAT.md): Registro da íntegra da conversa e decisões tomadas.
