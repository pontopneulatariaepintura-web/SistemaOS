# Publicar o Sistema OS no Render

Este projeto possui `render.yaml`, entao pode ser publicado como Blueprint no Render.

## Passo a passo

1. Suba a pasta `SistemaOS` para um repositorio no GitHub.
2. Entre em https://dashboard.render.com/.
3. Clique em `New +`.
4. Escolha `Blueprint`.
5. Conecte o repositorio do GitHub.
6. O Render vai ler o arquivo `render.yaml` e criar:
   - Web Service `sistema-os`
   - Banco PostgreSQL `sistema-os-db`
7. Confirme a criacao.
8. Aguarde o deploy finalizar.
9. Abra a URL gerada pelo Render.

## Login inicial

O usuario inicial sera:

```text
Usuario: admin
Senha: valor gerado em ADMIN_PASSWORD
```

Para ver a senha gerada:

1. Abra o servico `sistema-os` no Render.
2. Va em `Environment`.
3. Veja o valor de `ADMIN_PASSWORD`.

Depois do primeiro acesso, entre em `Alterar senha` e coloque uma senha sua.

## Se preferir configurar manualmente

Use:

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

Variaveis:

```text
SECRET_KEY
ADMIN_PASSWORD
DATABASE_URL
```
