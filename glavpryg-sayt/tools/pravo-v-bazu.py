#!/usr/bin/env python3
"""Правовые документы сайта: из Markdown в каталоге `glavpryg-sayt/pravo/` — в базу.

    /home/mokeeva/main/webui/.venv/bin/python glavpryg-sayt/tools/pravo-v-bazu.py [--zamenit] [--proverka]

Каждый `pravo/<slug>.md` (кроме подкаталогов) становится записью «Правовые
страницы» с тем же slug: заголовок — первая строка `# …`, остальное — HTML.
Метки реквизитов (`[[ПРОДАВЕЦ]]`, `[[ИНН]]` …) остаются в тексте как есть —
их подставляет сайт из «Настроек сайта» (LegalPage::tekst()).

⚠️ Документ, который уже правили в админке, без `--zamenit` не трогается:
затирать чужую правку молча нельзя. «Не правили» — это пустой текст или
заготовка поставки «Текст документа. Заполнить в админке.», либо текст,
совпадающий с тем, что этот же скрипт клал прошлый раз.

`--proverka` — только показать, что будет сделано, базу не менять.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

import markdown

KOREN = pathlib.Path(__file__).resolve().parent.parent
PRAVO = KOREN / 'pravo'
SAYT = pathlib.Path('/var/www/glavpryg')
ZAGOTOVKA = '<p>Текст документа. Заполнить в админке.</p>'

# Порядок в подвале — по id; новые документы встают в конец в этом порядке.
PORYADOK = ['privacy', 'personal-data', 'terms', 'marketing', 'cookies', 'oferta']


def sobrat(put: pathlib.Path) -> tuple[str, str]:
    tekst = put.read_text(encoding='utf-8').strip().split('\n')
    if not tekst[0].startswith('# '):
        sys.exit(f'{put.name}: первая строка должна быть заголовком «# …»')
    zagolovok = tekst[0][2:].strip()
    html = markdown.markdown('\n'.join(tekst[1:]).strip(), extensions=['sane_lists'])
    return zagolovok, html


def artisan(php: str) -> str:
    r = subprocess.run(['php8.4', 'artisan', 'tinker', '--execute', php],
                       cwd=SAYT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'artisan tinker упал:\n{r.stdout}\n{r.stderr}')
    return r.stdout


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--zamenit', action='store_true', help='заменить и правленные в админке')
    ap.add_argument('--proverka', action='store_true', help='только показать, базу не менять')
    a = ap.parse_args()

    fayly = {p.stem: p for p in PRAVO.glob('*.md')}
    neizvestnye = sorted(set(fayly) - set(PORYADOK))
    if neizvestnye:
        sys.exit(f'Нет в списке PORYADOK: {", ".join(neizvestnye)} — допишите, чтобы задать место в подвале')

    dokumenty = []
    for slug in PORYADOK:
        if slug in fayly:
            zagolovok, html = sobrat(fayly[slug])
            dokumenty.append({'slug': slug, 'title': zagolovok, 'content': html})

    # Что лежит в базе сейчас
    seychas = json.loads(artisan(
        'echo json_encode(App\\Models\\LegalPage::all(["slug","title","content"])->keyBy("slug"), JSON_UNESCAPED_UNICODE);'
    ).strip() or '{}')

    proshloe = KOREN / 'pravo' / '.v-baze.json'   # что клали прошлый раз — чтобы узнать нетронутые
    bylo = json.loads(proshloe.read_text(encoding='utf-8')) if proshloe.exists() else {}

    k_zapisi = []
    for d in dokumenty:
        tek = seychas.get(d['slug'])
        if tek is None:
            deystvie = 'новый'
        elif tek['content'] == d['content'] and tek['title'] == d['title']:
            print(f'  без изменений — {d["slug"]}')
            continue
        elif (tek['content'] or '').strip() in ('', ZAGOTOVKA) or tek['content'] == bylo.get(d['slug']):
            deystvie = 'обновить'
        elif a.zamenit:
            deystvie = 'заменить правку из админки'
        else:
            print(f'  ПРОПУЩЕН — {d["slug"]}: текст правили в админке; заменить — с --zamenit')
            continue
        print(f'  {deystvie} — {d["slug"]}: {d["title"]}')
        k_zapisi.append(d)

    if a.proverka or not k_zapisi:
        return

    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(k_zapisi, f, ensure_ascii=False)
    try:
        subprocess.run(['chmod', '644', f.name], check=True)
        artisan(
            f'foreach (json_decode(file_get_contents("{f.name}"), true) as $d) {{'
            ' App\\Models\\LegalPage::updateOrCreate(["slug" => $d["slug"]], ["title" => $d["title"], "content" => $d["content"]]); }'
            ' echo "ok";'
        )
    finally:
        pathlib.Path(f.name).unlink(missing_ok=True)

    bylo.update({d['slug']: d['content'] for d in k_zapisi})
    proshloe.write_text(json.dumps(bylo, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'Записано документов: {len(k_zapisi)}')


if __name__ == '__main__':
    main()
