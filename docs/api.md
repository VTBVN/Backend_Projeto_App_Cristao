# Contrato da API — v0.2

**Data:** 19/10/2026. **Estado:** `/api/health` e `/api/bible/passages` implementadas e verificadas na T03. As demais rotas são contratos para tarefas futuras. Referência: [arquitetura](arquitetura.md) e RF01–RF13 do [escopo](escopo-e-requisitos.md).

## Convenções

Prefixo `/api`. JSON UTF-8, exceto upload multipart e mídia. Identificadores hexadecimais de 24 caracteres; data ISO 8601 UTC. Entrada inválida: 400; recurso ausente/invisível: 404. Campos desconhecidos ou protegidos no payload são rejeitados com 400, nunca aplicados diretamente como operadores MongoDB.

Resposta individual: `{"data": {...}}`. Listagem: `{"data": [], "pagination": {"next_cursor": null, "has_more": false}}`. Limite padrão 10, intervalo 1–30; cursor opaco inválido ou usado com filtro diferente: 400. Sem resultados: 200 com lista vazia. Exclusão bem-sucedida: 204 sem corpo.

Erro: `{"error": {"code": "validation_error", "message": "Dados inválidos.", "fields": {"email": "E-mail inválido."}}}`. `fields` é opcional. Não expor stack trace ou dados sensíveis.

Demais códigos: 401 sem sessão autenticada válida; 403 CSRF inválido ou ação conhecida sem permissão; 409 conflito/duplicação; 413 limite de upload; 415 tipo de conteúdo não aceito; 422 mídia ilegível ou fora dos limites; 429 limite de tentativas; 502 resposta inválida de provedor; 503 dependência indisponível. JSON inválido: 400. Erro inesperado: 500 com mensagem genérica.

Todos os métodos mutáveis exigem cookie e `X-CSRF-Token`; isso inclui rotas públicas de cadastro e login. Sessão sem autenticação não autoriza interações. Respostas de sessão/CSRF/usuário próprio: `Cache-Control: no-store`.

## Objetos públicos

| Objeto | Campos |
| --- | --- |
| UserPublic | `id`, `name`, `bio`, `created_at` |
| UserSelf | UserPublic + `email`, `role` |
| Video | `id`, `author` (UserPublic), `caption`, `category`, `bible_reference` (string ou null), `status`, `created_at`, `updated_at`, `duration_seconds`, `media_url`, `reaction_count`, `comment_count`, `reacted_by_me` |
| VideoOwn/Moderation | Video + `review_reason` (string ou null) |
| Comment | `id`, `video_id`, `author` (UserPublic), `text`, `created_at` |
| Report | `id`, `video_id`, `reporter_id`, `reason`, `status`, `resolution_note`, `created_at`, `resolved_at` |

Coleções internas não definem diretamente o JSON público. Autor e administradores podem visualizar estados restritos; o público recebe somente aprovados e nunca notas internas.

## 1. Autenticação e perfis — RF01/RF08

| Método e rota | Entrada | Acesso | Sucesso |
| --- | --- | --- | --- |
| GET `/auth/csrf` | Sem corpo | Público | 200, `data.csrf_token`; cookie criado se necessário |
| POST `/users` | `name`, `email`, `password` | Público + CSRF | 201, UserSelf sem sessão autenticada; Location `/api/users/{id}` |
| POST `/auth/login` | `email`, `password` | Público + CSRF | 200, `data.user` UserSelf e `data.csrf_token`; cookie rotacionado |
| POST `/auth/logout` | Sem corpo | Autenticado + CSRF | 204, revogação no servidor e cookie expirado |
| GET `/me` | Sem corpo | Autenticado | 200, UserSelf |
| PATCH `/me` | `name` e/ou `bio` | Autenticado + CSRF | 200, UserSelf atualizado |
| GET `/users/{id}` | Sem corpo | Público | 200, UserPublic |
| GET `/me/videos` | `status` opcional, `cursor`, `limit` | Autenticado | 200, lista VideoOwn |

Validações: nome 2–80 caracteres após trim; bio até 300; e-mail obrigatório, até 254 caracteres, normalizado com trim/lowercase e índice único; senha entre 12 e 128 caracteres, sem trim ou truncamento. Senha deve ser tratada como string; e-mail não aceita objetos ou operadores de consulta. E-mail duplicado: 409. Cadastro não aceita `role`; falha de login retorna mensagem genérica e 401. Editar e-mail/senha não faz parte deste contrato.

