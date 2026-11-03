# Доступ к хранилищу Selectel S3 (бакет klod-kopii-mokeeva) для rclone: ключи — ~/.config/selectel-s3.json (600)
_s3() { python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.config/selectel-s3.json')))['$1'])"; }
export AWS_ACCESS_KEY_ID=$(_s3 access) AWS_SECRET_ACCESS_KEY=$(_s3 secret) AWS_DEFAULT_REGION=ru-1
export RCLONE_S3_PROVIDER=Selectel RCLONE_S3_ENDPOINT=$(_s3 endpoint) RCLONE_S3_REGION=ru-1 \
       RCLONE_S3_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID RCLONE_S3_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
unset -f _s3
S3_BAKET=klod-kopii-mokeeva
