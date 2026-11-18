# Como contribuir

Obrigado por ajudar a melhorar o Clipador.

## Antes de começar

1. Procure nas [issues](../../issues) se o assunto já foi aberto.
2. Para mudanças grandes, abra uma issue e combine a ideia primeiro.

## Preparar o ambiente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python clipador.py
```

No Linux e no macOS, ative com `source .venv/bin/activate`.

## Enviar uma mudança

1. Crie uma branch a partir de `main`.
2. Faça mudanças pequenas e com um objetivo só.
3. Confira a interface em tela grande e em tela pequena.
4. Abra o pull request explicando o que mudou e como testar.

## Regras do projeto

- O painel usa Python puro no servidor e JavaScript sem framework.
- Os estilos do editor usam o prefixo `st-`.
- A edição não pode destruir o vídeo original.
- Vídeos longos nunca são postados sem revisão.
- Nunca envie chaves, tokens, vídeos ou a pasta `dados`.

## Lançar uma versão

Abra `lancar-atualizacao.bat`, informe o número da versão e as novidades. O aviso aparece nos programas instalados depois que o instalador ficar pronto.