Fluxo React: obter CSRF → cadastrar → fazer login → atualizar token em memória → GET `/me`. Ao reabrir a página, obter CSRF e consultar `/me`. Logout limpa estado React após resposta; erro de rede não comprova revogação, portanto informar falha e permitir tentar novamente. Não guardar senha nem identificador de sessão no localStorage.

## 2. Feed, publicação e mídia — RF02–RF05

| Método e rota | Entrada | Acesso | Sucesso |
| --- | --- | --- | --- |
| GET `/videos` | `category`, `author_id`, `cursor`, `limit` opcionais | Público/sessão opcional | 200, lista Video aprovado |
| POST `/videos` | multipart: `file`, `caption`, `category`, `bible_reference` opcional | Autenticado + CSRF | 201, VideoOwn pendente; Location do detalhe |
| GET `/videos/{id}` | Sem corpo | Visibilidade do recurso | 200, Video ou VideoOwn/Moderation |
| PATCH `/videos/{id}` | `caption`, `category`, `bible_reference`, pelo menos um | Autor + CSRF | 200, VideoOwn; aprovado volta a pendente |
| DELETE `/videos/{id}` | Sem corpo | Autor + CSRF | 204, invisibilidade imediata e limpeza retomável |
| GET `/videos/{id}/media` | Header Range opcional | Mesma visibilidade do detalhe | 200 ou 206, `video/mp4`; 416 para intervalo inválido |

Categorias fixas: `louvor`, `devocional`, `testemunho`, `humor`, `estudo-biblico`. Legenda 1–500 caracteres após trim; referência bíblica até 100, string ou null; categoria fora da lista: 400. Edição não substitui arquivo. Limites: arquivo 50 MiB, requisição 51 MiB, duração (0, 90] segundos, MP4/H.264 e AAC opcional. Detalhes de validação e armazenamento na arquitetura.

O cadastro de vídeo não depende de consultar o provedor bíblico naquele momento; referência é validada como entrada e a existência da passagem é verificada na consulta. Falha de API externa não pode impedir a publicação de vídeo sem passagem confirmada.

Feed em ordem `created_at desc, id desc`, com os filtros incorporados ao cursor. Autor consulta pendentes/rejeitados por `/me/videos`; o filtro `author_id` no feed público não amplia visibilidade. Vídeo restrito para visitante/terceiro retorna 404; autor ou administrador podem inspecioná-lo. Autor bloqueado pelo consultante é ocultado nas consultas públicas individuais e listagens, inclusive mídia. Para gerir conteúdo próprio/moderação, privilégios explícitos têm precedência sobre filtro de descoberta.

Mídia deve ser autorizada a cada pedido, não por URL pública de arquivo estático. No piloto usar `Cache-Control: private, no-store` para reduzir exposição após revisão. Não prometer recolher bytes já entregues ao navegador antes da rejeição.

## 3. Reações e comentários — RF06/RF07

| Método e rota | Entrada | Acesso | Sucesso |
| --- | --- | --- | --- |
| PUT `/videos/{id}/reaction` | Sem corpo | Autenticado, vídeo aprovado visível + CSRF | 200, `data.reacted=true`, `data.reaction_count` |
| DELETE `/videos/{id}/reaction` | Sem corpo | Autenticado, vídeo aprovado visível + CSRF | 204, inclusive se não houver reação |
| GET `/videos/{id}/comments` | `cursor`, `limit` | Vídeo aprovado visível | 200, lista Comment |
| POST `/videos/{id}/comments` | `text` | Autenticado, vídeo aprovado visível + CSRF | 201, Comment; Location do comentário |
| GET `/comments/{id}` | Sem corpo | Vídeo aprovado visível e autor do comentário não bloqueado | 200, Comment |
| DELETE `/comments/{id}` | Sem corpo | Autor do comentário + CSRF | 204 |

Texto de comentário 1–1000 após trim. Comentários em ordem `created_at asc, id asc` com cursor próprio. Filtrar autores bloqueados antes da paginação; `comment_count` reflete comentários visíveis ao consultante. Repetir PUT de reação não duplica; índice único garante a regra. Não permitir novas interações em vídeo pendente/rejeitado, mesmo para o autor. O autor de comentário pode excluí-lo mesmo se o vídeo deixou de ser público.

## 4. Denúncias e bloqueios — RF09/RF10

