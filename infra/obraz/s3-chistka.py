"""Хранилище Selectel S3: уборка того, что само не уходит.

    s3-chistka.py versii [дней]            — стереть прежние версии файлов старше N дней (30)
    s3-chistka.py ostavit <папка/> <N>     — в папке оставить N последних файлов

В бакете включены версии: стёртый или перезаписанный файл остаётся прежней
версией — защита от случайного удаления. Правило «стирать прежние версии через
30 дней» Selectel принимает, но не хранит (проверено 03.11.2026), поэтому уборка здесь.
Ключи — ~/.config/selectel-s3.json; корневой сертификат Selectel есть только
в системном хранилище, отсюда verify.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

BAKET = "klod-kopii-mokeeva"
d = json.load(open(os.path.expanduser("~/.config/selectel-s3.json")))
s3 = boto3.client("s3", endpoint_url=d["endpoint"], region_name=d["region"],
                  aws_access_key_id=d["access"], aws_secret_access_key=d["secret"],
                  verify="/etc/ssl/certs/ca-certificates.crt")


def versii(dney: int) -> None:
    granica = datetime.now(timezone.utc) - timedelta(days=dney)
    staroe = []
    for stranica in s3.get_paginator("list_object_versions").paginate(Bucket=BAKET):
        for v in stranica.get("Versions", []) + stranica.get("DeleteMarkers", []):
            if not v["IsLatest"] and v["LastModified"] < granica:
                staroe.append({"Key": v["Key"], "VersionId": v["VersionId"]})
    for i in range(0, len(staroe), 1000):
        s3.delete_objects(Bucket=BAKET, Delete={"Objects": staroe[i:i + 1000], "Quiet": True})
    print(f"прежних версий старше {dney} дн. стёрто: {len(staroe)}")


def ostavit(papka: str, n: int) -> None:
    faily = []
    for stranica in s3.get_paginator("list_objects_v2").paginate(Bucket=BAKET, Prefix=papka):
        faily += stranica.get("Contents", [])
    faily.sort(key=lambda f: f["LastModified"], reverse=True)
    for f in faily[n:]:
        s3.delete_object(Bucket=BAKET, Key=f["Key"])
    print(f"{papka}: оставлено {min(n, len(faily))}, убрано {max(0, len(faily) - n)}")


if __name__ == "__main__":
    if sys.argv[1] == "versii":
        versii(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif sys.argv[1] == "ostavit":
        ostavit(sys.argv[2], int(sys.argv[3]))
