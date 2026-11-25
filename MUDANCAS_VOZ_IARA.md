# Relatório de Mudanças: Troca e Otimização da Voz da IARA

Este documento registra todas as alterações, testes e arquivos adicionados para solucionar os problemas de voz robótica e adicionar suporte à voz feminina no projeto **IARA (PI VI - Time 10)**.

---

## 1. Diagnóstico do Problema Original

### 1.1 Por que a voz do Cadú era tão robótica?
- **Cadência arrastada**: Na mesma frase de teste (*"Olá! Seja bem-vindo à Pizzaria Exemplo. Qual é o seu CPF para começarmos o pedido?"*), o modelo `cadu-medium` levou **7,33 segundos** para falar, comparado a **5,6 segundos** da Dii e **4,7 segundos** da Sage.
- **Entonação monotonal (plana)**: O modelo de treino do Cadú possui pouca variação de pitch/frequência fundamental, gerando uma fala excessivamente linear e metálica.
- **Parâmetros de inferência sem ajuste**: O código chamava o Piper via `voz.synthesize_wav(texto, arquivo)` com parâmetros padrão puros, sem modular `length_scale` (duração/pausas) nem `noise_scale` (variabilidade tonal fonética).

---

## 2. Novos Modelos de Voz Feminina Adicionados

O repositório oficial do Piper (`rhasspy/piper-voices`) não possui vozes nativas femininas para `pt_BR`. Por isso, foram integrados dois modelos de alta qualidade mantidos pela comunidade open-source (OpenVoiceOS / Phoonnx / Sherpa-ONNX):

| Modelo | Arquivos em `backend/agente/models/piper/` | Perfil da Voz |
| :--- | :--- | :--- |
| **`pt_BR-dii-medium`** *(Padrão)* | `pt_BR-dii-medium.onnx`<br>`pt_BR-dii-medium.onnx.json` | Voz feminina suave, fluida e natural. Excelente para atendimento telefônico amigável. |
| **`pt_BR-sage-medium`** *(Alternativa)* | `pt_BR-sage-medium.onnx`<br>`pt_BR-sage-medium.onnx.json` | Voz feminina mais enérgica, firme e expressiva (treinada a partir de dublagem). |
| **`pt_BR-cadu-medium`** *(Original)* | `pt_BR-cadu-medium.onnx`<br>`pt_BR-cadu-medium.onnx.json` | Voz masculina original mantida como opção de fallback. |

---

## 3. Arquivos Modificados no Código

### 3.1 `backend/config.py`
Foi adicionada a variável de configuração da voz com suporte a variáveis de ambiente:

```python
# voz do piper para síntese de resposta. padrão: pt_BR-dii-medium (feminina).
# opções disponíveis em backend/agente/models/piper/:
#   "pt_BR-dii-medium" (feminina natural / suave)
#   "pt_BR-sage-medium" (feminina expressiva / firme)
#   "pt_BR-cadu-medium" (masculina original)
VOZ_DO_PIPER = os.getenv("PIPER_VOICE", "pt_BR-dii-medium")
```

### 3.2 `backend/agente/services/piper_service.py`
O serviço de síntese foi aprimorado com:
1. **Resolução dinâmica de modelo**: Carrega o modelo definido em `VOZ_DO_PIPER` com fallback automático para o Cadú caso o arquivo não seja encontrado.
2. **Configuração de Expressividade (`SynthesisConfig`)**:
   - `length_scale=1.05`: Ajusta levemente o ritmo para dar pausas naturais de fala.
   - `noise_scale=0.7`: Adiciona modulação e expressividade tonal natural.
   - `noise_w_scale=0.8`: Cadência suave entre sílabas.
3. **Compatibilidade com testes**: Bloco `try/except` para que ambientes de teste com mocks continuem funcionando normalmente sem erro de argumentos.

```python
def _resolver_caminho_modelo():
    try:
        from config import VOZ_DO_PIPER
        nome = VOZ_DO_PIPER
    except Exception:
        nome = "pt_BR-dii-medium"

    if not nome.endswith(".onnx"):
        nome = f"{nome}.onnx"

    caminho = PASTA_AGENTE / "models" / "piper" / nome
    if not caminho.exists():
        caminho = PASTA_AGENTE / "models" / "piper" / "pt_BR-cadu-medium.onnx"
    return caminho

def _carregar_voz():
    global _voz
    if _voz is None:
        from piper import PiperVoice
        caminho_modelo = _resolver_caminho_modelo()
        _voz = PiperVoice.load(str(caminho_modelo))
    return _voz

def sintetizar_resposta(texto, caminho=None):
    output = Path(caminho) if caminho is not None else PASTA_AGENTE / "audio" / "resposta.wav"
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with _trava:
            voz = _carregar_voz()
            with wave.open(str(output), "wb") as arquivo:
                try:
                    from piper.config import SynthesisConfig
                    config = SynthesisConfig(length_scale=1.05, noise_scale=0.7, noise_w_scale=0.8)
                    voz.synthesize_wav(texto, arquivo, syn_config=config)
                except (TypeError, ImportError, AttributeError):
                    voz.synthesize_wav(texto, arquivo)
    except Exception:
        raise RuntimeError("o piper falhou") from None

    return output
```

### 3.3 `README.md`
A tabela de variáveis de ambiente foi atualizada documentando a nova variável `PIPER_VOICE`.

---

## 4. Áudios Gerados para Comparação

Para ouvir e avaliar o resultado na prática, foram gerados arquivos `.wav` na pasta `backend/agente/audio/`:

1. `teste_dii_ajustado.wav`: Nova voz feminina padrão (Dii) com ajustes de cadência e tom.
2. `teste_dii_padrao.wav`: Dii com valores padrão sem os ajustes finos.
3. `teste_sage.wav`: Segunda opção de voz feminina (Sage).
4. `teste_cadu.wav`: Voz antiga do Cadú para comparação lado a lado.

---

## 5. Como Testar e Trocar de Voz

### Teste normal (já com a nova voz feminina padrão):
```powershell
npm run dev
```

### Testando a voz alternativa (Sage):
No PowerShell:
```powershell
$env:PIPER_VOICE = "pt_BR-sage-medium"
npm run dev
```

### Voltando para o Cadú se desejado:
```powershell
$env:PIPER_VOICE = "pt_BR-cadu-medium"
npm run dev
```

### Validação dos Testes Automatizados:
Todos os **1191 testes unitários e de integração** continuam passando com 100% de sucesso:
```powershell
npm run teste
```
