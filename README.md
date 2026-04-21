# PhCharts — Site da Comunidade

## Estrutura de pastas

```
phcharts_site/
  app.py              ← servidor Flask (back-end)
  requirements.txt    ← dependências Python
  charts.json         ← banco de dados (criado automaticamente)
  uploads/            ← arquivos .phchart (criado automaticamente)
  static/
    index.html        ← site (front-end)
    covers/           ← capas dos charts (criado automaticamente)
```

---

## Rodar localmente (seu PC)

1. Instale o Flask uma vez só:
   ```
   pip install flask
   ```

2. Entre na pasta e execute:
   ```
   cd phcharts_site
   python app.py
   ```

3. Acesse no navegador: http://localhost:5000

> Enquanto rodar local, só você acessa. Para publicar na internet, siga o passo abaixo.

---

## Deploy gratuito no Railway (recomendado)

O Railway hospeda o servidor na nuvem — você não precisa deixar o PC ligado.

### Passo a passo

1. Crie conta em https://railway.app (pode entrar com GitHub)

2. Crie um repositório no GitHub com esses 3 arquivos:
   - `app.py`
   - `requirements.txt`
   - `static/index.html`

3. No Railway, clique em **New Project → Deploy from GitHub repo**

4. Selecione seu repositório. O Railway detecta Python automaticamente.

5. Em **Settings → Networking**, clique em **Generate Domain**.
   Vai aparecer um link tipo `phcharts.up.railway.app` — compartilhe esse link!

6. Pronto. O servidor roda 24/7 sem precisar do seu PC.

> **Atenção:** o plano gratuito do Railway tem 500 horas/mês (suficiente para uso moderado).
> Para uso pesado, o plano pago custa ~$5/mês.
> Alternativa gratuita sem limite de horas: **Render.com** (um pouco mais lento na inicialização).

---

## Como o site funciona

- **Qualquer pessoa** pode fazer upload de um .phchart
- A **dificuldade** é lida automaticamente do arquivo, ou pode ser inserida manualmente
  - 1–10 = Fácil (verde)
  - 11–14 = Normal (azul)
  - 15–16 = Difícil (laranja)
  - 17+ = Extremo (vermelho)
- **Rating** por estrelas (1–5) — cada IP vota uma vez por chart
- **Download** incrementa o contador automaticamente
- **Capa** extraída do .phchart ou enviada separadamente

## API (para referência)

| Rota                     | Método | Descrição                          |
|--------------------------|--------|------------------------------------|
| `/api/charts`            | GET    | lista charts (sort, diff, q)       |
| `/api/upload`            | POST   | envia chart (multipart/form-data)  |
| `/api/download/<id>`     | GET    | baixa .phchart + incrementa contador|
| `/api/rate/<id>`         | POST   | vota estrelas `{"stars": 1-5}`     |
| `/covers/<filename>`     | GET    | serve imagem de capa               |
