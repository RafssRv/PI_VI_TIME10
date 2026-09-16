PASSO A PASSO - RODAR O PROJETO DO ZERO

1. INSTALAR
   Git: https://git-scm.com/downloads
   Docker Desktop: https://www.docker.com/products/docker-desktop
   Se o Docker avisar que falta o WSL, abra o PowerShell como administrador,
   rode o comando abaixo e reinicie o PC:
      wsl --install

2. BAIXAR O PROJETO
      git clone https://github.com/RafssRv/PI_VI_TIME10.git
      cd PI_VI_TIME10

3. SE TIVER POSTGRESQL INSTALADO NO PC, DESLIGAR (usa a mesma porta 5432)
   No PowerShell como administrador (troque 18 pela sua versão):
      Stop-Service postgresql-x64-18
      Set-Service postgresql-x64-18 -StartupType Manual

4. SUBIR O BANCO (com o Docker Desktop aberto)
      docker compose up -d
   Na primeira vez, as tabelas são criadas sozinhas a partir do banco.sql.

5. CONFERIR
      docker exec pizzaria-db psql -U pizzaria -d pizzaria -c "\dt"
   Tem que aparecer: cliente, item_pedido, pedido e produto.

CONEXÃO COM O BANCO
   postgresql://pizzaria:pizzaria123@localhost:5432/pizzaria

NO DIA A DIA
   git pull                  pega as mudanças da equipe
   docker compose up -d      liga o banco (ex.: depois de reiniciar o PC)
   docker compose down -v    apaga o banco; rode o up de novo pra recriar
                             (necessário quando o banco.sql mudar)