| Método e rota | Entrada | Acesso | Sucesso |
| --- | --- | --- | --- |
| POST `/videos/{id}/reports` | `reason` | Autenticado, vídeo aprovado visível + CSRF | 201, `data.id`, `data.status=open`; sem Location público |
| GET `/me/blocks` | `cursor`, `limit` | Autenticado | 200, lista `user` UserPublic e `created_at` |
| PUT `/me/blocks/{user_id}` | Sem corpo | Autenticado + CSRF | 200, `data.blocked=true` |
| DELETE `/me/blocks/{user_id}` | Sem corpo | Autenticado + CSRF | 204, inclusive se não houver bloqueio |

Motivo 10–1000 caracteres após trim. Denúncia cria revisão e não altera estado editorial. Rejeitar bloqueio de si próprio com 400; usuário inexistente: 404. PUT repetido não duplica. Bloqueio é unilateral, não remove conta ou conteúdo globalmente; visitantes anônimos continuam vendo conteúdo aprovado. Denúncias completas são restritas ao painel administrativo.

## 5. Moderação — RF11/RF12

| Método e rota | Entrada | Acesso | Sucesso |
| --- | --- | --- | --- |
| GET `/moderation/videos` | `status=pending` padrão, `cursor`, `limit` | Admin | 200, lista VideoOwn/Moderation |
| PATCH `/moderation/videos/{id}` | `status=approved` ou `rejected`, `reason`, `expected_updated_at` | Admin + CSRF | 200, VideoOwn/Moderation |
| GET `/moderation/reports` | `status=open` padrão, `cursor`, `limit` | Admin | 200, lista Report |
| PATCH `/moderation/reports/{id}` | `status=resolved`, `resolution_note` | Admin + CSRF | 200, Report |

Motivo de revisão e nota de resolução: 10–1000 caracteres após trim. Decisão de vídeo exige `expected_updated_at`; atualização condicional que perdeu corrida com edição do autor retorna 409 e pede recarregar. Isso evita aprovar metadados diferentes dos revisados. Aprovar pendente, rejeitar pendente/aprovado e reavaliar rejeitado são ações administrativas; histórico deve registrar autor da decisão e data, sem mudar o autor do vídeo.

Resolver denúncia não implica rejeitar vídeo automaticamente. Para remover conteúdo denunciado, administrador usa PATCH de vídeo e depois registra resolução da denúncia. Usuário comum recebe 403 no painel. Listagens administrativas usam data crescente para priorizar itens antigos, com cursor estável.

## 6. Passagens bíblicas — RF13

GET `/bible/passages?reference=John%203%3A16&translation=almeida`, público. `reference` obrigatório 1–100 caracteres; tradução permitida no piloto: somente `almeida` (padrão quando omitida). Parâmetros desconhecidos ou repetidos retornam 400.

Implementado na T03: formato de livro, capítulo e versículo/faixa, com espaços normalizados. Aliases de João sem/com acento e Salmo/Salmos/Psalm/Psalms são normalizados; demais nomes são encaminhados ao provedor sem promessa de reconhecimento. A prova real confirmou `João 3:16` e `Salmos 23:1`. Para Salmos, usa-se o identificador `psa`, pois os nomes ingleses testados retornaram 404 no provedor. Não aceita URL arbitrária ou referências vazias.

Resposta 200: `{"data": {"reference": "...", "translation": "almeida", "text": "...", "source": "bible-api.com", "cached": false}}`. Referência inexistente: 404; timeout, limite ou indisponibilidade externa: 503; payload externo inválido: 502. Provedor e URL base não são parâmetros do cliente.

Cache de 24 horas checado a cada consulta; falhas não são armazenadas. Cache indisponível retorna 503 (`cache_unavailable`), sem desviar para outro armazenamento. Acesso ao provedor usa conexão de até 2s, leitura de até 5s entre dados, sem retries/redirects e corpo máximo de 256 KiB. Esses timeouts não equivalem a limite absoluto de duração total; Gunicorn também tem timeout operacional. Respostas HTTP têm `Cache-Control: no-store`; `cached` indica o cache do servidor, não do navegador.

## 7. Verificação de operação

GET `/health`, público: 200 com `data.status=ok` e sem segredos quando o processo está de pé. Não consulta Atlas e não comprova readiness. Verificação de Atlas deve ser registrada separadamente, sem expor URI ou detalhes internos em endpoint público.

## Entrega da primeira fatia (T04)

Implementar primeiro CSRF, cadastro, login, logout, GET/PATCH `/me` e GET `/users/{id}`, com formulário React e estados de erro. Testar revogação e expiração, CSRF, duplicação de e-mail, rejeição de `role` e ausência de dados sensíveis. Banco fake só valida comportamento local; Atlas e navegador conectado ao Flask precisam de evidências separadas para CA01/CA07.
