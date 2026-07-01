# Senha Facil

MVP de uma solucao SaaS para fila digital via QR Code, feita com Python, Flask, SQLite, CSS e JavaScript.

## Arquitetura proposta

O consultorio nao precisa de totem dedicado nem impressora termica. A unidade exibe um QR Code apontando para a URL do Web App do paciente, por exemplo:

`https://meuconsultorio.com/fila/unidade-centro`

Fluxo principal:

1. O paciente escaneia o QR Code e abre o Web App.
2. O paciente escolhe a categoria: consulta, retorno ou prioritario.
3. O frontend envia `POST /api/senhas/gerar`.
4. O backend gera uma senha consecutiva com transacao atomica no SQLite.
5. O paciente acompanha o status por SSE sem atualizar a pagina.
6. A recepcao ou medico usa `/gestao/unidade-centro` para chamar a proxima senha.
7. O painel opcional de TV em `/painel/unidade-centro` recebe as chamadas em tempo real.
8. Os relatorios diarios e semanais ficam em `/relatorios/unidade-centro`.

## Modulos

- Web App do paciente: substitui o totem fisico e preserva a senha no `localStorage`.
- API Flask: centraliza emissao, recuperacao, chamada, finalizacao e relatorios.
- Banco SQL: SQLite no MVP, com tabelas de unidades, senhas e contadores diarios.
- Painel de gestao: chamada da proxima senha, visualizacao da fila e finalizacao.
- Gestao da base: exclusao de senhas, reset da fila diaria e limpeza de registros.
- Painel de TV: exibicao da senha chamada e lista de espera.
- Relatorios: emissao diaria e semanal agrupada por categoria.

## Concorrencia

A numeracao consecutiva usa `BEGIN IMMEDIATE` e uma tabela `daily_counters`. Isso impede duplicidade quando varios pacientes emitem senha ao mesmo tempo. Em producao com multiplos processos/servidores, substitua o contador por Redis `INCR` ou por sequencias/transacoes no PostgreSQL.

## Tempo real

O MVP usa Server-Sent Events:

- `/api/eventos/ticket/<ticket_id>` para o celular do paciente.
- `/api/eventos/clinica/<clinic_id>` para gestao e painel de TV.

Para escala horizontal, use Redis Pub/Sub, filas ou Flask-SocketIO com message broker.

## Requisitos funcionais cobertos

- Emissao digital de senha por categoria.
- Numeracao diaria consecutiva.
- Recuperacao da senha ativa por dispositivo via `localStorage`.
- Atualizacao em tempo real por SSE.
- Wake Lock API no Web App do paciente, quando suportada pelo navegador.
- Dashboard de gestao.
- Relatorio diario e semanal.

## Melhorias para producao

- Autenticacao e perfis para recepcao, medico e administrador.
- Cadastro multi-clinica com planos SaaS.
- PostgreSQL em vez de SQLite.
- Redis para contador atomico e Pub/Sub.
- Geolocalizacao opcional com raio permitido por unidade.
- Notificacoes push via Service Worker.
- Exportacao CSV/PDF dos relatorios.
- Logs de auditoria.
- Deploy em HTTPS com Gunicorn/Uvicorn atras de Nginx.

## Como executar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Acesse:

- `http://127.0.0.1:5000/fila/unidade-centro`
- `http://127.0.0.1:5000/gestao/unidade-centro`
- `http://127.0.0.1:5000/admin/unidade-centro/base`
- `http://127.0.0.1:5000/painel/unidade-centro`
- `http://127.0.0.1:5000/relatorios/unidade-centro`
