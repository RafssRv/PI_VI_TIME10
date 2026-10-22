import ollama

print("Pensando...")

# Mandando uma mensagem para o Llama 3.2 que está rodando no seu PC
resposta = ollama.chat(model='llama3.2', messages=[
  {
    'role': 'user',
    'content': 'Você é o atendente de uma pizzaria. Responda em uma frase curta: um cliente acabou de pedir uma pizza de calabresa, o que você diz?',
  },
])

# Mostrando o que a IA respondeu
print("IA:", resposta['message']['content'])