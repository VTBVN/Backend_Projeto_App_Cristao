# Arquitetura e decisões técnicas — T01

**Data:** 19/10/2026. **Estado:** base Flask, consulta bíblica e cache implementados na T03; autenticação, mídia e frontend continuam como decisões para implementação. Veja [operação](operacao.md) para execução e verificação.

## Stack e organização

Preservar Flask, React web, MongoDB Atlas e AWS EC2 conforme RA01–RA05. Backend e frontend permanecem separados (RA08). Priorizar uma implantação de mesma origem: Nginx serve o build React e encaminha `/api` ao Gunicorn/Flask. Em desenvolvimento, Vite encaminhará `/api` ao Flask; não habilitar CORS amplo para compensar configuração incorreta.

- Backend: Python 3.12, Flask com application factory, blueprints por domínio, PyMongo síncrono e Requests para a API externa. Testes com Pytest e cliente Flask; banco de teste isolado por interface de repositório. Gunicorn para produção.
- Frontend: React com TypeScript e Vite; npm e `package-lock.json`. Componentes por fluxo e um cliente HTTP central para sessão, CSRF e erros. Sem estado global adicional até surgir necessidade real.
- Versões do backend resolvidas na T03 e registradas em `requirements.txt`/`requirements-dev.txt`; dependências instaladas somente no virtualenv local. Versões do frontend serão resolvidas na T04. Não utilizar `latest` sem registrar o resultado.
- Runtime de frontend alvo: Node 22, versão 22.12 ou superior nessa linha. O Node 18.19.1 observado no PATH precisa ser substituído para os comandos do frontend; não rebaixar Vite apenas para acomodá-lo.

Estrutura backend criada na T03: `app/`, `tests/`, dependências, `wsgi.py` e configuração Gunicorn. Frontend `src/`, configuração Vite e scripts permanecem pendentes.

## Autenticação e permissões — D004

Escolher sessão opaca persistida no MongoDB, em vez de JWT no localStorage ou de usar apenas cookie Flask com identidade assinada. A escolha permite revogação imediata no logout e mantém o identificador inacessível ao JavaScript.

- Gerar identificador aleatório criptográfico de pelo menos 256 bits; armazenar somente seu SHA-256 na coleção `sessions`. Não usar o cookie de sessão padrão do Flask como substituto silencioso desta decisão.
- Cookie `app_session`: HttpOnly, SameSite=Lax, Path=/, sem Domain; Secure em produção HTTPS. A única exceção de Secure é o desenvolvimento explícito em localhost HTTP.
- Sessão anônima para CSRF: 30 minutos. Sessão autenticada: 12 horas de duração absoluta, sem renovação deslizante. Validar `expires_at` a cada acesso; TTL só faz limpeza, não autorização.
- `GET /api/auth/csrf` cria/reutiliza sessão e retorna token CSRF; resposta sem cache. Guardar no servidor o hash do token e comparar em tempo constante. React mantém token em memória, envia `X-CSRF-Token` e cookies nas requisições mutáveis.
- Todas as operações POST/PUT/PATCH/DELETE, inclusive cadastro/login/logout, exigem CSRF. Validar Origin nas requisições do navegador contra origem configurada, rejeitar origem divergente e nunca retornar token via CORS público. Cliente sem Origin continua obrigado a apresentar cookie e token CSRF válido.
- Cadastro não autentica automaticamente. Login invalida sessão anterior, gera outra e retorna novo CSRF. Logout exclui a sessão no servidor e expira o cookie. Sessão revogada ou expirada retorna 401, inclusive se o cliente reutilizar cookie antigo.
- Hash de senha com `generate_password_hash` do Werkzeug, usando scrypt, e verificação pela função correspondente; senha nunca é registrada em log ou devolvida.
- Papel padrão `user`; `admin` só por comando operacional autenticado no ambiente do servidor, fora do cadastro público. Ler papel atual do usuário no servidor, não confiar em campos do cliente.
- Limitar tentativas de login: inicialmente 10 por combinação IP/e-mail em 15 minutos; resposta 429 e Retry-After. Implementar contador compartilhado entre workers, não apenas memória de processo. Mensagem de falha não distingue usuário inexistente de senha incorreta.

Coleção adicional `sessions`: `token_hash` único, `user_id` opcional, `csrf_hash`, `created_at`, `expires_at` BSON Date UTC. Índice TTL `expires_at` com `expireAfterSeconds=0`. Limpeza de contadores de tentativas também pode usar TTL.

## Upload e entrega de mídia — D005

Para o piloto, arquivos em `instance/uploads` localmente e volume persistente dedicado na EC2. Nunca no diretório público do React, no Git ou como binário no MongoDB.

