# Execução local e preparação de EC2 — T03

## Estado da entrega

Implementados `GET /api/health` e `GET /api/bible/passages`. Também implementados GET `/api/auth/csrf` e POST `/api/users`; login, logout, perfil e React permanecem pendentes. Nenhum recurso AWS foi criado e não existe URL pública de API nesta entrega.

## Preparar ambiente local

No diretório do backend, com Python 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/flask --app app init-cache
.venv/bin/flask --app app run --host 127.0.0.1 --port 5000
```

`cp` é para a primeira configuração; preserve `.env` existente. Não é necessário preencher MongoDB para testar a T03 local. O Flask CLI lê `.env` via python-dotenv; o Gunicorn depende de variáveis exportadas ou fornecidas pelo serviço systemd.

Em outro terminal:

```bash
curl --fail http://127.0.0.1:5000/api/health
curl --get --data-urlencode 'reference=João 3:16' http://127.0.0.1:5000/api/bible/passages
```

O provedor exige acesso à internet. Falha de rede retorna 503, preservando o health check. Cache de 24 horas em SQLite local compartilhado pelo caminho `instance/bible-cache.sqlite3`; não serve como evidência de Atlas nem armazena usuários. Produção exige URI MongoDB e usa a coleção `bible_cache`, sem fallback local. Com URI configurada em desenvolvimento, o cache também usa MongoDB.

## Testes e prova real

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/gunicorn --check-config --config gunicorn.conf.py wsgi:app
.venv/bin/python scripts/smoke_bible.py
```

Os testes são offline e não escrevem em banco real. A prova real é opt-in, usa a rota Flask com cache temporário isolado e faz duas chamadas externas mais uma consulta ao cache. Não imprime textos completos ou credenciais. Respeite os limites do provedor; não execute a prova em loop.

`health` comprova somente processo/rota; não consulta cache, Atlas ou API externa. `flask --app app init-cache` verifica o backend de cache e cria explicitamente o índice TTL no MongoDB quando configurado. A expiração é checada nas consultas, sem esperar a limpeza TTL.

## Configuração consumida nesta T03

`APP_ENV`, `MONGODB_URI`, `MONGODB_DATABASE`, `BIBLE_API_BASE_URL` (fixa em `https://bible-api.com`), `BIBLE_CONNECT_TIMEOUT_SECONDS`, `BIBLE_READ_TIMEOUT_SECONDS`, `BIBLE_CACHE_TTL_SECONDS` e `MAX_REQUEST_BYTES` são lidas pela factory. Sem URI e fora de produção, o cache usa SQLite em `instance`.

Tradução é restrita a `almeida`; não aceitar provedor/URL enviados na query. `APP_ORIGIN`, `SESSION_COOKIE_SECURE` e `ANONYMOUS_SESSION_TTL_SECONDS` são consumidos no cadastro. A sessão anônima tem duração absoluta fixa de 1800 segundos. `SESSION_TTL_SECONDS`, `UPLOAD_*`, `FFPROBE_PATH` e `MAX_VIDEO_*` permanecem contratos futuros.

## Preparação para EC2 (sem provisionamento nesta tarefa)

Arquivos disponíveis:

- `deploy/app-cristao.service`: modelo systemd com usuário dedicado, ambiente externo e Gunicorn em loopback.
- `deploy/nginx.conf.example`: modelo mesma origem com HTTPS, proxy `/api`, limite de 51 MiB e build React futuro. Não publica arquivos de upload.
- `gunicorn.conf.py`: dois workers, timeout de 30 segundos e sem access log com parâmetros de consulta.

Os modelos não foram instalados no sistema. Nginx/HTTPS e frontend ainda não estão disponíveis localmente para validação integral. Só ativar o serviço depois de adaptar e conferir os arquivos no servidor autorizado.

### Pré-requisitos no servidor já autorizado

