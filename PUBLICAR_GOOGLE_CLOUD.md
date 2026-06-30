# Publicar o Sistema OS no Google Cloud

Este projeto ja esta preparado para rodar no Google Cloud Run usando Docker.

## Importante

- Para acesso pela internet, use um banco online. Nao use o SQLite local (`sqlite:///database.db`) em producao.
- O banco recomendado no Google e Cloud SQL para PostgreSQL.
- As senhas dos usuarios ja sao salvas com hash.
- O primeiro usuario admin e criado automaticamente se nao existir.

## Variaveis de ambiente necessarias

Configure no Cloud Run:

```text
SECRET_KEY=uma-chave-grande-e-secreta
ADMIN_PASSWORD=senha-inicial-do-admin
DATABASE_URL=postgresql://USUARIO:SENHA@HOST:5432/NOME_DO_BANCO
```

Se usar Cloud SQL com conexao privada/socket, adapte o `DATABASE_URL` conforme a conexao escolhida no Google Cloud.

## Arquivos adicionados

- `Dockerfile`: empacota o Flask com Gunicorn para o Cloud Run.
- `.dockerignore`: evita enviar `venv`, banco local e arquivos temporarios.
- `.env.example`: modelo das variaveis que devem existir em producao.

## Passo a passo resumido

1. Crie um projeto no Google Cloud.
2. Ative Cloud Run, Cloud Build e Cloud SQL Admin API.
3. Crie uma instancia Cloud SQL PostgreSQL.
4. Crie um banco para o sistema, por exemplo `sistemaos`.
5. Crie um usuario e senha para esse banco.
6. Publique no Cloud Run usando este diretorio como origem.
7. Configure as variaveis `SECRET_KEY`, `ADMIN_PASSWORD` e `DATABASE_URL` no servico.
8. Permita acesso publico ao servico Cloud Run, porque o controle de entrada sera feito pelo login do proprio sistema.
9. Acesse a URL gerada pelo Cloud Run e entre com `admin` e a senha definida em `ADMIN_PASSWORD`.
10. Depois do primeiro acesso, altere a senha pelo menu `Alterar senha`.

## Comando de deploy por terminal

Depois de instalar e autenticar o Google Cloud CLI:

```bash
gcloud run deploy sistema-os --source . --region southamerica-east1 --allow-unauthenticated
```

Na primeira publicacao, confira no Console do Google Cloud se as variaveis de ambiente e o banco Cloud SQL foram configurados corretamente.

## Referencias oficiais

- Cloud Run aceita servicos HTTP em container e injeta a porta pela variavel `PORT`.
- O Google Cloud tambem documenta deploy direto de codigo-fonte para Cloud Run e conexao entre Cloud Run e Cloud SQL PostgreSQL.