- Um arquivo por requisição; limite do arquivo **50 MiB** (52.428.800 bytes). Limite total multipart **51 MiB** (53.477.376 bytes), consistente no proxy e no Flask.
- MP4 real com vídeo H.264, áudio AAC opcional e duração maior que zero e até 90 segundos. Nenhuma transcodificação nesta entrega.
- Validar nome/formato declarado, tamanho real e metadados com `ffprobe`; não aceitar só extensão/MIME. Não extrair arquivos, usar shell para nomes enviados ou aceitar caminhos fornecidos pelo cliente. `ffprobe` com timeout de 10 segundos e saída limitada; ausência da ferramenta gera indisponibilidade controlada (503), sem aceitar arquivo sem validação.
- Escrever progressivamente em área temporária, validar e mover com nome UUID gerado pelo servidor; limpar temporários em falha. Metadados incluem duração, codecs, bytes e localização privada. Não expor caminho de disco.
- `GET /api/videos/{id}/media` verifica as mesmas permissões do detalhe e só então entrega `video/mp4` com suporte a Range. O HTML `<video>` usa essa rota; não expor alias público que contorne a revisão.
- Exclusão lógica imediata retira o vídeo das consultas; remoção física e de relações é idempotente e retomável em caso de falha. Tombstone de exclusão não é um novo estado editorial público.
- Edição de metadados e nova aprovação invalidam imediatamente a visibilidade anterior; não usar cache público da mídia no piloto. Bloqueio é filtro por usuário autenticado e não impede acesso público anônimo a vídeo aprovado, coerente com o escopo.

Sem `ffprobe`, continuam possíveis testes com subprocesso simulado, formulários e regras; teste real de upload fica pendente até disponibilizar a ferramenta. Documentar codecs aceitos na UI antes de upload.

## Persistência e consultas — D006

Usar ObjectId no banco e IDs hexadecimais de 24 caracteres como strings na API. Datas BSON UTC; serialização ISO 8601 com `Z`. Nunca enviar senha, hashes de sessão ou caminhos internos.

Índices iniciais: `users.email_normalized` único; `sessions.token_hash` único e TTL separado; `videos(status, created_at desc, _id desc)`; `videos(author_id, created_at desc, _id desc)`; `reactions(user_id, video_id)` único; `blocks(user_id, blocked_user_id)` único; `comments(video_id, created_at, _id)`; `reports(status, created_at, _id)`. Nomear índices e criá-los por rotina explícita, sem apagar dados.

Listagens têm limite padrão 10, máximo 30, e cursor estável. Vídeos ordenados por `created_at desc, _id desc`; cursor carrega último par e contexto do filtro. Mudanças de categoria exigem reinício da paginação. Aplicar visibilidade/bloqueio antes do limite; bloqueios novos entre páginas podem reduzir resultados, sem promessa de snapshot imutável.

Reações são documentos únicos; comentários e denúncias ficam separados. Contadores podem ser calculados inicialmente, evitando sincronização prematura de cópias. Atlas é obrigatório para a verificação final; fake ou MongoDB local não substituem essa evidência.

## API externa e infraestrutura — D007

Consulta bíblica implementada pelo Flask com bible-api.com, tradução Almeida, validada em prova real na T03. Usar URL base fixa e parâmetros codificados, sem aceitar URL do cliente. Timeout de conexão 2 segundos, leitura 5 segundos, cache por referência/tradução por 24 horas e nenhuma repetição automática em cascata. Sem redirects e com resposta limitada a 256 KiB. MongoDB mantém cache compartilhado quando configurado; sem URI, apenas em desenvolvimento/teste, SQLite persistente oferece cache local compartilhado entre workers. Produção exige MongoDB e não faz fallback. Esse SQLite não substitui Atlas para dados do produto nem comprova RA03.

Sem cache válido e com falha externa: 503; resposta inválida do provedor: 502; passagem inexistente: 404. Reprodução de vídeo não depende da consulta bíblica. Não marcar RA07 concluído com resposta simulada.

Nginx + Gunicorn + build React na mesma EC2, HTTPS em produção, uploads persistentes fora do diretório de código. A configuração e a URL serão criadas/verificadas em T03/T12. Não criar recursos pagos nem inferir acesso AWS nesta tarefa.

## Fontes técnicas consultadas em 19/10/2026

- [Flask — segurança](https://flask.palletsprojects.com/en/stable/web-security/): cookies, CSRF e limites de requisição.
- [Werkzeug — hash de senhas](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash).
- [MongoDB — TTL](https://www.mongodb.com/docs/manual/core/index-ttl/): remoção não imediata; checar expiração na aplicação.
- [Vite — pré-requisitos](https://vite.dev/guide/): Node 20.19+ ou 22.12+; a decisão local é a linha 22.
- [FFprobe](https://ffmpeg.org/ffprobe.html): inspeção de contêiner e streams.

As escolhas de limites, duração de sessão e organização são decisões deste projeto, não valores impostos por essas fontes.
