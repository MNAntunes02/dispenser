# ADR 014 — Painel de desenvolvimento: Tkinter e processos locais

Status: implementada (2026-11-09).

## Contexto

Desenvolver o dispensador exige dois processos: o core Python e a UI Flutter.
Até aqui era preciso abrir dois terminais, lembrar os caminhos de banco, socket e
lock, e tomar cuidado para não rodar o core contra `/var/lib/dispenser` (o banco
do aparelho) nem carregar credenciais reais do backend. Também era fácil perder
a saída de um dos dois no meio da outra janela.

O systemd já resolve isso no Pi, mas no PC de desenvolvimento ele não ajuda:
as units usam `/var/lib/dispenser`, `/run/dispenser` e wrappers instalados em
`/usr/local/bin`, e alterá-las para modo dev exigiria `sudo` — além de misturar
o ciclo de vida do aparelho com o do desenvolvedor.

## Opções consideradas

- **Scripts shell + `yad`/`zenity`** — rápido, mas acompanhar dois logs ao vivo,
  filtrar, salvar e parar processos com escalonamento de sinal não cabe bem num
  formulário. Rejeitado.
- **Segundo app Flutter desktop** — visual consistente com a UI, mas cria mais
  um runner Linux, mais dependências e mais tempo de build para uma ferramenta
  interna. Rejeitado por enquanto.
- **Página web local** — permitiria acessar de outro dispositivo, mas adiciona
  servidor HTTP, porta, autenticação e superfície de segurança. Rejeitado.
- **Usar `systemctl`/`journalctl` também no PC** — exigiria `sudo`/polkit e
  units instaladas; não serve ao ciclo de desenvolvimento. Rejeitado.
- **Tkinter + `subprocess.Popen`** — biblioteca padrão, janela nativa, leitura
  de stdout/stderr por thread e controle de sinais direto. Escolhido.

## Escolha

- **Janela Tkinter** em `painel/`, entrada `python -m painel` a partir da raiz
  do `dispenser/`.
- **Processos locais**, sem shell, sem `sudo` e sem systemd. Cada serviço roda
  em sessão própria (`start_new_session=True`); parar envia `SIGTERM` ao grupo e
  escala para `SIGKILL` se necessário. Isso também encerra os filhos que o
  `flutter run` cria.
- **Estado isolado** em `dispenser/.run/` (ignorado pelo git): `state.db`,
  `core.sock`, `core.lock` e `agenda-demo.json`. O painel nunca toca
  `/var/lib/dispenser`.
- **Ambiente limpo**: credenciais do backend (`FIREBASE_*`,
  `DISPENSER_CREDENTIALS_PATH`) e variáveis do systemd (`NOTIFY_SOCKET`,
  `WATCHDOG_USEC` etc.) são removidas dos filhos. Um teste local não deve
  sincronizar com produção nem mandar watchdog para o systemd da sessão.
- **Logs por fila**: threads leem stdout/stderr e colocam eventos numa
  `queue.Queue`; a thread do Tkinter drena a cada 100 ms. O buffer é limitado
  (5.000 linhas por serviço), tem filtro, auto-rolagem, limpeza e exportação.
  Códigos ANSI são removidos para o `tk.Text` não mostrar lixo.
- **Sem auto-restart**: se um processo cair, o painel mostra o código de saída
  e uma dica; reiniciar é decisão explícita do desenvolvedor. Auto-restart
  esconderia justamente o erro que se está investigando.
- **Agenda de demonstração opcional**: grava uma dose para daqui a 2 minutos em
  `.run/agenda-demo.json` e aponta `DISPENSER_AGENDA_JSON` para ela. Não altera
  o core; serve para exercitar o começo do fluxo no simulador.

## Consequências

- O painel é ferramenta de **desenvolvimento**, não substitui os serviços
  systemd nem deve ser instalado no aparelho como interface do paciente.
- A UI continua sendo `dispenser-ui`; `app-saude` não é iniciado nem alterado.
- A janela não é testada automaticamente (Tkinter exige display); os contratos
  usados por ela — comandos, ambiente, buffer e ciclo de vida dos processos —
  têm testes em `tests/test_painel.py`.
- Logs salvos podem conter dados operacionais sensíveis (LGPD): o painel não
  adiciona nomes de medicamentos, mas o desenvolvedor deve tratar os arquivos
  exportados com o mesmo cuidado do banco local.
