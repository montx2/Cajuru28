"""
Modo desktop do NotasFlow.

O mesmo backend que roda em Docker (PostgreSQL + Redis + Celery + Next.js em
servidor) roda aqui como **programa instalado em cada computador**, com:

- banco SQLite no próprio arquivo (sem servidor de banco para instalar);
- fila em processo (threads) no lugar de Redis + Celery;
- painel web já compilado, servido pela própria API (sem Node.js);
- atualização automática a partir das Releases do GitHub (ou de uma pasta da
  rede).

Nada disso muda a lógica fiscal: os mesmos importadores, o mesmo governador de
consumo da SEFAZ, o mesmo cofre de certificados. O que muda é só *onde* as
peças rodam — e é justamente por isso que os dois modos podem coexistir no
mesmo código.
"""
