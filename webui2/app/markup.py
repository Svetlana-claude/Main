"""Разметка ответов: markdown в HTML. Сырой HTML из ответа не проходит."""
from markupsafe import Markup
from markdown_it import MarkdownIt

# html=False: теги из ответа показываются текстом. Ссылки проверяет сама
# библиотека (javascript: и подобное не превращается в ссылку).
_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True}).enable(
    ["table", "strikethrough"])


def _wide(html: str) -> str:
    # Таблица прокручивается внутри своей обёртки, страница вбок не едет
    return html.replace("<table>", '<div class="wide"><table>').replace("</table>", "</table></div>")


def render(text: str) -> Markup:
    return Markup(_wide(_md.render(text or "")))
