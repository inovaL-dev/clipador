# Configurar a postagem no YouTube Shorts

Os cortes prontos entram sozinhos na aba **Postagem**, na ordem em que foram feitos, com título, descrição, hashtags e horário.

Existem duas formas de postar:

| Forma | Quando usar |
|---|---|
| **Pela agenda** | Funciona hoje. Você baixa o vídeo, copia os textos e programa no YouTube Studio |
| **Envio automático** | O clipador envia e programa sozinho, depois que o YouTube aprovar a auditoria do seu projeto |

## Postar hoje pela agenda

1. Abra a aba **Postagem** e clique no título do vídeo.
2. Clique em **Baixar vídeo**.
3. No [YouTube Studio](https://studio.youtube.com), clique em **Criar > Enviar vídeos**.
4. Use **Copiar título** e **Copiar descrição** e cole no YouTube.
5. Em **Visibilidade**, escolha **Programar** e coloque o dia e o horário da agenda.
6. Volte ao painel e clique em **Já agendei no YouTube**.

## Ligar o envio automático

### 1. Criar o projeto no Google

1. Abra o [Google Cloud Console](https://console.cloud.google.com) com a conta do seu canal.
2. Clique no seletor de projetos, depois em **Novo projeto**. Use o nome `Clipador` e clique em **Criar**.
3. Abra a [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) e clique em **Ativar**.

### 2. Configurar o acesso

1. Abra a [Plataforma de autenticação do Google](https://console.cloud.google.com/auth/overview) e clique em **Começar**.
2. Preencha o nome do app, escolha seu e-mail, selecione **Externo** e conclua.
3. Em **Público-alvo**, clique em **Publicar app**. Sem isso, a conexão expira a cada 7 dias.
4. Em **Clientes**, clique em **Criar cliente**.
5. Em **Tipo de aplicativo**, escolha **App para computador** e clique em **Criar**.
6. Clique em **Baixar JSON** e guarde o arquivo. Ele é uma senha: não envie para ninguém.

### 3. Conectar o canal

1. No painel, abra **Postagem > Canal do YouTube**.
2. Escolha o arquivo JSON e clique em **Conectar canal**.
3. Entre com a conta do canal. Se aparecer **O Google não verificou este app**, clique em **Avançado** e em **Acessar Clipador**.
4. Autorize o acesso.
5. Clique em **Enviar vídeo de teste** e confira o vídeo privado no YouTube Studio.

### 4. Pedir a auditoria

Até a aprovação, todo vídeo enviado pela API fica preso no modo privado. Passar na auditoria depois não libera os vídeos que já foram enviados.

1. Abra o [formulário de auditoria da API do YouTube](https://support.google.com/youtube/contact/yt_api_form).
2. Informe o número do projeto, que aparece no painel inicial do Google Cloud.
3. Explique o uso: ferramenta própria para enviar e programar Shorts no seu canal, com cortes de lives autorizados.
4. Envie o formulário e responda aos e-mails do Google. O prazo e a aprovação dependem do YouTube.

### 5. Ligar

Depois da aprovação, abra **Postagem > Envio automático** e marque as duas opções. O clipador envia a fila com antecedência e o YouTube publica cada Short no horário escolhido.

## Boas práticas

- Tenha autorização do criador para postar os cortes e mantenha os créditos na descrição.
- Revise os títulos: eles são criados pela fala do corte e podem precisar de ajuste.
- Shorts com mais de 1 minuto que recebem reivindicação de direitos autorais podem ser bloqueados. Por isso, o clipador limita os cortes a menos de 60 segundos no padrão.
- Depois de algumas semanas, troque os horários de acordo com o público do seu canal no YouTube Studio.