1. Instância EC2 acessível, Python 3.12, Nginx, usuário de serviço `appcristao`, domínio e certificado HTTPS. Abrir somente as portas necessárias; Gunicorn permanece em `127.0.0.1:8000`.
2. Backend em `/srv/app-cristao/backend`; criar virtualenv e instalar `requirements.txt`. Executar testes em ambiente separado antes de publicar.
3. MongoDB Atlas com usuário restrito ao banco do projeto e acesso de rede autorizado para a EC2. Não desabilitar TLS para resolver falhas de conexão.
4. Criar `/var/lib/app-cristao` pertencente ao usuário do serviço, para uploads futuros. Código permanece separado dos dados persistentes.
5. Guardar ambiente em `/etc/app-cristao/backend.env`, legível apenas por root/serviço conforme a configuração operacional. Não usar exemplo como credencial real. Configurar `APP_ENV=production`, `MONGODB_URI` real e banco dedicado. `APP_ORIGIN=https://seu-dominio` e `SESSION_COOKIE_SECURE=true`.
6. Antes de ativar o serviço, carregar o ambiente de modo seguro na sessão operacional e executar `flask --app app init-cache` com o usuário adequado. Não copiar URI em logs, comandos compartilhados ou commits.
7. Adaptar domínio/certificados no exemplo Nginx; publicar build React somente quando existir. Validar com `nginx -t` e `systemd-analyze verify` no servidor, após os caminhos estarem instalados. O redirecionamento HTTP exige certificado previamente provisionado; este modelo não automatiza sua emissão.
8. Instalar unidade, recarregar systemd e iniciar somente após validação. Verificar health, uma passagem real e a segunda consulta em cache. Confirmar a coleção no Atlas sem divulgar URI. Documentar URL pública no README.

### Checklist de implantação pendente

- [ ] Acesso EC2 e configuração de domínio/HTTPS disponibilizados.
- [ ] Credenciais Atlas configuradas por canal privado e conectividade verificada.
- [ ] Modelos adaptados e validados no servidor de destino.
- [ ] Backend acessível publicamente; link real no README.
- [ ] Frontend implementado/publicado e fluxo completo verificado (T12).

O custo e a autorização de recursos continuam sob controle do usuário; este documento não executa provisionamento. Preparar esses arquivos atende à parte de preparação da T03, sem concluir RA05 ou CA12.

## Cadastro e CSRF — T04.1

Contas e sessões usam somente MongoDB; sem `MONGODB_URI`, as novas rotas retornam 503 controlado (sem fallback SQLite ou memória). Configure a URI fora do Git e execute antes do uso:

```bash
.venv/bin/flask --app app init-auth
```

O comando cria índices únicos de e-mail normalizado e hash de sessão, e TTL de sessões; conflitos/dados existentes ou banco inacessível causam falha controlada. Preserve os índices únicos para garantir duplicação inclusive em concorrência.

Fluxo: GET `/api/auth/csrf` → guardar cookie e `data.csrf_token` → POST `/api/users` com JSON `name`, `email`, `password` e cabeçalho `X-CSRF-Token`. Cadastro retorna 201, sem autenticar a sessão. Uma nova consulta CSRF rotaciona o token e preserva o prazo absoluto da sessão existente. Sessões armazenam somente hashes dos tokens; senhas usam scrypt.

`APP_ORIGIN` é a origem exata do cliente, sem caminho ou barra final. Requisições com Origin divergente são recusadas nas duas rotas; clientes sem Origin ainda precisam de cookie e CSRF no cadastro. Cookies são Secure por padrão; `SESSION_COOKIE_SECURE=false` só é aceito em testes ou `APP_ENV=development` com origem localhost HTTP. Desenvolvimento com Vite deve encaminhar `/api` ao Flask na mesma origem; não há CORS público.

Testes usam repositório fake injetado e adaptador Mongo simulado, sem rede ou dados reais. Não comprovam persistência no Atlas, concorrência real no banco, login ou integração React.
