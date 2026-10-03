<?php
/**
 * Сверка нашей копии макета админки с макетом Orchid.
 *
 *     php8.4 glavpryg-sayt/tests/check-maket-orchid.php [макет-orchid] [наша-копия]
 *
 * Зачем. Макет `platform::app` переопределён у себя
 * (`resources/views/vendor/platform/app.blade.php`) ради двух меток —
 * `turbo-root` и `dashboard-prefix`: сайт живёт в подкаталоге, и без полного
 * пути не работает ни одно поле загрузки файлов. Но копия чужого макета не
 * обновляется вместе с Orchid: после обновления админка тихо останется на
 * прежней разметке. Эта проверка и говорит, что копию пора пересобрать.
 *
 * Как сверяет. Из нашей копии выбрасываются шапка-комментарий и строки
 * «Наша правка», а две наши метки приводятся к виду Orchid. Остаток обязан
 * совпасть с макетом Orchid строка в строку; разошедшиеся строки печатаются.
 *
 * ⚠️ Отдельно проверяется, что обе наши метки на месте. Копия, совпавшая с
 * Orchid целиком, — тоже беда: значит, кто-то пересобрал её из поставки и
 * потерял правку, и загрузка файлов снова бьёт в 404.
 *
 * Код возврата: 0 — совпадает, 1 — разошлась.
 */

$sayt = '/var/www/glavpryg';
$orchid = $argv[1] ?? "$sayt/vendor/orchid/platform/resources/views/app.blade.php";
$nasha = $argv[2] ?? "$sayt/resources/views/vendor/platform/app.blade.php";

foreach ([$orchid, $nasha] as $put) {
    if (!is_file($put)) {
        fwrite(STDERR, "нет файла: $put\n");
        exit(1);
    }
}

// Пробелы внутри {{ }} в поставке Orchid стоят как попало («{{  Dashboard»),
// поэтому сравниваем строки со сжатыми пробелами.
$szhat = fn (string $s): string => trim(preg_replace('/\s+/', ' ', $s));

$tekst = file_get_contents($nasha);
$tekst = preg_replace('/\A\{\{--.*?--\}\}\R/s', '', $tekst, 1);

$nashiMetki = 0;
$stroki = [];
foreach (preg_split('/\R/', $tekst) as $stroka) {
    if (str_contains($stroka, 'Наша правка')) {
        continue;
    }
    if (str_contains($stroka, '\App\Support\Adminka::put()')) {
        $nashiMetki++;
        $stroka = str_replace('\App\Support\Adminka::put()', 'Dashboard::prefix()', $stroka);
    }
    $stroki[] = $szhat($stroka);
}

$ikh = array_map($szhat, preg_split('/\R/', file_get_contents($orchid)));

$bedy = 0;
if ($nashiMetki !== 2) {
    echo "ПРОВАЛ  наших меток в копии $nashiMetki, а нужно 2 (turbo-root и dashboard-prefix)\n";
    $bedy++;
}

$vsego = max(count($stroki), count($ikh));
for ($i = 0; $i < $vsego; $i++) {
    $u_nas = $stroki[$i] ?? '(нет строки)';
    $u_nikh = $ikh[$i] ?? '(нет строки)';
    if ($u_nas !== $u_nikh) {
        echo "ПРОВАЛ  строка " . ($i + 1) . " макета Orchid разошлась с копией\n"
            . "        Orchid: $u_nikh\n"
            . "        у нас:  $u_nas\n";
        $bedy++;
        if ($bedy > 10) {
            echo "        … дальше не печатаю: копию пора пересобрать из нового макета\n";
            break;
        }
    }
}

if ($bedy) {
    echo "\nКопия макета разошлась с Orchid. Пересобрать: скопировать новый макет\n"
        . "в resources/views/vendor/platform/app.blade.php и вернуть две метки.\n";
    exit(1);
}

echo "ок      копия макета совпадает с Orchid, обе наши метки на месте\n";
exit(0);
